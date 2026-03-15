"""
🎰 Рулетка-бот v4 — постоянное хранение + рассылка
"""
import os, json, logging, asyncio
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

# Постоянное хранилище: если подключён Volume на Railway — /data/spins.json
# Если нет — падаем обратно на /tmp (но лучше подключить Volume!)
_DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
try:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_FILE = _DATA_DIR / "spins.json"
    # Проверим, что папка реально доступна для записи
    DB_FILE.touch(exist_ok=True)
    log.info(f"DB path: {DB_FILE}")
except Exception:
    log.warning("⚠️  /data недоступен — используем /tmp (данные могут сброситься при рестарте!)")
    DB_FILE = Path("/tmp/spins.json")
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
    return {"spins": {}, "agreed": [], "users": {}}

def save_db(db: dict):
    try:
        DB_FILE.write_text(json.dumps(db, ensure_ascii=False, indent=2))
    except Exception as e:
        log.error(f"DB save error: {e}")

def already_spun(user_id: int) -> bool:
    db = load_db()
    uid = str(user_id)
    if uid not in db["spins"]:
        return False
    now = datetime.now(timezone.utc)
    s = db["spins"][uid]
    spin_date_str = s.get("date", "")
    try:
        spin_dt = datetime.strptime(spin_date_str, "%d.%m.%Y %H:%M").replace(tzinfo=timezone.utc)
        return (now - spin_dt).days < 14
    except Exception:
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

def register_user(user: types.User):
    """Сохраняем пользователя в базу для рассылки"""
    db = load_db()
    if "users" not in db:
        db["users"] = {}
    uid = str(user.id)
    db["users"][uid] = {
        "username": user.username or "",
        "full_name": user.full_name or "",
        "id": user.id
    }
    save_db(db)

def get_all_users() -> list[dict]:
    db = load_db()
    return list(db.get("users", {}).values())

# ── Проверка подписки ────────────────────────────

async def is_subscribed(user_id: int) -> bool:
    if not CHANNEL_ID:
        log.warning("CHANNEL_ID не задан — проверка подписки отключена!")
        return True
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        log.info(f"Sub check user={user_id} status={member.status}")
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        log.error(f"Sub check FAILED user={user_id} channel={CHANNEL_ID} error={e}")
        return False

# ── Тексты и клавиатуры ──────────────────────────

RULES = (
    "📋 <b>Правила участия в акции</b>\n\n"
    "Данная акция является <b>маркетинговой программой лояльности</b> "
    "и не является азартной игрой, лотереей или gambling.\n\n"
    "• Участие — добровольное и <b>бесплатное</b>\n"
    "• Призы — скидки и бесплатные услуги\n"
    "• Денежные средства не вносятся и не разыгрываются\n"
    "• <b>1 участие на 1 аккаунт раз в 14 дней</b>\n"
    "• <b>Бонус действует 7 дней</b> с момента розыгрыша, затем сгорает\n"
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
    register_user(msg.from_user)  # Сохраняем для рассылки
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
        await msg.answer("⏳ Ты уже крутил рулетку в течение последних 14 дней.\nПриходи позже! 🙂")
        return
    await msg.answer("🎰 Всё готово! Нажми кнопку и крути рулетку!", reply_markup=kb_spin())

@dp.message(F.web_app_data)
async def on_webapp_data(msg: types.Message):
    user = msg.from_user
    log.info(f"web_app_data from {user.id} @{user.username}: {msg.web_app_data.data}")

    if not await is_subscribed(user.id):
        log.warning(f"User {user.id} sent web_app_data without subscription — blocked!")
        await msg.answer(
            "❌ Прокрут не засчитан — ты не подписан на канал!\n\n"
            "Подпишись и начни заново через /start",
            reply_markup=kb_subscribe()
        )
        return

    try:
        data = json.loads(msg.web_app_data.data)
        prize = data.get("prize", "—")
    except Exception as e:
        log.error(f"Parse error: {e}")
        await msg.answer("Ошибка. Напиши /start и попробуй снова.")
        return

    if already_spun(user.id):
        await msg.answer(
            "⚠️ Твой прокрут уже засчитан!\nВозвращайся через 14 дней 🙂",
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
            f"⏱ Срок выдачи — до 14 дней.\n"
            f"⚠️ <b>Бонус действует 7 дней</b> — не забудь воспользоваться!",
            parse_mode="HTML",
            reply_markup=types.ReplyKeyboardRemove()
        )

    if ADMIN_ID:
        emoji = "😅" if is_loss else "🏆"
        log.info(f"Sending admin notify to {ADMIN_ID} for user {user.id}...")
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
            log.info(f"Admin notify sent OK to {ADMIN_ID}")
        except Exception as e:
            log.error(f"Admin notify FAILED to {ADMIN_ID}: {e}")

# ── Команды для админа ────────────────────────────

@dp.message(Command("stats"))
async def stats(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    db = load_db()
    spins = db.get("spins", {})
    users_count = len(db.get("users", {}))
    now = datetime.now(timezone.utc)
    this_month = [(v["full_name"], v["username"], v["prize"], v["date"])
                  for v in spins.values()
                  if v["year"] == now.year and v["month"] == now.month]
    lines = [f"📊 <b>Статистика за {now.strftime('%m.%Y')}:</b>\n",
             f"👥 Всего пользователей в базе: <b>{users_count}</b>\n"]
    if this_month:
        for name, uname, prize, date in this_month:
            lines.append(f"• {name} (@{uname or '—'}) — {prize} [{date}]")
    else:
        lines.append("Прокрутов в этом месяце ещё не было.")
    await msg.answer("\n".join(lines), parse_mode="HTML")

@dp.message(Command("broadcast"))
async def broadcast(msg: types.Message):
    """Рассылка всем пользователям.
    Использование: /broadcast Текст сообщения
    Поддерживает HTML-разметку: <b>жирный</b>, <i>курсив</i>
    """
    if msg.from_user.id != ADMIN_ID:
        return

    text = msg.text.removeprefix("/broadcast").strip()
    if not text:
        await msg.answer(
            "📢 <b>Рассылка</b>\n\n"
            "Использование:\n"
            "<code>/broadcast Текст сообщения</code>\n\n"
            "Поддерживается HTML:\n"
            "<code>/broadcast 🎰 &lt;b&gt;Акция!&lt;/b&gt; Крути рулетку прямо сейчас!</code>",
            parse_mode="HTML"
        )
        return

    users = get_all_users()
    total = len(users)
    if total == 0:
        await msg.answer("❌ В базе нет пользователей.")
        return

    await msg.answer(f"📤 Начинаю рассылку для <b>{total}</b> пользователей...", parse_mode="HTML")

    sent = 0
    failed = 0
    blocked = 0

    for user in users:
        try:
            await bot.send_message(user["id"], text, parse_mode="HTML")
            sent += 1
        except Exception as e:
            err = str(e).lower()
            if "blocked" in err or "deactivated" in err or "chat not found" in err:
                blocked += 1
            else:
                failed += 1
                log.error(f"Broadcast failed for {user['id']}: {e}")
        # Небольшая пауза чтобы не получить флуд-блок от Telegram
        await asyncio.sleep(0.05)

    await msg.answer(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📨 Отправлено: <b>{sent}</b>\n"
        f"🚫 Заблокировали бота: <b>{blocked}</b>\n"
        f"❌ Ошибки: <b>{failed}</b>",
        parse_mode="HTML"
    )

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
        await msg.answer("У тебя нет прокрута в базе.")

@dp.message(Command("reset_all"))
async def reset_all(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    db = load_db()
    count = len(db["spins"])
    db["spins"] = {}
    save_db(db)
    await msg.answer(f"✅ База прокрутов полностью сброшена. Удалено записей: {count}")

@dp.message(Command("reset_user"))
async def reset_user(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.split()
    if len(parts) < 2:
        await msg.answer(
            "Укажи ID пользователя:\n"
            "<code>/reset_user 123456789</code>\n\n"
            "ID можно найти в уведомлении о прокруте или через /stats",
            parse_mode="HTML"
        )
        return
    uid = parts[1].strip()
    db = load_db()
    if uid in db["spins"]:
        name = db["spins"][uid].get("full_name", "—")
        uname = db["spins"][uid].get("username", "—")
        del db["spins"][uid]
        save_db(db)
        await msg.answer(f"✅ Прокрут сброшен:\n{name} (@{uname}) ID: <code>{uid}</code>", parse_mode="HTML")
    else:
        await msg.answer(f"❌ Пользователь <code>{uid}</code> не найден в базе.", parse_mode="HTML")

# ── Запуск ────────────────────────────────────────

async def main():
    log.info("Starting bot v4...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    asyncio.run(main())
