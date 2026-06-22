import asyncio
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone

import aiohttp
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
EMPLOYEE_PHONE = os.getenv("EMPLOYEE_PHONE", "+998 XX XXX XX XX")

UZUM_AUTHORIZATION = os.getenv("UZUM_AUTHORIZATION")
UZUM_COOKIE = os.getenv("UZUM_COOKIE")
UZUM_POOL_SOURCE = os.getenv("UZUM_POOL_SOURCE", "FULLFILMENT")
UZUM_STOCK_ID = int(os.getenv("UZUM_STOCK_ID", "34"))

SEARCH_INTERVAL = int(os.getenv("SEARCH_INTERVAL", "3"))
SEARCH_HOURS = int(os.getenv("SEARCH_HOURS", "4"))

PAYMENT_CARD = os.getenv("PAYMENT_CARD", "0000 0000 0000 0000")
PAYMENT_OWNER = os.getenv("PAYMENT_OWNER", "Ism Familiya")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi.")

ADMIN_ID = int(ADMIN_ID) if ADMIN_ID and ADMIN_ID.isdigit() else 0

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_NAME = "bot.db"
UZ_TZ = timezone(timedelta(hours=5))

active_searches = {}
pending_payments = {}

STAR_PLANS = {
    "1": {"stars": 1, "price": 25000},
    "2": {"stars": 2, "price": 45000},
    "5": {"stars": 5, "price": 100000},
    "10": {"stars": 10, "price": 180000},
}


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
            store_name TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            store_id TEXT,
            store_name TEXT,
            invoice TEXT,
            date TEXT,
            status TEXT,
            result TEXT,
            created_at TEXT
        )
    """)

    ensure_column(cur, "users", "username", "TEXT")
    ensure_column(cur, "users", "stars", "INTEGER DEFAULT 1")
    ensure_column(cur, "users", "is_blocked", "INTEGER DEFAULT 0")
    ensure_column(cur, "users", "created_at", "TEXT")

    ensure_column(cur, "stores", "store_name", "TEXT")

    ensure_column(cur, "bookings", "store_name", "TEXT")
    ensure_column(cur, "bookings", "result", "TEXT")

    conn.commit()
    conn.close()


def now():
    return datetime.now(UZ_TZ).strftime("%Y-%m-%d %H:%M:%S")


def add_user(telegram_id, full_name="", username=""):
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
            (telegram_id, full_name or "", username or "", 1, 0, now())
        )
    else:
        cur.execute(
            "UPDATE users SET full_name = ?, username = ? WHERE telegram_id = ?",
            (full_name or "", username or "", telegram_id)
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

    cur.execute("SELECT telegram_id FROM users WHERE telegram_id = ?", (telegram_id,))
    exists = cur.fetchone()

    if not exists:
        cur.execute(
            """
            INSERT INTO users (telegram_id, full_name, username, stars, is_blocked, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (telegram_id, "", "", amount, 0, now())
        )
    else:
        cur.execute(
            "UPDATE users SET stars = stars + ? WHERE telegram_id = ?",
            (amount, telegram_id)
        )

    conn.commit()
    conn.close()


def store_used_by_other_user(store_id, telegram_id):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT telegram_id
        FROM stores
        WHERE store_id = ? AND telegram_id != ?
        LIMIT 1
        """,
        (store_id, telegram_id)
    )

    row = cur.fetchone()
    conn.close()

    return row[0] if row else None


def save_store(telegram_id, store_id, store_name):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT id FROM stores WHERE telegram_id = ? AND store_id = ?",
        (telegram_id, store_id)
    )
    exists = cur.fetchone()

    if exists:
        cur.execute(
            "UPDATE stores SET store_name = ? WHERE telegram_id = ? AND store_id = ?",
            (store_name, telegram_id, store_id)
        )
    else:
        cur.execute(
            """
            INSERT INTO stores (telegram_id, store_id, store_name, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (telegram_id, store_id, store_name, now())
        )

    conn.commit()
    conn.close()


def get_user_stores(telegram_id):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, store_id, store_name, created_at
        FROM stores
        WHERE telegram_id = ?
        ORDER BY id DESC
        """,
        (telegram_id,)
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_store_by_id(row_id, telegram_id=None):
    conn = db()
    cur = conn.cursor()

    if telegram_id is None:
        cur.execute(
            "SELECT id, telegram_id, store_id, store_name FROM stores WHERE id = ?",
            (row_id,)
        )
    else:
        cur.execute(
            "SELECT id, telegram_id, store_id, store_name FROM stores WHERE id = ? AND telegram_id = ?",
            (row_id, telegram_id)
        )

    row = cur.fetchone()
    conn.close()
    return row


def delete_store(row_id, telegram_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM stores WHERE id = ? AND telegram_id = ?", (row_id, telegram_id))
    conn.commit()
    conn.close()


def save_booking(telegram_id, store_id, store_name, invoice, date, status, result=""):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO bookings (telegram_id, store_id, store_name, invoice, date, status, result, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (telegram_id, store_id, store_name, invoice, date, status, result, now())
    )
    conn.commit()
    conn.close()


def get_user_bookings(telegram_id):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT store_name, store_id, invoice, date, status, result, created_at
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


def get_all_stores(limit=30):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT s.store_id, s.store_name, s.telegram_id, u.full_name, u.username, s.created_at
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


def get_all_bookings(limit=30):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT b.telegram_id, u.full_name, b.store_name, b.store_id, b.invoice, b.date, b.status, b.result, b.created_at
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


# ================= UZUM API =================

def uzum_headers():
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://seller.uzum.uz",
        "Referer": "https://seller.uzum.uz/",
    }

    if UZUM_AUTHORIZATION:
        headers["Authorization"] = UZUM_AUTHORIZATION

    if UZUM_COOKIE:
        headers["Cookie"] = UZUM_COOKIE

    return headers


async def read_response(response):
    try:
        return await response.json(content_type=None)
    except Exception:
        text = await response.text()
        return {"raw": text[:1000]}


def short_data(data, limit=500):
    text = str(data)
    return text[:limit] + "..." if len(text) > limit else text


def find_key_recursive(obj, keys):
    if isinstance(obj, dict):
        for key in keys:
            if key in obj and obj[key]:
                return obj[key]

        for value in obj.values():
            result = find_key_recursive(value, keys)
            if result:
                return result

    if isinstance(obj, list):
        for item in obj:
            result = find_key_recursive(item, keys)
            if result:
                return result

    return None


def find_shop_name_by_id(obj, shop_id):
    if isinstance(obj, dict):
        possible_id = obj.get("id") or obj.get("shopId") or obj.get("shop_id")

        if str(possible_id) == str(shop_id):
            name = find_key_recursive(obj, ["name", "shopName", "title", "storeName", "sellerName"])
            if name:
                return str(name)

        for value in obj.values():
            result = find_shop_name_by_id(value, shop_id)
            if result:
                return result

    if isinstance(obj, list):
        for item in obj:
            result = find_shop_name_by_id(item, shop_id)
            if result:
                return result

    return None


async def uzum_get_shop_name(shop_id: str):
    urls = [
        f"https://api-seller.uzum.uz/api/seller/shop/{shop_id}",
        f"https://api-seller.uzum.uz/api/seller/shop",
    ]

    async with aiohttp.ClientSession(headers=uzum_headers()) as session:
        for url in urls:
            try:
                async with session.get(url) as response:
                    data = await read_response(response)

                    if response.status != 200:
                        continue

                    exact_name = find_shop_name_by_id(data, shop_id)
                    if exact_name:
                        return exact_name
                    name = find_key_recursive(
                        data,
                        ["name", "shopName", "title", "storeName", "sellerName"]
                    )
                    if name:
                        return str(name)

            except Exception:
                continue

    return f"Do‘kon {shop_id}"


def find_invoice_record(obj, invoice_number):
    if isinstance(obj, dict):
        if str(obj.get("invoiceNumber")) == str(invoice_number):
            return obj

        for value in obj.values():
            result = find_invoice_record(value, invoice_number)
            if result:
                return result

    if isinstance(obj, list):
        for item in obj:
            result = find_invoice_record(item, invoice_number)
            if result:
                return result

    return None


def find_timeslots(obj):
    if isinstance(obj, dict):
        if "timeSlots" in obj and isinstance(obj["timeSlots"], list):
            return obj["timeSlots"]

        for value in obj.values():
            result = find_timeslots(value)
            if result:
                return result

    if isinstance(obj, list):
        for item in obj:
            result = find_timeslots(item)
            if result:
                return result

    return []


def uz_now():
    return datetime.now(UZ_TZ)


def normalize_date_text(date_text: str):
    value = (date_text or "").strip().lower()

    if value == "bugun":
        return uz_now().strftime("%d.%m.%Y")

    if value == "ertaga":
        return (uz_now() + timedelta(days=1)).strftime("%d.%m.%Y")

    try:
        dt = datetime.strptime(date_text.strip(), "%d.%m.%Y")
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return uz_now().strftime("%d.%m.%Y")


def date_to_timestamp_ms(date_text: str):
    wanted = normalize_date_text(date_text)

    try:
        dt = datetime.strptime(wanted, "%d.%m.%Y")
        dt = dt.replace(tzinfo=UZ_TZ)
        return int(dt.timestamp() * 1000)
    except Exception:
        return int(time.time() * 1000)


def slot_date_text(time_from):
    ts = int(time_from)

    if ts < 10_000_000_000:
        ts *= 1000

    dt = datetime.fromtimestamp(ts / 1000, UZ_TZ)
    return dt.strftime("%d.%m.%Y")


def parse_invoice_list(text: str):
    parts = re.split(r"[,\n\s]+", text.strip())
    return [p.strip() for p in parts if p.strip()]


async def uzum_find_invoice_id(shop_id: str, invoice_text: str):
    invoice_text = invoice_text.strip()

    if invoice_text.isdigit() and len(invoice_text) <= 8:
        return int(invoice_text)

    if invoice_text.isdigit() and invoice_text.startswith("11000") and len(invoice_text) >= 12:
        return int(invoice_text[5:])

    url = (
        f"https://api-seller.uzum.uz/api/seller/shop/{shop_id}/invoice"
        f"?page=0&size=20&invoiceNumber={invoice_text}"
    )

    async with aiohttp.ClientSession(headers=uzum_headers()) as session:
        async with session.get(url) as response:
            data = await read_response(response)

            if response.status != 200:
                raise Exception(
                    f"Invoice qidirishda xato: {response.status}. Javob: {short_data(data)}"
                )

            record = find_invoice_record(data, invoice_text)

            if not record:
                raise Exception(
                    f"Invoice topilmadi. Qidirilgan: {invoice_text}. Javob: {short_data(data)}"
                )

            return int(record["id"])


async def uzum_get_slots(shop_id: str, invoice_id: int, date_text: str):
    url = f"https://api-seller.uzum.uz/api/seller/shop/{shop_id}/v2/invoice/time-slot/get"

    payload = {
        "invoiceIds": [invoice_id],
        "poolSource": UZUM_POOL_SOURCE,
        "timeFrom": date_to_timestamp_ms(date_text)
    }

    async with aiohttp.ClientSession(headers=uzum_headers()) as session:
        async with session.post(url, json=payload) as response:
            data = await read_response(response)

            if response.status == 400:
                return []

            if response.status == 403:
                raise Exception(f"Ruxsat yo‘q: {short_data(data)}")

            if response.status != 200:
                return []

            return find_timeslots(data)


async def uzum_set_slot(shop_id: str, invoice_id: int, time_from: int):
    url = f"https://api-seller.uzum.uz/api/seller/shop/{shop_id}/v2/invoice/time-slot/set"

    payload = {
        "timeFrom": time_from,
        "invoiceIds": [invoice_id],
        "poolSource": UZUM_POOL_SOURCE,
        "stockId": UZUM_STOCK_ID
    }

    async with aiohttp.ClientSession(headers=uzum_headers()) as session:
        async with session.post(url, json=payload) as response:
            data = await read_response(response)

            if response.status != 200:
                raise Exception(
                    f"Slot saqlashda xato: {response.status}. Javob: {short_data(data)}"
                )

            return data


# ================= MENUS =================

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📦 Yangi bron"),
                KeyboardButton(text="🏬 Mening do‘konlarim"),
            ],
            [
                KeyboardButton(text="➕ Do‘kon qo‘shish"),
                KeyboardButton(text="🔍 Faol qidiruvlar"),
            ],
            [
                KeyboardButton(text="🛑 Qidiruvni to‘xtatish"),
                KeyboardButton(text="⭐ Balans"),
            ],
            [
                KeyboardButton(text="⭐ Yulduz sotib olish"),
                KeyboardButton(text="📜 Bronlar tarixi"),
            ],
        ],
        resize_keyboard=True
    )


def admin_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Statistika", callback_data="admin_stats")
    kb.button(text="👥 Userlar", callback_data="admin_users")
    kb.button(text="🏪 Do‘konlar", callback_data="admin_stores")
    kb.button(text="📦 Bronlar", callback_data="admin_bookings")
    kb.button(text="🔍 Faol qidiruvlar", callback_data="admin_active")
    kb.button(text="⭐ Userga yulduz qo‘shish", callback_data="admin_add_stars")
    kb.button(text="📢 Hammaga xabar yuborish", callback_data="admin_broadcast")
    kb.button(text="🚫 User bloklash", callback_data="admin_block_user")
    kb.button(text="✅ Blokdan chiqarish", callback_data="admin_unblock_user")
    kb.adjust(1)
    return kb.as_markup()


def store_select_keyboard(stores):
    kb = InlineKeyboardBuilder()
    for row_id, store_id, store_name, _ in stores:
        kb.button(text=f"🏪 {store_name}", callback_data=f"select_store:{row_id}")
    kb.button(text="❌ Bekor qilish", callback_data="cancel_booking")
    kb.adjust(1)
    return kb.as_markup()


def stores_list_keyboard(stores):
    kb = InlineKeyboardBuilder()
    for row_id, store_id, store_name, _ in stores:
        kb.button(text=f"❌ O‘chirish: {store_name}", callback_data=f"delete_store:{row_id}")
    kb.adjust(1)
    return kb.as_markup()


def dates_keyboard(selected_dates=None):
    selected_dates = selected_dates or []
    kb = InlineKeyboardBuilder()

    today = uz_now().date()

    for i in range(14):
        d = today + timedelta(days=i)
        text = d.strftime("%d.%m.%Y")
        label = f"✅ {text}" if text in selected_dates else text
        kb.button(text=label, callback_data=f"date_toggle:{text}")

    kb.button(text="✅ Tayyor", callback_data="dates_done")
    kb.button(text="❌ Bekor qilish", callback_data="cancel_booking")
    kb.adjust(2)
    return kb.as_markup()


def confirm_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tasdiqlash", callback_data="confirm_booking")
    kb.button(text="❌ Bekor qilish", callback_data="cancel_booking")
    kb.adjust(1)
    return kb.as_markup()


def search_stop_keyboard(searches):
    kb = InlineKeyboardBuilder()
    for search_id, item in searches.items():
        text = f"🛑 {item['store_name']} | {item['invoice_text']} | {', '.join(item['dates'])}"
        kb.button(text=text[:60], callback_data=f"stop_one:{search_id}")
    kb.adjust(1)
    return kb.as_markup()


def star_plans_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="⭐ 1 yulduz — 25 000 so‘m", callback_data="buy_plan:1")
    kb.button(text="⭐ 2 yulduz — 45 000 so‘m", callback_data="buy_plan:2")
    kb.button(text="⭐ 5 yulduz — 100 000 so‘m", callback_data="buy_plan:5")
    kb.button(text="⭐ 10 yulduz — 180 000 so‘m", callback_data="buy_plan:10")
    kb.button(text="❌ Bekor qilish", callback_data="cancel_payment")
    kb.adjust(1)
    return kb.as_markup()


def admin_payment_keyboard(payment_id):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tasdiqlash", callback_data=f"pay_ok:{payment_id}")
    kb.button(text="❌ Rad etish", callback_data=f"pay_no:{payment_id}")
    kb.adjust(2)
    return kb.as_markup()


def admin_check(user_id):
    return user_id == ADMIN_ID


async def blocked_guard(message):
    if is_blocked(message.from_user.id):
        await message.answer("Siz botdan foydalanishdan bloklangansiz.")
        return True
    return False


# ================= STATES =================

class StoreState(StatesGroup):
    waiting_store_id = State()


class BookingState(StatesGroup):
    choosing_store = State()
    waiting_invoice = State()
    choosing_dates = State()
    confirming = State()


class PaymentState(StatesGroup):
    waiting_receipt = State()


class AdminState(StatesGroup):
    waiting_user_id_for_stars = State()
    waiting_star_amount = State()
    waiting_broadcast_text = State()
    waiting_block_user_id = State()
    waiting_unblock_user_id = State()


# ================= SEARCH WORKER =================

async def refund_reserved_star(search_id, item):
    if item and item.get("star_reserved"):
        change_stars(item["telegram_id"], 1)
        item["star_reserved"] = False


async def auto_search_slot(search_id: str):
    item = active_searches.get(search_id)
    if not item:
        return

    telegram_id = item["telegram_id"]
    store_id = item["store_id"]
    store_name = item["store_name"]
    invoice_id = item["invoice_id"]
    invoice_text = item["invoice_text"]
    dates = item["dates"]

    deadline = time.time() + SEARCH_HOURS * 60 * 60

    await bot.send_message(
        telegram_id,
        "🔍 Qidiruv boshlandi!\n\n"
        f"🏪 Do‘kon: {store_name}\n"
        f"📦 Invoice: {invoice_text}\n"
        f"📅 Sanalar: {', '.join(dates)}\n\n"
        "⏳ Bu bir necha daqiqa vaqt olishi mumkin...\n"
        f"Agar {SEARCH_HOURS} soat ichida slot topilmasa, keyinroq qayta urinib ko‘rishingiz mumkin.",
        reply_markup=main_menu()
    )

    while time.time() < deadline:
        if search_id not in active_searches:
            return

        try:
            for date_text in dates:
                if search_id not in active_searches:
                    return

                wanted_date = normalize_date_text(date_text)
                slots = await uzum_get_slots(store_id, invoice_id, date_text)

                matched_slots = [
                    slot for slot in slots
                    if slot.get("timeFrom") and slot_date_text(slot.get("timeFrom")) == wanted_date
                ]

                if not matched_slots:
                    continue

                for selected_slot in matched_slots:
                    time_from = selected_slot.get("timeFrom")
                    if not time_from:
                        continue

                    try:
                        await uzum_set_slot(store_id, invoice_id, time_from)

                        save_booking(
                            telegram_id,
                            store_id,
                            store_name,
                            invoice_text,
                            wanted_date,
                            "booked",
                            f"invoice_id={invoice_id}, timeFrom={time_from}, search_id={search_id}"
                        )

                        active_searches.pop(search_id, None)

                        await bot.send_message(
                            telegram_id,
                            f"✅ Slot muvaffaqiyatli bron qilindi!\n\n"
                            f"🏪 Do‘kon: {store_name}\n"
                            f"📦 Invoice: {invoice_text}\n"
                            f"📅 Bron qilingan sana: {wanted_date}\n"
                            f"⏰ timeFrom: {time_from}\n\n"
                            f"⭐ 1 yulduz ishlatildi.",
                            reply_markup=main_menu()
                        )
                        return

                    except Exception:
                        continue

        except Exception as e:
            item = active_searches.get(search_id)
            await refund_reserved_star(search_id, item)

            save_booking(
                telegram_id,
                store_id,
                store_name,
                invoice_text,
                ", ".join(dates),
                "error",
                str(e)
            )

            active_searches.pop(search_id, None)

            await bot.send_message(
                telegram_id,
                f"❌ Qidiruvda xato chiqdi.\n\n"
                f"📦 Invoice: {invoice_text}\n"
                f"Xato: {e}\n\n"
                f"⭐ Yulduz qaytarildi.",
                reply_markup=main_menu()
            )
            return

        await asyncio.sleep(SEARCH_INTERVAL)

    item = active_searches.get(search_id)
    await refund_reserved_star(search_id, item)

    active_searches.pop(search_id, None)

    save_booking(
        telegram_id,
        store_id,
        store_name,
        invoice_text,
        ", ".join(dates),
        "timeout",
        f"{SEARCH_HOURS} soat ichida slot topilmadi"
    )

    await bot.send_message(
        telegram_id,
        f"⏰ Vaqt tugadi.\n\n"
        f"{SEARCH_HOURS} soat ichida siz tanlagan sanalarga slot topilmadi.\n\n"
        f"🏪 Do‘kon: {store_name}\n"
        f"📦 Invoice: {invoice_text}\n"
        f"📅 Sanalar: {', '.join(dates)}\n\n"
        "Keyinroq qayta urinib ko‘rishingiz mumkin.\n"
        "⭐ Yulduz qaytarildi.",
        reply_markup=main_menu()
    )


# ================= START =================

START_TEXT = (
    "📦 Uzum Time Slot Bot\n\n"
    "Uzum Market omboriga avtomatik slot bron qilish boti.\n\n"
    "✅ Bir nechta do‘kon ulash\n"
    "✅ Bir nechta invoice bo‘yicha qidirish\n"
    "✅ Tanlangan sana bo‘yicha slot qidirish\n"
    "✅ Slot topilsa avtomatik bron qilish\n\n"
    "⚠️ Bot javob bermasa /start ni bosing."
)


@dp.message(CommandStart())
async def start(message: Message):
    add_user(message.from_user.id, message.from_user.full_name, message.from_user.username)

    if await blocked_guard(message):
        return

    await message.answer(START_TEXT, reply_markup=main_menu())


@dp.message(Command("myid"))
async def my_id(message: Message):
    add_user(message.from_user.id, message.from_user.full_name, message.from_user.username)
    await message.answer(f"Sizning Telegram ID: {message.from_user.id}")


@dp.message(Command("admin"))
async def admin(message: Message):
    if not admin_check(message.from_user.id):
        await message.answer("Siz admin emassiz.")
        return

    await message.answer("Admin panel:", reply_markup=admin_menu())


# ================= USER MENU =================

@dp.message(F.text == "➕ Do‘kon qo‘shish")
async def add_store_start(message: Message, state: FSMContext):
    if await blocked_guard(message):
        return

    await message.answer(
        "🏪 Do‘konni bog‘lash uchun:\n\n"
        "1. Uzum Seller paneliga kiring\n"
        "2. Sozlamalar → Xodimlar bo‘limiga o‘ting\n"
        "3. Quyidagi telefon raqamni xodim sifatida qo‘shing:\n\n"
        f"📞 {EMPLOYEE_PHONE}\n\n"
        "Qo‘shgandan so‘ng, do‘kon ID raqamini yuboring."
    )
    await state.set_state(StoreState.waiting_store_id)


@dp.message(StoreState.waiting_store_id)
async def store_id_save(message: Message, state: FSMContext):
    if await blocked_guard(message):
        await state.clear()
        return

    store_id = message.text.strip()

    if not store_id.isdigit():
        await message.answer("Do‘kon ID faqat raqamlardan iborat bo‘lishi kerak. Qayta kiriting:")
        return

    wait_msg = await message.answer("🔄 Do‘kon tekshirilmoqda...")

    used_by = store_used_by_other_user(store_id, message.from_user.id)

    if used_by:
        await wait_msg.edit_text(
            "❌ Bu do‘kon allaqachon boshqa Telegram accountga ulangan.\n\n"
            "Agar bu sizning do‘koningiz bo‘lsa, admin bilan bog‘laning."
        )
        await state.clear()
        return

    store_name = await uzum_get_shop_name(store_id)

    save_store(message.from_user.id, store_id, store_name)

    await wait_msg.edit_text(
        f"✅ Do‘kon muvaffaqiyatli bog‘landi!\n\n"
        f"🏪 Do‘kon: {store_name}\n"
        f"🆔 Do‘kon ID: {store_id}\n\n"
        f"Endi bron qilishingiz mumkin."
    )

    await state.clear()


@dp.message(F.text == "🏬 Mening do‘konlarim")
async def my_stores(message: Message):
    if await blocked_guard(message):
        return

    stores = get_user_stores(message.from_user.id)

    if not stores:
        await message.answer("Sizda hali do‘kon ulanmagan.", reply_markup=main_menu())
        return

    text = "🏬 Mening do‘konlarim:\n\n"
    for _, store_id, store_name, created_at in stores:
        text += f"🏪 {store_name}\n🆔 {store_id}\n📅 {created_at}\n\n"

    await message.answer(text, reply_markup=stores_list_keyboard(stores))


@dp.callback_query(F.data.startswith("delete_store:"))
async def delete_store_callback(callback: CallbackQuery):
    row_id = int(callback.data.split(":")[1])
    delete_store(row_id, callback.from_user.id)
    await callback.message.answer("✅ Do‘kon o‘chirildi.", reply_markup=main_menu())
    await callback.answer()


@dp.message(F.text == "⭐ Balans")
async def balance(message: Message):
    add_user(message.from_user.id, message.from_user.full_name, message.from_user.username)
    stars = get_stars(message.from_user.id)
    await message.answer(f"⭐ Sizning balansingiz: {stars} yulduz", reply_markup=main_menu())


@dp.message(F.text == "📜 Bronlar tarixi")
async def history(message: Message):
    rows = get_user_bookings(message.from_user.id)

    if not rows:
        await message.answer("Sizda hali bronlar yo‘q.", reply_markup=main_menu())
        return

    text = "📜 Oxirgi bronlar tarixi:\n\n"

    for store_name, store_id, invoice, date, status, result, created_at in rows:
        text += (
            f"🏪 {store_name} ({store_id})\n"
            f"📦 Invoice: {invoice}\n"
            f"📅 Sana: {date}\n"
            f"Holat: {status}\n"
            f"Natija: {result or '-'}\n"
            f"Vaqt: {created_at}\n\n"
        )

    await message.answer(text, reply_markup=main_menu())


# ================= BOOKING FLOW =================

@dp.message(F.text == "📦 Yangi bron")
async def new_booking(message: Message, state: FSMContext):
    if await blocked_guard(message):
        return

    stores = get_user_stores(message.from_user.id)

    if not stores:
        await message.answer("Avval do‘kon qo‘shing.", reply_markup=main_menu())
        return

    if get_stars(message.from_user.id) <= 0:
        await message.answer(
            "❌ Yetarli yulduz yo‘q!\n\n"
            "Kerak: kamida 1 yulduz\n"
            f"Sizda: {get_stars(message.from_user.id)} yulduz\n\n"
            "⭐ Yulduz sotib olish tugmasini bosing.",
            reply_markup=main_menu()
        )
        return

    if len(stores) == 1:
        row_id, store_id, store_name, _ = stores[0]
        await state.update_data(store_db_id=row_id, store_id=store_id, store_name=store_name)
        await ask_invoices(message, state)
        return

    await message.answer(
        "🏪 Qaysi do‘kondan bron qilamiz?",
        reply_markup=store_select_keyboard(stores)
    )
    await state.set_state(BookingState.choosing_store)


@dp.callback_query(F.data.startswith("select_store:"))
async def select_store(callback: CallbackQuery, state: FSMContext):
    row_id = int(callback.data.split(":")[1])
    row = get_store_by_id(row_id, callback.from_user.id)

    if not row:
        await callback.message.answer("Do‘kon topilmadi.", reply_markup=main_menu())
        await callback.answer()
        return

    _, _, store_id, store_name = row
    await state.update_data(store_db_id=row_id, store_id=store_id, store_name=store_name)

    await callback.message.answer(f"✅ Tanlandi: {store_name}")
    await ask_invoices(callback.message, state)
    await callback.answer()


async def ask_invoices(message: Message, state: FSMContext):
    await message.answer(
        "📦 Invoice raqamlarini vergul bilan kiriting:\n\n"
        "Masalan:\n"
        "3535244, 3535245\n"
        "yoki:\n"
        "110003535244, 110003535245\n\n"
        "Invoice raqamini Uzum Seller → Buyurtmalar bo‘limida topishingiz mumkin."
    )
    await state.set_state(BookingState.waiting_invoice)


@dp.message(BookingState.waiting_invoice)
async def get_invoices(message: Message, state: FSMContext):
    if await blocked_guard(message):
        await state.clear()
        return

    invoices = parse_invoice_list(message.text)

    if not invoices:
        await message.answer("Invoice topilmadi. Qayta kiriting:")
        return

    await state.update_data(invoices=invoices, selected_dates=[])
    await message.answer(
        "📅 Sanani tanlang (bir yoki bir nechtasini):\n\n"
        "Tanlab bo‘lgach “✅ Tayyor” tugmasini bosing.",
        reply_markup=dates_keyboard([])
    )
    await state.set_state(BookingState.choosing_dates)


@dp.callback_query(F.data.startswith("date_toggle:"))
async def toggle_date(callback: CallbackQuery, state: FSMContext):
    date_text = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected_dates = data.get("selected_dates", [])

    if date_text in selected_dates:
        selected_dates.remove(date_text)
    else:
        selected_dates.append(date_text)

    await state.update_data(selected_dates=selected_dates)

    selected_text = ", ".join(selected_dates) if selected_dates else "hali tanlanmadi"

    await callback.message.edit_text(
        "📅 Sanani tanlang (bir yoki bir nechtasini):\n\n"
        f"Tanlangan sanalar: {selected_text}\n\n"
        "Tanlab bo‘lgach “✅ Tayyor” tugmasini bosing.",
        reply_markup=dates_keyboard(selected_dates)
    )
    await callback.answer()


@dp.callback_query(F.data == "dates_done")
async def dates_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_dates = data.get("selected_dates", [])

    if not selected_dates:
        await callback.answer("Kamida bitta sana tanlang.", show_alert=True)
        return

    store_name = data.get("store_name")
    store_id = data.get("store_id")
    invoices = data.get("invoices", [])
    user_stars = get_stars(callback.from_user.id)

    await callback.message.answer(
        "📋 Bron ma’lumotlari:\n\n"
        f"🏪 Do‘kon: {store_name}\n"
        f"🆔 Do‘kon ID: {store_id}\n"
        f"📦 Invoice: {', '.join(invoices)}\n"
        f"📅 Sanalar: {', '.join(selected_dates)}\n"
        f"⭐ Kerak bo‘ladi: {len(invoices)} yulduz\n"
        f"⭐ Sizda: {user_stars} yulduz\n\n"
        "Tasdiqlaysizmi?",
        reply_markup=confirm_keyboard()
    )
    await state.set_state(BookingState.confirming)
    await callback.answer()


@dp.callback_query(F.data == "confirm_booking")
async def confirm_booking(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    telegram_id = callback.from_user.id
    store_id = data.get("store_id")
    store_name = data.get("store_name")
    invoices = data.get("invoices", [])
    selected_dates = data.get("selected_dates", [])

    required_stars = len(invoices)
    user_stars = get_stars(telegram_id)

    if user_stars < required_stars:
        await callback.message.answer(
            "❌ Yetarli yulduz yo‘q.\n\n"
            f"Kerak: {required_stars} yulduz\n"
            f"Sizda: {user_stars} yulduz\n\n"
            "Har bir invoice uchun 1 yulduz kerak bo‘ladi.",
            reply_markup=main_menu()
        )
        await state.clear()
        await callback.answer()
        return

    started = 0
    errors = []

    for invoice_text in invoices:
        try:
            invoice_id = await uzum_find_invoice_id(store_id, invoice_text)

            change_stars(telegram_id, -1)

            search_id = uuid.uuid4().hex[:8]

            active_searches[search_id] = {
                "telegram_id": telegram_id,
                "store_id": store_id,
                "store_name": store_name,
                "invoice_id": invoice_id,
                "invoice_text": invoice_text,
                "dates": selected_dates,
                "started_at": now(),
                "star_reserved": True,
            }

            asyncio.create_task(auto_search_slot(search_id))
            started += 1

        except Exception as e:
            errors.append(f"{invoice_text}: {e}")

    await state.clear()

    text = (
        "✅ Qidiruv boshlandi!\n\n"
        f"🏪 Do‘kon: {store_name}\n"
        f"📦 Boshlangan qidiruvlar: {started} ta\n"
        f"📅 Sanalar: {', '.join(selected_dates)}\n\n"
        "⏳ Bu bir necha daqiqa vaqt olishi mumkin...\n"
        f"Agar {SEARCH_HOURS} soat ichida slot topilmasa, yana qayta urinib ko‘rishingiz mumkin.\n\n"
        "⭐ Har bir qidiruv uchun 1 yulduz band qilindi.\n"
        "Slot topilmasa yoki qidiruv to‘xtatilsa, yulduz qaytariladi."
    )

    if errors:
        text += "\n\n⚠️ Ayrim invoice’larda xato:\n" + "\n".join(errors[:5])

    await callback.message.answer(text, reply_markup=main_menu())
    await callback.answer()


@dp.callback_query(F.data == "cancel_booking")
async def cancel_booking(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Bekor qilindi.", reply_markup=main_menu())
    await callback.answer()


# ================= ACTIVE SEARCHES =================

@dp.message(F.text == "🔍 Faol qidiruvlar")
async def active_searches_user(message: Message):
    user_items = {
        sid: item for sid, item in active_searches.items()
        if item["telegram_id"] == message.from_user.id
    }

    if not user_items:
        await message.answer("Faol qidiruv yo‘q.", reply_markup=main_menu())
        return

    text = "🔍 Faol qidiruvlar:\n\n"

    for sid, item in user_items.items():
        text += (
            f"ID: {sid}\n"
            f"🏪 {item['store_name']}\n"
            f"📦 Invoice: {item['invoice_text']}\n"
            f"📅 Sanalar: {', '.join(item['dates'])}\n"
            f"Boshlangan: {item['started_at']}\n\n"
        )

    await message.answer(text, reply_markup=search_stop_keyboard(user_items))


@dp.message(F.text == "🛑 Qidiruvni to‘xtatish")
async def stop_search_menu(message: Message):
    user_items = {
        sid: item for sid, item in active_searches.items()
        if item["telegram_id"] == message.from_user.id
    }

    if not user_items:
        await message.answer("Faol qidiruv yo‘q.", reply_markup=main_menu())
        return

    await message.answer(
        "Qaysi qidiruvni to‘xtatamiz?",
        reply_markup=search_stop_keyboard(user_items)
    )


@dp.callback_query(F.data.startswith("stop_one:"))
async def stop_one_search(callback: CallbackQuery):
    search_id = callback.data.split(":")[1]
    item = active_searches.get(search_id)

    if not item:
        await callback.answer("Qidiruv topilmadi.", show_alert=True)
        return

    if item["telegram_id"] != callback.from_user.id and not admin_check(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q.", show_alert=True)
        return

    await refund_reserved_star(search_id, item)
    active_searches.pop(search_id, None)

    await callback.message.answer(
        "🛑 Qidiruv to‘xtatildi.\n\n"
        "⭐ Yulduz qaytarildi.",
        reply_markup=main_menu()
    )
    await callback.answer()


# ================= PAYMENTS =================

@dp.message(F.text == "⭐ Yulduz sotib olish")
async def buy_stars(message: Message):
    stars = get_stars(message.from_user.id)

    await message.answer(
        f"⭐ Sizning balansingiz: {stars} yulduz\n\n"
        "⭐ Yulduz paketini tanlang:\n\n"
        "⭐ 1 yulduz — 25 000 so‘m\n"
        "⭐ 2 yulduz — 45 000 so‘m\n"
        "⭐ 5 yulduz — 100 000 so‘m\n"
        "⭐ 10 yulduz — 180 000 so‘m",
        reply_markup=star_plans_keyboard()
    )


@dp.callback_query(F.data.startswith("buy_plan:"))
async def buy_plan(callback: CallbackQuery, state: FSMContext):
    plan_key = callback.data.split(":")[1]
    plan = STAR_PLANS.get(plan_key)

    if not plan:
        await callback.answer("Tarif topilmadi.", show_alert=True)
        return

    await state.update_data(plan_key=plan_key)

    price_text = f"{plan['price']:,}".replace(",", " ")

    await callback.message.answer(
        "💳 To‘lov ma’lumotlari:\n\n"
        f"⭐ Paket: {plan['stars']} yulduz\n"
        f"💰 Summa: {price_text} so‘m\n\n"
        f"💳 Karta: {PAYMENT_CARD}\n"
        f"👤 Karta egasi: {PAYMENT_OWNER}\n\n"
        "To‘lovdan so‘ng chek rasmini shu yerga yuboring."
    )

    await state.set_state(PaymentState.waiting_receipt)
    await callback.answer()


@dp.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("To‘lov bekor qilindi.", reply_markup=main_menu())
    await callback.answer()


@dp.message(PaymentState.waiting_receipt)
async def payment_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    plan_key = data.get("plan_key")
    plan = STAR_PLANS.get(plan_key)

    if not plan:
        await message.answer("Tarif topilmadi. Qayta urinib ko‘ring.", reply_markup=main_menu())
        await state.clear()
        return

    if not (message.photo or message.document):
        await message.answer("Iltimos, chek rasmini yuboring.")
        return

    payment_id = uuid.uuid4().hex[:8]

    pending_payments[payment_id] = {
        "telegram_id": message.from_user.id,
        "full_name": message.from_user.full_name,
        "username": message.from_user.username or "",
        "stars": plan["stars"],
        "price": plan["price"],
        "created_at": now(),
    }

    await message.answer(
        "✅ Chek adminga yuborildi.\n"
        "Tasdiqlangandan keyin balansingizga yulduz qo‘shiladi.",
        reply_markup=main_menu()
    )

    if ADMIN_ID:
        price_text = f"{plan['price']:,}".replace(",", " ")

        admin_text = (
            "🧾 Yangi to‘lov cheki\n\n"
            f"Payment ID: {payment_id}\n"
            f"👤 User: {message.from_user.full_name}\n"
            f"🆔 User ID: {message.from_user.id}\n"
            f"Username: @{message.from_user.username or '-'}\n"
            f"⭐ Paket: {plan['stars']} yulduz\n"
            f"💰 Summa: {price_text} so‘m\n"
            f"📅 Vaqt: {now()}"
        )

        await bot.send_message(
            ADMIN_ID,
            admin_text,
            reply_markup=admin_payment_keyboard(payment_id)
        )

        try:
            await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
        except Exception:
            pass

    await state.clear()


@dp.callback_query(F.data.startswith("pay_ok:"))
async def payment_ok(callback: CallbackQuery):
    if not admin_check(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q.", show_alert=True)
        return

    payment_id = callback.data.split(":")[1]
    payment = pending_payments.pop(payment_id, None)

    if not payment:
        await callback.answer("To‘lov topilmadi yoki allaqachon ko‘rilgan.", show_alert=True)
        return

    user_id = payment["telegram_id"]
    stars = payment["stars"]

    change_stars(user_id, stars)
    new_balance = get_stars(user_id)

    await callback.message.answer(
        f"✅ To‘lov tasdiqlandi.\n\n"
        f"User ID: {user_id}\n"
        f"Qo‘shildi: {stars} yulduz\n"
        f"Yangi balans: {new_balance} yulduz"
    )

    try:
        await bot.send_message(
            user_id,
            f"✅ To‘lov tasdiqlandi!\n\n"
            f"⭐ +{stars} yulduz\n"
            f"💰 Yangi balans: {new_balance} yulduz",
            reply_markup=main_menu()
        )
    except Exception:
        pass

    await callback.answer()


@dp.callback_query(F.data.startswith("pay_no:"))
async def payment_no(callback: CallbackQuery):
    if not admin_check(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q.", show_alert=True)
        return

    payment_id = callback.data.split(":")[1]
    payment = pending_payments.pop(payment_id, None)

    if not payment:
        await callback.answer("To‘lov topilmadi yoki allaqachon ko‘rilgan.", show_alert=True)
        return

    user_id = payment["telegram_id"]

    await callback.message.answer(f"❌ To‘lov rad etildi. User ID: {user_id}")

    try:
        await bot.send_message(
            user_id,
            "❌ To‘lov rad etildi.\n\n"
            "Agar xato bo‘lsa, qayta chek yuboring.",
            reply_markup=main_menu()
        )
    except Exception:
        pass

    await callback.answer()


# ================= ADMIN =================

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
        f"🔍 Faol qidiruvlar: {len(active_searches)}\n"
        f"🚫 Bloklanganlar: {blocked_count}",
        reply_markup=admin_menu()
    )

    await callback.answer()


@dp.callback_query(F.data == "admin_active")
async def admin_active(callback: CallbackQuery):
    if not admin_check(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q.")
        return

    if not active_searches:
        await callback.message.answer("Faol qidiruvlar yo‘q.", reply_markup=admin_menu())
        await callback.answer()
        return

    text = "🔍 Faol qidiruvlar:\n\n"

    for sid, item in active_searches.items():
        text += (
            f"ID: {sid}\n"
            f"User ID: {item['telegram_id']}\n"
            f"🏪 {item['store_name']} ({item['store_id']})\n"
            f"📦 Invoice: {item['invoice_text']}\n"
            f"📅 Sanalar: {', '.join(item['dates'])}\n"
            f"Boshlangan: {item['started_at']}\n\n"
        )

    await callback.message.answer(text, reply_markup=admin_menu())
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

    for telegram_id, full_name, username, stars, blocked, created_at in rows:
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

    for store_id, store_name, telegram_id, full_name, username, created_at in rows:
        username_text = f"@{username}" if username else "username yo‘q"
        text += (
            f"🏪 {store_name}\n"
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

    for telegram_id, full_name, store_name, store_id, invoice, date, status, result, created_at in rows:
        text += (
            f"User ID: {telegram_id}\n"
            f"Ism: {full_name}\n"
            f"Do‘kon: {store_name} ({store_id})\n"
            f"Invoice: {invoice}\n"
            f"Sana: {date}\n"
            f"Holat: {status}\n"
            f"Natija: {result or '-'}\n"
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
        await message.answer("Yulduz soni raqam bo‘lishi kerak.")
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
        await bot.send_message(
            target_user_id,
            f"⭐ Balansingizga {amount} yulduz qo‘shildi.",
            reply_markup=main_menu()
        )
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
        await message.answer("Telegram ID faqat raqam bo‘lishi kerak.")
        return

    set_block_status(int(user_id), 1)

    await message.answer(
        f"🚫 User bloklandi.\n\nUser ID: {user_id}",
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
        await message.answer("Telegram ID faqat raqam bo‘lishi kerak.")
        return

    set_block_status(int(user_id), 0)

    await message.answer(
        f"✅ User blokdan chiqarildi.\n\nUser ID: {user_id}",
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
