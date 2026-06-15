import os
import json
import logging
import random
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters
)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID     = os.environ.get("CHANNEL_ID", "")
ADMIN_ID       = int(os.environ.get("ADMIN_ID", "0"))
DATA_FILE      = "participants.json"

# Состояния для /create
ASK_TITLE, ASK_PRIZE, ASK_DESCRIPTION = range(3)

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"participants": {}, "winner": None, "active": False, "giveaway": None}

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

# ─── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data["active"] or not data.get("giveaway"):
        await update.message.reply_text("Сейчас нет активных розыгрышей.")
        return
    g = data["giveaway"]
    kb = [[InlineKeyboardButton("🎯 Участвовать", callback_data="join")]]
    note = ""
    if data["winner"]:
        note = f"\n\n🏆 Победитель: {data['winner']['name']}"
    await update.message.reply_text(
        f"🎉 {g['title']}\n\n"
        f"🎁 Приз: {g['prize']}\n\n"
        f"{g['description']}\n\n"
        f"Подпишитесь на канал и нажмите кнопку ниже!{note}",
        reply_markup=InlineKeyboardMarkup(kb) if not data["winner"] else None
    )

# ─── /create ──────────────────────────────────────────────────────────────────
async def create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return ConversationHandler.END
    await update.message.reply_text(
        "📝 Создание нового розыгрыша\n\nШаг 1/3 — Введите название розыгрыша:"
    )
    return ASK_TITLE

async def create_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["title"] = update.message.text
    await update.message.reply_text(
        f"✅ Название: {update.message.text}\n\nШаг 2/3 — Введите приз:"
    )
    return ASK_PRIZE

async def create_prize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["prize"] = update.message.text
    await update.message.reply_text(
        f"✅ Приз: {update.message.text}\n\nШаг 3/3 — Введите описание розыгрыша (или напишите '-' чтобы пропустить):"
    )
    return ASK_DESCRIPTION

async def create_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text
    if desc == "-":
        desc = "Участвуйте в нашем розыгрыше!"

    title = context.user_data["title"]
    prize = context.user_data["prize"]

    # Сохраняем и сбрасываем участников
    data = load_data()
    data["giveaway"] = {
        "title": title,
        "prize": prize,
        "description": desc,
        "created_at": datetime.utcnow().isoformat()
    }
    data["participants"] = {}
    data["winner"] = None
    data["active"] = True
    save_data(data)

    # Публикуем пост в канал
    bot_info = await context.bot.get_me()
    bot_username = bot_info.username
    kb = [[InlineKeyboardButton(
        "🎯 Участвовать в розыгрыше",
        url=f"https://t.me/{bot_username}?start=join"
    )]]
    channel_text = (
        f"🎉 *{title}*\n\n"
        f"🎁 Приз: *{prize}*\n\n"
        f"{desc}\n\n"
        f"👇 Нажмите кнопку ниже чтобы участвовать!\n"
        f"_(необходима подписка на канал)_"
    )
    await context.bot.send_message(
        CHANNEL_ID,
        channel_text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

    await update.message.reply_text(
        f"✅ Розыгрыш создан и опубликован в канале!\n\n"
        f"🎉 {title}\n"
        f"🎁 {prize}\n\n"
        f"Используйте /admin для управления."
    )
    return ConversationHandler.END

async def create_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Создание розыгрыша отменено.")
    return ConversationHandler.END

# ─── Участие ──────────────────────────────────────────────────────────────────
async def join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = load_data()
    user = query.from_user
    uid = str(user.id)

    if not data["active"]:
        await query.edit_message_text("Розыгрыш завершён.")
        return
    if data["winner"]:
        await query.answer("Победитель уже выбран!", show_alert=True)
        return
    if uid in data["participants"]:
        await query.answer("Вы уже участвуете!", show_alert=True)
        return
    if not await is_subscribed(context, user.id):
        kb = [[InlineKeyboardButton(
            "📢 Подписаться на канал",
            url=f"https://t.me/{CHANNEL_ID.lstrip('@')}"
        )]]
        await query.message.reply_text(
            f"❌ Сначала подпишитесь на {CHANNEL_ID}, затем нажмите Участвовать снова.",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    data["participants"][uid] = {
        "id": user.id,
        "name": user.full_name,
        "username": user.username or "",
        "joined_at": datetime.utcnow().isoformat()
    }
    save_data(data)
    await query.answer("🎉 Вы зарегистрированы!", show_alert=True)
    await query.message.reply_text(
        f"✅ {user.full_name}, вы участвуете в розыгрыше!\n"
        f"👥 Всего участников: {len(data['participants'])}"
    )

# ─── /admin ───────────────────────────────────────────────────────────────────
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    data = load_data()
    g = data.get("giveaway")
    title = g["title"] if g else "—"
    prize = g["prize"] if g else "—"
    total = len(data["participants"])
    status = "активен" if data["active"] else "завершён"
    winner_line = f"\n🏆 Победитель: {data['winner']['name']}" if data["winner"] else ""

    kb = [
        [InlineKeyboardButton("👥 Список участников", callback_data="admin_list_0")],
        [InlineKeyboardButton("🎲 Выбрать победителя", callback_data="admin_pick")],
        [InlineKeyboardButton("📢 Объявить победителя в канале", callback_data="admin_announce")],
        [InlineKeyboardButton("🔒 Завершить розыгрыш", callback_data="admin_close")],
        [InlineKeyboardButton("🔓 Открыть розыгрыш", callback_data="admin_open")],
    ]
    await update.message.reply_text(
        f"🛠 Панель администратора\n\n"
        f"📌 {title}\n"
        f"🎁 {prize}\n"
        f"👥 Участников: {total}\n"
        f"🔄 Статус: {status}{winner_line}",
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
            await query.edit_message_text("Участников пока нет.")
            return
        lines = [f"👥 Участники (стр. {page+1} из {(len(parts)-1)//10+1})\n"]
        for i, p in enumerate(chunk, page*10+1):
            uname = f"@{p['username']}" if p["username"] else ""
            lines.append(f"{i}. {p['name']} {uname}")
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"admin_list_{page-1}"))
        if (page+1)*10 < len(parts):
            nav.append(InlineKeyboardButton("▶️", callback_data=f"admin_list_{page+1}"))
        kb = [nav] if nav else []
        kb.append([InlineKeyboardButton("🔙 В меню", callback_data="admin_back")])
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb))

    elif action == "admin_pick":
        parts = list(data["participants"].values())
        if not parts:
            await query.edit_message_text("Нет участников.")
            return
        kb = [[InlineKeyboardButton(
            f"{p['name']}" + (f" @{p['username']}" if p["username"] else ""),
            callback_data=f"admin_win_{p['id']}"
        )] for p in parts]
        kb.append([InlineKeyboardButton("🎲 Выбрать случайно", callback_data="admin_random")])
        kb.append([InlineKeyboardButton("🔙 В меню", callback_data="admin_back")])
        await query.edit_message_text("Выберите победителя:", reply_markup=InlineKeyboardMarkup(kb))

    elif action == "admin_random":
        parts = list(data["participants"].values())
        if not parts:
            await query.edit_message_text("Нет участников.")
            return
        winner = random.choice(parts)
        data["winner"] = winner
        save_data(data)
        uname = f"@{winner['username']}" if winner["username"] else ""
        await query.edit_message_text(
            f"🏆 Победитель выбран!\n\n{winner['name']} {uname}\n\nНажмите 'Объявить' в /admin"
        )

    elif action.startswith("admin_win_"):
        uid = str(action.split("_")[-1])
        winner = data["participants"].get(uid)
        if winner:
            data["winner"] = winner
            save_data(data)
            uname = f"@{winner['username']}" if winner["username"] else ""
            await query.edit_message_text(
                f"🏆 Победитель выбран!\n\n{winner['name']} {uname}\n\nНажмите 'Объявить' в /admin"
            )

    elif action == "admin_announce":
        if not data["winner"]:
            await query.answer("Сначала выберите победителя!", show_alert=True)
            return
        g = data.get("giveaway", {})
        w = data["winner"]
        uname = f"@{w['username']}" if w["username"] else ""
        await context.bot.send_message(
            CHANNEL_ID,
            f"🎉 *{g.get('title', 'Розыгрыш')}* — Результаты!\n\n"
            f"🏆 Победитель: {w['name']} {uname}\n\n"
            f"🎁 Приз: {g.get('prize', '')}\n\nПоздравляем! 🎊",
            parse_mode="Markdown"
        )
        await query.edit_message_text("✅ Объявление опубликовано в канале!")

    elif action == "admin_close":
        data["active"] = False
        save_data(data)
        await query.edit_message_text("🔒 Розыгрыш завершён.")

    elif action == "admin_open":
        data["active"] = True
        save_data(data)
        await query.edit_message_text("🔓 Розыгрыш открыт!")

    elif action == "admin_back":
        g = data.get("giveaway")
        title = g["title"] if g else "—"
        prize = g["prize"] if g else "—"
        total = len(data["participants"])
        status = "активен" if data["active"] else "завершён"
        winner_line = f"\n🏆 Победитель: {data['winner']['name']}" if data["winner"] else ""
        kb = [
            [InlineKeyboardButton("👥 Список участников", callback_data="admin_list_0")],
            [InlineKeyboardButton("🎲 Выбрать победителя", callback_data="admin_pick")],
            [InlineKeyboardButton("📢 Объявить победителя в канале", callback_data="admin_announce")],
            [InlineKeyboardButton("🔒 Завершить розыгрыш", callback_data="admin_close")],
            [InlineKeyboardButton("🔓 Открыть розыгрыш", callback_data="admin_open")],
        ]
        await query.edit_message_text(
            f"🛠 Панель администратора\n\n"
            f"📌 {title}\n🎁 {prize}\n"
            f"👥 Участников: {total}\n🔄 Статус: {status}{winner_line}",
            reply_markup=InlineKeyboardMarkup(kb)
        )

async def reset_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    save_data({"participants": {}, "winner": None, "active": False, "giveaway": None})
    await update.message.reply_text("♻️ Розыгрыш сброшен. Используйте /create для нового.")

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # ConversationHandler для /create
    conv = ConversationHandler(
        entry_points=[CommandHandler("create", create_start)],
        states={
            ASK_TITLE:       [MessageHandler(filters.TEXT & ~filters.COMMAND, create_title)],
            ASK_PRIZE:       [MessageHandler(filters.TEXT & ~filters.COMMAND, create_prize)],
            ASK_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_description)],
        },
        fallbacks=[CommandHandler("cancel", create_cancel)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("admin",  admin_panel))
    app.add_handler(CommandHandler("reset",  reset_giveaway))
    app.add_handler(CallbackQueryHandler(join_callback,  pattern="^join$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))

    logger.info("Bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
