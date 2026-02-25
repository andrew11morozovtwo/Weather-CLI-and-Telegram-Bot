import asyncio
import os
import json
import logging
import requests
import sqlite3
from datetime import datetime, timedelta
import pytz
from timezonefinder import TimezoneFinder
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

load_dotenv()

DB_NAME = "bot_messages.db"
CITIES_FILE = "selected_cities.json"

class AdminStates(StatesGroup):
    waiting_for_city = State()
    waiting_for_delete_time = State()

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS messages (chat_id INTEGER, message_id INTEGER, delete_after TEXT)")

def register_message(chat_id, message_id):
    global delete_after_minutes
    delete_after = (datetime.now() + timedelta(minutes=delete_after_minutes)).isoformat()
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT INTO messages (chat_id, message_id, delete_after) VALUES (?, ?, ?)", (chat_id, message_id, delete_after))

async def delete_expired_messages():
    while True:
        try:
            now_str = datetime.now().isoformat()
            with sqlite3.connect(DB_NAME) as conn:
                expired = conn.execute("SELECT chat_id, message_id FROM messages WHERE delete_after <= ?", (now_str,)).fetchall()
                for chat_id, msg_id in expired:
                    try:
                        await bot.delete_message(chat_id, msg_id)
                    except:
                        pass
                    conn.execute("DELETE FROM messages WHERE chat_id = ? AND message_id = ?", (chat_id, msg_id))
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Ошибка удаления: {e}")
            await asyncio.sleep(60)

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
CHAT_ID = os.getenv("CHAT_ID")

tf = TimezoneFinder()

def load_config():
    if os.path.exists(CITIES_FILE):
        with open(CITIES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return {"cities": data, "delete_after_minutes": 720}
            return data
    return {"cities": ["Moscow"], "delete_after_minutes": 720}

def save_config(cfg):
    with open(CITIES_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False)

def fmt_time(mins):
    return f"{mins // 60}:{mins % 60:02d}"

config = load_config()
selected_cities = config.get("cities", [])
delete_after_minutes = config.get("delete_after_minutes", 720)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

def get_weather(city):
    try:
        r = requests.get(f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru", timeout=10)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def get_tz(data):
    try:
        c = data.get('coord') or data.get('city', {}).get('coord')
        return pytz.timezone(tf.timezone_at(lat=c['lat'], lng=c['lon']))
    except:
        return pytz.UTC

async def send_weather(city):
    d = get_weather(city)
    if not d:
        return
    text = f"☀️ **{d['name']}**: {d['main']['temp']}°C, {d['weather'][0]['description'].capitalize()}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 Прогноз 12ч", callback_data=f"fc_{city}")]])
    try:
        msg = await bot.send_message(CHAT_ID, text, reply_markup=kb, parse_mode="Markdown")
        register_message(msg.chat.id, msg.message_id)
    except:
        pass

@dp.callback_query(lambda c: c.data.startswith('fc_'))
async def show_fc(callback: CallbackQuery):
    await callback.answer("Обрабатываю...")
    city = callback.data.replace("fc_", "")
    try:
        r = requests.get(f"http://api.openweathermap.org/data/2.5/forecast?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru", timeout=10)
        d = r.json()
        if r.status_code != 200:
            return
        tz = get_tz(d['city'])
        now = datetime.now(tz)
        report = f"📅 **{d['city']['name']}:**\n"
        points = [{"dt": i['dt'], "temp": i['main']['temp'], "desc": i['weather'][0]['description']} for i in d['list'][:7]]
        for off in [0, 3, 6, 9, 12]:
            target = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=off+1))
            ts = target.timestamp()
            p1, p2 = points[0], points[1]
            for j in range(len(points)-1):
                if points[j]['dt'] <= ts <= points[j+1]['dt']:
                    p1, p2 = points[j], points[j+1]
                    break
            diff = p2['dt'] - p1['dt']
            temp = p1['temp'] + (p2['temp'] - p1['temp']) * ((ts - p1['dt']) / diff) if diff > 0 else p1['temp']
            desc = p1['desc'] if (ts - p1['dt']) < (p2['dt'] - ts) else p2['desc']
            report += f"\n🕒 {target.strftime('%H:%M')} | {temp:.1f}°C | {desc.capitalize()}"
        try:
            msg = await bot.send_message(callback.from_user.id, report, parse_mode="Markdown")
            register_message(msg.chat.id, msg.message_id)
        except:
            try:
                msg = await callback.message.answer(report, parse_mode="Markdown")
                register_message(msg.chat.id, msg.message_id)
            except:
                pass
    except:
        pass

@dp.message(Command("admin"))
async def admin(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    btns = [[InlineKeyboardButton(text=f"❌ {c}", callback_data=f"del_{c}")] for c in selected_cities]
    btns.extend([
        [InlineKeyboardButton(text="➕ Добавить", callback_data="add_city")],
        [InlineKeyboardButton(text="🔄 Тест", callback_data="test_all")],
        [InlineKeyboardButton(text=f"⚙️ {fmt_time(delete_after_minutes)}", callback_data="set_time")]
    ])
    await msg.answer("Админка:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query()
async def cb(callback: CallbackQuery, state: FSMContext):
    global selected_cities, config, delete_after_minutes
    if callback.data.startswith("del_"):
        c = callback.data.replace("del_", "")
        if c in selected_cities:
            selected_cities.remove(c)
            config["cities"] = selected_cities
            save_config(config)
            await admin(callback.message)
    elif callback.data == "add_city":
        await state.set_state(AdminStates.waiting_for_city)
        await callback.message.answer("Город:")
    elif callback.data == "test_all":
        for c in selected_cities:
            await send_weather(c)
    elif callback.data == "set_time":
        await state.set_state(AdminStates.waiting_for_delete_time)
        await callback.message.answer(f"Время (ч:м, пример: 12:30):\nТекущее: {fmt_time(delete_after_minutes)}")
    await callback.answer()

@dp.message(AdminStates.waiting_for_city)
async def add_city(msg: Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID:
        await state.clear()
        return
    d = get_weather(msg.text.strip())
    if d:
        name = d['name']
        if name not in selected_cities:
            selected_cities.append(name)
            config["cities"] = selected_cities
            save_config(config)
            await msg.answer(f"✅ {name}")
        await state.clear()
        await admin(msg)
    else:
        await msg.answer("❌ Не найден")

@dp.message(AdminStates.waiting_for_delete_time)
async def set_time(msg: Message, state: FSMContext):
    global delete_after_minutes, config
    if msg.from_user.id != ADMIN_ID:
        await state.clear()
        return
    try:
        parts = msg.text.strip().split(":")
        h, m = int(parts[0]), int(parts[1])
        if h < 0 or m < 0 or m >= 60:
            raise ValueError
        total = h * 60 + m
        if total == 0:
            await msg.answer("❌ Не может быть 0")
            return
        delete_after_minutes = total
        config["delete_after_minutes"] = total
        save_config(config)
        await msg.answer(f"✅ {fmt_time(total)}")
        await state.clear()
        await admin(msg)
    except:
        await msg.answer("❌ Формат: ч:м (12:30)")

@dp.message(Command("get_id"))
async def get_id(msg: Message):
    await msg.answer(f"ID: `{msg.chat.id}`", parse_mode="Markdown")

@dp.message()
async def handle(msg: Message):
    pass

async def scheduler():
    sent = {}
    tz_cache = {}
    while True:
        day = datetime.now().strftime("%Y-%m-%d")
        if day not in sent:
            sent[day] = []
        for city in selected_cities:
            if city in sent[day]:
                continue
            if city in tz_cache:
                if datetime.now(tz_cache[city]).hour != 8:
                    continue
            d = get_weather(city)
            if not d:
                continue
            tz = get_tz(d)
            tz_cache[city] = tz
            if datetime.now(tz).hour == 8:
                await send_weather(city)
                sent[day].append(city)
        await asyncio.sleep(60)

async def main():
    init_db()
    asyncio.create_task(scheduler())
    asyncio.create_task(delete_expired_messages())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except:
        pass
