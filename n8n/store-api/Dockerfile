FROM python:3.12-alpine

WORKDIR /app
COPY app.py /app/app.py

RUN adduser -D -u 10001 appuser && mkdir -p /data && chown -R appuser:appuser /data
USER appuser

EXPOSE 8000
CMD ["python", "/app/app.py"]
