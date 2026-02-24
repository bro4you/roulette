"""
🎰 Рулетка-бот v4 — прокрут раз в 14 дней
"""

import os, json, logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BOT_TOKEN  = os.getenv("BOT_TOKEN", "")
ADMIN_ID   = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://bro4you.github.io/roulette")
DB_FILE    = Path("/tmp/spins.json")

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()

# ───────── БАЗА ─────────

def load_db():
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text())
    return {"spins": {}, "agreed": []}

def save_db(db):
    DB_FILE.write_text(json.dumps(db, ensure_ascii=False))

def already_spun(user_id: int):
    db = load_db()
    uid = str(user_id)
    if uid not in db["spins"]:
        return False

    now = datetime.now(timezone.utc)
    spin_time = datetime.strptime(db["spins"][uid]["date"], "%d.%m.%Y %H:%M")
    spin_time = spin_time.replace(tzinfo=timezone.utc)

    return now - spin_time < timedelta(days=14)

def record_spin(user_id, username, full_name, prize):
    db = load_db()
    now = datetime.now(timezone.utc)
    db["spins"][str(user_id)] = {
        "prize": prize,
        "username": username,
        "full_name": full_name,
        "date": now.strftime("%d.%m.%Y %H:%M")
    }
    save_db(db)

def has_agreed(user_id):
    db = load_db()
    return str(user_id) in db.get("agreed", [])

def set_agreed(user_id):
    db = load_db()
    db.setdefault("agreed", []).append(str(user_id))
    save_db(db)

# ───────── ПРАВИЛА ─────────

RULES = (
    "📋 <b>Правила участия</b>\n\n"
    "• Участие бесплатное\n"
    "• 1 участие раз в 14 дней\n"
    "• Бонус действует 7 дней\n"
    "• Требуется подписка на канал\n\n"
    "⏱ Срок выдачи приза — до 14 дней."
)

def kb_rules():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принимаю", callback_data="agree")
    ]])

def kb_spin():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🎰 Крутить", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True
    )

# ───────── ХЭНДЛЕРЫ ─────────

@dp.message(CommandStart())
async def start(msg: types.Message):
    if not has_agreed(msg.from_user.id):
        await msg.answer(RULES, reply_markup=kb_rules(), parse_mode="HTML")
    else:
        if already_spun(msg.from_user.id):
            await msg.answer("⏳ Ты уже крутил рулетку. Попробуй через 14 дней.")
        else:
            await msg.answer("🎰 Нажми кнопку и крути!", reply_markup=kb_spin())

@dp.callback_query(F.data == "agree")
async def agree(call: types.CallbackQuery):
    set_agreed(call.from_user.id)
    await call.message.edit_reply_markup()
    await call.message.answer("🎰 Теперь можешь крутить!", reply_markup=kb_spin())

@dp.message(F.web_app_data)
async def result(msg: types.Message):
    user = msg.from_user

    if already_spun(user.id):
        await msg.answer("⚠️ Прокрут уже был.")
        return

    data = json.loads(msg.web_app_data.data)
    prize = data.get("prize", "-")

    record_spin(user.id, user.username or "", user.full_name or "", prize)

    await msg.answer(
        f"🎉 <b>Твой приз:</b> {prize}\n\n"
        f"⚠️ Бонус действует 7 дней.\n"
        f"Напиши нам для получения.",
        parse_mode="HTML"
    )

    if ADMIN_ID:
        await bot.send_message(
            ADMIN_ID,
            f"🎰 Новый прокрут\n{user.full_name} (@{user.username})\nПриз: {prize}"
        )

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
