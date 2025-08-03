import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from db.session import get_session
from db import models
from agents.supplier_search import search_suppliers
from agents.intake import IntakeAgent
from agents import manager_ui, manager_apps_ui, client_apps_ui
from agents.ui_nav import BACK_CALLBACK, MENU_CALLBACK, main_menu_keyboard
from agents.manager_comm import notify_manager
from agents.negotiation import start_negotiation
from agents.invoice import generate_invoice
from integrations.amocrm import AmoClient, STATUS_MAP

# ---- amoCRM status sync helper ----
async def sync_amo_status(ctx, app):
    """Update lead status in amoCRM if amocrm_id present."""
    amo: AmoClient = ctx.application.bot_data.get("amo_client") if ctx else None
    if not amo or not getattr(app, "amocrm_id", None):
        return
    status_id = STATUS_MAP.get(app.status)
    if status_id:
        try:
            await amo.update_status(app.amocrm_id, status_id)
        except Exception as e:
            logger.error("AMO status sync failed: %s", e)
from agents.email_listener import start_email_polling

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MANAGER_CHAT_ID = int(os.getenv("MANAGER_CHAT_ID", "0"))

NAV_STACK_KEY = "nav_stack"


def push_nav(context, data):
    stack = context.user_data.setdefault(NAV_STACK_KEY, [])
    stack.append(data)


def pop_nav(context):
    stack = context.user_data.get(NAV_STACK_KEY, [])
    if stack:
        stack.pop()
    return stack[-1] if stack else None


# --- Logging setup ------------------------------------------------------
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
root_level = getattr(logging, log_level_str, logging.INFO)
logging.basicConfig(
    level=root_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Показываем расширенную отладку только для amoCRM клиента
logging.getLogger("integrations.amocrm").setLevel(logging.DEBUG)
# Подавляем детализацию шумных библиотек
for noisy in ["httpx", "asyncio", "urllib3"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

# State for dynamic intake using AI agent
INTAKE_STATE = 10
SUPPORT_CHAT_STATE = 30

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Здравствуйте! Я помогу найти поставщика. Просто опишите ваш запрос в свободной форме.")


async def intake_ai_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    intake_agent: IntakeAgent = context.user_data["intake_agent"]
    next_q = await intake_agent.process(update.message.text)
    if intake_agent.finished:
        # Save details
        session = get_session()
        application_id = context.user_data["application_id"]
        application = session.query(models.Application).get(application_id)
        # Convert dict to multiline string
        details_txt = "\n".join([f"{k}: {v}" for k, v in intake_agent.collected.items()])
        # Save collected details
        application.details = details_txt
        # Determine search term (используем первое сообщение пользователя или volume)
        product = intake_agent.collected.get("product", "")
        city = intake_agent.collected.get("city", "")
        base_term = product or context.user_data.get("initial_term") or ""
        search_term = f"{base_term} {city}".strip()
        application.search_term = search_term
        # Сначала статус intake_done
        application.status = "searching"
        session.commit()

        # --- amoCRM lead creation ---
        amo: AmoClient = context.application.bot_data.get("amo_client")
        if amo and not application.amocrm_id:
            try:
                buyer = application.buyer  # may be None yet
                logger.info("Creating amoCRM lead for application %s via intake", application.id)
                application.amocrm_id = await amo.create_lead(application, buyer)
            except Exception as e:
                logger.error("AMO lead creation failed: %s", e)

        # --- supplier search ---
        suppliers = []
        if search_term:
            from agents.supplier_search import search_suppliers
            suppliers = search_suppliers(search_term, session, city)
            if suppliers:
                application.supplier_id = suppliers[0].id
                application.status = "manager_review"
                await sync_amo_status(context, application)
        session.commit()

        # Ответ пользователю
        await update.message.reply_text("Спасибо! Ваша заявка передана менеджеру.")

        # Notify manager with suppliers list
        if MANAGER_CHAT_ID:
            if suppliers:
                await notify_manager(context.bot, MANAGER_CHAT_ID, application, suppliers)
            else:
                await context.bot.send_message(chat_id=MANAGER_CHAT_ID,
                    text=f"Заявка #{application.id} детали:\n{details_txt}\nПоставщики не найдены автоматически.")
        # Now safe to close session
        session.close()
        return ConversationHandler.END
    else:
        if not next_q:
            next_q = "Уточните, пожалуйста, товар, город и адрес доставки."
        await update.message.reply_text(next_q)
        return INTAKE_STATE

async def handle_manager_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data  # format action:app_id
    action, app_id_str = data.split(":", 1)
    app_id = int(app_id_str)
    session = get_session()
    application = session.query(models.Application).get(app_id)
    if not application:
        await query.edit_message_text("Заявка не найдена")
        session.close()
        return

    # Log action
    m_action = models.ManagerAction(application_id=app_id, action=action, notes="")
    session.add(m_action)

    if action == "negotiation":
        application.status = "negotiating"
        await sync_amo_status(context, application)
        session.commit()
        session.close()
        await query.edit_message_text("Переговоры инициированы. Бот свяжется с поставщиками.")
        # Start negotiation asynchronously (stub)
        await start_negotiation(app_id, context)
    elif action == "request_info":
        application.status = "info_requested"
        await sync_amo_status(context, application)
        session.commit()
        session.close()
        await query.edit_message_text("Запрос дополнительной информации отправлен пользователю.")
    elif action == "reject":
        application.status = "rejected"
        await sync_amo_status(context, application)
        session.commit()
        session.close()
        await query.edit_message_text("Заявка отклонена.")
    elif action == "invoice":
        # Generate invoice (simple fixed amount for demo)
        pdf_path = generate_invoice(app_id, amount=100000)
        session.commit()
        session.close()
        await query.edit_message_text("Счёт сформирован.")
        # Send PDF to manager and requester
        await context.bot.send_document(chat_id=MANAGER_CHAT_ID, document=open(pdf_path, "rb"))
        await context.bot.send_document(chat_id=application.requester.telegram_id, document=open(pdf_path, "rb"))
    else:
        session.commit()
        session.close()
        await query.edit_message_text("Неизвестное действие.")

async def free_text_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain text as a supplier search if user is not in an active conversation."""
    # If user already in intake, route to intake handler
    if context.user_data.get("intake_agent"):
        return await intake_ai_step(update, context)

    # Start intake flow immediately using the first user message as context
    initial_msg = update.message.text.strip()
    if not initial_msg:
        await update.message.reply_text("Я вас слушаю, чем могу помочь?")
        return ConversationHandler.END

    session = get_session()
    user = update.message.from_user
    requester = session.query(models.Requester).filter_by(telegram_id=user.id).first()
    if not requester:
        requester = models.Requester(telegram_id=user.id, username=user.username, full_name=user.full_name)
        session.add(requester)
        session.commit()

    # Create draft application; supplier will be filled after intake
    application = models.Application(
        requester_id=requester.id,
        supplier_id=None,
        search_term="",  # to be filled after intake
        status="intake",
        details="draft",
    )
    session.add(application)
    session.commit()

    # Debug log about amo client
    amo: AmoClient = context.application.bot_data.get("amo_client")
    logger.info("free_text_entry: amo_client=%s amocrm_id=%s", bool(amo), application.amocrm_id)

    # Create amoCRM lead immediately (пока у нас нет Buyer — передаём None)
    amo: AmoClient = context.application.bot_data.get("amo_client")
    if amo and not application.amocrm_id:
        try:
            logger.info("Creating amoCRM lead for application %s via free_text", application.id)
            application.amocrm_id = await amo.create_lead(application, None)
            session.commit()
            logger.info("Created amoCRM lead id=%s for app=%s", application.amocrm_id, application.id)
        except Exception as e:
            logger.exception("Failed to create amoCRM lead for app %s: %s", application.id, e)

    session.close()

    # Kick off IntakeAgent with the first message
    intake_agent = IntakeAgent(requester_id=requester.id)
    context.user_data["application_id"] = application.id
    context.user_data["intake_agent"] = intake_agent

    # Pass the first user message directly
    first_bot_reply = await intake_agent.process(initial_msg)
    if not first_bot_reply:
        first_bot_reply = "Спасибо! Уточните, пожалуйста, товар, город и адрес доставки."
    await update.message.reply_text(first_bot_reply)
    return INTAKE_STATE

# --- Navigation handlers ---
async def nav_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == MENU_CALLBACK:
        context.user_data[NAV_STACK_KEY] = []
        await query.edit_message_text("Главное меню:", reply_markup=main_menu_keyboard())
    elif data == BACK_CALLBACK:
        prev = pop_nav(context)
        if prev:
            # re-dispatch by sending fake callback
            query.data = prev
            await main_callback_router(update, context)
        else:
            await query.edit_message_text("Главное меню:", reply_markup=main_menu_keyboard())
    else:
        pass  # noop

def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set in environment")

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    # Reuse single AmoClient instance
    application.bot_data["amo_client"] = AmoClient()
    # Navigation handler
    application.add_handler(CallbackQueryHandler(nav_callback, pattern="^nav:"))
    # Manager suppliers UI
    application.add_handler(CommandHandler("suppliers", manager_ui.handle_suppliers_command))
    application.add_handler(CallbackQueryHandler(manager_ui.handle_callback_query))
    # Manager applications UI
    application.add_handler(CommandHandler("apps", manager_apps_ui.handle_apps_command))
    application.add_handler(CallbackQueryHandler(manager_apps_ui.handle_callback_query))
    # Client menu
    application.add_handler(CommandHandler("myapps", client_apps_ui.handle_myapps_command))
    application.add_handler(CallbackQueryHandler(client_apps_ui.handle_callback_query))
    # Support chat per application
    support_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(client_apps_ui.start_support_chat, pattern="^cact:chat")],
        states={
            SUPPORT_CHAT_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, client_apps_ui.support_chat_step)],
        },
        fallbacks=[CommandHandler("back", client_apps_ui.support_chat_end)],
    )
    application.add_handler(support_conv)

    intake_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, free_text_entry)],
        states={
            INTAKE_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, intake_ai_step)],
        },
        fallbacks=[],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(intake_conv)
    application.add_handler(CallbackQueryHandler(handle_manager_action))

    # start IMAP polling (supplier replies)
    try:
        start_email_polling(application.bot)
    except Exception as e:
        logger.warning("Email polling not started: %s", e)


    logger.info("Bot started")
    application.run_polling()


if __name__ == "__main__":
    main()
