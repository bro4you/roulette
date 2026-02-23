"""
🎰 Рулетка-бот для Telegram Mini App
Автор: настраивай под себя в секции КОНФИГ ниже
"""

import os
import sqlite3
import json
import logging
from datetime import datetime, timezone
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

logging.basicConfig(level=logging.INFO)

# ════════════════════════════════════════════════
#  ⚙️  КОНФИГ — меняй только здесь
# ════════════════════════════════════════════════

BOT_TOKEN   = os.getenv("BOT_TOKEN", "ВСТАВЬ_ТОКЕН_СЮДА")
ADMIN_ID    = int(os.getenv("ADMIN_ID", "0"))          # твой Telegram user_id
CHANNEL_ID  = os.getenv("CHANNEL_ID", "-1001234567890") # числовой id канала (не invite-link!)
WEBAPP_URL  = os.getenv("WEBAPP_URL", "https://ВАШ_САЙТ.github.io/roulette")

# Webhook (нужен для Railway/Render). Для локального теста — закомментируй
WEBHOOK_HOST = os.getenv("RAILWAY_STATIC_URL", "")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL  = f"https://{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST else ""

# Призы — синхронизируй с roulette.html !
# label — то что видит клиент, weight — вероятность (чем больше, тем чаще)
PRIZES = [
    {"label": "1 отзыв бесплатно",   "weight": 3,  "rare": False},
    {"label": "Скидка 10%",           "weight": 3,  "rare": False},
    {"label": "2 отзыва бесплатно",   "weight": 1,  "rare": True},
    {"label": "Скидка 15%",           "weight": 2,  "rare": False},
    {"label": "Бонус на след. заказ", "weight": 3,  "rare": False},
    {"label": "Попробуй ещё раз 😅",  "weight": 4,  "rare": False},
    {"label": "Скидка 5%",            "weight": 3,  "rare": False},
    {"label": "3 отзыва бесплатно",   "weight": 1,  "rare": True},
]

# ════════════════════════════════════════════════

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()

# ── База данных ──────────────────────────────────

def get_db():
    conn = sqlite3.connect("spins.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS spins (
                user_id     INTEGER NOT NULL,
                username    TEXT,
                full_name   TEXT,
                prize       TEXT NOT NULL,
                spun_at     TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS agreements (
                user_id   INTEGER PRIMARY KEY,
                agreed_at TEXT NOT NULL
            )
        """)

def last_spin_this_month(user_id: int) -> bool:
    with get_db() as db:
        now = datetime.now(timezone.utc)
        row = db.execute("""
            SELECT spun_at FROM spins
            WHERE user_id = ?
            ORDER BY spun_at DESC LIMIT 1
        """, (user_id,)).fetchone()
        if not row:
            return False
        last = datetime.fromisoformat(row["spun_at"])
        return last.year == now.year and last.month == now.month

def save_spin(user_id: int, username: str, full_name: str, prize: str):
    with get_db() as db:
        db.execute("""
            INSERT INTO spins (user_id, username, full_name, prize, spun_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, username, full_name, prize, datetime.now(timezone.utc).isoformat()))

def has_agreed(user_id: int) -> bool:
    with get_db() as db:
        row = db.execute("SELECT 1 FROM agreements WHERE user_id = ?", (user_id,)).fetchone()
        return row is not None

def save_agreement(user_id: int):
    with get_db() as db:
        db.execute("""
            INSERT OR IGNORE INTO agreements (user_id, agreed_at) VALUES (?, ?)
        """, (user_id, datetime.now(timezone.utc).isoformat()))

# ── Проверка подписки ────────────────────────────

async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

# ── Хэндлеры ────────────────────────────────────

RULES_TEXT = """
📋 <b>Правила участия в акции</b>

Данная акция является <b>маркетинговой программой лояльности</b> и не является азартной игрой, лотереей или иной формой gambling.

• Участие в акции — добровольное и бесплатное
• Призы — маркетинговые бонусы (скидки, бесплатные услуги)
• Никакие денежные средства не вносятся и не разыгрываются
• 1 участие на 1 аккаунт в месяц
• Участник должен быть подписчиком канала

⏱ <b>Срок выдачи приза:</b> до 14 календарных дней с момента выигрыша.
В случае форс-мажорных обстоятельств организатор вправе перенести срок выдачи, уведомив участника.

Нажимая «Принимаю», вы соглашаетесь с правилами.
"""

def rules_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принимаю правила", callback_data="agree")
    ]])

def spin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🎰 Крутить рулетку!",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    ]])

def subscribe_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/+pBThlAbAOA0wZjky")],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")]
    ])

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user = message.from_user
    if not has_agreed(user.id):
        await message.answer(RULES_TEXT, reply_markup=rules_kb(), parse_mode="HTML")
        return
    await show_spin_or_block(message, user)

@dp.callback_query(F.data == "agree")
async def cb_agree(call: types.CallbackQuery):
    save_agreement(call.from_user.id)
    await call.message.edit_reply_markup()
    await call.answer("Правила приняты ✅")
    await show_spin_or_block(call.message, call.from_user)

@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(call: types.CallbackQuery):
    if await is_subscribed(call.from_user.id):
        await call.answer("Отлично, подписка подтверждена! ✅")
        await show_spin_or_block(call.message, call.from_user, edit=True)
    else:
        await call.answer("Ты ещё не подписан 😕", show_alert=True)

async def show_spin_or_block(message: types.Message, user, edit=False):
    if not await is_subscribed(user.id):
        text = "📢 Для участия нужно подписаться на наш канал!"
        kb = subscribe_kb()
        if edit:
            await message.edit_text(text, reply_markup=kb)
        else:
            await message.answer(text, reply_markup=kb)
        return

    if last_spin_this_month(user.id):
        text = "⏳ Ты уже крутил рулетку в этом месяце.\nПриходи в следующем!"
        if edit:
            await message.edit_text(text)
        else:
            await message.answer(text)
        return

    text = "🎰 Всё готово! Нажми кнопку и крути рулетку!"
    kb = spin_kb()
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)

# ── Получаем результат от Mini App ──────────────

@dp.message(F.web_app_data)
async def handle_webapp_data(message: types.Message):
    user = message.from_user
    try:
        data = json.loads(message.web_app_data.data)
        prize = data.get("prize", "—")
    except Exception:
        await message.answer("Что-то пошло не так 😢 Попробуй снова.")
        return

    # Защита от двойного прокрута
    if last_spin_this_month(user.id):
        await message.answer("Этот результат уже засчитан. Возвращайся в следующем месяце! 🙂")
        return

    save_spin(user.id, user.username or "", user.full_name or "", prize)

    # Сообщение победителю
    if "ещё раз" in prize:
        await message.answer(f"😅 К сожалению, в этот раз не повезло.\nПриходи в следующем месяце!")
    else:
        await message.answer(
            f"🎉 Поздравляем!\n\n"
            f"Твой приз: <b>{prize}</b>\n\n"
            f"Свяжись с нами для получения приза.\n"
            f"⏱ Срок выдачи — до 14 дней.",
            parse_mode="HTML"
        )

    # Уведомление тебе как админу
    if ADMIN_ID:
        await bot.send_message(
            ADMIN_ID,
            f"🎰 <b>Новый выигрыш!</b>\n\n"
            f"👤 {user.full_name} (@{user.username or '—'})\n"
            f"🆔 <code>{user.id}</code>\n"
            f"🏆 Приз: <b>{prize}</b>\n"
            f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            parse_mode="HTML"
        )

# ── Запуск ───────────────────────────────────────

async def on_startup(app):
    init_db()
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL)
        logging.info(f"Webhook set: {WEBHOOK_URL}")
    else:
        logging.info("Polling mode")

async def main():
    init_db()
    if WEBHOOK_URL:
        app = web.Application()
        app.on_startup.append(on_startup)
        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
        port = int(os.getenv("PORT", 8080))
        web.run_app(app, host="0.0.0.0", port=port)
    else:
        await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
