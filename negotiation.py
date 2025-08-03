import os, json, re, asyncio
from email.message import EmailMessage

from telegram.ext import ContextTypes

from dotenv import load_dotenv
from aiosmtplib import send

from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain.memory import ConversationBufferMemory

from agents.llm_agent import LLMAgent

from db.session import get_session
from db import models

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
FROM_EMAIL = SMTP_USER

if not SMTP_HOST:
    raise RuntimeError("SMTP settings not configured")


# ---------- Helper for sending mail ----------


async def _send_email(to_address: str, subject: str, body: str):
    msg = EmailMessage()
    msg["From"] = FROM_EMAIL
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.set_content(body)
    await send(
        msg,
        hostname=SMTP_HOST,
        port=SMTP_PORT,
        username=SMTP_USER,
        password=SMTP_PASSWORD,
        start_tls=True,
    )


# ---------- Negotiation Agent ----------


def _build_memory(app_id: int):
    """Return ConversationBufferMemory backed by persistent SQL storage."""
    chat_history = SQLChatMessageHistory(
        connection_string="sqlite:///data/ai_memory.db",
        session_id=str(app_id),
    )
    return ConversationBufferMemory(memory_key="history", return_messages=True, chat_memory=chat_history)


def _build_negotiation_agent(app_id: int) -> LLMAgent:
    persona = (
        """
        Ты — закупщик-переговорщик: вежливый, но настойчивый. Твоя миссия — добиться лучших условий.
        Всегда веди переписку на русском. Используй деловой/дружелюбный тон, избегай шаблонов.
        На вход ты будешь получать структуру JSON с ключами role (system/user/assistant/supplier) и content.
        Если role == "system", там информация о заявке, поставщике и покупателе. Сформируй первое письмо.
        Если role == "supplier", это ответ поставщика — проанализируй и сформируй следующий шаг.
        Всегда возвращай JSON {"subject": "...", "body": "...", "done": bool, "summary": "..."}. 
        Если done==true, переговоры завершены согласованием условий.
        """
    )
    memory = _build_memory(app_id)
    return LLMAgent(persona_system_prompt=persona, memory=memory, temperature=0.4)


async def start_negotiation(app_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Initiate negotiation workflow via AI-generated email."""
    session = get_session()
    app: models.Application | None = session.query(models.Application).get(app_id)
    if not app or not app.supplier_id:
        session.close()
        return

    supplier = session.query(models.Supplier).get(app.supplier_id)

    agent = _build_negotiation_agent(app_id)

    # Compose system info for first prompt
    sys_info = {
        "role": "system",
        "content": (
            f"Supplier: {supplier.name}. Email: {supplier.email}.\n"
            f"Requester: {app.requester.full_name or app.requester.username}.\n"
            f"Details: {app.details}"
        ),
    }

    # Ask LLM for first email
    ai_resp = await agent.reply(json.dumps(sys_info, ensure_ascii=False))

    try:
        data = json.loads(re.search(r"\{.*\}", ai_resp, re.S).group())
    except Exception:
        # fallback
        data = {"subject": "Запрос коммерческого предложения", "body": ai_resp, "done": False}

    subject, body = data["subject"], data["body"]

    to_email = supplier.email or "info@example.com"
    try:
        await _send_email(to_email, subject, body)
        status_note = "email_sent"
    except Exception as e:
        status_note = f"email_failed:{e}"

    email_rec = models.EmailRecord(
        application_id=app.id, to_address=to_email, subject=subject, body=body, direction="out"
    )
    session.add(email_rec)

    app.status = "negotiation_email_sent"
    session.commit()
    session.close()

    # Notify requester chat
    await context.bot.send_message(
        chat_id=app.requester.telegram_id,
        text="Мы отправили запрос поставщику, сообщим о ходе переговоров.",
    )


# ---------- Reply Handler ----------


async def process_supplier_reply(app_id: int, supplier_text: str, context: ContextTypes.DEFAULT_TYPE):
    """Record supplier reply and ask LLM for next step (counter-offer or conclude)."""
    session = get_session()
    app: models.Application | None = session.query(models.Application).get(app_id)
    if not app:
        session.close()
        return "Заявка не найдена"

    supplier = session.query(models.Supplier).get(app.supplier_id) if app.supplier_id else None

    # Log incoming email content
    in_rec = models.EmailRecord(
        application_id=app.id,
        to_address=FROM_EMAIL,
        subject="RE: переговоры",
        body=supplier_text,
        direction="in",
    )
    session.add(in_rec)
    session.commit()

    agent = _build_negotiation_agent(app_id)

    sup_msg = {"role": "supplier", "content": supplier_text}

    ai_resp = await agent.reply(json.dumps(sup_msg, ensure_ascii=False))

    try:
        data = json.loads(re.search(r"\{.*\}", ai_resp, re.S).group())
    except Exception:
        data = {"subject": "Ответ", "body": ai_resp, "done": False}

    if data.get("done"):
        app.status = "negotiation_agreed"
        session.commit()
        session.close()
        await context.bot.send_message(
            chat_id=app.requester.telegram_id,
            text="Условия согласованы! Формируем счёт...",
        )
        # trigger invoice
        from agents.invoice import generate_invoice

        pdf_path = generate_invoice(app.supplier_id, amount=0)  # placeholder amount
        await context.bot.send_document(chat_id=app.requester.telegram_id, document=open(pdf_path, "rb"))
        return "Переговоры завершены, счёт отправлен"

    # otherwise send next counter email
    subject, body = data["subject"], data["body"]
    to_email = supplier.email or "info@example.com"
    try:
        await _send_email(to_email, subject, body)
    except Exception:
        pass

    out_rec = models.EmailRecord(
        application_id=app.id, to_address=to_email, subject=subject, body=body, direction="out"
    )
    session.add(out_rec)
    session.commit()
    session.close()

    await context.bot.send_message(
        chat_id=app.requester.telegram_id, text="Отправлен встречный ответ поставщику."
    )
    return "Ответ отправлен"
