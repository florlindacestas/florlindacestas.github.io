import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


DB_PATH = os.environ.get("STORE_DB", "/data/florlinda.db")
ALLOWED_UIDS = {
    value.strip()
    for value in os.environ.get(
        "STORE_ADMIN_UIDS",
        "TzTFIRf1C6WPfQekQgeC1vGi8KS2,98qz01xFPoW6iyMJEaD1GBPfAeM2",
    ).split(",")
    if value.strip()
}
COLLECTIONS = {"orders", "products", "clients", "finance", "drivers", "deliveries"}


def database():
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 30000")
    db.execute("PRAGMA foreign_keys = ON")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS firebase_records (
            collection TEXT NOT NULL,
            record_key TEXT NOT NULL,
            data_json TEXT NOT NULL,
            PRIMARY KEY (collection, record_key)
        )
        """
    )
    db.execute("CREATE TABLE IF NOT EXISTS store_meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT OR IGNORE INTO store_meta (name, value) VALUES ('schemaVersion', '2')")
    return db


def payload(handler):
    length = int(handler.headers.get("Content-Length", 0))
    return json.loads(handler.rfile.read(length) or b"{}")


def record_data(db, collection):
    rows = db.execute(
        "SELECT record_key, data_json FROM firebase_records WHERE collection = ?",
        (collection,),
    ).fetchall()
    return {row["record_key"]: json.loads(row["data_json"]) for row in rows}


class Handler(BaseHTTPRequestHandler):
    def response_headers(self, content_type="application/json"):
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-UID")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, PATCH, OPTIONS")

    def respond(self, status, value):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.response_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.response_headers()
        self.end_headers()

    def authorized(self):
        return self.headers.get("X-Admin-UID") in ALLOWED_UIDS

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self.respond(200, {"ok": True, "database": DB_PATH})
            return
        if not self.authorized():
            self.respond(401, {"error": "Sessão administrativa necessária"})
            return
        if path == "/api/data/schemaVersion":
            with database() as db:
                value = db.execute("SELECT value FROM store_meta WHERE name = 'schemaVersion'").fetchone()[0]
            self.respond(200, int(value))
            return
        if path == "/api/data/backups/latest":
            with database() as db:
                row = db.execute("SELECT value FROM store_meta WHERE name = 'backup_latest'").fetchone()
            self.respond(200, json.loads(row[0]) if row else None)
            return
        collection = path.removeprefix("/api/data/")
        if collection in COLLECTIONS:
            with database() as db:
                self.respond(200, record_data(db, collection))
            return
        self.respond(404, {"error": "not found"})

    def do_PATCH(self):
        self.write_state()

    def do_PUT(self):
        path = urlparse(self.path).path
        if path == "/api/data/backups/latest":
            if not self.authorized():
                self.respond(401, {"error": "Sessão administrativa necessária"})
                return
            value = payload(self)
            with database() as db:
                db.execute(
                    "INSERT OR REPLACE INTO store_meta (name, value) VALUES ('backup_latest', ?)",
                    (json.dumps(value, ensure_ascii=False),),
                )
            self.respond(200, {"ok": True})
            return
        if path == "/api/data":
            self.write_state()
            return
        self.respond(404, {"error": "not found"})

    def write_state(self):
        if not self.authorized():
            self.respond(401, {"error": "Sessão administrativa necessária"})
            return
        updates = payload(self)
        if not isinstance(updates, dict):
            self.respond(400, {"error": "invalid JSON"})
            return
        with database() as db:
            for path, value in updates.items():
                parts = path.split("/")
                if len(parts) < 2 or parts[0] not in COLLECTIONS:
                    continue
                collection, record_key = parts[0], parts[1]
                if len(parts) == 2:
                    if value is None:
                        db.execute(
                            "DELETE FROM firebase_records WHERE collection = ? AND record_key = ?",
                            (collection, record_key),
                        )
                    else:
                        db.execute(
                            "INSERT OR REPLACE INTO firebase_records (collection, record_key, data_json) VALUES (?, ?, ?)",
                            (collection, record_key, json.dumps(value, ensure_ascii=False)),
                        )
                    continue
                row = db.execute(
                    "SELECT data_json FROM firebase_records WHERE collection = ? AND record_key = ?",
                    (collection, record_key),
                ).fetchone()
                current = json.loads(row[0]) if row else {}
                field_path = parts[2:]
                target = current
                for field in field_path[:-1]:
                    target = target.setdefault(field, {})
                target[field_path[-1]] = value
                db.execute(
                    "INSERT OR REPLACE INTO firebase_records (collection, record_key, data_json) VALUES (?, ?, ?)",
                    (collection, record_key, json.dumps(current, ensure_ascii=False)),
                )
        self.respond(200, {"ok": True})

    def log_message(self, *_):
        return


if __name__ == "__main__":
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    database().close()
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
