import os
import json
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# --- SOZLAMALAR ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "6211403603"))

# Fayl - bronlar saqlanadi
BOOKINGS_FILE = "bookings.json"

# Conversation states
CHOOSING_DATE, CHOOSING_SLOT, ENTERING_NAME, ENTERING_PHONE, ENTERING_CAR = range(5)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- YORDAMCHI FUNKSIYALAR ---

def load_bookings():
    if os.path.exists(BOOKINGS_FILE):
        with open(BOOKINGS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_bookings(bookings):
    with open(BOOKINGS_FILE, "w") as f:
        json.dump(bookings, f, ensure_ascii=False, indent=2)

def get_available_slots(date_str):
    """Sana uchun bo'sh slotlarni qaytaradi"""
    # Vaqt slotlari - bularni o'zgartirishingiz mumkin
    all_slots = [
        "08:00", "09:00", "10:00", "11:00",
        "12:00", "13:00", "14:00", "15:00",
        "16:00", "17:00", "18:00"
    ]
    bookings = load_bookings()
    booked = bookings.get(date_str, {}).keys()
    available = [s for s in all_slots if s not in booked]
    return available

def get_next_days(n=7):
    """Keyingi n kunni qaytaradi"""
    days = []
    today = datetime.now()
    for i in range(n):
        day = today + timedelta(days=i)
        days.append(day.strftime("%Y-%m-%d"))
    return days

def format_date(date_str):
    """2024-05-21 → 21-May (Seshanba)"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    weekdays = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
    months = ["", "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
              "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"]
    return f"{dt.day} {months[dt.month]} ({weekdays[dt.weekday()]})"

# --- HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("📅 Slot bron qilish", callback_data="book")],
        [InlineKeyboardButton("📋 Mening bronlarim", callback_data="my_bookings")],
    ]
    if update.effective_user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("👑 Admin panel", callback_data="admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"Salom, {user.first_name}! 👋\n\n"
        "📦 *Uzum ombori — Slot bron qilish boti*\n\n"
        "Yuk tushirish/yuklash uchun qulay vaqt tanlang:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    return ConversationHandler.END

async def book_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    days = get_next_days(7)
    keyboard = []
    for day in days:
        available = get_available_slots(day)
        if available:
            btn_text = f"📅 {format_date(day)} ({len(available)} bo'sh)"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"date_{day}")])
    
    keyboard.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel")])
    
    await query.edit_message_text(
        "📅 *Sanani tanlang:*\n\n"
        "Qaysi kuni kelmoqchisiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING_DATE

async def choose_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    date_str = query.data.replace("date_", "")
    context.user_data["chosen_date"] = date_str
    
    available = get_available_slots(date_str)
    keyboard = []
    row = []
    for i, slot in enumerate(available):
        row.append(InlineKeyboardButton(f"🕐 {slot}", callback_data=f"slot_{slot}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="book")])
    
    await query.edit_message_text(
        f"📅 *{format_date(date_str)}*\n\n"
        "🕐 *Vaqtni tanlang:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING_SLOT

async def choose_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    slot = query.data.replace("slot_", "")
    context.user_data["chosen_slot"] = slot
    
    await query.edit_message_text(
        f"✅ Vaqt: *{format_date(context.user_data['chosen_date'])}* soat *{slot}*\n\n"
        "👤 Ism-familiyangizni kiriting:",
        parse_mode="Markdown"
    )
    return ENTERING_NAME

async def enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("📞 Telefon raqamingizni kiriting:\n\n_Masalan: +998901234567_", parse_mode="Markdown")
    return ENTERING_PHONE

async def enter_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text
    await update.message.reply_text("🚗 Mashina raqamini kiriting:\n\n_Masalan: 01A123BC_", parse_mode="Markdown")
    return ENTERING_CAR

async def enter_car(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["car"] = update.message.text
    
    date_str = context.user_data["chosen_date"]
    slot = context.user_data["chosen_slot"]
    name = context.user_data["name"]
    phone = context.user_data["phone"]
    car = context.user_data["car"]
    user_id = update.effective_user.id
    
    # Bronni saqlash
    bookings = load_bookings()
    if date_str not in bookings:
        bookings[date_str] = {}
    
    bookings[date_str][slot] = {
        "name": name,
        "phone": phone,
        "car": car,
        "user_id": user_id,
        "booked_at": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    save_bookings(bookings)
    
    # Foydalanuvchiga tasdiqlash
    await update.message.reply_text(
        "✅ *Bron tasdiqlandi!*\n\n"
        f"📅 Sana: *{format_date(date_str)}*\n"
        f"🕐 Vaqt: *{slot}*\n"
        f"👤 Ism: *{name}*\n"
        f"📞 Tel: *{phone}*\n"
        f"🚗 Mashina: *{car}*\n\n"
        "Vaqtingizda keling! 🙏",
        parse_mode="Markdown"
    )
    
    # Adminga xabar
    await update.get_bot().send_message(
        chat_id=ADMIN_ID,
        text=f"🆕 *Yangi bron!*\n\n"
             f"📅 Sana: *{format_date(date_str)}*\n"
             f"🕐 Vaqt: *{slot}*\n"
             f"👤 Ism: *{name}*\n"
             f"📞 Tel: *{phone}*\n"
             f"🚗 Mashina: *{car}*\n"
             f"🆔 Telegram ID: `{user_id}`",
        parse_mode="Markdown"
    )
    
    return ConversationHandler.END

async def my_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    bookings = load_bookings()
    
    user_bookings = []
    for date_str, slots in bookings.items():
        for slot, info in slots.items():
            if info["user_id"] == user_id:
                user_bookings.append((date_str, slot, info))
    
    if not user_bookings:
        await query.edit_message_text(
            "📋 Sizda hozircha bron yo'q.\n\n"
            "/start — bosh menyu",
        )
        return
    
    text = "📋 *Sizning bronlaringiz:*\n\n"
    for date_str, slot, info in sorted(user_bookings):
        text += f"📅 {format_date(date_str)} — 🕐 {slot}\n"
        text += f"🚗 {info['car']}\n\n"
    
    await query.edit_message_text(text, parse_mode="Markdown")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    
    days = get_next_days(7)
    keyboard = []
    for day in days:
        bookings = load_bookings()
        count = len(bookings.get(day, {}))
        btn_text = f"📅 {format_date(day)} — {count} ta bron"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"admin_day_{day}")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="cancel")])
    
    await query.edit_message_text(
        "👑 *Admin panel*\n\nKunni tanlang:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        return
    
    date_str = query.data.replace("admin_day_", "")
    bookings = load_bookings()
    day_bookings = bookings.get(date_str, {})
    
    if not day_bookings:
        await query.edit_message_text(
            f"📅 *{format_date(date_str)}*\n\n"
            "Bu kun hozircha bron yo'q.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="admin")]])
        )
        return
    
    text = f"📅 *{format_date(date_str)}* bronlari:\n\n"
    for slot in sorted(day_bookings.keys()):
        info = day_bookings[slot]
        text += f"🕐 *{slot}*\n"
        text += f"  👤 {info['name']}\n"
        text += f"  📞 {info['phone']}\n"
        text += f"  🚗 {info['car']}\n\n"
    
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="admin")]])
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Bekor qilindi. /start — bosh menyu")
    return ConversationHandler.END

# --- MAIN ---

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(book_start, pattern="^book$")],
        states={
            CHOOSING_DATE: [CallbackQueryHandler(choose_date, pattern="^date_")],
            CHOOSING_SLOT: [CallbackQueryHandler(choose_slot, pattern="^slot_")],
            ENTERING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_name)],
            ENTERING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_phone)],
            ENTERING_CAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_car)],
        },
        fallbacks=[CallbackQueryHandler(cancel, pattern="^cancel$")],
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(my_bookings, pattern="^my_bookings$"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin$"))
    app.add_handler(CallbackQueryHandler(admin_day, pattern="^admin_day_"))
    app.add_handler(CallbackQueryHandler(cancel, pattern="^cancel$"))
    
    logger.info("Bot ishga tushdi!")
    app.run_polling()

if __name__ == "__main__":
    main()
