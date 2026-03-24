import asyncio
import logging
import os
from datetime import datetime, timedelta
import zoneinfo

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from aiohttp import web

# ================= НАСТРОЙКИ =================
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080))
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL")

if not TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в Environment!")

if not WEBHOOK_URL:
    raise ValueError("❌ RENDER_EXTERNAL_URL не найден!")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
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

# ================= СОСТОЯНИЯ =================
class ReminderForm(StatesGroup):
    waiting_for_text = State()
    waiting_for_time = State()

# ================= ХЕНДЛЕРЫ =================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("Привет! 👋\n\n/new — новое напоминание\n/my — мои напоминания")

@dp.message(Command("new"))
async def cmd_new(message: Message, state: FSMContext):
    await message.answer("Напиши текст напоминания:")
    await state.set_state(ReminderForm.waiting_for_text)

@dp.message(ReminderForm.waiting_for_text)
async def process_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer("Когда напомнить?\nПример:\nчерез 10 минут\nили\n2026-03-25 15:30")
    await state.set_state(ReminderForm.waiting_for_time)

@dp.message(ReminderForm.waiting_for_time)
async def process_time(message: Message, state: FSMContext):
    data = await state.get_data()
    text = data.get("text", "")
    user_input = message.text.strip().lower()

    try:
        moscow_tz = zoneinfo.ZoneInfo("Europe/Moscow")
        now = datetime.now(moscow_tz)

        if user_input.startswith("через"):
            parts = user_input.split()
            value = int(parts[1])
            delta = timedelta(hours=value) if "час" in user_input else timedelta(minutes=value)
            remind_time = now + delta
        else:
            remind_time_naive = datetime.strptime(user_input, "%Y-%m-%d %H:%M")
            remind_time = remind_time_naive.replace(tzinfo=moscow_tz)

        remind_str = remind_time.strftime("%Y-%m-%d %H:%M:%S")

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO reminders (user_id, text, remind_time) VALUES (?, ?, ?)",
                (message.from_user.id, text, remind_str)
            )
            await db.commit()

        scheduler.add_job(send_reminder, DateTrigger(run_date=remind_time), args=[message.from_user.id, text])

        await message.answer(f"✅ Сохранено!\nНапомню: {remind_time.strftime('%d.%m.%Y %H:%M')} (Москва)")
        await state.clear()

    except Exception:
        await message.answer("Не понял время.\nПример: через 10 минут или 2026-03-25 15:30")

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

# ================= WEBHOOK =================
async def on_startup(bot: Bot):
    webhook_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
    await bot.set_webhook(webhook_url)
    await init_db()
    scheduler.start()
    print(f"🚀 Бот запущен! Webhook: {webhook_url}")

async def on_shutdown(bot: Bot):
    await bot.delete_webhook(drop_pending_updates=True)
    print("🛑 Бот остановлен")

# ================= ЗАПУСК =================
app = web.Application()
dp["bot"] = bot

# Регистрируем хендлеры
dp.startup.register(on_startup)
dp.shutdown.register(on_shutdown)

SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)

setup_application(app, dp, bot=bot)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)