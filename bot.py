"""
Quant3.5-Pro — ИИ-бот от Quantum Mole
Модель: openai/gpt-oss-120b:free (текст)
Зрение: nvidia/nemotron-nano-12b-v2-vl:free (JPEG)
Поиск: DuckDuckGo через duckduckgo_search (автоматический)
"""

import asyncio
import json
import logging
import os  # <-- ДЛЯ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
from datetime import datetime, timedelta
from duckduckgo_search import DDGS
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile
from openai import AsyncOpenAI
import base64
from PIL import Image
import io

# ================== НАСТРОЙКИ (БЕРУТСЯ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ) ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY_GPT = os.getenv("OPENROUTER_API_KEY_GPT")
OPENROUTER_API_KEY_VL = os.getenv("OPENROUTER_API_KEY_VL")

# Проверка, что переменные заданы (если нет — бот не запустится)
if not TELEGRAM_TOKEN:
    raise ValueError("❌ Ошибка: TELEGRAM_TOKEN не задан в переменных окружения!")
if not OPENROUTER_API_KEY_GPT:
    raise ValueError("❌ Ошибка: OPENROUTER_API_KEY_GPT не задан!")
if not OPENROUTER_API_KEY_VL:
    raise ValueError("❌ Ошибка: OPENROUTER_API_KEY_VL не задан!")

AI_MODEL = "openai/gpt-oss-120b:free"
VL_MODEL = "nvidia/nemotron-nano-12b-v2-vl:free"
MAX_SEARCH_RESULTS = 5

# ================== ЛОГИРОВАНИЕ ==================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== КЛИЕНТЫ ==================
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

client_gpt = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY_GPT,
)

client_vl = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY_VL,
)

# ================== ИСТОРИЯ И АКТИВНОСТЬ ==================
chat_histories = {}
last_activity = {}
reminder_sent = {}

# ================== НАПОМИНАНИЯ ==================
REMINDER_MESSAGES = [
    "👋 Привет! Давно не общались. Задай вопрос или просто поболтаем!",
    "💡 У меня появились новые знания. Может, хочешь что-то узнать?",
    "🔍 Я всё так же быстро ищу в интернете. Нужна помощь?",
    "📚 Без тебя скучно... Задай вопрос, я готов помочь!",
    "⚡ Я тут прокачался! Проверим мои новые способности?",
]

async def reminder_loop():
    while True:
        await asyncio.sleep(3600)
        now = datetime.now()
        for user_id, last_time in list(last_activity.items()):
            if (now - last_time > timedelta(hours=1) and 
                not reminder_sent.get(user_id, False)):
                try:
                    msg = REMINDER_MESSAGES[int(now.timestamp()) % len(REMINDER_MESSAGES)]
                    await bot.send_message(user_id, msg)
                    reminder_sent[user_id] = True
                except Exception as e:
                    logger.error(f"Ошибка отправки напоминания: {e}")

# ================== ПОИСК DUCKDUCKGO ==================
def search_duckduckgo(query: str) -> str:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, region="ru-ru", max_results=MAX_SEARCH_RESULTS))
        if results:
            formatted = "\n\n".join(
                [f"[{i+1}] {r['title']}\nСсылка: {r['href']}\n{r['body']}" 
                 for i, r in enumerate(results)]
            )
            return formatted
        return "Ничего не найдено."
    except Exception as e:
        logger.error(f"Ошибка поиска: {e}")
        return "Ошибка при поиске."

# ================== РАСПОЗНАВАНИЕ JPEG ==================
async def describe_image(image_path: str) -> str:
    try:
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        
        response = await client_vl.chat.completions.create(
            model=VL_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Опиши, что на этом изображении. Будь подробным, но без лишних деталей."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}
                    ]
                }
            ],
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Ошибка распознавания: {e}")
        return "Не удалось распознать изображение."

# ================== ИНСТРУМЕНТЫ ДЛЯ FUNCTION CALLING ==================
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Поиск актуальной информации в интернете через DuckDuckGo. Используй, когда нужны свежие данные, новости или факты, которых нет в твоих знаниях.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Поисковый запрос"}
                },
                "required": ["query"]
            }
        }
    }
]

# ================== СИСТЕМНЫЙ ПРОМТ ==================
SYSTEM_PROMPT = """Ты — Quant3.5-Pro, ИИ-ассистент от Quantum Mole. 

Твой характер и стиль общения:
- Ты дружелюбный, полезный и поддерживающий собеседник.
- Отвечаешь на русском языке, грамотно и развёрнуто.
- Ты любознательный — тебе искренне интересно, о чём тебя спрашивают.
- Объясняешь сложные вещи простыми словами, но без снисходительного тона.
- Можешь пошутить, но к месту, не перебарщивая.
- Если вопрос требует актуальной информации — сам решаешь, когда использовать поиск в интернете.
- Если чего-то не знаешь — честно признаёшься, не придумываешь.
- Ты не просто отвечаешь на вопросы — ты ведёшь диалог, задаёшь уточняющие вопросы, если нужно.
- Твой тон — как у умного друга, который всегда рад помочь."""

# ================== ОБРАБОТЧИК СООБЩЕНИЙ ==================
async def process_query(user_id: int, text: str, reply_func, image_path: str = None):
    last_activity[user_id] = datetime.now()
    reminder_sent[user_id] = False

    if user_id not in chat_histories:
        chat_histories[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    if image_path:
        await reply_func(text="👁️ Смотрю на картинку...")
        description = await describe_image(image_path)
        text = f"Пользователь прислал изображение. Вот его описание:\n\n{description}\n\nСообщение пользователя: {text}"

    chat_histories[user_id].append({"role": "user", "content": text})
    await reply_func(action="typing")

    try:
        response = await client_gpt.chat.completions.create(
            model=AI_MODEL,
            messages=chat_histories[user_id],
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.7,
            max_tokens=1500,
        )
    except Exception as e:
        logger.error(f"Ошибка GPT: {e}")
        await reply_func(text="⚠️ Ошибка связи с ИИ.")
        return

    msg = response.choices[0].message

    if msg.tool_calls:
        search_query = json.loads(msg.tool_calls[0].function.arguments).get("query", text)
        
        await reply_func(text=f"🔍 Ищу в интернете: *{search_query}*")
        search_results = search_duckduckgo(search_query)
        
        chat_histories[user_id].append({
            "role": "assistant", "content": None, "tool_calls": msg.tool_calls
        })
        chat_histories[user_id].append({
            "role": "tool", "tool_call_id": msg.tool_calls[0].id, "content": search_results
        })
        
        await reply_func(text="💡 Готовлю ответ на основе найденного...")
        await reply_func(action="typing")
        
        try:
            final = await client_gpt.chat.completions.create(
                model=AI_MODEL,
                messages=chat_histories[user_id],
                temperature=0.7,
                max_tokens=1500,
            )
            answer = final.choices[0].message.content
        except Exception as e:
            answer = "⚠️ Ошибка при обработке результатов поиска."
    else:
        answer = msg.content

    chat_histories[user_id].append({"role": "assistant", "content": answer})

    if len(chat_histories[user_id]) > 20:
        chat_histories[user_id] = chat_histories[user_id][:1] + chat_histories[user_id][-19:]

    await reply_func(text=answer)

# ================== REPLY WRAPPER ==================
class ReplyWrapper:
    def __init__(self, message: Message):
        self.message = message

    async def __call__(self, text: str = None, action: str = None):
        if action:
            await bot.send_chat_action(chat_id=self.message.chat.id, action=action)
        elif text:
            await self.message.answer(text)

# ================== ХЭНДЛЕРЫ ==================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    last_activity[message.from_user.id] = datetime.now()
    reminder_sent[message.from_user.id] = False
    await message.answer(
        "👋 Я **Quant3.5-Pro** — ИИ-ассистент от **Quantum Mole**!\n\n"
        "Задай вопрос текстом или пришли картинку (JPEG) — я пойму.\n"
        "Если нужно — сам найду информацию в интернете.\n\n"
        "🔔 Если заскучаешь — я напомню о себе!"
    )

@dp.message(F.photo)
async def handle_photo(message: Message):
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_path = f"photo_{message.from_user.id}.jpg"
    await bot.download_file(file.file_path, file_path)

    caption = message.caption or "Что на этом изображении?"
    await process_query(
        message.from_user.id, caption,
        reply_func=ReplyWrapper(message),
        image_path=file_path
    )

    if os.path.exists(file_path):
        os.remove(file_path)

@dp.message()
async def handle_text(message: Message):
    await process_query(
        message.from_user.id, message.text,
        reply_func=ReplyWrapper(message)
    )

# ================== ЗАПУСК ==================
async def main():
    asyncio.create_task(reminder_loop())
    logger.info("Quant3.5-Pro запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
