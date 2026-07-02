# ShedColony — установка (Minecraft)

Мод-коннектор для **Minecraft 1.21.1 (NeoForge)**. Даёт зрителям твоего Twitch-стрима
управлять своими колонистами в MineColonies за крустики.

## Нужно
- Minecraft **1.21.1** + **NeoForge**
- Мод **MineColonies** (той же версии)
- `shedcolony-0.1.0.jar` (кнопка «Скачать» на shedoy23.ru)

## Шаги
1. Скачай `shedcolony-0.1.0.jar` и положи в папку `mods/` своего **сервера** (или клиента)
   рядом с MineColonies.
2. Запусти сервер один раз — мод создаст файл `config/shedcolony.json`.
3. Открой `config/shedcolony.json` и впиши два значения из своего дашборда
   (**shedoy23.ru/streamer** → залогинься через Twitch → выбери игру Minecraft → скопируй токен):
   ```json
   {
     "backend_url": "https://shedoy23.ru",
     "module_token": "<ТВОЙ ТОКЕН С ДАШБОРДА>",
     "channel_id": <ТВОЙ TWITCH CHANNEL ID>,
     "poll_interval_ms": 3000
   }
   ```
4. Перезапусти сервер. В логе должно появиться `net ON — backend=https://shedoy23.ru`.
5. Основай колонию (поставь ратушу MineColonies) — зрители смогут управлять колонистами
   из расширения на твоём канале.

## Целостность
Сверь скачанный файл: он должен совпасть с `shedcolony-0.1.0.jar.sha256`.
```
sha256sum shedcolony-0.1.0.jar
```

## Помощь
Что-то не так — пиши в Telegram: **@ttvshedoy23**
