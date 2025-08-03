"""amoCRM integration helpers.

Handles lead creation and status updates for buyer applications.
Currently only applications (buyer requests) are synced; suppliers are NOT pushed.

Usage:
    from integrations.amocrm import AmoClient
    amo = AmoClient()
    lead_id = await amo.create_lead(application, buyer)
    await amo.update_status(lead_id, new_status_id)
"""
from __future__ import annotations

import os
import logging
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("AMO_DOMAIN", "https://2104454.amocrm.ru").rstrip("/")
API_BASE = f"{BASE_URL}/api/v4"
ACCESS_TOKEN = os.getenv("AMO_ACCESS_TOKEN")

# Pipeline & status IDs (should be stored in .env)
PIPELINE_ID = int(os.getenv("AMO_PIPELINE_ID", "0"))  # required
STATUS_NEW = int(os.getenv("AMO_STATUS_NEW", "0"))
STATUS_WORK = int(os.getenv("AMO_STATUS_WORK", "0"))
STATUS_DONE = int(os.getenv("AMO_STATUS_DONE", "0"))
STATUS_LOST = int(os.getenv("AMO_STATUS_LOST", "0"))

STATUS_MAP = {
    "new": STATUS_NEW,
    "searching": STATUS_WORK or STATUS_NEW,
    "manager_review": STATUS_WORK,
    "negotiating": STATUS_WORK,
    "info_requested": STATUS_WORK,
    "closed": STATUS_DONE,
    "rejected": STATUS_LOST,
}


# Helper to safely convert env var to int (handles unset or empty)

def _env_int(key: str) -> int:
    val = os.getenv(key)
    try:
        return int(val) if val else 0
    except ValueError:
        return 0

# Custom field IDs (integers)
CF_CITY = _env_int("AMO_CF_CITY")
CF_ADDRESS = _env_int("AMO_CF_ADDRESS")
CF_VOLUME = _env_int("AMO_CF_VOLUME")
CF_BUYER = _env_int("AMO_CF_BUYER")
CF_PHONE = _env_int("AMO_CF_PHONE")
CF_EMAIL = _env_int("AMO_CF_EMAIL")

TIMEOUT = httpx.Timeout(10.0, read=15.0)


class AmoAuthError(RuntimeError):
    """Unauthorized / token expired"""


class AmoClient:
    """Small async HTTP wrapper for amoCRM."""

    def __init__(self):
        if not ACCESS_TOKEN:
            raise RuntimeError("AMO_ACCESS_TOKEN env var is not set")
        if PIPELINE_ID == 0 or STATUS_NEW == 0:
            raise RuntimeError("AMO pipeline/status IDs are not configured in .env")
        self.headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "ai-supplier-bot/1.0",
        }
        self.client = httpx.AsyncClient(headers=self.headers, timeout=TIMEOUT, base_url=API_BASE)

    async def _request(self, method: str, url: str, **kwargs) -> Any:
        logger.debug("amoCRM %s %s payload=%s", method, url, kwargs.get("json") or kwargs.get("params"))
        resp = await self.client.request(method, url, **kwargs)
        logger.debug("amoCRM response %s %s", resp.status_code, resp.text[:500])
        if resp.status_code == 401:
            raise AmoAuthError("Unauthorized to amoCRM – check ACCESS_TOKEN")
        if resp.is_error:
            logger.error("amoCRM error %s %s: %s", method, url, resp.text)
            resp.raise_for_status()
        if resp.status_code == 204:
            return None
        return resp.json()

    async def create_lead(self, application, buyer) -> int:
        """Create lead in amoCRM for given application & buyer; returns lead_id."""
        payload = [self._lead_payload(application, buyer)]
        data = await self._request("POST", "/leads", json=payload)
        lead_id = data["_embedded"]["leads"][0]["id"]
        logger.info("Created amoCRM lead %s for app %s", lead_id, application.id)
        return lead_id

    async def update_status(self, lead_id: int, status_id: int):
        body = {"status_id": status_id}
        await self._request("PATCH", f"/leads/{lead_id}", json=body)
        logger.info("amoCRM lead %s set to status %s", lead_id, status_id)

    # ---------------------------------------------------------------------
    def _lead_payload(self, app, buyer) -> Dict[str, Any]:
        """Build payload dict for lead creation."""
        cf_values: List[Dict[str, Any]] = []
        def add_cf(field_id: int, value: str | None):
            if field_id and value:
                cf_values.append({"field_id": field_id, "values": [{"value": value}]})

        # Only include phone/email as custom fields; city, address and volume are no longer used.
        add_cf(CF_PHONE, buyer.phone if buyer else None)
        add_cf(CF_EMAIL, buyer.email if buyer else None)

        volume = None
        if hasattr(app, "collected"):
            volume = app.collected.get("volume")
        # Fallback: try attribute directly
        volume = volume or getattr(app, "volume", None)

        lead_body = {
            "name": f"Заявка #{app.id} | {app.search_term or ''}",
            "pipeline_id": PIPELINE_ID,
            # status_id removed – amoCRM will assign the first status of the pipeline automatically
            "price": volume or 0,
            "custom_fields_values": cf_values,
            "request_id": f"app-{app.id}",
        }

        # Embed contact if buyer info present
        if buyer and (buyer.full_name or buyer.phone):
            contact_cf = []
            if buyer.phone:
                contact_cf.append({
                    "field_code": "PHONE",
                    "values": [{"value": buyer.phone, "enum_code": "WORK"}],
                })
            if buyer.email:
                contact_cf.append({
                    "field_code": "EMAIL",
                    "values": [{"value": buyer.email, "enum_code": "WORK"}],
                })
            contact = {
                "first_name": buyer.full_name or buyer.name or buyer.username or "Покупатель",
                "custom_fields_values": contact_cf,
            }
            lead_body["_embedded"] = {"contacts": [contact]}

        return lead_body

    async def close(self):
        await self.client.aclose()
