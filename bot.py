import os
import json
import logging
import random
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
GIVEAWAY_TITLE = os.environ.get("GIVEAWAY_TITLE", "Розыгрыш!")
PRIZE_TEXT = os.environ.get("PRIZE_TEXT", "Суперприз")
DATA_FILE = "participants.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"participants": {}, "winner": None, "active": True}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

async def is_subscribed(context, user_id):
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in (ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER)
    except Exception as e:
        logger.warning(f"Sub check failed: {e}")
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    kb = [[InlineKeyboardButton("Участвовать", callback_data="join")]]
    note = ""
    if not data["active"]:
        note = "\n\nРозыгрыш завершён."
    elif data["winner"]:
        note = f"\n\nПобедитель: {data['winner']['name']}"
    await update.message.reply_text(
        f"{GIVEAWAY_TITLE}\nПриз: {PRIZE_TEXT}\n\nПодпишитесь на {CHANNEL_ID} и нажмите кнопку.{note}",
        reply_markup=InlineKeyboardMarkup(kb) if data["active"] else None
    )

async def join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = load_data()
    user = query.from_user
    uid = str(user.id)
    if not data["active"]:
        await query.edit_message_text("Розыгрыш завершён.")
        return
    if uid in data["participants"]:
        await query.answer("Вы уже участвуете!", show_alert=True)
        return
    if not await is_subscribed(context, user.id):
        kb = [[InlineKeyboardButton("Подписаться", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}")]]
        await query.message.reply_text(
            f"Сначала подпишитесь на {CHANNEL_ID}, затем нажмите Участвовать снова.",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return
    data["participants"][uid] = {
        "id": user.id, "name": user.full_name,
        "username": user.username or "", "joined_at": datetime.utcnow().isoformat()
    }
    save_data(data)
    await query.answer("Вы зарегистрированы!", show_alert=True)
    await query.message.reply_text(f"{user.full_name}, вы участвуете! Всего: {len(data['participants'])}")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    data = load_data()
    kb = [
        [InlineKeyboardButton("Список участников", callback_data="admin_list_0")],
        [InlineKeyboardButton("Выбрать победителя", callback_data="admin_pick")],
        [InlineKeyboardButton("Завершить розыгрыш", callback_data="admin_close")],
        [InlineKeyboardButton("Открыть розыгрыш", callback_data="admin_open")],
    ]
    w = f"\nПобедитель: {data['winner']['name']}" if data["winner"] else ""
    await update.message.reply_text(
        f"Админ панель\nУчастников: {len(data['participants'])}\nСтатус: {'активен' if data['active'] else 'завершён'}{w}",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("Нет доступа", show_alert=True)
        return
    await query.answer()
    data = load_data()
    action = query.data

    if action.startswith("admin_list_"):
        page = int(action.split("_")[-1])
        parts = list(data["participants"].values())
        chunk = parts[page*10:(page+1)*10]
        if not chunk:
            await query.edit_message_text("Участников нет.")
            return
        lines = [f"Участники (стр.{page+1})"]
        for i, p in enumerate(chunk, page*10+1):
            lines.append(f"{i}. {p['name']} @{p['username']}")
        nav = []
        if page > 0: nav.append(InlineKeyboardButton("<<", callback_data=f"admin_list_{page-1}"))
        if (page+1)*10 < len(parts): nav.append(InlineKeyboardButton(">>", callback_data=f"admin_list_{page+1}"))
        kb = [nav] if nav else []
        kb.append([InlineKeyboardButton("В меню", callback_data="admin_back")])
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb))

    elif action == "admin_pick":
        parts = list(data["participants"].values())
        if not parts:
            await query.edit_message_text("Нет участников.")
            return
        kb = [[InlineKeyboardButton(f"{p['name']}", callback_data=f"admin_win_{p['id']}")] for p in parts]
        kb.append([InlineKeyboardButton("Случайно", callback_data="admin_random")])
        kb.append([InlineKeyboardButton("В меню", callback_data="admin_back")])
        await query.edit_message_text("Выберите победителя:", reply_markup=InlineKeyboardMarkup(kb))

    elif action == "admin_random":
        parts = list(data["participants"].values())
        if not parts:
            await query.edit_message_text("Нет участников.")
            return
        winner = random.choice(parts)
        data["winner"] = winner
        save_data(data)
        await query.edit_message_text(f"Победитель: {winner['name']} @{winner['username']}")

    elif action.startswith("admin_win_"):
        uid = str(action.split("_")[-1])
        winner = data["participants"].get(uid)
        if winner:
            data["winner"] = winner
            save_data(data)
            await query.edit_message_text(f"Победитель: {winner['name']} @{winner['username']}")

    elif action == "admin_close":
        data["active"] = False
        save_data(data)
        await query.edit_message_text("Розыгрыш завершён.")

    elif action == "admin_open":
        data["active"] = True
        save_data(data)
        await query.edit_message_text("Розыгрыш открыт!")

    elif action == "admin_back":
        await admin_panel(query, context)

async def announce_winner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    data = load_data()
    if not data["winner"]:
        await update.message.reply_text("Победитель не выбран.")
        return
    w = data["winner"]
    await context.bot.send_message(CHANNEL_ID,
        f"{GIVEAWAY_TITLE}\nПобедитель: {w['name']} @{w['username']}\nПриз: {PRIZE_TEXT}\nПоздравляем!")
    await update.message.reply_text("Отправлено в канал!")

async def reset_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    save_data({"participants": {}, "winner": None, "active": True})
    await update.message.reply_text("Розыгрыш сброшен.")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("announce", announce_winner))
    app.add_handler(CommandHandler("reset", reset_giveaway))
    app.add_handler(CallbackQueryHandler(join_callback, pattern="^join$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    logger.info("Bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
