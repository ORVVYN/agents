from typing import Dict, Any
from langchain_community.chat_models import ChatOpenAI
from langchain.memory import ConversationBufferMemory
from langchain.chains import ConversationChain
from langchain_core.messages import AIMessage
import asyncio

class LLMAgent:
    """Unified wrapper around LangChain ConversationChain with pluggable memory."""

    def __init__(
        self,
        persona_system_prompt: str,
        temperature: float = 0.4,
        memory: ConversationBufferMemory | None = None,
    ):
        self.llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=temperature)
        self.memory = memory or ConversationBufferMemory(memory_key="history", return_messages=True)
        self.chain = ConversationChain(llm=self.llm, memory=self.memory, verbose=False)
        # prime with persona prompt once (supports async chat history)
        if not getattr(self.memory, "_persona_primed", False):
            chat_mem = self.memory.chat_memory
            try:
                if getattr(chat_mem, "async_mode", False):
                    # run async add in current loop or create one
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # schedule and wait
                        loop.create_task(chat_mem.aadd_message(AIMessage(content=persona_system_prompt)))
                    else:
                        loop.run_until_complete(chat_mem.aadd_message(AIMessage(content=persona_system_prompt)))
                else:
                    chat_mem.add_ai_message(persona_system_prompt)
            finally:
                setattr(self.memory, "_persona_primed", True)

    async def reply(self, user_message: str) -> str:
        return await self.chain.apredict(input=user_message)

    def save_context(self, **kwargs):
        self.memory.save_context(kwargs)
