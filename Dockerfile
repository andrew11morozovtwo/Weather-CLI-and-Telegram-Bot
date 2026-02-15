# Используем легковесный образ Python
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем системные зависимости (если понадобятся для сборки некоторых пакетов)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем Python-пакеты без кэширования для уменьшения размера
RUN pip install --no-cache-dir -r requirements.txt

# Копируем только необходимые файлы проекта
COPY bot1.py .
COPY .env .
# Копируем файл городов, если он существует (или он создастся сам)
COPY selected_cities.json* ./

# Команда для запуска бота
CMD ["python", "bot1.py"]
