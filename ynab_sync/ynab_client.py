import logging
from decimal import Decimal

import httpx

logger = logging.getLogger(__name__)

YNAB_API = "https://api.ynab.com/v1"


class YNABClient:
    def __init__(self, api_key: str, budget_id: str, account_name: str = "Gnosis"):
        self._client = httpx.Client(
            base_url=YNAB_API,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        self.budget_id = budget_id
        self.account_name = account_name
        self._account_id: str | None = None

    def _milliunits(self, amount: Decimal) -> int:
        return int(amount * 1000)

    def _lookup_account_id(self) -> str:
        if self._account_id:
            return self._account_id
        resp = self._client.get(f"/budgets/{self.budget_id}/accounts")
        resp.raise_for_status()
        accounts = resp.json()["data"]["accounts"]
        for acc in accounts:
            if acc["name"].lower() == self.account_name.lower():
                self._account_id = acc["id"]
                logger.info("Found YNAB account '%s' = %s", acc["name"], acc["id"])
                return acc["id"]
        raise ValueError(f"Account '{self.account_name}' not found in YNAB budget")

    def find_transaction(self, amount: Decimal, date: str, payee: str) -> dict | None:
        account_id = self._lookup_account_id()
        milli = abs(self._milliunits(amount))
        since = date[:10]
        resp = self._client.get(
            f"/budgets/{self.budget_id}/transactions",
            params={"since_date": since, "type": "unapproved"},
        )
        if resp.status_code != 200:
            return None
        txns = resp.json().get("data", {}).get("transactions", [])
        for t in txns:
            if t.get("account_id") != account_id:
                continue
            if abs(t.get("amount", 0)) != milli:
                continue
            return t
        return None

    def create_transaction(
        self, amount: Decimal, payee: str, date: str, cleared: bool,
        memo: str | None = None, source_id: str | None = None,
    ) -> dict:
        account_id = self._lookup_account_id()
        body = {
            "transaction": {
                "account_id": account_id,
                "date": date,
                "amount": self._milliunits(amount),
                "payee_name": payee,
                "cleared": "cleared" if cleared else "uncleared",
                "approved": False,
            }
        }
        if memo:
            body["transaction"]["memo"] = memo
        resp = self._client.post(
            f"/budgets/{self.budget_id}/transactions",
            json=body,
        )
        resp.raise_for_status()
        created = resp.json()["data"]["transaction"]
        logger.info("Created YNAB transaction: %s %s (%s)", payee, amount, date)
        return created

    def update_cleared(self, transaction_id: str) -> dict:
        resp = self._client.put(
            f"/budgets/{self.budget_id}/transactions/{transaction_id}",
            json={"transaction": {"cleared": "cleared"}},
        )
        resp.raise_for_status()
        return resp.json()["data"]["transaction"]

    def close(self):
        self._client.close()
