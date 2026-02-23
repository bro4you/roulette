"""
🎰 Рулетка-бот v3 — полная перепись
"""
import os, json, logging
from datetime import datetime, timezone
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ══════════════════════════════════════
#  КОНФИГ
# ══════════════════════════════════════
BOT_TOKEN  = os.getenv("BOT_TOKEN", "")
ADMIN_ID   = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://bro4you.github.io/roulette")
DB_FILE    = Path("/tmp/spins.json")
# ══════════════════════════════════════

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()

# ── База данных (JSON-файл) ──────────────────────

def load_db() -> dict:
    try:
        if DB_FILE.exists():
            return json.loads(DB_FILE.read_text())
    except Exception as e:
        log.error(f"DB load error: {e}")
    return {"spins": {}, "agreed": []}

def save_db(db: dict):
    try:
        DB_FILE.write_text(json.dumps(db, ensure_ascii=False))
    except Exception as e:
        log.error(f"DB save error: {e}")

def already_spun(user_id: int) -> bool:
    db = load_db()
    uid = str(user_id)
    if uid not in db["spins"]:
        return False
    now = datetime.now(timezone.utc)
    s = db["spins"][uid]
    return s["year"] == now.year and s["month"] == now.month

def record_spin(user_id: int, username: str, full_name: str, prize: str):
    db = load_db()
    now = datetime.now(timezone.utc)
    db["spins"][str(user_id)] = {
        "year": now.year, "month": now.month,
        "prize": prize, "username": username,
        "full_name": full_name,
        "date": now.strftime("%d.%m.%Y %H:%M")
    }
    save_db(db)

def has_agreed(user_id: int) -> bool:
    db = load_db()
    return str(user_id) in db.get("agreed", [])

def set_agreed(user_id: int):
    db = load_db()
    if "agreed" not in db:
        db["agreed"] = []
    uid = str(user_id)
    if uid not in db["agreed"]:
        db["agreed"].append(uid)
    save_db(db)

# ── Проверка подписки ────────────────────────────

async def is_subscribed(user_id: int) -> bool:
    if not CHANNEL_ID:
        return True
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        log.warning(f"Sub check error: {e}")
        return True

# ── Тексты и клавиатуры ──────────────────────────

RULES = (
    "📋 <b>Правила участия в акции</b>\n\n"
    "Данная акция является <b>маркетинговой программой лояльности</b> "
    "и не является азартной игрой, лотереей или gambling.\n\n"
    "• Участие — добровольное и <b>бесплатное</b>\n"
    "• Призы — скидки и бесплатные услуги\n"
    "• Денежные средства не вносятся и не разыгрываются\n"
    "• <b>1 участие на 1 аккаунт в месяц</b>\n"
    "• Необходима подписка на канал организатора\n\n"
    "⏱ <b>Срок выдачи приза — до 14 календарных дней.</b>\n"
    "В случае форс-мажора организатор вправе перенести срок, уведомив участника.\n\n"
    "Нажимая «Принимаю», вы подтверждаете согласие с правилами."
)

def kb_rules():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принимаю правила", callback_data="agree")
    ]])

def kb_spin():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🎰 Крутить рулетку!", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True, one_time_keyboard=True
    )

def kb_subscribe():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/+pBThlAbAOA0wZjky")],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")]
    ])

# ── Хэндлеры ─────────────────────────────────────

@dp.message(CommandStart())
async def start(msg: types.Message):
    if not has_agreed(msg.from_user.id):
        await msg.answer(RULES, reply_markup=kb_rules(), parse_mode="HTML")
    else:
        await check_and_show(msg, msg.from_user)

@dp.callback_query(F.data == "agree")
async def on_agree(call: types.CallbackQuery):
    set_agreed(call.from_user.id)
    await call.answer("Принято ✅")
    await call.message.edit_reply_markup(reply_markup=None)
    await check_and_show(call.message, call.from_user)

@dp.callback_query(F.data == "check_sub")
async def on_check_sub(call: types.CallbackQuery):
    if await is_subscribed(call.from_user.id):
        await call.answer("Подписка подтверждена ✅")
        await call.message.edit_reply_markup(reply_markup=None)
        await check_and_show(call.message, call.from_user)
    else:
        await call.answer("Ты ещё не подписан 😕", show_alert=True)

async def check_and_show(msg: types.Message, user: types.User):
    if not await is_subscribed(user.id):
        await msg.answer("📢 Для участия нужно подписаться на канал!", reply_markup=kb_subscribe())
        return
    if already_spun(user.id):
        await msg.answer("⏳ Ты уже крутил рулетку в этом месяце.\nПриходи в следующем! 🙂")
        return
    await msg.answer("🎰 Всё готово! Нажми кнопку и крути рулетку!", reply_markup=kb_spin())

@dp.message(F.web_app_data)
async def on_webapp_data(msg: types.Message):
    user = msg.from_user
    log.info(f"web_app_data from {user.id} @{user.username}: {msg.web_app_data.data}")

    try:
        data = json.loads(msg.web_app_data.data)
        prize = data.get("prize", "—")
    except Exception as e:
        log.error(f"Parse error: {e}")
        await msg.answer("Ошибка. Напиши /start и попробуй снова.")
        return

    # Защита от двойного прокрута
    if already_spun(user.id):
        await msg.answer(
            "⚠️ Твой прокрут уже засчитан!\nВозвращайся в следующем месяце 🙂",
            reply_markup=types.ReplyKeyboardRemove()
        )
        return

    record_spin(user.id, user.username or "", user.full_name or "", prize)
    is_loss = "ещё раз" in prize.lower()

    if is_loss:
        await msg.answer(
            "😅 В этот раз не повезло...\nПриходи в следующем месяце!",
            reply_markup=types.ReplyKeyboardRemove()
        )
    else:
        await msg.answer(
            f"🎉 <b>Поздравляем!</b>\n\n"
            f"Твой приз: <b>{prize}</b>\n\n"
            f"Напиши нам чтобы получить приз.\n"
            f"⏱ Срок выдачи — до 14 дней.",
            parse_mode="HTML",
            reply_markup=types.ReplyKeyboardRemove()
        )

    if ADMIN_ID:
        emoji = "😅" if is_loss else "🏆"
        try:
            await bot.send_message(
                ADMIN_ID,
                f"🎰 <b>Новый прокрут!</b>\n\n"
                f"👤 {user.full_name} (@{user.username or '—'})\n"
                f"🆔 <code>{user.id}</code>\n"
                f"{emoji} Приз: <b>{prize}</b>\n"
                f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                parse_mode="HTML"
            )
        except Exception as e:
            log.error(f"Admin notify failed: {e}")

# ── Команды для админа ────────────────────────────

@dp.message(Command("stats"))
async def stats(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    db = load_db()
    spins = db.get("spins", {})
    now = datetime.now(timezone.utc)
    this_month = [(v["full_name"], v["username"], v["prize"], v["date"])
                  for v in spins.values()
                  if v["year"] == now.year and v["month"] == now.month]
    if not this_month:
        await msg.answer("В этом месяце прокрутов ещё не было.")
        return
    lines = [f"📊 <b>Прокруты за {now.strftime('%m.%Y')}:</b>\n"]
    for name, uname, prize, date in this_month:
        lines.append(f"• {name} (@{uname or '—'}) — {prize} [{date}]")
    await msg.answer("\n".join(lines), parse_mode="HTML")

@dp.message(Command("reset_me"))
async def reset_me(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    db = load_db()
    uid = str(msg.from_user.id)
    if uid in db["spins"]:
        del db["spins"][uid]
        save_db(db)
        await msg.answer("✅ Твой прокрут сброшен.")
    else:
        await msg.answer("У тебя нет прокрута в этом месяце.")

# ── Запуск ────────────────────────────────────────

async def main():
    log.info("Starting bot v3...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
