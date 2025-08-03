import logging
from typing import List, Dict
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from db.session import get_session
from db import models
from agents.ui_nav import add_nav, BACK_CALLBACK, MENU_CALLBACK

logger = logging.getLogger(__name__)

# Callback data prefixes
CITY_PREFIX = "city:"
CAT_PREFIX = "cat:"
SUP_PREFIX = "sup:"
ACT_PREFIX = "act:"


def list_cities_keyboard() -> InlineKeyboardMarkup:
    """Return keyboard with all cities that have suppliers."""
    session = get_session()
    cities = (
        session.query(models.Supplier.city)
        .filter(models.Supplier.city.isnot(None))
        .distinct()
        .order_by(models.Supplier.city)
        .all()
    )
    session.close()
    buttons = [
        [InlineKeyboardButton(city[0], callback_data=CITY_PREFIX + city[0])] for city in cities if city[0]
    ]
    add_nav(buttons, include_back=False, include_menu=True)
    return InlineKeyboardMarkup(buttons or [[InlineKeyboardButton("Нет городов", callback_data="noop")]])


def list_categories_keyboard(city: str) -> InlineKeyboardMarkup:
    session = get_session()
    cats = (
        session.query(models.Supplier.category)
        .filter(models.Supplier.city == city, models.Supplier.category.isnot(None))
        .distinct()
        .order_by(models.Supplier.category)
        .all()
    )
    session.close()
    buttons = [
        [InlineKeyboardButton(cat[0], callback_data=CAT_PREFIX + city + "|" + cat[0])] for cat in cats if cat[0]
    ]
    add_nav(buttons)
    return InlineKeyboardMarkup(buttons or [[InlineKeyboardButton("Нет категорий", callback_data="noop")]])


def list_suppliers_keyboard(city: str, category: str) -> InlineKeyboardMarkup:
    session = get_session()
    sups: List[models.Supplier] = (
        session.query(models.Supplier)
        .filter_by(city=city, category=category)
        .all()
    )
    session.close()
    buttons = []
    for s in sups:
        label = f"{s.name}"[:60]
        buttons.append([InlineKeyboardButton(label, callback_data=SUP_PREFIX + str(s.id))])
    if not buttons:
        buttons = [[InlineKeyboardButton("Нет поставщиков", callback_data="noop")]]
    add_nav(buttons)
    return InlineKeyboardMarkup(buttons)


def supplier_card(s: models.Supplier) -> str:
    lines = [f"<b>{s.name}</b>"]
    if s.address:
        lines.append(f"🏠 {s.address}")
    if s.phone:
        lines.append(f"📞 {s.phone}")
    if s.email:
        lines.append(f"✉️ {s.email}")
    if s.website:
        lines.append(f"🌐 {s.website}")
    if s.whatsapp:
        lines.append(f"💬 WhatsApp: {s.whatsapp}")
    return "\n".join(lines)


def supplier_actions_keyboard(s: models.Supplier) -> InlineKeyboardMarkup:
    buttons = []
    if s.phone:
        buttons.append([InlineKeyboardButton("Позвонить", callback_data=ACT_PREFIX + f"call|{s.id}")])
    if s.email:
        buttons.append([InlineKeyboardButton("Написать email", callback_data=ACT_PREFIX + f"email|{s.id}")])
    if s.whatsapp:
        buttons.append([InlineKeyboardButton("WhatsApp", callback_data=ACT_PREFIX + f"wa|{s.id}")])
    if not buttons:
        buttons = [[InlineKeyboardButton("Нет действий", callback_data="noop")]]
    add_nav(buttons)
    return InlineKeyboardMarkup(buttons)


async def handle_suppliers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for /suppliers"""
    await update.message.reply_text("Выберите город:", reply_markup=list_cities_keyboard())


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data.startswith(CITY_PREFIX):
        city = data[len(CITY_PREFIX):]
        await query.edit_message_text(
            f"Город: {city}\nВыберите категорию:", reply_markup=list_categories_keyboard(city)
        )
    elif data.startswith(CAT_PREFIX):
        city, cat = data[len(CAT_PREFIX):].split("|", 1)
        await query.edit_message_text(
            f"{city} – {cat}\nВыберите поставщика:", reply_markup=list_suppliers_keyboard(city, cat)
        )
    elif data.startswith(SUP_PREFIX):
        sup_id = int(data[len(SUP_PREFIX):])
        session = get_session()
        sup = session.query(models.Supplier).get(sup_id)
        session.close()
        if not sup:
            await query.edit_message_text("Поставщик не найден")
            return
        card = supplier_card(sup)
        await query.edit_message_text(
            card,
            parse_mode="HTML",
            reply_markup=supplier_actions_keyboard(sup),
        )
    elif data.startswith(ACT_PREFIX):
        action, sup_id = data[len(ACT_PREFIX):].split("|", 1)
        sup_id = int(sup_id)
        session = get_session()
        sup = session.query(models.Supplier).get(sup_id)
        session.close()
        if not sup:
            await query.edit_message_text("Поставщик не найден")
            return
        from agents import contact_agents
        if action == "call":
            txt = await contact_agents.call_supplier(sup)
        elif action == "email":
            txt = await contact_agents.email_supplier(sup)
        elif action == "wa":
            txt = await contact_agents.whatsapp_supplier(sup)
        else:
            txt = "Неизвестное действие."
        await query.edit_message_text(txt)
    else:
        # noop
        pass
