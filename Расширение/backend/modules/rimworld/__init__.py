"""
modules/rimworld/ — RimWorld game module (этап 3 PLATFORM_VISION roadmap).

ТЕКУЩИЙ СТАТУС: foundation в этапе. Manifest и adapter-stub созданы.
Реальные routes (~1981 строка) ещё в `backend/rimworld.py` — миграция
поэтапная, см. docs/MODULE_MIGRATION.md.

Когда миграция завершится:
  - rimworld.py исчезнет (либо станет shim-ом для legacy-эндпоинтов)
  - все RimWorld-specific routes / handlers / DB-логика — здесь
  - Manifest публикует capabilities; ядро только знает Module API
  - Bannerlord / Minecraft модули добавляются параллельно тем же
    интерфейсом (см. project_bannerlord_module.md)
"""
from ._adapter import RimWorldAdapter

__all__ = ["RimWorldAdapter"]
