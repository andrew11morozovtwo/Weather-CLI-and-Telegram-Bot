import asyncio
import os
import json
import logging
import requests
from datetime import datetime, timedelta
import pytz
from timezonefinder import TimezoneFinder
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

# Минимальное логирование только для критических ошибок
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

load_dotenv()

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
CHAT_ID = os.getenv("CHAT_ID")

CITIES_FILE = "selected_cities.json"
tf = TimezoneFinder()

class AdminStates(StatesGroup):
    waiting_for_city = State()

def load_cities():
    if os.path.exists(CITIES_FILE):
        with open(CITIES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return ["Moscow"]

def save_cities(cities):
    with open(CITIES_FILE, "w", encoding="utf-8") as f:
        json.dump(cities, f, ensure_ascii=False)

selected_cities = load_cities()
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

def get_weather(city, mode="weather"):
    url = f"http://api.openweathermap.org/data/2.5/{mode}?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    try:
        r = requests.get(url, timeout=10)
        return r.json() if r.status_code == 200 else None
    except: return None

def get_tz(data):
    try:
        c = data.get('coord') or data.get('city', {}).get('coord')
        return pytz.timezone(tf.timezone_at(lat=c['lat'], lng=c['lon']))
    except: return pytz.UTC

async def send_weather(city):
    d = get_weather(city)
    if not d: return
    text = f"☀️ **{d['name']}**: {d['main']['temp']}°C, {d['weather'][0]['description'].capitalize()}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 Прогноз 12ч", callback_data=f"fc_{city}")]])
    await bot.send_message(CHAT_ID, text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(lambda c: c.data.startswith('fc_'))
async def show_fc(callback: CallbackQuery):
    city = callback.data.replace("fc_", "")
    d = get_weather(city, "forecast")
    if not d: return
    
    tz = get_tz(d)
    now = datetime.now(tz)
    report = f"📅 **Прогноз: {d['city']['name']}**\n"
    
    points = [{"dt": i['dt'], "temp": i['main']['temp'], "desc": i['weather'][0]['description']} for i in d['list'][:7]]
    
    for off in [0, 3, 6, 9, 12]:
        target = now.replace(minute=0,second=0,microsecond=0) + timedelta(hours=off+1)
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
    
    await callback.message.answer(report, parse_mode="Markdown")
    await callback.answer()

@dp.message(Command("admin"))
async def admin(message: Message):
    if message.from_user.id != ADMIN_ID: return
    btns = [[InlineKeyboardButton(text=f"❌ {c}", callback_data=f"del_{c}")] for c in selected_cities]
    btns.append([InlineKeyboardButton(text="➕ Добавить", callback_data="add")])
    btns.append([InlineKeyboardButton(text="🔄 Тест", callback_data="test")])
    await message.answer("Админка:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query()
async def cb(callback: CallbackQuery, state: FSMContext):
    global selected_cities
    if callback.data.startswith("del_"):
        c = callback.data.replace("del_", "")
        if c in selected_cities:
            selected_cities.remove(c); save_cities(selected_cities)
            await admin(callback.message)
    elif callback.data == "add":
        await state.set_state(AdminStates.waiting_for_city)
        await callback.message.answer("Город:")
    elif callback.data == "test":
        for c in selected_cities: await send_weather(c)
    await callback.answer()

@dp.message(AdminStates.waiting_for_city)
async def add_c(message: Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        c = message.text.strip()
        d = get_weather(c)
        if d:
            name = d['name']
            if name not in selected_cities:
                selected_cities.append(name); save_cities(selected_cities)
                await message.answer(f"✅ {name} добавлен")
            await state.clear(); await admin(message)
        else: await message.answer("❌ Не найден")

async def scheduler():
    sent = {}
    while True:
        day = datetime.now().strftime("%Y-%m-%d")
        if day not in sent: sent[day] = []
        for c in selected_cities:
            if c not in sent[day]:
                d = get_weather(c)
                if d and datetime.now(get_tz(d)).hour >= 8:
                    await send_weather(c)
                    sent[day].append(c)
        await asyncio.sleep(60)

async def main():
    asyncio.create_task(scheduler())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
