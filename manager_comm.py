from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot

from db.models import Application, Supplier
from agents.llm_agent import LLMAgent

_manager_agent: LLMAgent | None = None


def _get_manager_agent() -> LLMAgent:
    global _manager_agent
    if _manager_agent is None:
        persona = (
            """
            Ты – личный ассистент менеджера по закупкам. Пишешь кратко, по делу, без лишней воды. 
            При передаче заявки включаешь: номер, ФИО клиента, запрос, итоги сбора данных и список найденных поставщиков.
            Всегда пиши на русском, корпоративный стиль.
            """
        )
        _manager_agent = LLMAgent(persona_system_prompt=persona, temperature=0.3)
    return _manager_agent


async def notify_manager(bot: Bot, chat_id: int, app: Application, suppliers: List[Supplier]):
    """Send application overview with action buttons to manager using LLM-generated text."""
    supplier_lines = "\n".join([f"• {s.name} — {s.address or '-'}" for s in suppliers[:5]])
    user_info = app.requester.full_name or app.requester.username
    ai_input = (
        f"Номер заявки: {app.id}\n"
        f"Клиент: {user_info}\n"
        f"Запрос: {app.search_term}\n"
        f"Детали: {app.details}\n"
        f"Поставщики:\n{supplier_lines}"
    )
    manager_agent = _get_manager_agent()
    text = await manager_agent.reply(ai_input)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Переговоры", callback_data=f"negotiation:{app.id}"),
         InlineKeyboardButton("Уточнить", callback_data=f"request_info:{app.id}"),
         InlineKeyboardButton("Отклонить", callback_data=f"reject:{app.id}")]
    ])
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)


def ask_invoice(bot: Bot, chat_id: int, app_id: int):
    """Send button to create invoice."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Выставить счёт", callback_data=f"invoice:{app_id}")]
    ])
    bot.send_message(chat_id=chat_id, text=f"Завершены переговоры по заявке #{app_id}. Выставить счёт?", reply_markup=keyboard)
