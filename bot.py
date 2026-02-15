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

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
CHAT_ID = os.getenv("CHAT_ID")

CITIES_FILE = "selected_cities.json"
tf = TimezoneFinder()

# Настройка состояний
class AdminStates(StatesGroup):
    waiting_for_city = State()

def load_selected_cities():
    if os.path.exists(CITIES_FILE):
        with open(CITIES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return ["Moscow", "London", "Dubai"]

def save_selected_cities(cities):
    with open(CITIES_FILE, "w", encoding="utf-8") as f:
        json.dump(cities, f, ensure_ascii=False)

selected_cities = load_selected_cities()
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

def get_weather_data(city):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    logger.info(f"Запрос погоды для города: {city} по URL: {url.replace(WEATHER_API_KEY, 'HIDDEN')}")
    try:
        response = requests.get(url)
        logger.info(f"Ответ API для {city}: Статус {response.status_code}, Тело: {response.text}")
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        logger.error(f"Ошибка API для {city}: {e}")
        return None

def get_city_timezone(data):
    try:
        if 'coord' in data:
            lat = data['coord']['lat']
            lon = data['coord']['lon']
        elif 'city' in data and 'coord' in data['city']:
            lat = data['city']['coord']['lat']
            lon = data['city']['coord']['lon']
        else:
            return pytz.UTC
        tz_name = tf.timezone_at(lat=lat, lng=lon)
        return pytz.timezone(tz_name)
    except Exception as e:
        logger.error(f"Ошибка определения таймзоны: {e}")
        return pytz.UTC

async def send_weather_for_city(city_name):
    data = get_weather_data(city_name)
    if not data:
        return
    temp = data['main']['temp']
    desc = data['weather'][0]['description'].capitalize()
    text = f"☀️ **Ежедневный прогноз: {data['name']}** ☀️\n\n📍 Температура: {temp}°C\n📝 Состояние: {desc}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Прогноз на 12 часов", callback_data=f"fc_{city_name}")]
    ])
    try:
        await bot.send_message(CHAT_ID, text, reply_markup=kb, parse_mode="Markdown")
        logger.info(f"Отправлена погода для {city_name} в чат {CHAT_ID}")
    except Exception as e:
        logger.error(f"Ошибка отправки для {city_name}: {e}")

@dp.callback_query(lambda c: c.data.startswith('fc_'))
async def show_forecast(callback: CallbackQuery):
    city = callback.data.replace("fc_", "")
    url = f"http://api.openweathermap.org/data/2.5/forecast?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    try:
        response = requests.get(url)
        data = response.json()
        if response.status_code != 200:
            await callback.message.answer(f"❌ Город '{city}' не найден в базе прогнозов.")
            await callback.answer()
            return
        forecast_list = data['list']
        city_name = data['city']['name']
        tz = get_city_timezone(data['city'])
        now_local = datetime.now(tz)
        report = f"📅 **Прогноз для {city_name}:**\n"
        offsets = [0, 3, 6, 9, 12]
        points = []
        for item in forecast_list[:7]:
            points.append({
                "dt": item['dt'],
                "temp": item['main']['temp'],
                "desc": item['weather'][0]['description']
            })
        for offset in offsets:
            if offset == 0:
                target_time = now_local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            else:
                base_hour = now_local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                target_time = base_hour + timedelta(hours=offset)
            target_ts = target_time.timestamp()
            p1 = points[0]
            p2 = points[1]
            for j in range(len(points) - 1):
                if points[j]['dt'] <= target_ts <= points[j+1]['dt']:
                    p1 = points[j]
                    p2 = points[j+1]
                    break
            time_diff = p2['dt'] - p1['dt']
            if time_diff > 0:
                fraction = (target_ts - p1['dt']) / time_diff
                interp_temp = p1['temp'] + (p2['temp'] - p1['temp']) * fraction
            else:
                interp_temp = p1['temp']
            desc = p1['desc'] if (target_ts - p1['dt']) < (p2['dt'] - target_ts) else p2['desc']
            time_str = target_time.strftime("%H:%M")
            report += f"\n🕒 {time_str} | {interp_temp:.1f}°C | {desc.capitalize()}"
        await callback.message.answer(report, parse_mode="Markdown")
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка прогноза для {city}: {e}")
        await callback.answer("Произошла ошибка")

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID: return
    buttons = []
    for city in selected_cities:
        buttons.append([InlineKeyboardButton(text=f"❌ Удалить {city}", callback_data=f"del_{city}")])
    buttons.append([InlineKeyboardButton(text="➕ Добавить город", callback_data="add_city")])
    buttons.append([InlineKeyboardButton(text="🔄 Проверить сейчас", callback_data="test_all")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Управление городами:", reply_markup=kb)

@dp.callback_query()
async def process_callbacks(callback: CallbackQuery, state: FSMContext):
    global selected_cities
    if callback.data.startswith("del_"):
        city = callback.data.replace("del_", "")
        if city in selected_cities:
            selected_cities.remove(city)
            save_selected_cities(selected_cities)
            await callback.answer(f"Удален {city}")
            await admin_panel(callback.message)
    elif callback.data == "add_city":
        await state.set_state(AdminStates.waiting_for_city)
        await callback.message.answer("Пришлите название города:")
        await callback.answer()
    elif callback.data == "test_all":
        for city in selected_cities:
            await send_weather_for_city(city)
        await callback.answer("Тест запущен")

@dp.message(AdminStates.waiting_for_city)
async def process_add_city(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return
    city = message.text.strip()
    data = get_weather_data(city)
    if data:
        city_name = data['name']
        if city_name not in selected_cities:
            selected_cities.append(city_name)
            save_selected_cities(selected_cities)
            await message.answer(f"✅ Город {city_name} добавлен!")
        else:
            await message.answer(f"Город {city_name} уже в списке.")
        await state.clear()
        await admin_panel(message)
    else:
        await message.answer("❌ Город не найден. Попробуйте еще раз или напишите /cancel")

@dp.message(Command("cancel"))
async def cancel_action(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.")

@dp.message(Command("get_id"))
async def get_id(message: Message):
    await message.answer(f"ID чата: `{message.chat.id}`", parse_mode="Markdown")

@dp.message()
async def handle_msg(message: Message):
    pass

async def weather_scheduler():
    sent_today = {}
    while True:
        now_utc = datetime.now(pytz.UTC)
        current_date = now_utc.strftime("%Y-%m-%d")
        if current_date not in sent_today:
            sent_today[current_date] = []
        for city in selected_cities:
            if city in sent_today[current_date]:
                continue
            data = get_weather_data(city)
            if not data: continue
            tz = get_city_timezone(data)
            local_time = datetime.now(tz)
            if local_time.hour >= 8:
                await send_weather_for_city(city)
                sent_today[current_date].append(city)
                logger.info(f"Рассылка для {city} выполнена (местное время {local_time.strftime('%H:%M')})")
        await asyncio.sleep(60)

async def main():
    asyncio.create_task(weather_scheduler())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except:
        logger.info("Бот остановлен")
