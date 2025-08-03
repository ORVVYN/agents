# AI Supplier Bot

Telegram-бот с AI-агентами (LangChain) для поиска поставщиков (через SerpApi Google Maps), ведения переговоров, выписки счетов и управления заявками.

## Функции MVP
1. Поиск компаний в России по категории/запросу.
2. Сбор минимального набора данных от запрашивающего пользователя.
3. Создание заявки и уведомление менеджера.
4. Многошаговые переговоры с поставщиком от лица менеджера.
5. Генерация PDF-счета.

## Стек
- Python 3.11
- python-telegram-bot
- LangChain
- SerpApi (Google Maps API)
- SQLite + SQLAlchemy

## Быстрый старт
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заполнить ключи
python -m bot.main
```

## Переменные окружения (.env)
- `BOT_TOKEN` — токен Telegram-бота
- `SERP_API_KEY` — ключ SerpApi
- `OPENAI_API_KEY` — ключ OpenAI (для LLM)
- `MANAGER_CHAT_ID` — Telegram chat_id менеджера
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` — для отправки email

## Структура
```
ai_supplier_bot/
├─ bot/
│  └─ main.py
├─ agents/
│  ├─ supplier_search.py
│  ├─ intake.py
│  ├─ manager_comm.py
│  └─ negotiation.py
├─ db/
│  ├─ models.py
│  └─ session.py
├─ invoices/
└─ requirements.txt
```
