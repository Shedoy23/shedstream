"""
modules/bannerlord/ — Mount & Blade II: Bannerlord game module.

СТАТУС: scaffold (этап 3 step 6.c). Тонкий stub для архитектурной валидации:
если этот модуль загружается, регистрируется и его endpoints отдают данные
без core-кодовых изменений — значит Game Bridge SDK действительно game-agnostic.

Реальная имплементация:
  - C# submodule в Bannerlord (BLT-fork или native): ~3-5 недель работы
  - Расширенный _adapter.py (handle_event для hero.* events): ~200-400 строк
  - Полный план: memory/project_bannerlord_module.md

См. ARCHITECTURE.md §6.2 (recipe «Как добавить новый game module»).
"""
from ._adapter import BannerlordAdapter

__all__ = ["BannerlordAdapter"]
