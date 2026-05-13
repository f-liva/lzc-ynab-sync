import json
import logging
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SASession

from .models import SyncLog, TransactionMap, SyncState
from .connectors.base import SyncConnector
from .ynab_client import YNABClient

logger = logging.getLogger(__name__)


def run_sync(
    connector: SyncConnector,
    ynab: YNABClient,
    db_path: str,
):
    engine = create_engine(f"sqlite:///{db_path}")

    with SASession(engine) as session:
        state = session.query(SyncState).filter_by(connector=connector.name).first()
        last_sync = datetime.fromisoformat(state.last_sync_time) if state else datetime(2000, 1, 1)

        log_entry = SyncLog(
            connector=connector.name,
            started_at=datetime.utcnow().isoformat(),
            status="running",
        )
        session.add(log_entry)
        session.commit()
        log_id = log_entry.id

    try:
        if not connector.authenticate():
            raise RuntimeError("Connector authentication failed")

        txns = connector.fetch_transactions(last_sync)

        created = 0
        cleared = 0
        skipped = 0
        errors = 0
        new_txns = []

        with SASession(engine) as session:
            for txn in txns:
                try:
                    existing_map = session.query(TransactionMap).filter_by(
                        connector=connector.name, source_id=txn.source_id
                    ).first()

                    if existing_map:
                        if existing_map.status == "pending" and not txn.is_pending:
                            ynab.update_cleared(existing_map.ynab_transaction_id)
                            existing_map.status = "cleared"
                            existing_map.cleared_at = datetime.utcnow().isoformat()
                            cleared += 1
                            logger.info("Cleared txn: %s", txn.source_id)
                        else:
                            skipped += 1
                        continue

                    existing_ynab = ynab.find_transaction(
                        txn.amount, txn.date.strftime("%Y-%m-%d"), txn.payee
                    )
                    if existing_ynab:
                        ynab_tid = existing_ynab["id"]
                        status = "cleared" if existing_ynab.get("cleared") == "cleared" else "pending"
                    else:
                        ynab_txn = ynab.create_transaction(
                            amount=txn.amount,
                            payee=txn.payee,
                            date=txn.date.strftime("%Y-%m-%d"),
                            cleared=not txn.is_pending,
                            memo=txn.memo,
                            source_id=txn.source_id,
                        )
                        ynab_tid = ynab_txn["id"]
                        status = "cleared" if not txn.is_pending else "pending"
                        created += 1
                        new_txns.append({
                            "source_id": txn.source_id,
                            "ynab_id": ynab_tid,
                            "payee": txn.payee,
                            "amount": str(txn.amount),
                            "status": status,
                        })

                    mapping = TransactionMap(
                        connector=connector.name,
                        source_id=txn.source_id,
                        ynab_transaction_id=ynab_tid,
                        ynab_account_id=ynab._lookup_account_id(),
                        status=status,
                        amount=str(txn.amount),
                        payee=txn.payee,
                        created_at=datetime.utcnow().isoformat(),
                        cleared_at=datetime.utcnow().isoformat() if not txn.is_pending else None,
                    )
                    session.add(mapping)
                    session.commit()

                except Exception as e:
                    errors += 1
                    logger.error("Error processing txn %s: %s", txn.source_id, e)
                    session.rollback()

        with SASession(engine) as session:
            le = session.query(SyncLog).filter_by(id=log_id).first()
            le.status = "success"
            le.finished_at = datetime.utcnow().isoformat()
            le.created_count = created
            le.cleared_count = cleared
            le.skipped_count = skipped
            le.error_count = errors
            le.details = json.dumps(new_txns) if new_txns else None

            if txns:
                latest = max(t.date for t in txns)
                st = session.query(SyncState).filter_by(connector=connector.name).first()
                if not st:
                    st = SyncState(connector=connector.name)
                    session.add(st)
                st.last_sync_time = latest.isoformat()
                st.last_source_id = txns[-1].source_id

            session.commit()

        logger.info(
            "Sync complete: %d created, %d cleared, %d skipped, %d errors",
            created, cleared, skipped, errors,
        )

    except Exception as e:
        logger.error("Sync failed: %s", e)
        with SASession(engine) as session:
            le = session.query(SyncLog).filter_by(id=log_id).first()
            le.status = "error"
            le.finished_at = datetime.utcnow().isoformat()
            le.error_detail = str(e)
            session.commit()
