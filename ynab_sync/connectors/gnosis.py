import json
import logging
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct

from .base import SyncConnector, SyncTransaction

logger = logging.getLogger(__name__)

SIWE_DOMAIN = "app.gnosispay.com"
GP_API = "https://api.gnosispay.com"


class GnosisConnector(SyncConnector):
    def __init__(
        self,
        private_key: str,
        safe_address: str,
        jwt_cache: str = "/data/jwt_cache.json",
    ):
        self._pk = private_key
        self._safe_address = safe_address.lower()
        self._jwt_cache = Path(jwt_cache)
        self._jwt: str | None = None
        self._client = httpx.Client(base_url=GP_API)

    @property
    def name(self) -> str:
        return "gnosis"

    def _load_cached_jwt(self) -> str | None:
        if not self._jwt_cache.exists():
            return None
        try:
            data = json.loads(self._jwt_cache.read_text())
            if data.get("expires_at", 0) > time.time():
                return data["token"]
        except (json.JSONDecodeError, KeyError):
            pass
        return None

    def _save_jwt(self, token: str, ttl: int):
        self._jwt_cache.parent.mkdir(parents=True, exist_ok=True)
        self._jwt_cache.write_text(json.dumps({
            "token": token,
            "expires_at": time.time() + ttl - 300,  # 5min buffer
        }))

    def _siwe_login(self) -> str:
        nonce_resp = self._client.get("/api/v1/auth/nonce")
        nonce_resp.raise_for_status()
        nonce = nonce_resp.json()["nonce"]

        message = (
            f"{SIWE_DOMAIN} wants you to sign in with your Ethereum account:\n"
            f"{self._safe_address}\n\n"
            f"Sign in to Gnosis Pay\n\n"
            f"URI: https://{SIWE_DOMAIN}/login\n"
            f"Version: 1\n"
            f"Chain ID: 100\n"
            f"Nonce: {nonce}\n"
            f"Issued At: {datetime.utcnow().isoformat()}Z"
        )

        signed = Account.sign_message(encode_defunct(text=message), self._pk)

        challenge_resp = self._client.post(
            "/api/v1/auth/challenge",
            json={
                "message": message,
                "signature": signed.signature.hex(),
                "ttlInSeconds": 3600,
            },
        )
        challenge_resp.raise_for_status()
        token = challenge_resp.json()["jwt"]
        self._save_jwt(token, 3600)
        logger.info("Gnosis SIWE auth successful")
        return token

    def authenticate(self) -> bool:
        cached = self._load_cached_jwt()
        if cached:
            self._jwt = cached
            logger.debug("Using cached JWT")
            return True
        try:
            self._jwt = self._siwe_login()
            return True
        except Exception as e:
            logger.error("Gnosis auth failed: %s", e)
            return False

    def fetch_transactions(self, since: datetime) -> list[SyncTransaction]:
        if not self._jwt:
            if not self.authenticate():
                return []

        params = {"limit": 100, "offset": 0}
        if since:
            params["after"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")

        result: list[SyncTransaction] = []
        while True:
            resp = self._client.get(
                "/api/v1/cards/transactions",
                params=params,
                headers={"Authorization": f"Bearer {self._jwt}"},
            )
            if resp.status_code == 401:
                self._jwt = self._siwe_login()
                resp = self._client.get(
                    "/api/v1/cards/transactions",
                    params=params,
                    headers={"Authorization": f"Bearer {self._jwt}"},
                )
            resp.raise_for_status()
            data = resp.json()
            for event in data.get("results", []):
                kind = event.get("kind")
                if kind == "Reversal":
                    continue
                date_str = event.get("createdAt", "")
                parsed_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                billing_amount = Decimal(event.get("billingAmount", "0"))
                is_refund = kind == "Refund"
                amount = billing_amount if not is_refund else -billing_amount
                if amount > 0 and not is_refund:
                    amount = -amount
                merchant = event.get("merchant", {})
                merchant_name = merchant.get("name", "Unknown")
                city = merchant.get("city", "")
                memo_parts = [f"Gnosis: {city}"] if city else ["Gnosis"]
                memo_parts.append(f"thread:{event.get('threadId', '')}")
                result.append(SyncTransaction(
                    source_id=event.get("threadId", ""),
                    date=parsed_date,
                    amount=amount,
                    payee=merchant_name,
                    memo=" | ".join(memo_parts),
                    currency=event.get("billingCurrency", {}).get("code", "EUR"),
                    is_pending=event.get("isPending", False),
                ))
            if not data.get("next"):
                break
            params["offset"] += params["limit"]

        logger.info("Gnosis: fetched %d transactions since %s", len(result), since)
        return result
