"""SupportAgent: общается с клиентом по конкретной заявке.
Пока реализует заглушку: эхо-ответ + указание, что функция в разработке.
В будущем заменим на полноценный LLM-помощник.
"""

from typing import Optional
import logging
from db.models import Application

logger = logging.getLogger(__name__)

class SupportAgent:
    def __init__(self, application: Application):
        self.app = application

    async def reply(self, user_message: str) -> str:
        logger.info("[Stub] Support chat for app %s: user said '%s'", self.app.id, user_message)
        return f"[Stub] Заявка #{self.app.id}: я получил ваше сообщение и скоро отвечу по сути."
