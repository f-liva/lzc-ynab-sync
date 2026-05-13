from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class SyncTransaction(BaseModel):
    source_id: str
    date: datetime
    amount: Decimal  # positive = inflow, negative = outflow
    payee: str
    memo: str | None = None
    currency: str = "EUR"
    is_pending: bool = False


class SyncConnector(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def authenticate(self) -> bool: ...

    @abstractmethod
    def fetch_transactions(self, since: datetime) -> list[SyncTransaction]: ...
