import logging
import os
import threading

from apscheduler.schedulers.background import BackgroundScheduler

from .app import create_app
from .connectors.gnosis import GnosisConnector
from .models import init_db
from .sync_worker import run_sync
from .ynab_client import YNABClient

logger = logging.getLogger(__name__)


def _sync_job(db_path: str):
    pk = os.environ["YNAB_SYNC_GNOSIS_PK"]
    address = os.environ["YNAB_SYNC_GNOSIS_ADDRESS"]
    api_key = os.environ["YNAB_SYNC_API_KEY"]
    budget_id = os.environ["YNAB_SYNC_BUDGET_ID"]
    account_name = os.environ.get("YNAB_SYNC_ACCOUNT_NAME", "Gnosis")

    connector = GnosisConnector(pk, address)
    ynab = YNABClient(api_key, budget_id, account_name)
    try:
        run_sync(connector, ynab, db_path)
    finally:
        ynab.close()


def main():
    logging.basicConfig(
        level=os.environ.get("YNAB_SYNC_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    db_path = os.environ.get("YNAB_SYNC_DB_PATH", "/data/ynab_sync.db")
    port = int(os.environ.get("YNAB_SYNC_PORT", "8080"))
    interval = int(os.environ.get("YNAB_SYNC_INTERVAL", "60"))

    os.makedirs(os.path.dirname(db_path) if "/" in db_path else ".", exist_ok=True)
    init_db(db_path)

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _sync_job,
        trigger="interval",
        minutes=interval,
        args=[db_path],
        id="sync_gnosis",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: syncing every %d minutes", interval)

    # Run first sync immediately
    threading.Thread(target=_sync_job, args=[db_path], daemon=True).start()

    app = create_app(db_path)
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
