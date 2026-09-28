"""
backend/modules/ — pluggable game integrations.

Каждый модуль — папка `modules/<id>/` с `manifest.yaml` и Python-имплементацией
ModuleAdapter из `_base.py`. Загружаются через `_loader.discover_modules()`
во время startup.

См. docs/MODULE_API.md (spec) и docs/MODULE_MIGRATION.md (план миграции
существующих RimWorld эндпоинтов из `backend/rimworld.py`).

Этап 3 PLATFORM_VISION roadmap — текущая работа.
"""
