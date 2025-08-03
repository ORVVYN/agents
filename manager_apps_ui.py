import logging
from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from db.session import get_session
from db import models
from agents.ui_nav import add_nav

logger = logging.getLogger(__name__)

APP_PREFIX = "app:"
ACT_PREFIX = "appact:"


def _application_title(app: models.Application) -> str:
    title = app.search_term or "(нет поискового запроса)"
    status = app.status
    return f"#{app.id} {title} [{status}]"


def list_applications_keyboard(limit: int = 20) -> InlineKeyboardMarkup:
    session = get_session()
    apps: List[models.Application] = (
        session.query(models.Application)
        .order_by(models.Application.created_at.desc())
        .limit(limit)
        .all()
    )
    session.close()
    buttons = [
        [InlineKeyboardButton(_application_title(a)[:60], callback_data=f"{APP_PREFIX}{a.id}")]
        for a in apps
    ]
    add_nav(buttons)
    if not buttons:
        buttons = [[InlineKeyboardButton("Нет заявок", callback_data="noop")]]
    return InlineKeyboardMarkup(buttons)


def app_card(app: models.Application) -> str:
    lines = [f"<b>Заявка #{app.id}</b>"]
    if app.search_term:
        lines.append(f"🔎 {app.search_term}")
    if app.details:
        lines.append(app.details)
    lines.append(f"Статус: {app.status}")
    if app.supplier:
        lines.append("\n<b>Поставщик:</b>")
        lines.append(app.supplier.name)
        if app.supplier.phone:
            lines.append(f"📞 {app.supplier.phone}")
        if app.supplier.email:
            lines.append(f"✉️ {app.supplier.email}")
    return "\n".join(lines)


def app_actions_keyboard(app: models.Application) -> InlineKeyboardMarkup:
    buttons = []
    if app.supplier and app.supplier.phone:
        buttons.append([InlineKeyboardButton("Позвонить поставщику", callback_data=ACT_PREFIX + f"call|{app.id}")])
    if app.supplier and app.supplier.email:
        buttons.append([InlineKeyboardButton("Запросить документы (email)", callback_data=ACT_PREFIX + f"docs|{app.id}")])
    buttons.append([InlineKeyboardButton("Запросить недостающие данные", callback_data=ACT_PREFIX + f"info|{app.id}")])
    if not buttons:
        buttons = [[InlineKeyboardButton("Нет действий", callback_data="noop")]]
    add_nav(buttons)
    return InlineKeyboardMarkup(buttons)


async def handle_apps_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Список заявок:", reply_markup=list_applications_keyboard())


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data.startswith(APP_PREFIX):
        app_id = int(data[len(APP_PREFIX):])
        session = get_session()
        app = session.query(models.Application).get(app_id)
        session.close()
        if not app:
            await query.edit_message_text("Заявка не найдена")
            return
        await query.edit_message_text(
            app_card(app), parse_mode="HTML", reply_markup=app_actions_keyboard(app)
        )
    elif data.startswith(ACT_PREFIX):
        action, app_id = data[len(ACT_PREFIX):].split("|", 1)
        app_id = int(app_id)
        session = get_session()
        app = session.query(models.Application).get(app_id)
        session.close()
        if not app:
            await query.edit_message_text("Заявка не найдена")
            return
        from agents import contact_agents
        if action == "call":
            txt = await contact_agents.call_supplier(app.supplier, application=app)
        elif action == "docs":
            txt = await contact_agents.email_supplier(app.supplier, application=app, subject="Запрос документов", body="Пожалуйста, пришлите пакет документов для договора")
        elif action == "info":
            txt = await contact_agents.email_supplier(app.supplier, application=app, subject="Уточнение по заявке", body="Просьба уточнить недостающие данные по поставке")
        else:
            txt = "Неизвестное действие."
        await query.edit_message_text(txt)
    else:
        pass
