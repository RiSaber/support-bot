"""Telegram-бот поддержки магазина (aiogram 3).

Запуск: python bot.py  (нужны TELEGRAM_BOT_TOKEN и GEMINI_API_KEY в .env)
Если задан OPERATOR_CHAT_ID, вопросы, которые бот не может закрыть сам,
пересылаются в этот чат.
"""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

from assistant import Assistant

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

dp = Dispatcher()
assistant: Assistant | None = None
OPERATOR_CHAT_ID = os.environ.get("OPERATOR_CHAT_ID", "").strip()

GREETING = (
    "Здравствуйте! Я ассистент магазина. Отвечу на вопросы о наушниках X1, "
    "доставке и возврате. Напишите ваш вопрос."
)


@dp.message(CommandStart())
async def on_start(message: Message) -> None:
    await message.answer(GREETING)


@dp.message(Command("id"))
async def on_id(message: Message) -> None:
    # Служебная команда: узнать id чата для OPERATOR_CHAT_ID
    await message.answer(f"id этого чата: {message.chat.id}")


@dp.message(F.text)
async def on_text(message: Message, bot: Bot) -> None:
    await bot.send_chat_action(message.chat.id, "typing")
    reply = await assistant.answer(message.text)
    log.info("Q=%r | A=%r | source=%s %s", message.text, reply.text, reply.source, reply.reason)
    await message.answer(reply.text)

    if reply.escalate and OPERATOR_CHAT_ID:
        user = message.from_user
        who = f"@{user.username}" if user and user.username else f"id {message.chat.id}"
        await bot.send_message(
            OPERATOR_CHAT_ID,
            f"Нужен оператор. Клиент {who}:\n{message.text}",
        )


@dp.message()
async def on_other(message: Message) -> None:
    await message.answer("Я понимаю только текстовые сообщения. Напишите, пожалуйста, вопрос текстом.")


async def main() -> None:
    global assistant
    assistant = Assistant()
    bot = Bot(os.environ["TELEGRAM_BOT_TOKEN"])
    log.info("Бот запущен, модель %s", assistant.model)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
