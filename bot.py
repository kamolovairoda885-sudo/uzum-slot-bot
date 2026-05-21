import asyncio
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# Vaqtincha oddiy xotira bazasi
users = {}
stores = {}
bookings = {}


class RegisterStore(StatesGroup):
    waiting_store_id = State()


class NewBooking(StatesGroup):
    waiting_invoice = State()
    waiting_date = State()
    confirm = State()


def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🏪 Do‘kon ulash", callback_data="connect_store")
    kb.button(text="📦 Yangi bron", callback_data="new_booking")
    kb.button(text="⭐ Balans", callback_data="balance")
    kb.button(text="📜 Bronlar tarixi", callback_data="history")
    kb.adjust(1)
    return kb.as_markup()


def language_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🇺🇿 O‘zbekcha", callback_data="lang_uz")
    kb.button(text="🇷🇺 Русский", callback_data="lang_ru")
    kb.adjust(1)
    return kb.as_markup()


@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id

    users[user_id] = {
        "name": message.from_user.full_name,
        "stars": 1,
        "language": None
    }

    await message.answer(
        "Assalomu alaykum!\n\n"
        "Uzum Time Slot botiga xush kelibsiz.\n\n"
        "Tilni tanlang:",
        reply_markup=language_menu()
    )


@dp.callback_query(F.data == "lang_uz")
async def set_lang_uz(callback: CallbackQuery):
    user_id = callback.from_user.id
    users.setdefault(user_id, {})
    users[user_id]["language"] = "uz"
    users[user_id].setdefault("stars", 1)

    await callback.message.answer(
        "Xush kelibsiz!\n\n"
        "Sizga 1 ta bepul yulduz berildi.\n"
        "Har bir muvaffaqiyatli bron 1 yulduzga teng.",
        reply_markup=main_menu()
    )
    await callback.answer()


@dp.callback_query(F.data == "lang_ru")
async def set_lang_ru(callback: CallbackQuery):
    user_id = callback.from_user.id
    users.setdefault(user_id, {})
    users[user_id]["language"] = "ru"
    users[user_id].setdefault("stars", 1)

    await callback.message.answer(
        "Добро пожаловать!\n\n"
        "Вам начислена 1 бесплатная звезда.\n"
        "Каждая успешная бронь = 1 звезда.",
        reply_markup=main_menu()
    )
    await callback.answer()


@dp.callback_query(F.data == "connect_store")
async def connect_store(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "Do‘koningizni ulash uchun:\n\n"
        "1. Uzum Seller paneliga kiring\n"
        "2. Xodimlar bo‘limiga o‘ting\n"
        "3. Bot uchun berilgan telefon raqamni xodim sifatida qo‘shing\n"
        "4. Keyin do‘kon ID raqamini yuboring.\n\n"
        "Do‘kon ID raqamini kiriting:"
    )
    await state.set_state(RegisterStore.waiting_store_id)
    await callback.answer()


@dp.message(RegisterStore.waiting_store_id)
async def save_store_id(message: Message, state: FSMContext):
    user_id = message.from_user.id
    store_id = message.text.strip()

    if not store_id.isdigit():
        await message.answer("Do‘kon ID faqat raqamlardan iborat bo‘lishi kerak. Qayta kiriting:")
        return

    stores[user_id] = {
        "store_id": store_id,
        "status": "connected"
    }

    await message.answer(
        f"✅ Do‘kon muvaffaqiyatli ulandi!\n\n"
        f"🏪 Do‘kon ID: {store_id}\n\n"
        f"Endi bron qilishingiz mumkin.",
        reply_markup=main_menu()
    )
    await state.clear()


@dp.callback_query(F.data == "new_booking")
async def new_booking(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id

    if user_id not in stores:
        await callback.message.answer(
            "Avval do‘koningizni ulang.",
            reply_markup=main_menu()
        )
        await callback.answer()
        return

    stars = users.get(user_id, {}).get("stars", 0)

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
    await state.set_state(NewBooking.waiting_invoice)
    await callback.answer()


@dp.message(NewBooking.waiting_invoice)
async def get_invoice(message: Message, state: FSMContext):
    invoice = message.text.strip()

    if len(invoice) < 5:
        await message.answer("Invoice raqami noto‘g‘ri ko‘rinadi. Qayta kiriting:")
        return

    await state.update_data(invoice=invoice)

    kb = InlineKeyboardBuilder()
    kb.button(text="Bugun", callback_data="date_today")
    kb.button(text="Ertaga", callback_data="date_tomorrow")
    kb.button(text="Boshqa sana", callback_data="date_custom")
    kb.adjust(1)

    await message.answer("Sanani tanlang:", reply_markup=kb.as_markup())


@dp.callback_query(F.data == "date_today")
async def date_today(callback: CallbackQuery, state: FSMContext):
    await state.update_data(date="Bugun")
    await show_confirm(callback, state)


@dp.callback_query(F.data == "date_tomorrow")
async def date_tomorrow(callback: CallbackQuery, state: FSMContext):
    await state.update_data(date="Ertaga")
    await show_confirm(callback, state)


@dp.callback_query(F.data == "date_custom")
async def date_custom(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Sanani yozing. Masalan: 14.05.2026")
    await state.set_state(NewBooking.waiting_date)
    await callback.answer()


@dp.message(NewBooking.waiting_date)
async def custom_date(message: Message, state: FSMContext):
    await state.update_data(date=message.text.strip())

    class FakeCallback:
        def __init__(self, message):
            self.message = message

        async def answer(self):
            pass

    await show_confirm(FakeCallback(message), state)


async def show_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.message.chat.id
    store = stores.get(user_id, {})

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tasdiqlash", callback_data="confirm_booking")
    kb.button(text="❌ Bekor qilish", callback_data="cancel_booking")
    kb.adjust(1)

    await callback.message.answer(
        "📋 Bron ma’lumotlari:\n\n"
        f"🏪 Do‘kon ID: {store.get('store_id')}\n"
        f"📦 Invoice: {data.get('invoice')}\n"
        f"📅 Sana: {data.get('date')}\n"
        f"⭐ Sarflanadi: 1 yulduz\n\n"
        "Tasdiqlaysizmi?",
        reply_markup=kb.as_markup()
    )
    await state.set_state(NewBooking.confirm)


@dp.callback_query(F.data == "confirm_booking")
async def confirm_booking(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()

    booking_id = len(bookings) + 1

    bookings[booking_id] = {
        "user_id": user_id,
        "store_id": stores[user_id]["store_id"],
        "invoice": data.get("invoice"),
        "date": data.get("date"),
        "status": "searching"
    }

    await callback.message.answer(
        "✅ Bron jarayoni boshlandi!\n\n"
        "🔍 Slot qidirilmoqda...\n"
        "Bu bir necha daqiqa davom etishi mumkin.\n\n"
        "Hozircha bu MVP test rejimi. Keyingi bosqichda Uzum API ulanadi."
    )

    await state.clear()
    await callback.answer()


@dp.callback_query(F.data == "cancel_booking")
async def cancel_booking(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Bron bekor qilindi.", reply_markup=main_menu())
    await callback.answer()


@dp.callback_query(F.data == "balance")
async def balance(callback: CallbackQuery):
    user_id = callback.from_user.id
    stars = users.get(user_id, {}).get("stars", 0)

    await callback.message.answer(
        f"⭐ Sizning balansingiz: {stars} yulduz",
        reply_markup=main_menu()
    )
    await callback.answer()


@dp.callback_query(F.data == "history")
async def history(callback: CallbackQuery):
    user_id = callback.from_user.id

    user_bookings = [
        b for b in bookings.values()
        if b["user_id"] == user_id
    ]

    if not user_bookings:
        await callback.message.answer("Sizda hali bronlar yo‘q.", reply_markup=main_menu())
        await callback.answer()
        return

    text = "📜 Bronlar tarixi:\n\n"

    for b in user_bookings:
        text += (
            f"🏪 Do‘kon ID: {b['store_id']}\n"
            f"📦 Invoice: {b['invoice']}\n"
            f"📅 Sana: {b['date']}\n"
            f"Holat: {b['status']}\n\n"
        )

    await callback.message.answer(text, reply_markup=main_menu())
    await callback.answer()


async def main():
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    @dp.message(Command("myid"))
async def my_id(message: Message):
    await message.answer(f"Sizning Telegram ID: {message.from_user.id}")


async def main():
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
