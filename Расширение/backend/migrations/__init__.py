"""Миграции БД. Запускаются из main.py:run_migrations() при старте.

Каждая миграция — отдельный модуль `<name>.py` с функцией `async def apply(conn)`.
Идемпотентны через таблицу `migrations_applied`.
"""
