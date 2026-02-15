import requests
import sys
import argparse
import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

def get_weather(city, api_key):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric&lang=ru"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        city_name = data['name']
        country = data['sys']['country']
        temp = data['main']['temp']
        description = data['weather'][0]['description']
        humidity = data['main']['humidity']
        wind_speed = data['wind']['speed']
        
        return {
            "city": city_name,
            "country": country,
            "temp": temp,
            "description": description,
            "humidity": humidity,
            "wind_speed": wind_speed
        }
        
    except requests.exceptions.HTTPError as http_err:
        if response.status_code == 404:
            return "not_found"
        elif response.status_code == 401:
            return "invalid_key"
        else:
            return f"error: {http_err}"
    except Exception as err:
        return f"error: {err}"

def display_weather(data):
    # Эмодзи для разных состояний погоды
    weather_icons = {
        "ясно": "☀️",
        "облачно": "☁️",
        "пасмурно": "☁️",
        "дождь": "🌧️",
        "гроза": "⛈️",
        "снег": "❄️",
        "туман": "🌫️"
    }
    
    # Подбор иконки
    icon = "🌡️"
    for key, value in weather_icons.items():
        if key in data['description'].lower():
            icon = value
            break

    from datetime import datetime
    current_time = datetime.now().strftime("%H:%M:%S")

    print(f"\n🌍 Погода в городе {data['city']} ({data['country']}):")
    print(f"🕒 Время запроса: {current_time}")
    print("-" * 30)
    print(f"{icon} Температура: {data['temp']}°C")
    print(f"📝 Состояние: {data['description'].capitalize()}")
    print(f"💧 Влажность: {data['humidity']}%")
    print(f"💨 Скорость ветра: {data['wind_speed']} м/с")
    print("-" * 30)

def get_forecast(city, api_key):
    # API для прогноза на 5 дней с шагом 3 часа
    url = f"http://api.openweathermap.org/data/2.5/forecast?q={city}&appid={api_key}&units=metric&lang=ru"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        # Берем первые 8 записей (8 * 3 часа = 24 часа)
        forecast_list = data['list'][:8]
        results = []
        for item in forecast_list:
            results.append({
                "time": item['dt_txt'],
                "temp": item['main']['temp'],
                "description": item['weather'][0]['description']
            })
        return results
    except Exception as err:
        return f"error: {err}"

def display_forecast(forecast_data, city_name):
    print(f"\n📅 Прогноз на ближайшие 24 часа для {city_name}:")
    print("-" * 45)
    print(f"{'Время':<20} | {'Темп.':<7} | {'Состояние'}")
    print("-" * 45)
    for item in forecast_data:
        # Форматируем время из "2026-02-15 15:00:00" в "15:00"
        time_short = item['time'].split(" ")[1][:5]
        print(f"{time_short:<20} | {item['temp']:>5}°C | {item['description'].capitalize()}")
    print("-" * 45)

def main():
    # Загружаем переменные из .env файла
    load_dotenv()
    api_key = os.getenv("OPENWEATHER_API_KEY", "80026e9526188e40428d011d87e07833")

    print("=== Программа Погода 🌦️ ===")

    while True:
        city_input = input("\nКакой город вас интересует? (или 'выход' для завершения): ").strip()
        
        if city_input.lower() in ['выход', 'exit', 'quit', 'stop']:
            print("До свидания!")
            break

        if not city_input:
            continue

        # Предварительная проверка города (делаем запрос)
        result = get_weather(city_input, api_key)

        if result == "not_found":
            print(f"❌ Ошибка: Город '{city_input}' не найден. Попробуйте еще раз.")
            continue
        elif result == "invalid_key":
            print("❌ Ошибка: Неверный API ключ. Проверьте файл .env.")
            break
        elif isinstance(result, str) and result.startswith("error:"):
            print(f"❌ Произошла ошибка: {result}")
            continue

        # Подтверждение города
        confirm = input(f"Вы имели в виду город {result['city']} ({result['country']})? (да/нет): ").strip().lower()
        
        if confirm in ['да', 'д', 'yes', 'y']:
            display_weather(result)
            
            # Добавляем предложение прогноза
            show_forecast = input("\nПоказать прогноз на ближайшие 24 часа? (да/нет): ").strip().lower()
            if show_forecast in ['да', 'д', 'yes', 'y']:
                forecast = get_forecast(city_input, api_key)
                if isinstance(forecast, list):
                    display_forecast(forecast, result['city'])
                else:
                    print(f"❌ Не удалось получить прогноз: {forecast}")
        else:
            print("Хорошо, давайте попробуем другой город.")
            continue

        # Предложение выбрать другой город
        again = input("Хотите узнать погоду в другом городе? (да/нет): ").strip().lower()
        if again not in ['да', 'д', 'yes', 'y']:
            print("Спасибо за использование! До свидания!")
            break

if __name__ == "__main__":
    main()

if __name__ == "__main__":
    main()
