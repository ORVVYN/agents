"""Stub implementations of contact actions (call, email, WhatsApp).
In the future these will integrate with Twilio, SMTP, WhatsApp API, etc.
For now they just return a confirmation string and log the intent."""

import logging
from db.models import Supplier, Application
from typing import Optional

logger = logging.getLogger(__name__)


def _supplier_ident(s: Supplier) -> str:
    return f"{s.name} (id={s.id})"


async def call_supplier(supplier: Supplier, application: Optional[Application] = None) -> str:
    logger.info("[Stub] Would call supplier %s, phone=%s app=%s", _supplier_ident(supplier), supplier.phone, application.id if application else None)
    return f"[Stub] Звонок поставщику {supplier.phone} запланирован."


async def email_supplier(supplier: Supplier, application: Optional[Application] = None, subject: str | None = None, body: str | None = None) -> str:
    logger.info("[Stub] Would email supplier %s, email=%s app=%s", _supplier_ident(supplier), supplier.email, application.id if application else None)
    return f"[Stub] Письмо будет отправлено на {supplier.email}."


async def whatsapp_supplier(supplier: Supplier, application: Optional[Application] = None, text: str | None = None) -> str:
    logger.info("[Stub] Would WhatsApp supplier %s, wa=%s app=%s", _supplier_ident(supplier), supplier.whatsapp, application.id if application else None)
    return f"[Stub] Сообщение WhatsApp будет отправлено на {supplier.whatsapp}."
