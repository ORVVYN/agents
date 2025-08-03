import asyncio
import os
import imaplib
import email
from email.header import decode_header
from typing import Tuple

from telegram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from db.session import get_session
from db import models
from agents.negotiation import process_supplier_reply

IMAP_HOST = os.getenv("IMAP_HOST")
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")

if not IMAP_HOST:
    raise RuntimeError("IMAP settings not configured (set IMAP_HOST, IMAP_USER, IMAP_PASSWORD)")

# interval minutes
POLL_INTERVAL = int(os.getenv("IMAP_POLL_INTERVAL", "3"))


def _connect() -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL(IMAP_HOST)
    imap.login(IMAP_USER, IMAP_PASSWORD)
    return imap


def _parse_email(msg_bytes: bytes) -> Tuple[str, str, str]:
    """Return (from_email, subject, plain_text_body)"""
    msg = email.message_from_bytes(msg_bytes)
    from_email = email.utils.parseaddr(msg.get("From"))[1]
    subject_raw = msg.get("Subject", "")
    try:
        dh = decode_header(subject_raw)[0]
        subject = dh[0].decode(dh[1]) if isinstance(dh[0], bytes) else dh[0]
    except Exception:
        subject = subject_raw

    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition"))
            if ctype == "text/plain" and "attachment" not in disp:
                charset = part.get_content_charset() or "utf-8"
                body = part.get_payload(decode=True).decode(charset, errors="ignore")
                break
    else:
        charset = msg.get_content_charset() or "utf-8"
        body = msg.get_payload(decode=True).decode(charset, errors="ignore")
    return from_email, subject, body


async def _poll(bot: Bot):
    imap = _connect()
    imap.select("INBOX")
    status, data = imap.search(None, "UNSEEN")
    if status != "OK":
        imap.logout()
        return
    for num in data[0].split():
        status, msg_data = imap.fetch(num, "(RFC822)")
        if status != "OK":
            continue
        raw_email = msg_data[0][1]
        from_email, subject, body = _parse_email(raw_email)

        # find supplier by email
        session = get_session()
        supplier = session.query(models.Supplier).filter_by(email=from_email).first()
        if not supplier:
            session.close()
            continue
        # find active application
        app = (
            session.query(models.Application)
            .filter_by(supplier_id=supplier.id)
            .filter(models.Application.status.like("negotiation%"))
            .order_by(models.Application.created_at.desc())
            .first()
        )
        session.close()
        if not app:
            continue

        # pass to negotiation handler
        await process_supplier_reply(app.id, body, bot)

        # mark seen
        imap.store(num, "+FLAGS", "(\\Seen)")
    imap.logout()


def start_email_polling(bot: Bot):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(_poll, "interval", minutes=POLL_INTERVAL, args=[bot])
    scheduler.start()
