import os
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ContentType
from aiogram.filters import CommandStart
from dotenv import load_dotenv

# --- Load ENV ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

# --- Bot & Dispatcher ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# --- SQLite Setup ---
conn = sqlite3.connect("user_data.db")
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        last_sent_time TEXT
    )
""")
conn.commit()

# --- FSM States ---
class Submission(StatesGroup):
    waiting_for_message = State()
    waiting_for_contact = State()

# --- Keyboards ---
main_menu = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [KeyboardButton(text="📝 Отправить заявку")],
    [KeyboardButton(text="❓ Помощь")]
])

back_menu = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [KeyboardButton(text="🔙 Назад")]
])

# --- Time Control ---
def can_send(user_id):
    cursor.execute("SELECT last_sent_time FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        return True
    last_time = datetime.fromisoformat(row[0])
    return datetime.now() - last_time >= timedelta(hours=12)

def update_send_time(user_id):
    now = datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO users (user_id, last_sent_time)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET last_sent_time = excluded.last_sent_time
    """, (user_id, now))
    conn.commit()

# --- Track Last Messages ---
user_last_message_id = {}

async def delete_previous(message: Message):
    old_msg_id = user_last_message_id.get(message.from_user.id)
    if old_msg_id:
        try:
            await bot.delete_message(message.chat.id, old_msg_id)
        except:
            pass

async def send_and_store(message: Message, text, reply_markup=None):
    await delete_previous(message)
    sent = await message.answer(text, reply_markup=reply_markup)
    user_last_message_id[message.from_user.id] = sent.message_id

# --- Handlers ---

@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await send_and_store(message, "👋 Привет! Здесь ты можешь отправить заявку в канал.", main_menu)

@router.message(F.text == "📝 Отправить заявку")
async def start_submission(message: Message, state: FSMContext):
    if not can_send(message.from_user.id):
        await send_and_store(message, "⏳ Вы можете отправлять заявку только раз в 12 часов.", main_menu)
        return
    await state.set_state(Submission.waiting_for_message)
    await send_and_store(message, "✏️ Введите текст или отправьте фото с текстом для заявки:", back_menu)

@router.message(F.text == "❓ Помощь")
async def help_msg(message: Message):
    await send_and_store(message, "ℹ️ Просто нажмите 'Отправить заявку' и следуйте инструкциям!", main_menu)

@router.message(F.text == "🔙 Назад")
async def back_to_menu(message: Message, state: FSMContext):
    await state.clear()
    await send_and_store(message, "🔙 Вы вернулись в главное меню.", main_menu)

@router.message(Submission.waiting_for_message, F.content_type.in_({ContentType.TEXT, ContentType.PHOTO}))
async def receive_main_content(message: Message, state: FSMContext):
    await state.update_data(message=message)
    await state.set_state(Submission.waiting_for_contact)
    await send_and_store(message, "📱 Теперь укажите ваш контакт (например, @username или ссылка):", back_menu)

@router.message(Submission.waiting_for_contact, F.text)
async def receive_contact(message: Message, state: FSMContext):
    data = await state.get_data()
    user_msg = data["message"]
    contact = message.text

    caption = ""
    if user_msg.content_type == ContentType.TEXT:
        caption = user_msg.text + f"\n\n📞 Контакт: {contact}"
        await bot.send_message(CHANNEL_ID, caption)
    elif user_msg.content_type == ContentType.PHOTO:
        caption = (user_msg.caption or "") + f"\n\n📞 Контакт: {contact}"
        await bot.send_photo(CHANNEL_ID, photo=user_msg.photo[-1].file_id, caption=caption)

    update_send_time(message.from_user.id)
    await send_and_store(message, "✅ Заявка успешно отправлена в канал!", main_menu)
    await state.clear()

# --- Run Bot ---
if __name__ == "__main__":
    import asyncio
    async def main():
        await dp.start_polling(bot)
    asyncio.run(main())
