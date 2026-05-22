import asyncio
import os
import sqlite3
from datetime import datetime

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
EMPLOYEE_PHONE = os.getenv("EMPLOYEE_PHONE", "+998200276702")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi. Railway Variables ichiga BOT_TOKEN qo‘ying.")

ADMIN_ID = int(ADMIN_ID) if ADMIN_ID and ADMIN_ID.isdigit() else 0

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_NAME = "bot.db"


# ================= DATABASE =================

def db():
    return sqlite3.connect(DB_NAME)


def ensure_column(cur, table, column, column_type):
    cur.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cur.fetchall()]
    if column not in columns:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            stars INTEGER DEFAULT 1,
            is_blocked INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS stores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            store_id TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            store_id TEXT,
            invoice TEXT,
            date TEXT,
            status TEXT,
            created_at TEXT
        )
    """)

    ensure_column(cur, "users", "username", "TEXT")
    ensure_column(cur, "users", "stars", "INTEGER DEFAULT 1")
    ensure_column(cur, "users", "is_blocked", "INTEGER DEFAULT 0")
    ensure_column(cur, "users", "created_at", "TEXT")

    conn.commit()
    conn.close()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def add_user(telegram_id, full_name, username):
    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT telegram_id FROM users WHERE telegram_id = ?", (telegram_id,))
    exists = cur.fetchone()

    if not exists:
        cur.execute(
            """
            INSERT INTO users (telegram_id, full_name, username, stars, is_blocked, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (telegram_id, full_name, username or "", 1, 0, now())
        )
    else:
        cur.execute(
            "UPDATE users SET full_name = ?, username = ? WHERE telegram_id = ?",
            (full_name, username or "", telegram_id)
        )

    conn.commit()
    conn.close()


def is_blocked(telegram_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT is_blocked FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cur.fetchone()
    conn.close()
    return bool(row and row[0] == 1)


def set_block_status(telegram_id, status):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_blocked = ? WHERE telegram_id = ?", (status, telegram_id))
    conn.commit()
    conn.close()


def get_stars(telegram_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT stars FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0


def change_stars(telegram_id, amount):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET stars = stars + ? WHERE telegram_id = ?", (amount, telegram_id))
    conn.commit()
    conn.close()


def save_store(telegram_id, store_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM stores WHERE telegram_id = ?", (telegram_id,))
    cur.execute(
        "INSERT INTO stores (telegram_id, store_id, created_at) VALUES (?, ?, ?)",
        (telegram_id, store_id, now())
    )
    conn.commit()
    conn.close()


def get_store(telegram_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT store_id FROM stores WHERE telegram_id = ?", (telegram_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def save_booking(telegram_id, store_id, invoice, date, status):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO bookings (telegram_id, store_id, invoice, date, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (telegram_id, store_id, invoice, date, status, now())
    )
    conn.commit()
    conn.close()


def get_user_bookings(telegram_id):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT store_id, invoice, date, status, created_at
        FROM bookings
        WHERE telegram_id = ?
        ORDER BY id DESC
        LIMIT 10
        """,
        (telegram_id,)
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_stats():
    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    users_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM stores")
    stores_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM bookings")
    bookings_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1")
    blocked_count = cur.fetchone()[0]

    conn.close()
    return users_count, stores_count, bookings_count, blocked_count


def get_all_users(limit=20):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT telegram_id, full_name, username, stars, is_blocked, created_at
        FROM users
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,)
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_all_stores(limit=20):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT s.store_id, s.telegram_id, u.full_name, u.username, s.created_at
        FROM stores s
        LEFT JOIN users u ON s.telegram_id = u.telegram_id
        ORDER BY s.id DESC
        LIMIT ?
        """,
        (limit,)
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_all_bookings(limit=20):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT b.telegram_id, u.full_name, b.store_id, b.invoice, b.date, b.status, b.created_at
        FROM bookings b
        LEFT JOIN users u ON b.telegram_id = u.telegram_id
        ORDER BY b.id DESC
        LIMIT ?
        """,
        (limit,)
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_all_user_ids():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT telegram_id FROM users WHERE is_blocked = 0")
    rows = cur.fetchall()
    conn.close()
    return [row[0] for row in rows]


# ================= STATES =================

class StoreState(StatesGroup):
    waiting_store_id = State()


class BookingState(StatesGroup):
    waiting_invoice = State()
    waiting_custom_date = State()
    confirming = State()


class AdminState(StatesGroup):
    waiting_user_id_for_stars = State()
    waiting_star_amount = State()
    waiting_broadcast_text = State()
    waiting_block_user_id = State()
    waiting_unblock_user_id = State()


# ================= MENUS =================

def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🏪 Do‘kon ulash", callback_data="connect_store")
    kb.button(text="📦 Yangi bron", callback_data="new_booking")
    kb.button(text="⭐ Balans", callback_data="balance")
    kb.button(text="💳 Yulduz sotib olish", callback_data="buy_stars")
    kb.button(text="📜 Bronlar tarixi", callback_data="history")
    kb.adjust(1)
    return kb.as_markup()


def date_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="Bugun", callback_data="date_today")
    kb.button(text="Ertaga", callback_data="date_tomorrow")
    kb.button(text="Boshqa sana", callback_data="date_custom")
    kb.adjust(1)
    return kb.as_markup()


def confirm_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tasdiqlash", callback_data="confirm_booking")
    kb.button(text="❌ Bekor qilish", callback_data="cancel_booking")
    kb.adjust(1)
    return kb.as_markup()


def admin_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Statistika", callback_data="admin_stats")
    kb.button(text="👥 Userlar", callback_data="admin_users")
    kb.button(text="🏪 Do‘konlar", callback_data="admin_stores")
    kb.button(text="📦 Bronlar", callback_data="admin_bookings")
    kb.button(text="⭐ Userga yulduz qo‘shish", callback_data="admin_add_stars")
    kb.button(text="📢 Hammaga xabar yuborish", callback_data="admin_broadcast")
    kb.button(text="🚫 User bloklash", callback_data="admin_block_user")
    kb.button(text="✅ Blokdan chiqarish", callback_data="admin_unblock_user")
    kb.adjust(1)
    return kb.as_markup()


def admin_check(user_id):
    return user_id == ADMIN_ID


async def blocked_guard(message):
    if is_blocked(message.from_user.id):
        await message.answer("Siz botdan foydalanishdan bloklangansiz.")
        return True
    return False


# ================= USER COMMANDS =================

@dp.message(CommandStart())
async def start(message: Message):
    add_user(message.from_user.id, message.from_user.full_name, message.from_user.username)

    if await blocked_guard(message):
        return

    await message.answer(
        "Assalomu alaykum!\n\n"
        "Uzum Time Slot botiga xush kelibsiz ✅\n\n"
        "Quyidagi menyudan foydalaning:",
        reply_markup=main_menu()
    )


@dp.message(Command("myid"))
async def my_id(message: Message):
    await message.answer(f"Sizning Telegram ID: {message.from_user.id}")


@dp.message(Command("admin"))
async def admin(message: Message):
    if not admin_check(message.from_user.id):
        await message.answer("Siz admin emassiz.")
        return

    await message.answer("Admin panel:", reply_markup=admin_menu())


# ================= STORE =================

@dp.callback_query(F.data == "connect_store")
async def connect_store(callback: CallbackQuery, state: FSMContext):
    if is_blocked(callback.from_user.id):
        await callback.message.answer("Siz botdan foydalanishdan bloklangansiz.")
        await callback.answer()
        return

    await callback.message.answer(
        "Do‘koningizni ulash uchun:\n\n"
        "1. Uzum Seller paneliga kiring\n"
        "2. Xodimlar bo‘limiga o‘ting\n"
        "3. Quyidagi telefon raqamni xodim sifatida qo‘shing:\n\n"
        f"{EMPLOYEE_PHONE}\n\n"
        "4. Rol sifatida “Tovarlarni tayyorlash markazi xodimi” ni tanlang\n"
        "5. Xodim qo‘shilgandan keyin do‘kon ID raqamini yuboring.\n\n"
        "Do‘kon ID raqamini kiriting:"
    )

    await state.set_state(StoreState.waiting_store_id)
    await callback.answer()


@dp.message(StoreState.waiting_store_id)
async def store_id_save(message: Message, state: FSMContext):
    if await blocked_guard(message):
        await state.clear()
        return

    store_id = message.text.strip()

    if not store_id.isdigit():
        await message.answer("Do‘kon ID faqat raqamlardan iborat bo‘lishi kerak. Qayta kiriting:")
        return

    save_store(message.from_user.id, store_id)

    await message.answer(
        f"✅ Do‘kon muvaffaqiyatli ulandi!\n\n"
        f"🏪 Do‘kon ID: {store_id}\n\n"
        f"Endi bron qilishingiz mumkin.",
        reply_markup=main_menu()
    )

    await state.clear()


# ================= BOOKING =================

@dp.callback_query(F.data == "new_booking")
async def new_booking(callback: CallbackQuery, state: FSMContext):
    if is_blocked(callback.from_user.id):
        await callback.message.answer("Siz botdan foydalanishdan bloklangansiz.")
        await callback.answer()
        return

    telegram_id = callback.from_user.id
    store_id = get_store(telegram_id)

    if not store_id:
        await callback.message.answer("Avval do‘koningizni ulang.", reply_markup=main_menu())
        await callback.answer()
        return

    stars = get_stars(telegram_id)

    if stars <= 0:
        await callback.message.answer(
            "Balansingizda yulduz yo‘q.\n"
            "Bron qilish uchun balansni to‘ldiring."
        )
        await callback.answer()
        return

    await callback.message.answer(
        "Invoice raqamini kiriting.\n\n"
        "Masalan:\n"
        "110003500721\n\n"
        "Bir nechta invoice bo‘lsa vergul bilan yozing:\n"
        "110003500721, 110003105384"
    )

    await state.set_state(BookingState.waiting_invoice)
    await callback.answer()


@dp.message(BookingState.waiting_invoice)
async def get_invoice(message: Message, state: FSMContext):
    if await blocked_guard(message):
        await state.clear()
        return

    invoice = message.text.strip()

    if len(invoice) < 3:
        await message.answer("Invoice noto‘g‘ri ko‘rinadi. Qayta kiriting:")
        return

    await state.update_data(invoice=invoice)
    await message.answer("Sanani tanlang:", reply_markup=date_menu())


@dp.callback_query(F.data == "date_today")
async def date_today(callback: CallbackQuery, state: FSMContext):
    await state.update_data(date="Bugun")
    await show_booking_confirm(callback.message, callback.from_user.id, state)
    await callback.answer()


@dp.callback_query(F.data == "date_tomorrow")
async def date_tomorrow(callback: CallbackQuery, state: FSMContext):
    await state.update_data(date="Ertaga")
    await show_booking_confirm(callback.message, callback.from_user.id, state)
    await callback.answer()


@dp.callback_query(F.data == "date_custom")
async def date_custom(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Sanani yozing. Masalan: 14.05.2026")
    await state.set_state(BookingState.waiting_custom_date)
    await callback.answer()


@dp.message(BookingState.waiting_custom_date)
async def custom_date(message: Message, state: FSMContext):
    if await blocked_guard(message):
        await state.clear()
        return

    await state.update_data(date=message.text.strip())
    await show_booking_confirm(message, message.from_user.id, state)


async def show_booking_confirm(message: Message, telegram_id: int, state: FSMContext):
    data = await state.get_data()
    store_id = get_store(telegram_id)

    await message.answer(
        "📋 Bron ma’lumotlari:\n\n"
        f"🏪 Do‘kon ID: {store_id}\n"
        f"📦 Invoice: {data.get('invoice')}\n"
        f"📅 Sana: {data.get('date')}\n"
        f"⭐ Sarflanadi: 1 yulduz\n\n"
        "Tasdiqlaysizmi?",
        reply_markup=confirm_menu()
    )

    await state.set_state(BookingState.confirming)


@dp.callback_query(F.data == "confirm_booking")
async def confirm_booking(callback: CallbackQuery, state: FSMContext):
    if is_blocked(callback.from_user.id):
        await callback.message.answer("Siz botdan foydalanishdan bloklangansiz.")
        await state.clear()
        await callback.answer()
        return

    telegram_id = callback.from_user.id
    data = await state.get_data()

    store_id = get_store(telegram_id)
    stars = get_stars(telegram_id)

    if stars <= 0:
        await callback.message.answer("Balansingizda yulduz yo‘q.")
        await state.clear()
        await callback.answer()
        return

    save_booking(
        telegram_id=telegram_id,
        store_id=store_id,
        invoice=data.get("invoice"),
        date=data.get("date"),
        status="searching"
    )

    change_stars(telegram_id, -1)

    await callback.message.answer(
        "✅ Bron jarayoni boshlandi!\n\n"
        "🔍 Slot qidirilmoqda...\n"
        "Bu bir necha daqiqa davom etishi mumkin.\n\n"
        "Hozircha bu MVP test rejimi. Keyingi bosqichda Uzum API ulanadi.",
        reply_markup=main_menu()
    )

    await state.clear()
    await callback.answer()


@dp.callback_query(F.data == "cancel_booking")
async def cancel_booking(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Bron bekor qilindi.", reply_markup=main_menu())
    await callback.answer()


# ================= BALANCE / PAYMENT / HISTORY =================

@dp.callback_query(F.data == "balance")
async def balance(callback: CallbackQuery):
    stars = get_stars(callback.from_user.id)

    await callback.message.answer(
        f"⭐ Sizning balansingiz: {stars} yulduz",
        reply_markup=main_menu()
    )

    await callback.answer()


@dp.callback_query(F.data == "buy_stars")
async def buy_stars(callback: CallbackQuery):
    await callback.message.answer(
        "💳 Yulduz sotib olish\n\n"
        "⭐ Tariflar:\n\n"
        "10 yulduz — 10 000 so‘m\n"
        "50 yulduz — 45 000 so‘m\n"
        "100 yulduz — 80 000 so‘m\n\n"
        "To‘lov qilganingizdan keyin chekni adminga yuboring.\n\n"
        f"Sizning Telegram ID: {callback.from_user.id}\n\n"
        "Admin sizga yulduz qo‘shib beradi.",
        reply_markup=main_menu()
    )
    await callback.answer()


@dp.callback_query(F.data == "history")
async def history(callback: CallbackQuery):
    rows = get_user_bookings(callback.from_user.id)

    if not rows:
        await callback.message.answer("Sizda hali bronlar yo‘q.", reply_markup=main_menu())
        await callback.answer()
        return

    text = "📜 Oxirgi bronlar tarixi:\n\n"

    for row in rows:
        store_id, invoice, date, status, created_at = row
        text += (
            f"🏪 Do‘kon ID: {store_id}\n"
            f"📦 Invoice: {invoice}\n"
            f"📅 Sana: {date}\n"
            f"Holat: {status}\n"
            f"Vaqt: {created_at}\n\n"
        )

    await callback.message.answer(text, reply_markup=main_menu())
    await callback.answer()


# ================= ADMIN PANEL =================

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not admin_check(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q.")
        return

    users_count, stores_count, bookings_count, blocked_count = get_stats()

    await callback.message.answer(
        "📊 Statistika:\n\n"
        f"👥 Userlar: {users_count}\n"
        f"🏪 Do‘konlar: {stores_count}\n"
        f"📦 Bronlar: {bookings_count}\n"
        f"🚫 Bloklanganlar: {blocked_count}",
        reply_markup=admin_menu()
    )

    await callback.answer()


@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if not admin_check(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q.")
        return

    rows = get_all_users()

    if not rows:
        await callback.message.answer("Userlar yo‘q.", reply_markup=admin_menu())
        await callback.answer()
        return

    text = "👥 Oxirgi userlar:\n\n"

    for row in rows:
        telegram_id, full_name, username, stars, blocked, created_at = row
        username_text = f"@{username}" if username else "username yo‘q"
        status = "🚫 Blok" if blocked else "✅ Aktiv"

        text += (
            f"ID: {telegram_id}\n"
            f"Ism: {full_name}\n"
            f"Username: {username_text}\n"
            f"⭐ Yulduz: {stars}\n"
            f"Holat: {status}\n"
            f"Sana: {created_at}\n\n"
        )

    await callback.message.answer(text, reply_markup=admin_menu())
    await callback.answer()


@dp.callback_query(F.data == "admin_stores")
async def admin_stores(callback: CallbackQuery):
    if not admin_check(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q.")
        return

    rows = get_all_stores()

    if not rows:
        await callback.message.answer("Ulangan do‘konlar yo‘q.", reply_markup=admin_menu())
        await callback.answer()
        return

    text = "🏪 Oxirgi ulangan do‘konlar:\n\n"

    for row in rows:
        store_id, telegram_id, full_name, username, created_at = row
        username_text = f"@{username}" if username else "username yo‘q"

        text += (
            f"Do‘kon ID: {store_id}\n"
            f"User ID: {telegram_id}\n"
            f"Ism: {full_name}\n"
            f"Username: {username_text}\n"
            f"Sana: {created_at}\n\n"
        )

    await callback.message.answer(text, reply_markup=admin_menu())
    await callback.answer()


@dp.callback_query(F.data == "admin_bookings")
async def admin_bookings(callback: CallbackQuery):
    if not admin_check(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q.")
        return

    rows = get_all_bookings()

    if not rows:
        await callback.message.answer("Bronlar yo‘q.", reply_markup=admin_menu())
        await callback.answer()
        return

    text = "📦 Oxirgi bronlar:\n\n"

    for row in rows:
        telegram_id, full_name, store_id, invoice, date, status, created_at = row

        text += (
            f"User ID: {telegram_id}\n"
            f"Ism: {full_name}\n"
            f"Do‘kon ID: {store_id}\n"
            f"Invoice: {invoice}\n"
            f"Sana: {date}\n"
            f"Holat: {status}\n"
            f"Vaqt: {created_at}\n\n"
        )

    await callback.message.answer(text, reply_markup=admin_menu())
    await callback.answer()


@dp.callback_query(F.data == "admin_add_stars")
async def admin_add_stars(callback: CallbackQuery, state: FSMContext):
    if not admin_check(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q.")
        return

    await callback.message.answer("Yulduz qo‘shmoqchi bo‘lgan user Telegram ID sini yuboring:")
    await state.set_state(AdminState.waiting_user_id_for_stars)
    await callback.answer()


@dp.message(AdminState.waiting_user_id_for_stars)
async def admin_get_user_id_for_stars(message: Message, state: FSMContext):
    if not admin_check(message.from_user.id):
        return

    user_id = message.text.strip()

    if not user_id.isdigit():
        await message.answer("Telegram ID faqat raqam bo‘lishi kerak. Qayta kiriting:")
        return

    await state.update_data(target_user_id=int(user_id))
    await message.answer("Nechta yulduz qo‘shamiz? Masalan: 5")
    await state.set_state(AdminState.waiting_star_amount)


@dp.message(AdminState.waiting_star_amount)
async def admin_get_star_amount(message: Message, state: FSMContext):
    if not admin_check(message.from_user.id):
        return

    amount = message.text.strip()

    if not amount.lstrip("-").isdigit():
        await message.answer("Yulduz soni raqam bo‘lishi kerak. Masalan: 5")
        return

    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    amount = int(amount)

    change_stars(target_user_id, amount)

    await message.answer(
        f"✅ Userga yulduz qo‘shildi.\n\n"
        f"User ID: {target_user_id}\n"
        f"Qo‘shilgan yulduz: {amount}",
        reply_markup=admin_menu()
    )

    try:
        await bot.send_message(target_user_id, f"⭐ Balansingizga {amount} yulduz qo‘shildi.")
    except Exception:
        pass

    await state.clear()


@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if not admin_check(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q.")
        return

    await callback.message.answer("Hammaga yuboriladigan xabar matnini kiriting:")
    await state.set_state(AdminState.waiting_broadcast_text)
    await callback.answer()


@dp.message(AdminState.waiting_broadcast_text)
async def admin_send_broadcast(message: Message, state: FSMContext):
    if not admin_check(message.from_user.id):
        return

    text = message.text
    user_ids = get_all_user_ids()

    sent = 0
    failed = 0

    for user_id in user_ids:
        try:
            await bot.send_message(user_id, f"📢 Xabar:\n\n{text}")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await message.answer(
        f"📢 Xabar yuborish tugadi.\n\n"
        f"✅ Yuborildi: {sent}\n"
        f"❌ Yuborilmadi: {failed}",
        reply_markup=admin_menu()
    )

    await state.clear()


@dp.callback_query(F.data == "admin_block_user")
async def admin_block_user(callback: CallbackQuery, state: FSMContext):
    if not admin_check(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q.")
        return

    await callback.message.answer("Bloklamoqchi bo‘lgan user Telegram ID sini yuboring:")
    await state.set_state(AdminState.waiting_block_user_id)
    await callback.answer()


@dp.message(AdminState.waiting_block_user_id)
async def admin_block_user_id(message: Message, state: FSMContext):
    if not admin_check(message.from_user.id):
        return

    user_id = message.text.strip()

    if not user_id.isdigit():
        await message.answer("Telegram ID faqat raqam bo‘lishi kerak. Qayta kiriting:")
        return

    set_block_status(int(user_id), 1)

    await message.answer(
        f"🚫 User bloklandi.\n\n"
        f"User ID: {user_id}",
        reply_markup=admin_menu()
    )

    try:
        await bot.send_message(int(user_id), "🚫 Siz botdan foydalanishdan bloklandingiz.")
    except Exception:
        pass

    await state.clear()


@dp.callback_query(F.data == "admin_unblock_user")
async def admin_unblock_user(callback: CallbackQuery, state: FSMContext):
    if not admin_check(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q.")
        return

    await callback.message.answer("Blokdan chiqariladigan user Telegram ID sini yuboring:")
    await state.set_state(AdminState.waiting_unblock_user_id)
    await callback.answer()


@dp.message(AdminState.waiting_unblock_user_id)
async def admin_unblock_user_id(message: Message, state: FSMContext):
    if not admin_check(message.from_user.id):
        return

    user_id = message.text.strip()

    if not user_id.isdigit():
        await message.answer("Telegram ID faqat raqam bo‘lishi kerak. Qayta kiriting:")
        return

    set_block_status(int(user_id), 0)

    await message.answer(
        f"✅ User blokdan chiqarildi.\n\n"
        f"User ID: {user_id}",
        reply_markup=admin_menu()
    )

    try:
        await bot.send_message(int(user_id), "✅ Siz botdan qayta foydalanishingiz mumkin.")
    except Exception:
        pass

    await state.clear()


# ================= RUN =================

async def main():
    init_db()
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
