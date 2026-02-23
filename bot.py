"""
🎰 Рулетка-бот — исправленная версия
"""

import os
import json
import logging
from datetime import datetime, timezone
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
)

logging.basicConfig(level=logging.INFO)

# ════════════════════════════════════════════════
#  ⚙️  КОНФИГ
# ════════════════════════════════════════════════
BOT_TOKEN  = os.getenv("BOT_TOKEN", "")
ADMIN_ID   = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://bro4you.github.io/roulette")
# ════════════════════════════════════════════════

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()

# Хранилище в памяти: {user_id: {"year": int, "month": int, "prize": str}}
spins: dict = {}
# Кто принял правила
agreed: dict = {}

def already_spun_this_month(user_id: int) -> bool:
    if user_id not in spins:
        return False
    now = datetime.now(timezone.utc)
    s = spins[user_id]
    return s["year"] == now.year and s["month"] == now.month

def save_spin(user_id: int, prize: str):
    now = datetime.now(timezone.utc)
    spins[user_id] = {"year": now.year, "month": now.month, "prize": prize}

# ── Клавиатуры ───────────────────────────────────

def rules_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принимаю правила", callback_data="agree")
    ]])

def spin_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(
            text="🎰 Крутить рулетку!",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def subscribe_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/+pBThlAbAOA0wZjky")],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")]
    ])

# ── Проверка подписки ────────────────────────────

async def is_subscribed(user_id: int) -> bool:
    if not CHANNEL_ID:
        return True
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logging.warning(f"Subscription check failed: {e}")
        return True

# ── Хэндлеры ────────────────────────────────────

RULES_TEXT = (
    "📋 <b>Правила участия в акции</b>\n\n"
    "Данная акция является <b>маркетинговой программой лояльности</b> и не является "
    "азартной игрой, лотереей или иной формой gambling.\n\n"
    "• Участие — добровольное и бесплатное\n"
    "• Призы — маркетинговые бонусы (скидки, бесплатные услуги)\n"
    "• Никакие денежные средства не вносятся и не разыгрываются\n"
    "• 1 участие на 1 аккаунт в месяц\n"
    "• Участник должен быть подписчиком канала\n\n"
    "⏱ <b>Срок выдачи приза:</b> до 14 календарных дней с момента выигрыша.\n"
    "В случае форс-мажора организатор вправе перенести срок, уведомив участника.\n\n"
    "Нажимая «Принимаю», вы соглашаетесь с правилами."
)

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user = message.from_user
    if user.id not in agreed:
        await message.answer(RULES_TEXT, reply_markup=rules_kb(), parse_mode="HTML")
    else:
        await show_spin_or_block(message, user)

@dp.callback_query(F.data == "agree")
async def cb_agree(call: types.CallbackQuery):
    agreed[call.from_user.id] = True
    await call.answer("Правила приняты ✅")
    await call.message.edit_reply_markup(reply_markup=None)
    await show_spin_or_block(call.message, call.from_user)

@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(call: types.CallbackQuery):
    if await is_subscribed(call.from_user.id):
        await call.answer("Подписка подтверждена ✅")
        await call.message.edit_reply_markup(reply_markup=None)
        await show_spin_or_block(call.message, call.from_user)
    else:
        await call.answer("Ты ещё не подписан 😕", show_alert=True)

async def show_spin_or_block(message: types.Message, user):
    if not await is_subscribed(user.id):
        await message.answer(
            "📢 Для участия нужно подписаться на наш канал!",
            reply_markup=subscribe_kb()
        )
        return

    if already_spun_this_month(user.id):
        await message.answer("⏳ Ты уже крутил рулетку в этом месяце.\nПриходи в следующем! 🙂")
        return

    await message.answer(
        "🎰 Всё готово! Нажми кнопку ниже и крути рулетку!",
        reply_markup=spin_kb()
    )

# ── Получаем результат от Mini App ──────────────

@dp.message(F.web_app_data)
async def handle_webapp_data(message: types.Message):
    user = message.from_user
    logging.info(f"web_app_data from {user.id}: {message.web_app_data.data}")

    try:
        data = json.loads(message.web_app_data.data)
        prize = data.get("prize", "—")
    except Exception as e:
        logging.error(f"Parse error: {e}")
        await message.answer("Что-то пошло не так 😢 Попробуй /start")
        return

    if already_spun_this_month(user.id):
        await message.answer(
            "⚠️ Результат уже засчитан. Возвращайся в следующем месяце! 🙂",
            reply_markup=types.ReplyKeyboardRemove()
        )
        return

    save_spin(user.id, prize)
    is_loss = "ещё раз" in prize

    if is_loss:
        await message.answer(
            "😅 К сожалению, в этот раз не повезло.\nПриходи в следующем месяце!",
            reply_markup=types.ReplyKeyboardRemove()
        )
    else:
        await message.answer(
            f"🎉 <b>Поздравляем!</b>\n\n"
            f"Твой приз: <b>{prize}</b>\n\n"
            f"Напиши нам для получения приза.\n"
            f"⏱ Срок выдачи — до 14 дней.",
            parse_mode="HTML",
            reply_markup=types.ReplyKeyboardRemove()
        )

    # Уведомление админу
    if ADMIN_ID:
        status = "😅 Не повезло" if is_loss else f"🏆 {prize}"
        try:
            await bot.send_message(
                ADMIN_ID,
                f"🎰 <b>Новый прокрут!</b>\n\n"
                f"👤 {user.full_name} (@{user.username or '—'})\n"
                f"🆔 <code>{user.id}</code>\n"
                f"🎁 Результат: <b>{status}</b>\n"
                f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Admin notify failed: {e}")

# ── Сброс для теста (только для админа) ─────────

@dp.message(Command("reset"))
async def cmd_reset(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        spins.clear()
        agreed.clear()
        await message.answer("✅ База сброшена")
    else:
        await message.answer("❌ Нет доступа")

# ── Запуск ───────────────────────────────────────

async def main():
    logging.info("Bot starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
