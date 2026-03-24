import asyncio
import logging
from datetime import datetime, timedelta
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# ================= НАСТРОЙКИ =================
TOKEN = os.getenv("BOT_TOKEN")  # Берём токен из переменных окружения Render

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler()

DB_NAME = "reminders.db"

# ================= БАЗА ДАННЫХ =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                text TEXT,
                remind_time TEXT
            )
        """)
        await db.commit()

class ReminderForm(StatesGroup):
    waiting_for_text = State()
    waiting_for_time = State()

# Хендлеры (те же, что раньше)
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("Привет! 👋\n\n/new — добавить напоминание\n/my — мои напоминания")

@dp.message(Command("new"))
async def cmd_new(message: Message, state: FSMContext):
    await message.answer("Напиши текст напоминания:")
    await state.set_state(ReminderForm.waiting_for_text)

@dp.message(ReminderForm.waiting_for_text)
async def process_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer("Когда напомнить?\nПример: через 5 минут или 2026-03-25 15:30")
    await state.set_state(ReminderForm.waiting_for_time)

@dp.message(ReminderForm.waiting_for_time)
async def process_time(message: Message, state: FSMContext):
    data = await state.get_data()
    text = data.get("text", "")
    user_input = message.text.strip().lower()

    try:
        if user_input.startswith("через"):
            parts = user_input.split()
            value = int(parts[1])
            if "час" in user_input:
                delta = timedelta(hours=value)
            else:
                delta = timedelta(minutes=value)
            remind_time = datetime.now() + delta
        else:
            remind_time = datetime.strptime(user_input, "%Y-%m-%d %H:%M")

        remind_str = remind_time.strftime("%Y-%m-%d %H:%M:%S")

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO reminders (user_id, text, remind_time) VALUES (?, ?, ?)",
                (message.from_user.id, text, remind_str)
            )
            await db.commit()

        scheduler.add_job(send_reminder, DateTrigger(run_date=remind_time),
                          args=[message.from_user.id, text])

        await message.answer(f"✅ Сохранено!\nНапомню: {remind_time.strftime('%d.%m.%Y %H:%M')}")
        await state.clear()
    except:
        await message.answer("Не понял время. Попробуй ещё раз.")

async def send_reminder(user_id: int, text: str):
    try:
        await bot.send_message(user_id, f"⏰ <b>НАПОМИНАНИЕ!</b>\n\n{text}")
    except:
        pass

@dp.message(Command("my"))
async def cmd_my(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT text, remind_time FROM reminders WHERE user_id = ?",
            (message.from_user.id,)
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await message.answer("Пока нет напоминаний.")
        return

    text = "📋 Твои напоминания:\n\n"
    for row in rows:
        dt = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
        text += f"• {dt.strftime('%d.%m.%Y %H:%M')} — {row[0]}\n"
    await message.answer(text)

# ================= ЗАПУСК =================
async def main():
    await init_db()
    scheduler.start()
    print("✅ Бот запущен на Render!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())