# Pets v3 — pixel-art overhaul (chat handoff)

**Назначение:** handoff для продолжения работы над **визуальным обновлением Pets**
(v2 emoji-blob → v3 pixel-art chibi character + PixelLab pipeline).
**Last updated:** 2026-05-24 (после deploy в прод + overlay walking polish).

---

## TL;DR

Pets v2 (sprint 5.21-5.22) — smooth SVG blob creature + 20 emoji items в БД.
Концептуально OK, но emoji-ceiling достигнут, плюс эстетика generic.

**v3 цель:** заменить blob на pixel-art chibi character (PixelLab-generated),
а 20 emoji items — на pixel-art items в том же стиле. Live-extension эстетика
из «just another Twitch extension» → «curated indie-game vibe».

**Current state (2026-05-24, после деплоя):**
- ✅ Character (kimono/underwear, 8 directions) — В ПРОДЕ
- ✅ M37 миграция — В ПРОДЕ (catalog wiped, mythic + png_path добавлены)
- ✅ Skin items (skin_kimono, skin_underwear) — В МАГАЗИНЕ, юзер может купить
- ✅ Overlay: pet 2× размер + direction-aware walking + bob — В ПРОДЕ
- 🟡 29 themed items — ЖДЁМ PixelLab subscription (Tier 1 $12/мес, завтра)

---

## Что сделано в этой сессии (CHRONO)

### Frontend visual rebuild
- ✅ **PixelLab character скопирован в репо:**
  - `frontend/pet-assets/v2/kimono/{south,south-east,east,north-east,north,north-west,west,south-west}.png`
  - `frontend/pet-assets/v2/underwear/{...}.png`
  - 16 PNG sprites @ 104×104, image-rendering: pixelated
- ✅ **pet-stage.js переписан под PNG-creature:**
  - `_buildCreatureSvg()` → `_buildCreatureImg(variant, direction)`
  - Опции `renderHtml(pet, equipped, {variant, direction, size})`
  - Backward-compat: `CREATURE_SVG` экспорт возвращает img-tag
  - Public API дополнен: `PetStage.buildCreatureImg`, `PetStage.VARIANTS`, `PetStage.DIRECTIONS`
- ✅ **Variant swap через equipped body:** если `equipped.body.item_id`
  начинается с `skin_` → меняет character variant (`skin_kimono` → kimono),
  body НЕ рендерится как overlay-слой (он уже встроен в creature).
- ✅ **Emoji fallback СТРИПНУТ** в `_renderItem()`:
  - Items с одним лишь `emoji:` полем silently не рендерятся
  - Только `svg_path` или `png_path` → render
- ✅ **Slot CSS:** full overlay 100%×100% per slot, item сам себя позиционирует.

### Backend
- ✅ **M37 миграция написана + захук'ана + ВЫПОЛНЕНА в проде:**
  - DELETE FROM pet_purchases, pet_equipped, pet_inventory, pets (clean slate)
  - DROP & rebuild pet_catalog с `mythic` в CHECK rarity + `png_path TEXT` колонкой
  - Hooked в `main.py:run_migrations()` после M36
- ✅ **Hot-fix static mount в main.py:**
  ```python
  _pet_assets_path = os.path.join(FRONTEND_PATH, "pet-assets")
  if os.path.exists(_pet_assets_path):
      app.mount("/pet-assets", StaticFiles(directory=_pet_assets_path),
                name="pet-assets")
  ```
  (без этого 404 на `/pet-assets/v2/.../south.png` через HTTPS)
- ✅ **Skin items добавлены в каталог:** `skin_kimono`, `skin_underwear`
  (rare, обе по 100 bits, доступны юзерам)
- ✅ **Pet shedoy23 вылупился вручную** (`UPDATE pets SET pet_type='chick'`)
  потому что hatch триггерится первым item purchase, а каталог был пуст.

### Overlay polish (post-deploy)
- ✅ **2× размер:** `--pet-stage-size` default 64px → 128px.
- ✅ **Direction-aware walking:**
  - Stacked imgs: south (creature) + east + west (overlays)
  - Opacity-keyframes свопят кадры синхронно с pet-walk position
  - При `dir = -1` (pet идёт первой ногой влево) — JS свопает src
    у east/west img'ов, чтобы спрайт всегда матчил направление
- ✅ **Bob во время ходьбы:** translateY(-5px) ↔ 0 чередуется
  каждые 2.5% цикла = 5 «шагов» на одну ногу путешествия
- ✅ **No-overlap fix:** south creature opacity:0 во время walking-фаз
  (30-50% и 80-100%) — нет наложения с east/west overlay
- ✅ **Slowdown:** cycle duration 54-90s → **90-150s** (одна нога 18-30s)

### Deployment
- ✅ Backend `main.py` + M37 — задеплоено через scp+supervisorctl restart
- ✅ Frontend pet-stage.js, viewer.css, overlay.html, mobile.html,
  extension.html — задеплоено
- ✅ Pet-assets PNG'и (16 файлов) — на проде
- ✅ Cache-bust: `pet-stage.js?v=20260524a` в трёх HTML'ах

---

## Decisions taken (DON'T REVISIT)

- **Strategy**: full replacement (character + items pixel-art)
- **Rarity**: добавлен `mythic` в CHECK constraint (M37 table rebuild)
- **Default variant**: `kimono` (одетый), `underwear` опциональный skin
- **PixelLab tier**: Tier 1 ($12/мес, 2000 credits/мес) — оплата завтра
- **Refund**: НЕ нужен (PETS_BITS_REQUIRED=False, mock mode, реальных bits никто не платил)
- **Emoji fallback**: УБРАН полностью (pixel + emoji = диссонанс)
- **Body splitting**: НЕ делаем (PixelLab edit'ит ЦЕЛИКОМ, outline-fragility)
- **Items как overlay vs baked-in**: финальное решение зависит от PixelLab capability check (см. ниже)

---

## Что НЕ сделано (открытые вопросы для завтра)

### Pending decisions (юзер думает)

1. **PixelLab workflow check** — выяснить умеет ли он:
   - (a) Standalone item generation с transparent BG → items как overlay layers
   - (b) Только character-edit (item baked-in) → one-sprite-per-equip, combos невозможны

   Архитектура render-flow зависит от ответа. Если (a) — продолжаем
   текущий slot-overlay подход; если (b) — combos в коде заменяем
   на готовые «character с шапкой» сприты, что значительно дороже
   по credits (combinatorial explosion).

2. **Female version** — параллельно с male или sequentially?
   PixelLab supports generating new base character с тем же style ref.

3. **29 items prompts** — готовы (см. ниже), но **финализировать перед батчем**:
   - Confirm style consistency parameter (PixelLab UI flag)
   - Confirm transparent BG mode

### Pending implementation (после subscription)

1. **PixelLab generate batch (29 items):**
   - Если standalone-mode работает → одна view (south) каждого item с
     transparent BG, ~30 credits.
   - Если только character-edit → character с item, 29 × variants × directions
     = explosion, нужно урезать item list или ограничить directions до `south`.

2. **M38 миграция:**
   - INSERT 29 items с `png_path` в pet_catalog
   - Rarities mix: common/rare/epic/mythic
   - Hook в `main.py:run_migrations()` после M37

3. **Female variant character** (опционально):
   - PixelLab новый base + 8 directions
   - `pet-assets/v2/kimono-f/{...}.png`, `underwear-f/{...}.png`
   - Расширить `PetStage.VARIANTS` до `['kimono', 'underwear', 'kimono-f', 'underwear-f']`

4. **UI для выбора variant** (если female добавляем):
   - В магазине отдельные skin items `skin_kimono_f`, `skin_underwear_f`
   - JS определяет variant из `body.item_id` (уже работает для текущих двух)

### Prompts ready-to-paste в PixelLab

PixelLab берёт текущий character как базу — промпты короткие, style match'ит автомат:

```
HEAD (надевается на голову):
  witch_hat       "wearing a tall pointed purple witch hat with gold buckle"
  knight_helmet   "wearing a polished steel knight helmet with red feather"
  pirate_tricorn  "wearing a black pirate tricorn hat with red feather plume"
  crown           "wearing a golden jeweled crown with red ruby"
  halo            "with a glowing golden halo floating above head"

FACE (на лицо):
  eyepatch        "wearing a black eyepatch over right eye"
  vr_visor        "wearing a futuristic cyan glowing VR visor"
  round_glasses   "wearing simple round wire-frame glasses"
  monocle         "wearing a gold monocle on right eye with chain"
  bandana         "wearing a red bandit bandana covering nose and mouth"

BODY (заменяет/добавляется на торс):
  armor_plates    "wearing polished steel plate armor"
  witch_robe      "wearing a flowing purple witch robe with star pattern"
  neon_circuit    "wearing a black neon cyberpunk circuit bodysuit"
  gold_sash       "with a golden silk sash diagonally across torso"
  striped_scarf   "wearing a red and white striped scarf"

ACCESSORY (в руке / на плече):
  pixel_sword     "holding a shiny pixel steel sword in right hand"
  broomstick      "holding a witch's wooden broomstick"
  parrot          "with a colorful red parrot sitting on left shoulder"
  magic_wand      "holding a glowing magic wand with star tip"
  microphone      "holding a microphone with red cord"
  torch           "holding a burning torch with orange flame"

AURA (свечение вокруг):
  aura_blue_glow         "surrounded by soft blue magical glow"
  aura_purple_particles  "surrounded by floating purple sparkle particles"
  aura_gold_burst        "with radiating golden light beams around body"
  aura_rainbow_swirl     "with swirling rainbow magical particles"

BACKGROUND (фон под персонажем):
  bg_spotlight     "standing in golden spotlight beam from above"
  bg_hologram_grid "on cyberpunk holographic blue grid background"
  bg_starfield     "with starfield night sky background"
  bg_confetti      "with colorful confetti falling around"
```

---

## Файлы изменённые в этой сессии

```
# Frontend
Расширение/frontend/pet-assets/v2/kimono/*.png          (NEW, 8 файлов)
Расширение/frontend/pet-assets/v2/underwear/*.png       (NEW, 8 файлов)
Расширение/frontend/pet-assets/v2/metadata.json         (NEW)
Расширение/frontend/pet-stage.js                        (MODIFIED — _buildCreatureImg + skin variant swap + emoji strip)
Расширение/frontend/viewer.css                          (MODIFIED — pixelated + slot full-overlay)
Расширение/frontend/overlay.html                        (MODIFIED — 2× size, walking, bob, slowdown)
Расширение/frontend/extension.html                      (MODIFIED — cache bust pet-stage.js?v=20260524a)
Расширение/frontend/mobile.html                         (MODIFIED — cache bust)
Расширение/frontend/_pet-stage-test.html                (MODIFIED — 12 character variants + LLM benchmark)

# Backend
Расширение/backend/main.py                              (MODIFIED — pet-assets StaticFiles mount + M37 hook)
Расширение/backend/migrations/m37_pets_v3_clean_slate.py (NEW)

# Docs
Расширение/docs/CONTEXT_PETS_V3.md                      (this file)
Расширение/docs/CONTEXT.md                              (MODIFIED — ссылка на этот handoff)
```

**Backups в проде:** `/root/twitch-extension/backups/*.bak` — overlay, main.py
снимки до каждого деплоя.

---

## Tasks из текущей сессии

#9–19 в TaskList (все completed):
- ✅ Copy character PNG assets to repo
- ✅ Replace pet-stage.js creature with PNG character
- ✅ Add pixelated image-rendering CSS
- ✅ Sanity-check integration locally
- ✅ Strip emoji fallback, simplify slot positioning
- ✅ Write M37 migration — pets v3 clean slate
- ✅ Hook M37 into main.py:run_migrations
- ✅ Prepare deploy bundles (backend + frontend tar)
- ✅ Hot-fix: mount pet-assets as StaticFiles in main.py
- ✅ Wire variant swap from equipped body item
- ✅ Overlay 2× size + direction-aware walking (+ bob + slowdown)

---

## Overlay walking — техническая шпаргалка

Конструкция для будущей правки:

```
.pet-card (position:absolute, animation: pet-walk)
  └─ .pet-card-visual (anchor для overlays, position:relative)
       ├─ .pet-stage (south creature, opacity-animated to hide during walk)
       ├─ .pet-walk-frame--east (img, opacity-animated 30-50%)
       └─ .pet-walk-frame--west (img, opacity-animated 80-100%)
```

Cycle timing (% of total duration 90-150s):
- **0-30%** — idle на старте, south visible
- **30-50%** — walking right, east visible, south hidden, X: 0→amp, bob ×4
- **50-80%** — idle на правом краю, south visible
- **80-100%** — walking back, west visible, south hidden, X: amp→0, bob ×4

При `dir = -1` (выпало случайно идти первой ногой влево) JS свопает
`east.src` ↔ `west.src` пост-рендера, чтобы east-timing-slot показывал
west-sprite. CSS-классы остаются те же.

CSS-переменные на `.pet-card`:
- `--walk-start` — стартовая X-позиция (vw)
- `--walk-amp` — амплитуда движения (vw, signed)
- `--walk-duration` — длительность цикла (s)
- `--walk-delay` — стартовая задержка (s, для стаггера)

---

## Когда возвращаемся к этой работе

1. Прочитай этот файл → context loaded
2. Юзер оплачивает PixelLab Tier 1
3. Проверяем PixelLab workflow: standalone item gen или character-edit-only?
4. По результату — либо batch'им 29 items, либо ограничиваем scope
5. Пишу M38 миграцию (INSERT 29 items)
6. Deploy на Timeweb

---

## Deployment план (для контекста, не выполнять без явного запроса)

```bash
# Hot-fix overlay/frontend (НЕ требует restart backend):
cd Расширение && tar czf /tmp/deploy.tar.gz frontend/<files>
scp /tmp/deploy.tar.gz root@31.130.132.224:/tmp/
ssh root@31.130.132.224 'cd /root/twitch-extension && \
    cp <file> backups/<file>.pre-<change>-$(date +%Y%m%d-%H%M%S).bak && \
    tar xzf /tmp/deploy.tar.gz'

# Backend migration (требует restart):
ssh root@31.130.132.224 'cd /root/twitch-extension && tar xzf /tmp/deploy.tar.gz && \
    supervisorctl restart twitchbot'
```

**Timeweb host:** `31.130.132.224` (см. `CONTEXT.md` для полной инфры).

---

## Ссылки на related docs

- `CONTEXT.md` — main extension context (multi-tenant infra, core features)
- `CONTEXT_BANNERLORD.md` — Bannerlord module (active dev sprint 5.27v)
- `CONTEXT_RIMWORLD.md` — legacy module
- `ARCHITECTURE.md` — overall system architecture

Pets v3 не блокирует другие модули. Работа параллелится с Bannerlord sprints.
