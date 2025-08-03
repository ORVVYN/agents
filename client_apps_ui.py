import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters

from db.session import get_session
from db import models
from agents.ui_nav import add_nav

logger = logging.getLogger(__name__)

APP_PREFIX = "capp:"
ACT_PREFIX = "cact:"


def _app_title(app: models.Application) -> str:
    return f"#{app.id} {app.search_term or ''} [{app.status}]"


def list_user_apps_keyboard(user_telegram_id: int):
    session = get_session()
    requester = session.query(models.Requester).filter_by(telegram_id=user_telegram_id).first()
    if not requester:
        session.close()
        return InlineKeyboardMarkup([[InlineKeyboardButton("Нет заявок", callback_data="noop")]])
    apps = (
        session.query(models.Application)
        .filter_by(requester_id=requester.id)
        .order_by(models.Application.created_at.desc())
        .all()
    )
    session.close()
    buttons = [
        [InlineKeyboardButton(_app_title(a)[:60], callback_data=f"{APP_PREFIX}{a.id}")]
        for a in apps
    ] or [[InlineKeyboardButton("Нет заявок", callback_data="noop")]]
    return InlineKeyboardMarkup(buttons)


def app_card(app: models.Application) -> str:
    lines = [f"<b>Заявка #{app.id}</b>"]
    lines.append(f"Статус: {app.status}")
    if app.search_term:
        lines.append(f"Запрос: {app.search_term}")
    if app.details:
        lines.append(app.details)
    if app.supplier:
        lines.append("\n<b>Поставщик:</b>")
        lines.append(app.supplier.name)
        if app.supplier.phone:
            lines.append(f"📞 {app.supplier.phone}")
    return "\n".join(lines)


def app_actions_keyboard(app: models.Application) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton("Чат по заявке", callback_data=ACT_PREFIX + f"chat|{app.id}")]]
    return InlineKeyboardMarkup(buttons)


async def handle_myapps_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ваши заявки:", reply_markup=list_user_apps_keyboard(update.effective_user.id))


# --- Support chat handlers ---
async def start_support_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    # data pattern cact:chat|<app_id>
    _, payload = data.split(":",1)
    action, app_id = payload.split("|",1)
    app_id = int(app_id)
    session = get_session()
    app = session.query(models.Application).get(app_id)
    session.close()
    if not app or app.requester.telegram_id != query.from_user.id:
        await query.edit_message_text("Заявка не найдена")
        return ConversationHandler.END
    from agents.support_agent import SupportAgent
    context.user_data["support_agent"] = SupportAgent(app)
    await query.edit_message_text(f"Чат по заявке #{app.id} открыт. Пишите ваши сообщения. /back чтобы выйти")
    return context.bot_data.get("SUPPORT_CHAT_STATE")

async def support_chat_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent = context.user_data.get("support_agent")
    if not agent:
        await update.message.reply_text("Сессия чата не найдена. Используйте /myapps и откройте заново.")
        return ConversationHandler.END
    reply = await agent.reply(update.message.text)
    await update.message.reply_text(reply)
    return context.bot_data.get("SUPPORT_CHAT_STATE")

async def support_chat_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("support_agent", None)
    await update.message.reply_text("Вы вышли из чата заявки.")
    return ConversationHandler.END

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data.startswith(APP_PREFIX):
        app_id = int(data[len(APP_PREFIX):])
        session = get_session()
        app = session.query(models.Application).get(app_id)
        session.close()
        if not app or app.requester.telegram_id != query.from_user.id:
            await query.edit_message_text("Заявка не найдена")
            return
        await query.edit_message_text(app_card(app), parse_mode="HTML", reply_markup=app_actions_keyboard(app))
    elif data.startswith(ACT_PREFIX):
        action, app_id = data[len(ACT_PREFIX):].split("|", 1)
        app_id = int(app_id)
        if action == "chat":
            await query.edit_message_text("[Stub] Откроется чат с ИИ по заявке. Пока в разработке.")
    else:
        pass
