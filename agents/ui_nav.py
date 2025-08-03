from telegram import InlineKeyboardButton

BACK_CALLBACK = "nav:back"
MENU_CALLBACK = "nav:menu"


from telegram import InlineKeyboardMarkup

MAIN_MENU_PREFIX = "main:"


def main_menu_keyboard(is_manager=False):
    rows = []
    if is_manager:
        rows.append([InlineKeyboardButton("🏭 Поставщики", callback_data="/suppliers")])
        rows.append([InlineKeyboardButton("📄 Заявки", callback_data="/mapps")])
    else:
        rows.append([InlineKeyboardButton("📋 Мои заявки", callback_data="/myapps")])
    return InlineKeyboardMarkup(rows)


def add_nav(row_list, include_back=True, include_menu=True):
    """Append back/menu buttons to existing rows list.
    Args:
        row_list: list of rows (each row = list[InlineKeyboardButton])
    Returns same list reference for chaining.
    """
    nav_row = []
    if include_back:
        nav_row.append(InlineKeyboardButton("⬅️ Назад", callback_data=BACK_CALLBACK))
    if include_menu:
        nav_row.append(InlineKeyboardButton("🏠 Меню", callback_data=MENU_CALLBACK))
    if nav_row:
        row_list.append(nav_row)
    return row_list
