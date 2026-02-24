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
import sqlite3

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

DB_NAME = "bot_messages.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                chat_id INTEGER,
                message_id INTEGER,
                delete_after DATETIME
            )
        """)
    logger.info("База данных инициализирована")

def register_message(chat_id, message_id):
    global delete_after_minutes
    delete_after = datetime.now() + timedelta(minutes=delete_after_minutes)
    delete_after_str = delete_after.isoformat()  # Конвертируем в строку для Python 3.12+
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT INTO messages (chat_id, message_id, delete_after) VALUES (?, ?, ?)",
            (chat_id, message_id, delete_after_str)
        )
    logger.info(f"Сообщение {message_id} зарегистрировано для удаления после {delete_after}")

async def delete_expired_messages():
    while True:
        try:
            now_str = datetime.now().isoformat()  # Конвертируем в строку для Python 3.12+
            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.execute(
                    "SELECT chat_id, message_id FROM messages WHERE delete_after <= ?",
                    (now_str,)
                )
                expired = cursor.fetchall()
                
                for chat_id, msg_id in expired:
                    try:
                        await bot.delete_message(chat_id, msg_id)
                        logger.info(f"Сообщение {msg_id} успешно удалено")
                    except Exception as e:
                        logger.warning(f"Не удалось удалить сообщение {msg_id}: {e}")
                    
                    # Удаляем запись из БД в любом случае
                    conn.execute(
                        "DELETE FROM messages WHERE chat_id = ? AND message_id = ?",
                        (chat_id, msg_id)
                    )
            await asyncio.sleep(30) # Проверка каждые 30 секунд
        except Exception as e:
            logger.error(f"Ошибка в цикле удаления: {e}")
            await asyncio.sleep(60)

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
CHAT_ID = os.getenv("CHAT_ID")

CITIES_FILE = "selected_cities.json"
tf = TimezoneFinder()

# Настройка состояний
class AdminStates(StatesGroup):
    waiting_for_city = State()
    waiting_for_delete_time = State()

def load_config():
    if os.path.exists(CITIES_FILE):
        with open(CITIES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Поддержка старого формата (просто список городов)
            if isinstance(data, list):
                return {"cities": data, "delete_after_minutes": 720}  # 12 часов по умолчанию
            return data
    return {"cities": ["Moscow", "London", "Dubai"], "delete_after_minutes": 720}

def save_config(config):
    with open(CITIES_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def format_delete_time(minutes):
    """Форматирует минуты в читаемый формат 'часы:минуты'"""
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}:{mins:02d}"

config = load_config()
selected_cities = config.get("cities", [])
delete_after_minutes = config.get("delete_after_minutes", 720)
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
        msg = await bot.send_message(CHAT_ID, text, reply_markup=kb, parse_mode="Markdown")
        register_message(msg.chat.id, msg.message_id)
        logger.info(f"Отправлена погода для {city_name} в чат {CHAT_ID}")
    except Exception as e:
        logger.error(f"Ошибка отправки для {city_name}: {e}")

@dp.callback_query(lambda c: c.data.startswith('fc_'))
async def show_forecast(callback: CallbackQuery):
    # Сразу отвечаем на callback, чтобы избежать timeout
    await callback.answer("Обрабатываю запрос...")
    
    city = callback.data.replace("fc_", "")
    url = f"http://api.openweathermap.org/data/2.5/forecast?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    try:
        response = requests.get(url)
        data = response.json()
        if response.status_code != 200:
            await callback.message.answer(f"❌ Город '{city}' не найден в базе прогнозов.")
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
        
        # Отправляем прогноз пользователю в личные сообщения
        try:
            msg = await bot.send_message(callback.from_user.id, report, parse_mode="Markdown")
            register_message(msg.chat.id, msg.message_id)
            logger.info(f"Прогноз для {city} отправлен пользователю {callback.from_user.id}")
        except Exception as e:
            logger.warning(f"Не удалось отправить прогноз пользователю {callback.from_user.id}: {e}")
            # Если не получилось отправить в личку, отправляем в чат
            try:
                msg = await callback.message.answer("❌ Пожалуйста, сначала напишите боту в личные сообщения!\n\n" + report, parse_mode="Markdown")
                register_message(msg.chat.id, msg.message_id)
            except Exception as e2:
                logger.error(f"Ошибка отправки прогноза в чат: {e2}")
    except Exception as e:
        logger.error(f"Ошибка прогноза для {city}: {e}")
        try:
            await callback.message.answer("❌ Произошла ошибка при получении прогноза.")
        except:
            pass  # Если и это не получилось, просто игнорируем

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID: return
    buttons = []
    for city in selected_cities:
        buttons.append([InlineKeyboardButton(text=f"❌ Удалить {city}", callback_data=f"del_{city}")])
    buttons.append([InlineKeyboardButton(text="➕ Добавить город", callback_data="add_city")])
    buttons.append([InlineKeyboardButton(text="🔄 Проверить сейчас", callback_data="test_all")])
    buttons.append([InlineKeyboardButton(text=f"⚙️ Время удаления: {format_delete_time(delete_after_minutes)}", callback_data="set_delete_time")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Управление городами:", reply_markup=kb)

@dp.callback_query()
async def process_callbacks(callback: CallbackQuery, state: FSMContext):
    global selected_cities, config
    if callback.data.startswith("del_"):
        city = callback.data.replace("del_", "")
        if city in selected_cities:
            selected_cities.remove(city)
            config["cities"] = selected_cities
            save_config(config)
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
    elif callback.data == "set_delete_time":
        await state.set_state(AdminStates.waiting_for_delete_time)
        await callback.message.answer(
            "⚙️ **Настройка времени удаления сообщений**\n\n"
            "Введите время в формате **часы:минуты**\n"
            "Пример: `12:30` (12 часов 30 минут)\n"
            "Пример: `0:15` (15 минут)\n"
            "Пример: `24:0` (24 часа)\n\n"
            "Текущее значение: " + format_delete_time(delete_after_minutes),
            parse_mode="Markdown"
        )
        await callback.answer()

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
            config["cities"] = selected_cities
            save_config(config)
            await message.answer(f"✅ Город {city_name} добавлен!")
        else:
            await message.answer(f"Город {city_name} уже в списке.")
        await state.clear()
        await admin_panel(message)
    else:
        await message.answer("❌ Город не найден. Попробуйте еще раз или напишите /cancel")

@dp.message(AdminStates.waiting_for_delete_time)
async def process_delete_time(message: Message, state: FSMContext):
    global delete_after_minutes, config
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return
    
    time_str = message.text.strip()
    try:
        # Парсим формат "часы:минуты"
        parts = time_str.split(":")
        if len(parts) != 2:
            raise ValueError("Неверный формат")
        
        hours = int(parts[0])
        minutes = int(parts[1])
        
        if hours < 0 or minutes < 0 or minutes >= 60:
            raise ValueError("Неверные значения")
        
        total_minutes = hours * 60 + minutes
        if total_minutes == 0:
            await message.answer("❌ Время не может быть нулевым. Попробуйте еще раз.")
            return
        
        delete_after_minutes = total_minutes
        config["delete_after_minutes"] = total_minutes
        save_config(config)
        
        await message.answer(
            f"✅ Время удаления установлено: **{format_delete_time(total_minutes)}**\n"
            f"Сообщения будут удаляться через {hours} ч. {minutes} мин.",
            parse_mode="Markdown"
        )
        await state.clear()
        await admin_panel(message)
    except (ValueError, IndexError):
        await message.answer(
            "❌ Неверный формат!\n\n"
            "Используйте формат: **часы:минуты**\n"
            "Примеры:\n"
            "• `12:30` - 12 часов 30 минут\n"
            "• `0:15` - 15 минут\n"
            "• `24:0` - 24 часа\n\n"
            "Попробуйте еще раз или напишите /cancel",
            parse_mode="Markdown"
        )

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
    city_timezones = {}  # Кэш часовых поясов городов
    while True:
        now_utc = datetime.now(pytz.UTC)
        current_date = now_utc.strftime("%Y-%m-%d")
        if current_date not in sent_today:
            sent_today[current_date] = []
        
        for city in selected_cities:
            if city in sent_today[current_date]:
                continue
            
            # Сначала проверяем время по кэшированному часовому поясу
            if city in city_timezones:
                tz = city_timezones[city]
                local_time = datetime.now(tz)
                # Если не 8:00, пропускаем запрос к API
                if local_time.hour != 8:
                    continue
            
            # Только если время подходящее или часовой пояс неизвестен - делаем запрос
            data = get_weather_data(city)
            if not data: 
                continue
            
            # Сохраняем часовой пояс в кэш
            tz = get_city_timezone(data)
            city_timezones[city] = tz
            local_time = datetime.now(tz)
            
            # Отправляем только если время между 8:00 и 8:59
            if local_time.hour == 8:
                await send_weather_for_city(city)
                sent_today[current_date].append(city)
                logger.info(f"Рассылка для {city} выполнена (местное время {local_time.strftime('%H:%M')})")
        await asyncio.sleep(60)

async def main():
    init_db()
    asyncio.create_task(weather_scheduler())
    asyncio.create_task(delete_expired_messages())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except:
        logger.info("Бот остановлен")
