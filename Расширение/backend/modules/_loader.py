"""
modules/_loader.py — discovery + регистрация модулей при startup.

Сканирует `backend/modules/<id>/manifest.yaml`, парсит, инстанциирует
соответствующий ModuleAdapter (если найдён в `<id>/__init__.py`) и кладёт
в реестр `_REGISTRY: Dict[id, ModuleAdapter]`.

Использование (main.py startup):
    from modules._loader import discover_modules, get_module
    discover_modules()
    rimworld = get_module("rimworld")  # → RimWorldAdapter instance

Минимальная имплементация: YAML manifest парсится через PyYAML (если есть)
или через простой ручной парсер. Для текущего MVP — PyYAML.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Dict, List, Optional

from ._base import ModuleAdapter, ModuleManifest


_REGISTRY: Dict[str, ModuleAdapter] = {}


def _modules_dir() -> Path:
    """Абсолютный путь к этой папке."""
    return Path(__file__).parent.absolute()


def load_manifest(manifest_path: Path) -> ModuleManifest:
    """Прочитать manifest.yaml в ModuleManifest.

    Для минимизации зависимостей: попытаемся через PyYAML, fallback на
    простой парсер для базовых типов (наш формат не использует якоря/теги).
    """
    text = manifest_path.read_text(encoding="utf-8")
    data = _parse_yaml(text)
    extensions = data.get("extensions") or {}
    return ModuleManifest(
        id=data["id"],
        version=data.get("version", "0.0.1"),
        core_api_version=data.get("core_api_version", ">=1.0.0"),
        display_name=data.get("display_name", data["id"]),
        description=data.get("description", ""),
        icon=data.get("icon"),
        events=list(data.get("events") or []),
        actions=list(data.get("actions") or []),
        extension_events=list(extensions.get("events") or []),
        extension_actions=list(extensions.get("actions") or []),
        catalogs=list(data.get("catalogs") or []),
        ui_slots=list(data.get("ui_slots") or []),
    )


def _parse_yaml(text: str) -> dict:
    """Парсер manifest.yaml. PyYAML предпочтительнее, но не обязателен."""
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        return _parse_yaml_minimal(text)


def _parse_yaml_minimal(text: str) -> dict:
    """Минимальный fallback для нашего формата manifest'ов:
    - top-level scalar key: value
    - top-level list key: with `- item` блоком
    - один уровень вложенности (extensions.events / extensions.actions)
    Не поддерживает: якоря, теги, multiline literals, complex maps.
    Достаточно для нашего manifest.yaml шаблона.
    """
    result: dict = {}
    current_list_key: Optional[str] = None
    current_nested_key: Optional[str] = None
    current_nested_list: Optional[str] = None
    nested_dict: dict = {}

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        # Top-level list item (- foo)
        if line.startswith("  - "):
            item = line[4:].strip().strip('"\'')
            if current_nested_list and current_nested_key:
                nested_dict.setdefault(current_nested_list, []).append(item)
            elif current_list_key:
                result.setdefault(current_list_key, []).append(item)
            continue
        if line.startswith("    - "):
            item = line[6:].strip().strip('"\'')
            if current_nested_list and current_nested_key:
                nested_dict.setdefault(current_nested_list, []).append(item)
            continue
        # 2-space indent ключ под extensions
        if line.startswith("  ") and ":" in line and not line.lstrip().startswith("-"):
            key, _, val = line.lstrip().partition(":")
            key = key.strip()
            val = val.strip().strip('"\'')
            if current_nested_key:
                if val:
                    nested_dict[key] = val
                    current_nested_list = None
                else:
                    current_nested_list = key
            continue
        # Top-level key: value or key:
        if ":" in line and not line.startswith(" "):
            # Закрываем предыдущий nested если был
            if current_nested_key:
                result[current_nested_key] = nested_dict
                nested_dict = {}
                current_nested_key = None
                current_nested_list = None
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"\'')
            if val:
                result[key] = val
                current_list_key = None
            else:
                # Может быть top-level list (events: \n  - foo) или nested map (extensions: \n  events: \n)
                if key == "extensions":
                    current_nested_key = key
                    current_list_key = None
                else:
                    current_list_key = key
                    current_nested_key = None
    if current_nested_key:
        result[current_nested_key] = nested_dict
    return result


def discover_modules() -> Dict[str, ModuleAdapter]:
    """Просканировать `modules/<id>/`, загрузить manifest'ы и инстанциировать
    adapter'ы. Идемпотентно — повторный вызов чистит реестр и пере-сканирует.
    """
    _REGISTRY.clear()
    base = _modules_dir()
    discovered: List[str] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("_") or child.name.startswith("."):
            continue
        manifest_path = child / "manifest.yaml"
        if not manifest_path.exists():
            continue
        try:
            manifest = load_manifest(manifest_path)
        except Exception as e:
            print(f"⚠️  Module '{child.name}': failed to load manifest: {e}")
            continue

        # Дёрнуть подмодуль и найти Adapter-класс. Конвенция: класс
        # экспортируется в __init__.py + он наследник ModuleAdapter.
        try:
            mod = importlib.import_module(f"modules.{child.name}")
        except Exception as e:
            print(f"⚠️  Module '{child.name}': import failed: {e}")
            continue

        adapter_cls = None
        for attr in dir(mod):
            obj = getattr(mod, attr)
            if (isinstance(obj, type)
                    and issubclass(obj, ModuleAdapter)
                    and obj is not ModuleAdapter):
                adapter_cls = obj
                break
        if not adapter_cls:
            print(f"⚠️  Module '{child.name}': no ModuleAdapter subclass exported")
            continue

        try:
            adapter = adapter_cls(manifest)
        except Exception as e:
            print(f"⚠️  Module '{child.name}': adapter __init__ failed: {e}")
            continue
        _REGISTRY[manifest.id] = adapter
        discovered.append(manifest.id)

    print(f"✅ Modules discovered: {discovered}")
    return _REGISTRY


def get_module(module_id: str) -> Optional[ModuleAdapter]:
    return _REGISTRY.get(module_id)


def list_modules() -> List[ModuleAdapter]:
    return list(_REGISTRY.values())
