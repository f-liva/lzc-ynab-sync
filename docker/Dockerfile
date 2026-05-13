FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY ynab_sync/ ynab_sync/

RUN mkdir -p /data

EXPOSE 8080

CMD ["python3", "-m", "ynab_sync.main"]
