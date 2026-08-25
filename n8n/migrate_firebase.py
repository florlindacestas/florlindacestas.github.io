import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone


COLLECTIONS = (
    "orders",
    "products",
    "clients",
    "finance",
    "drivers",
    "deliveries",
    "pending_payments",
)


def migrate(source_path, database_path):
    with open(source_path, "rb") as source:
        raw = source.read()
    payload = json.loads(raw)

    db = sqlite3.connect(database_path)
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS firebase_records (
            collection TEXT NOT NULL,
            record_key TEXT NOT NULL,
            data_json TEXT NOT NULL,
            PRIMARY KEY (collection, record_key)
        );
        CREATE TABLE IF NOT EXISTS migration_meta (
            name TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS firebase_root (
            name TEXT PRIMARY KEY,
            data_json TEXT NOT NULL
        );
        """
    )

    counts = {}
    with db:
        for name, value in payload.items():
            if name not in COLLECTIONS:
                db.execute(
                    "INSERT OR REPLACE INTO firebase_root (name, data_json) VALUES (?, ?)",
                    (name, json.dumps(value, ensure_ascii=False, separators=(",", ":"))),
                )
        for collection in COLLECTIONS:
            records = payload.get(collection) or {}
            if not isinstance(records, dict):
                records = {}
            count = 0
            for record_key, value in records.items():
                db.execute(
                    "INSERT OR REPLACE INTO firebase_records (collection, record_key, data_json) VALUES (?, ?, ?)",
                    (collection, str(record_key), json.dumps(value, ensure_ascii=False, separators=(",", ":"))),
                )
                count += 1
            counts[collection] = count

        db.execute(
            "INSERT OR REPLACE INTO migration_meta (name, value) VALUES (?, ?)",
            ("source_sha256", hashlib.sha256(raw).hexdigest()),
        )
        db.execute(
            "INSERT OR REPLACE INTO migration_meta (name, value) VALUES (?, ?)",
            ("source_schema_version", str(payload.get("schemaVersion", ""))),
        )
        db.execute(
            "INSERT OR REPLACE INTO migration_meta (name, value) VALUES (?, ?)",
            ("migrated_at", datetime.now(timezone.utc).isoformat()),
        )
    db.close()
    return counts


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: migrate_firebase.py EXPORT_JSON SQLITE_DB")
    result = migrate(sys.argv[1], sys.argv[2])
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
