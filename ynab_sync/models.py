import json
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class SyncLog(Base):
    __tablename__ = "sync_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    connector = Column(String(50), nullable=False)
    started_at = Column(String(30), nullable=False, default=lambda: datetime.utcnow().isoformat())
    finished_at = Column(String(30), nullable=True)
    status = Column(String(20), nullable=False, default="running")
    created_count = Column(Integer, default=0)
    cleared_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    error_detail = Column(Text, nullable=True)
    details = Column(Text, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "connector": self.connector,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "created_count": self.created_count,
            "cleared_count": self.cleared_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "error_detail": self.error_detail,
            "details": json.loads(self.details) if self.details else None,
        }


class TransactionMap(Base):
    __tablename__ = "transaction_map"

    id = Column(Integer, primary_key=True, autoincrement=True)
    connector = Column(String(50), nullable=False)
    source_id = Column(String(100), nullable=False)
    ynab_transaction_id = Column(String(100), nullable=False)
    ynab_account_id = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    amount = Column(String(30), nullable=False)
    payee = Column(String(255), nullable=False)
    created_at = Column(String(30), nullable=False, default=lambda: datetime.utcnow().isoformat())
    cleared_at = Column(String(30), nullable=True)

    __table_args__ = (
        UniqueConstraint("connector", "source_id", name="uq_connector_source"),
    )


class SyncState(Base):
    __tablename__ = "sync_state"

    connector = Column(String(50), primary_key=True)
    last_sync_time = Column(String(30), nullable=False)
    last_source_id = Column(String(100), nullable=True)


def init_db(db_path: str) -> "sqlalchemy.engine.Engine":
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return engine
