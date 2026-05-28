# BannerlordLink — матрица совместимости (COMPAT-3)

> Дата: 2026-05-29 · Mod `Shedoy23.BannerlordLink` v0.1.0
> Назначение: что мы патчим, на какой версии игры это валидно, с чем
> конфликтуем, и как мы защищаемся от version-drift.

---

## 1. Целевая версия игры

| Параметр | Значение |
|---|---|
| **Поддерживаемая версия** | Bannerlord **1.3.15.x** (build 110062) |
| **Сборка против** | `X:\SteamLibrary\...\bin\Win64_Shipping_Client\TaleWorlds.*.dll` (1.3.15) |
| **Runtime** | net472, x64, `Win64_Shipping_Client` |
| **Почему 1.3.15** | Baseline = BLT-RC22 (Randomchair22 BT 5.2.4) — стабильная ветка для 1.3.15. Все паттерны адаптированы из неё. См. `BLT_RC22_REFERENCE.md`. |
| **1.4.5+** | ⚠️ Не поддерживается. Naval-расширение сдвинуло сигнатуры; engine-fix-патчи (siege/militia) и DamageHook требуют ре-аудита перед апгрейдом. |

### Обязательные зависимости (`SubModule.xml`, все `LoadBeforeThis`)
- `Bannerlord.Harmony` — обязательно (весь patch-слой)
- `Native`
- `SandBoxCore`
- `Sandbox`

---

## 2. Инвентарь Harmony-патчей

8 patch-классов. **Зелёные** = строгий `[HarmonyPatch(typeof(...))]` (упадём
явно если метод исчез). **Жёлтые** = `TargetMethods()` с graceful `yield break`
— если метод отсутствует в текущей версии, патч молча пропускается (mod
грузится, фича выключена). См. COMPAT-1/COMPAT-2.

| Патч | Цель | Тип | Привязка | Риск конфликта | Назначение |
|---|---|---|---|---|---|
| **DamageHookPatch** | `Mission.RegisterBlow` | Prefix | 🟢 строгая | 🔴 **высокий** | Powers-урон + централизованный фильтр (rage/retribution/poison). |
| **AdoptedHeroDeathPatch** | `KillCharacterAction.ApplyInternal` | Prefix | 🟢 строгая | 🔴 **высокий** | Блок permadeath усыновлённых героев. |
| **AdoptedHeroDeathPatch** | `Mission.OnAgentRemoved` | Prefix | 🟢 строгая | 🟠 средний | Killed→Unconscious для усыновлённых + их коней. |
| **SiegeRetreatFix** | `MapEvent.CalculateAndCommitMapEventResults` | Prefix/Postfix | 🟢 строгая | 🟠 средний | Engine-bug fix: отступление при осаде. |
| **MilitiaSallyOutFix** | `Town.GetDefenderParties` | Prefix | 🟢 строгая | 🟠 средний | Включить ополчение в вылазку гарнизона. |
| **TournamentParticipantsPatch** | `FightTournamentGame.*` (+ `TournamentBehavior.EndCurrentMatch`) | Prefix | 🟡 graceful | 🟠 средний | Гарантировать участие героя зрителя в турнире. |
| **IsSideDepletedPatch** | `MissionAgentSpawnLogic.IsSideDepleted` | Prefix | 🟡 graceful | 🟢 низкий | Reinforcement-логика для summon. |
| **NameMarkerPatch** | (nametag rendering) | — | 🟡 graceful | 🟢 низкий | В 1.3.15 `yield break` → **выключен**. Нейтрализован. |
| **BannerCampaignBehaviorPatch** | behavior с `(Hero)`-методом | 🟡 graceful | 🟢 низкий | Баннеры героев. |

> Динамический инвентарь патчей: `grep -rn "\[HarmonyPatch" BannerlordLink/src/Patches/`.

---

## 3. Известные конфликты с другими модами

### 🔴 Взаимоисключающие (НЕ запускать вместе)
- **Bannerlord-Twitch (BLT) / BLTAdoptAHero** — патчит те же `Mission.RegisterBlow`
  и `KillCharacterAction` (мы из него и адаптировали). Два Prefix'а на один метод
  = непредсказуемый порядок + двойная обработка урона/смерти. **Это конкурент-мод,
  одновременный запуск не поддерживаем.**
- **Combat overhaul моды**, патчащие `RegisterBlow` (Realistic Battle Mode,
  RBM combat, кастомные damage-моды) — будут драться за тот же Prefix. Возможен
  двойной/потерянный урон от powers.

### 🟠 Условно-совместимые (тестировать)
- **Adopt-a-hero-подобные / death-prevention моды** — конкуренция за
  `KillCharacterAction.ApplyInternal` / `Mission.OnAgentRemoved`. Если оба
  возвращают `false` из Prefix — ок; если ожидают друг от друга вызов оригинала
  — рассинхрон.
- **Siege / settlement моды**, трогающие `MapEvent.CalculateAndCommitMapEventResults`
  или `Town.GetDefenderParties` (Diplomacy, Improved Garrisons и т.п.).
- **Tournament-моды** (Arena Overhaul) — конкуренция за `FightTournamentGame`.

### 🟢 Безопасные
- Косметические / UI / map-icon / texture-моды — не пересекаются.
- Моды без Harmony-патчей на перечисленные методы.

---

## 4. Рекомендация по load order

```
Bannerlord.Harmony      (LoadBeforeThis — обязательно первым)
Native
SandBoxCore
Sandbox
... другие SandBox-зависимые моды ...
Shedoy23.BannerlordLink (как можно позже — наши Prefix'ы видят финальное состояние)
```

Если стоит другой combat/death-патч-мод — **выбрать один**. По умолчанию
BannerlordLink рассчитан на чистый ваниль + Harmony.

---

## 5. Version-fragility (что сломается при апгрейде игры)

| Уязвимость | Где | Митигация |
|---|---|---|
| Сигнатура `RegisterBlow` меняется между версиями | DamageHookPatch | 🟢 строгая привязка — **упадёт явно** на старте (видно в логе), не тихо. |
| `KillCharacterAction.ApplyInternal` (private) переименован | AdoptedHeroDeathPatch | 🟢 строгая — явный fail на старте. |
| Имена `FightTournamentGame` / spawn-логики плавают | Tournament/IsSideDepleted/NameMarker/Banner | 🟡 graceful `TargetMethods()` → мод грузится, фича off, в логе диагностика. |
| `AccessTools` бросает на null-типе в static cctor | все патчи | 🟢 COMPAT-1: cctor'ы обёрнуты. |
| `GetTypes()` бросает `ReflectionTypeLoadException` | reflection-сканы | 🟢 COMPAT-2: обёрнут в catch. |

**Правило при апгрейде версии игры:** пересобрать против новых DLL → если
зелёный патч не находит цель, build/старт ругнётся → ре-аудит сигнатуры по
BLT-эквиваленту. Жёлтые патчи сами выключатся; проверить, что фича не критична.

---

## 6. Как проверить совместимость на новой версии (чеклист)

1. Обновить `BannerlordPath` DLL → `dotnet build BannerlordLink.csproj -c Release`.
2. Старт игры → `Logs/*.log`: искать `[patch]`/`TargetMethod error`/Harmony exceptions.
3. Smoke в бою: powers-урон применяется? усыновлённый герой не умирает насмерть?
4. Кампания: осада/вылазка/турнир без краша?
5. Если зелёный патч упал — сверить сигнатуру с BLT-RC22 reference, поправить, пересобрать.
