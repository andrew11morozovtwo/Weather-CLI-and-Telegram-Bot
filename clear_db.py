#!/usr/bin/env python3
"""
Служебный скрипт для очистки базы данных бота.
Удаляет файл bot_messages.db для тестирования на чистой базе.
"""

import os

DB_NAME = "bot_messages.db"

def clear_database():
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)
        print(f"✅ База данных {DB_NAME} успешно удалена.")
    else:
        print(f"ℹ️  Файл {DB_NAME} не найден. База уже пустая.")

if __name__ == "__main__":
    print("Очистка базы данных бота...")
    clear_database()
    print("Готово! Теперь можно запускать бота на чистой базе.")
