# YNAB Sync — Design Document

## Overview

**YNAB Sync** is a lightweight Docker container that periodically syncs transactions from external payment sources (connectors) into YNAB. It starts with Gnosis Pay as the first connector, with a pluggable architecture for future sources (PayPal, ING, Revolut, etc.).

## Architecture

Single Docker container with three concurrent threads:

```ascii
┌─────────────────────────────────────────────┐
│              lzc-ynab-sync                   │
│                                              │
│  ┌──────────┐    ┌──────────────────────┐   │
│  │ Scheduler ├────►   Sync Worker        │   │
│  │ (hourly)  │    │                      │   │
│  └──────────┘    │ ① Auth → Connector    │   │
│                  │ ② Fetch transactions  │   │
│  ┌──────────┐    │ ③ Match/Create YNAB   │   │
│  │ Flask    │    │ ④ Update clearing     │   │
│  │ :8080    │    │ ⑤ Log → SQLite        │   │
│  │ /log     │    └──────────┬────────────┘   │
│  └──────────┘               │                │
│                             │                │
│  /data/                                     │
│   ├── ynab_sync.db                          │
│   └── jwt_cache.json                        │
└─────────────────────────────────────────────┘
```

### Components

- **Scheduler**: `APScheduler` running the sync every hour
- **Sync Worker**: executes connector fetch → YNAB push logic per cycle, all synchronous HTTP calls via `httpx`
- **Flask Web Server**: port 8080, serves log/history page
- **SQLite DB**: persistent state (sync log + transaction mappings)

## Connector Interface

```python
class SyncConnector(ABC):
    name: str  # e.g., "gnosis"
    def authenticate() -> bool
    def fetch_transactions(since: datetime) -> list[SyncTransaction]
```

`SyncTransaction` is a canonical model:

```python
class SyncTransaction(BaseModel):
    source_id: str          # unique ID in source system (e.g., Gnosis threadId)
    date: datetime
    amount: Decimal         # positive = inflow, negative = outflow
    payee: str
    memo: str | None
    currency: str           # ISO 4217
    is_pending: bool
```

## Gnosis Connector Details

### Auth Flow (SIWE)

1. `GET /api/v1/auth/nonce` → get nonce
2. Construct SIWE message: domain, address, URI, nonce
3. Sign with `eth_account.Account.sign_message()` using private key (EIP-191)
4. `POST /api/v1/auth/challenge` with message + signature → JWT
5. JWT cached in `jwt_cache.json`; re-auth only on 401 or expiry

### Transaction Fetch

- `GET /api/v1/cards/transactions?after=<last_sync_time>`
- Handles pagination (limit=100, offset)
- Filters out reversals upstream-linked (deduplicated via threadId)

## Sync Flow (per cycle)

1. Authenticate to Gnosis Pay (or use cached JWT)
2. Fetch all transactions since `last_sync_time` (from DB)
3. For each Gnosis transaction, ordered by date:
   a. Look up `gnosis_thread_id` in `transaction_map` table:
      - **Found + pending** → skip (already created uncleared)
      - **Found + cleared** → skip (already cleared in YNAB)
      - **Not found + is_pending** → create in YNAB (cleared=false), store mapping
      - **Not found + is_cleared** → create in YNAB (cleared=true), store mapping
4. For any mapped transaction that transitioned from pending → cleared:
   - Update YNAB transaction: `cleared=cleared`
5. Update `last_sync_time`
6. Write sync log entry

### Deduplication Strategy

- Primary key: `gnosis_threadId → ynab_transaction_id` mapping in DB
- Before creating: search YNAB for matching amount + date (±1 day) + payee similarity
  (rapidfuzz >85%) as final guard against race conditions
- `memo` field stores `Gnosis: <merchant.city> | thread:<threadId>`

## Database Schema

### sync_log
```sql
CREATE TABLE sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connector TEXT NOT NULL,          -- 'gnosis'
    started_at TEXT NOT NULL,         -- ISO 8601
    finished_at TEXT,
    status TEXT NOT NULL,             -- 'running', 'success', 'error'
    created_count INTEGER DEFAULT 0,
    cleared_count INTEGER DEFAULT 0,  -- status transitions
    skipped_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    error_detail TEXT,
    details TEXT                      -- JSON array of new txns
);
```

### transaction_map
```sql
CREATE TABLE transaction_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connector TEXT NOT NULL,          -- 'gnosis'
    source_id TEXT NOT NULL,          -- Gnosis threadId
    ynab_transaction_id TEXT NOT NULL,
    ynab_account_id TEXT NOT NULL,
    status TEXT NOT NULL,             -- 'pending', 'cleared'
    amount TEXT NOT NULL,             -- Decimal as string
    payee TEXT NOT NULL,
    created_at TEXT NOT NULL,
    cleared_at TEXT,
    UNIQUE(connector, source_id)
);
```

### sync_state
```sql
CREATE TABLE sync_state (
    connector TEXT PRIMARY KEY,       -- 'gnosis'
    last_sync_time TEXT NOT NULL,     -- ISO 8601
    last_source_id TEXT               -- last threadId seen
);
```

## YNAB Integration

- Uses YNAB API v1 directly via `httpx`
- Amounts converted to milliunits (multiply by 1000)
- Fetch YNAB account ID from account name "Gnosis" at startup (cached)
- Transactions created with `approved=false` for manual review
- Category left null → YNAB auto-assigns based on payee history; first occurrence stays uncategorized until user assigns once
- Rate limit: ~200 req/h, conservative (we do ~10 req/cycle max)

## Web UI

Single page at `/` rendered via Flask + Jinja2:

- **Table**: last 50 sync runs (pagination)
  - Columns: datetime, connector, status badge, created/cleared/skipped/error counts
- **Row detail**: expandable JSON showing transactions created that cycle
- **Auto-refresh**: meta refresh every 30s
- **Recent errors** highlighted in red

## Configuration (Env Vars)

| Variable | Required | Description |
|----------|----------|-------------|
| `YNAB_SYNC_API_KEY` | yes | YNAB Personal Access Token |
| `YNAB_SYNC_BUDGET_ID` | yes | YNAB budget ID |
| `YNAB_SYNC_ACCOUNT_NAME` | no | Default "Gnosis" |
| `YNAB_SYNC_GNOSIS_PK` | yes | Ethereum private key (no 0x prefix) |
| `YNAB_SYNC_GNOSIS_ADDRESS` | yes | Safe address for SIWE auth |
| `YNAB_SYNC_INTERVAL` | no | Minutes between syncs, default 60 |
| `YNAB_SYNC_PORT` | no | Default 8080 |
| `YNAB_SYNC_LOG_LEVEL` | no | Default "INFO" |

## Docker

- Base: `python:3.11-slim`
- Dependencies: flask, apscheduler, httpx, eth-account, pydantic, sqlalchemy
- Volume mount: `/data` for SQLite + JWT cache
- Healthcheck: `curl -f http://localhost:8080/`
- Non-root user: `appuser` (uid 1000)

## Lazycat

Manifest with:
- Route: `/=http://ynab-sync.cloud.lazycat.app.ynab-sync.lzcapp:8080`
- Bind: `/lzcapp/var/data:/data`
- Env vars for all configuration

## Connector Roadmap (not in v1)

- PayPal connector
- ING Bank connector (reuse existing CSV parser from ynab-reconciler)
- Revolut connector
- Each connector is a single file in `connectors/` implementing `SyncConnector`
