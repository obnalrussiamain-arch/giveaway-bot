import os
import json
import logging
import random
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID     = os.environ.get("CHANNEL_ID", "")
ADMIN_ID       = int(os.environ.get("ADMIN_ID", "0"))
GIVEAWAY_TITLE = os.environ.get("GIVEAWAY_TITLE", "Розыгрыш!")
PRIZE_TEXT     = os.environ.get("PRIZE_TEXT", "Суперприз")
DATA_FILE      = "participants.json"
# ─── Persistent storage ───────────────────────────────────────────────────────
def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"participants": {}, "winner": None, "active": True}

def save_data(data: dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ─── Helpers ──────────────────────────────────────────────────────────────────
async def is_subscribed(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in (
            ChatMember.MEMBER,
            ChatMember.ADMINISTRATOR,
            ChatMember.OWNER,
        )
    except Exception as e:
        logger.warning(f"Subscription check failed: {e}")
        return False

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id != ADMIN_ID:
            await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
            return
        return await func(update, context)
    return wrapper

# ─── User commands ────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    keyboard = [[InlineKeyboardButton("🎯 Участвовать", callback_data="join")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    status_line = ""
    if not data["active"]:
        status_line = "\n\n🔒 *Розыгрыш завершён.*"
    elif data["winner"]:
        w = data["winner"]
        status_line = f"\n\n🏆 Победитель: [{w['name']}](tg://user?id={w['id']})"

    await update.message.reply_text(
        f"*{GIVEAWAY_TITLE}*\n\n"
        f"🎁 Приз: *{PRIZE_TEXT}*\n\n"
        f"Чтобы участвовать — подпишитесь на канал {CHANNEL_ID} и нажмите кнопку ниже.{status_line}",
        parse_mode="Markdown",
        reply_markup=reply_markup if data["active"] else None,
    )

async def join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = load_data()
    user = query.from_user
    uid  = str(user.id)

    if not data["active"]:
        await query.edit_message_text("🔒 Розыгрыш уже завершён.")
        return

    if uid in data["participants"]:
        await query.answer("✅ Вы уже участвуете!", show_alert=True)
        return

    subscribed = await is_subscribed(update, context, user.id)
    if not subscribed:
        keyboard = [[InlineKeyboardButton(
            "📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}"
        )]]
        await query.message.reply_text(
            "❌ Вы не подписаны на канал!\n\n"
            f"Подпишитесь на {CHANNEL_ID} и нажмите «Участвовать» снова.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    data["participants"][uid] = {
        "id":       user.id,
        "name":     user.full_name,
        "username": user.username or "",
        "joined_at": datetime.utcnow().isoformat(),
    }
    save_data(data)

    total = len(data["participants"])
    await query.answer("🎉 Вы успешно зарегистрированы!", show_alert=True)
    await query.message.reply_text(
        f"✅ *{user.full_name}*, вы участвуете в розыгрыше!\n"
        f"👥 Всего участников: *{total}*",
        parse_mode="Markdown",
    )

# ─── Admin commands ────────────────────────────────────────────────────────────
@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    parts = data["participants"]
    total = len(parts)

    lines = [f"🛠 *Панель администратора*\n",
             f"📊 Участников: *{total}*",
             f"🔄 Статус: {'активен' if data['active'] else 'завершён'}"]

    if data["winner"]:
        w = data["winner"]
        lines.append(f"🏆 Победитель: [{w['name']}](tg://user?id={w['id']})")

    keyboard = [
        [InlineKeyboardButton("👥 Список участников", callback_data="admin_list_0")],
        [InlineKeyboardButton("🎲 Выбрать победителя", callback_data="admin_pick")],
        [InlineKeyboardButton("🔒 Завершить розыгрыш", callback_data="admin_close")],
        [InlineKeyboardButton("🔓 Открыть розыгрыш",   callback_data="admin_open")],
    ]
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return
    await query.answer()

    data = load_data()
    action = query.data

    # ── List participants (paginated, 10 per page) ──
    if action.startswith("admin_list_"):
        page = int(action.split("_")[-1])
        parts = list(data["participants"].values())
        page_size = 10
        start = page * page_size
        chunk = parts[start:start + page_size]

        if not chunk:
            await query.edit_message_text("👥 Участников пока нет.")
            return

        lines = [f"👥 *Участники* (стр. {page+1})\n"]
        for i, p in enumerate(chunk, start + 1):
            uname = f"@{p['username']}" if p["username"] else "—"
            lines.append(f"{i}. [{p['name']}](tg://user?id={p['id']}) {uname}")

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"admin_list_{page-1}"))
        if start + page_size < len(parts):
            nav.append(InlineKeyboardButton("▶️", callback_data=f"admin_list_{page+1}"))

        keyboard = [nav] if nav else []
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_back")])

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # ── Pick winner ──
    elif action == "admin_pick":
        parts = list(data["participants"].values())
        if not parts:
            await query.edit_message_text("👥 Нет участников для розыгрыша.")
            return

        # Show list with buttons to manually pick
        lines = ["🎯 *Выберите победителя вручную или нажмите «Случайно»:*\n"]
        keyboard = []
        for p in parts:
            keyboard.append([InlineKeyboardButton(
                f"{p['name']} (@{p['username'] or '—'})",
                callback_data=f"admin_setwinner_{p['id']}"
            )])
        keyboard.append([InlineKeyboardButton("🎲 Выбрать случайно", callback_data="admin_random")])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_back")])

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # ── Random winner ──
    elif action == "admin_random":
        parts = list(data["participants"].values())
        if not parts:
            await query.edit_message_text("👥 Нет участников.")
            return
        winner = random.choice(parts)
        await _set_winner(query, data, winner)

    # ── Manual winner ──
    elif action.startswith("admin_setwinner_"):
        uid = str(action.split("_")[-1])
        winner = data["participants"].get(uid)
        if not winner:
            await query.edit_message_text("❌ Участник не найден.")
            return
        await _set_winner(query, data, winner)

    # ── Close giveaway ──
    elif action == "admin_close":
        data["active"] = False
        save_data(data)
        await query.edit_message_text("🔒 Розыгрыш завершён.")

    # ── Open giveaway ──
    elif action == "admin_open":
        data["active"] = True
        save_data(data)
        await query.edit_message_text("🔓 Розыгрыш открыт!")

    # ── Back to panel ──
    elif action == "admin_back":
        parts = data["participants"]
        total = len(parts)
        lines = [f"🛠 *Панель администратора*\n",
                 f"📊 Участников: *{total}*",
                 f"🔄 Статус: {'активен' if data['active'] else 'завершён'}"]
        if data["winner"]:
            w = data["winner"]
            lines.append(f"🏆 Победитель: [{w['name']}](tg://user?id={w['id']})")

        keyboard = [
            [InlineKeyboardButton("👥 Список участников", callback_data="admin_list_0")],
            [InlineKeyboardButton("🎲 Выбрать победителя", callback_data="admin_pick")],
            [InlineKeyboardButton("🔒 Завершить розыгрыш", callback_data="admin_close")],
            [InlineKeyboardButton("🔓 Открыть розыгрыш",   callback_data="admin_open")],
        ]
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

async def _set_winner(query, data: dict, winner: dict) -> None:
    data["winner"] = winner
    save_data(data)
    uname = f"@{winner['username']}" if winner["username"] else ""
    await query.edit_message_text(
        f"🏆 *Победитель выбран!*\n\n"
        f"👤 [{winner['name']}](tg://user?id={winner['id']}) {uname}\n\n"
        f"Объявите победителя в канале!",
        parse_mode="Markdown",
    )

@admin_only
async def announce_winner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if not data["winner"]:
        await update.message.reply_text("⚠️ Победитель ещё не выбран. Используйте /admin")
        return
    w = data["winner"]
    uname = f"@{w['username']}" if w["username"] else ""
    text = (
        f"🎉 *{GIVEAWAY_TITLE}* — Результаты!\n\n"
        f"🏆 Победитель: [{w['name']}](tg://user?id={w['id']}) {uname}\n\n"
        f"🎁 Приз: *{PRIZE_TEXT}*\n\n"
        f"Поздравляем!"
    )
    await context.bot.send_message(CHANNEL_ID, text, parse_mode="Markdown")
    await update.message.reply_text("✅ Объявление отправлено в канал!")

@admin_only
async def reset_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    save_data({"participants": {}, "winner": None, "active": True})
    await update.message.reply_text("♻️ Розыгрыш сброшен. Все участники удалены.")

# ─── Main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("admin",    admin_panel))
    app.add_handler(CommandHandler("announce", announce_winner))
    app.add_handler(CommandHandler("reset",    reset_giveaway))

    app.add_handler(CallbackQueryHandler(join_callback,  pattern="^join$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))

    logger.info("Bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
