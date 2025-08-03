from typing import Dict, Any, List, Optional
import json, re, os, pathlib
from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain.memory import ConversationBufferMemory
from agents.llm_agent import LLMAgent

# SQLite file for chat memories (relative to project root)
MEMORY_DB = os.getenv("MEMORY_DB", "data/ai_memory.db")
# Ensure DB file path exists
pathlib.Path(MEMORY_DB).parent.mkdir(parents=True, exist_ok=True)

# Legacy list kept for fallback (not used with LLM prompt now)
QUESTIONS: List[str] = []

PERSONA_PROMPT = (
    """
    Твоя роль — персональный AI-помощник отдела снабжения стройкомпании. Ты:
    • Понимаешь строительную тематику (бетон, ЖБИ, арматура, логистика). 
    • Умеешь вести дружелюбный, человечный диалог в Telegram без канцелярита.
    • Отличаешь, когда собеседник хочет:
        – оформить новую заявку,
        – изменить существующую,
        – просто поболтать или задать совет по стройке.
    • Держишь в памяти контекст прошлых заказов клиента.

    При обработке сообщений действуй так:
    1. Проанализируй вход: <text>.
        – Если это чисто разговор/совет (нет явного намерения заказать) — дай полезный ответ по теме.
        – Если пользователь формулирует/модифицирует заявку → извлеки детали.
    2. Ключевые поля заявки (если речь о заказе):
        product, volume, city, address, deadline, wishes (доп. пожелания).
        • Допустим свободный текст: «бетон м400 20 кубов завтра Уфа, Омская 64 с разгрузкой».
    3. Если ВСЕ обязательные поля (product, city, address) найдены — верни EXACT JSON:
        {"status": "done", "details": { ... }}.
       Дополнительные поля volume, deadline, wishes включай, если смог распознать.
    4. Если чего-то не хватает — верни JSON:
        {"status": "ask", "question": "<твоя формулировка вопроса>"}.
       Вопросы задавай по одному, начиная с самого важного отсутствующего.
    5. Если собеседник ругается/оффтоп — мягко попроси соблюдать вежливость и верни очередной вопрос.

    Формат ответов:
      • Только вышеуказанные JSON-структуры, НИКАКИХ других символов вокруг.
      • В поле question говори по-русски, живым разговорным стилем.
      • Избегай повторов и шаблонности: вариативность формулировок.

    Дополнительно умеешь кратко советовать:
      – Марка бетона / выбор арматуры.
      – Способы разгрузки, требования к подъезду.
      – Примерный вес/габариты.

    Примеры:
    ----------
    USER: «Нужен бетон М400 20 кубов завтра, Уфа, Омская 64, оплата безнал»
    AI: {"status": "done", "details": {"product": "бетон М400", "volume": "20 м³", "city": "Уфа", "address": "ул. Омская, 64", "deadline": "завтра", "wishes": "оплата безнал"}}

    USER: «Сколько кубов минимально привозите?»
    AI: {"status": "ask", "question": "Минимально можно 1 м³. Уточните, какой объём вам нужен?"}

    USER: «Хочу изменить адрес на Ленина 5» (после оформления)
    AI: {"status": "ask", "question": "Адрес изменён на Ленина, 5. Нужно ещё что-то поправить?"}

    Помни: никакого текста вне JSON! Если нужен совет без оформления заявки — ответь коротко и полезно текстом вопроса внутри поля question.
    """
)

class IntakeAgent:
    """Interactive intake agent with persistent user-specific memory."""

    def __init__(self, requester_id: int):
        # Build persistent memory per requester
        async_conn = f"sqlite+aiosqlite:///{MEMORY_DB}"
        chat_history = SQLChatMessageHistory(
            session_id=str(requester_id),
            connection=async_conn,
            async_mode=True,
        )
        memory = ConversationBufferMemory(memory_key="history", return_messages=True, chat_memory=chat_history)
        self.llm_agent = LLMAgent(PERSONA_PROMPT, memory=memory)
        self.finished = False
        self.collected: Dict[str, Any] = {}

    async def process(self, user_message: Optional[str] = None) -> Optional[str]:
        """Process user message and return next bot reply (question or None when done)."""
        prompt_in = user_message or "start"
        reply = await self.llm_agent.reply(prompt_in)

        # Extract mandatory JSON payload
        match = re.search(r"\{.*\}", reply, re.S)
        if not match:
            # model failed to comply — return whole reply and continue
            return reply

        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return reply

        status = data.get("status")
        if status == "done":
            self.collected = data.get("details", {})
            required = ["product", "city", "address"]
            missing = [f for f in required if not self.collected.get(f)]
            if missing:
                rus_map = {"product": "товар", "city": "город", "address": "адрес доставки"}
                readable = ", ".join(rus_map.get(f, f) for f in missing)
                self.finished = False
                return f"Уточните, пожалуйста: {readable}."
            self.finished = True
            return None
        if status == "ask":
            return data.get("question")
        return None

def next_question(step: int) -> str | None:
    """Return next question or None if done"""
    if step < len(QUESTIONS):
        return QUESTIONS[step]
    return None

def format_details(answers: List[str]) -> str:
    return (
        f"Объём: {answers[0]}\n"
        f"Сроки: {answers[1]}\n"
        f"Пожелания: {answers[2]}"
    )
