# Колдунчик: связанное поведение, 26.09.2026

Предпросмотр: https://shedoy23.ru/pet-assets/mage-behaviour-v1/preview.html

20 поз: прежние 8 кадров ходьбы и 12 новых поз для дыхания, начала/завершения шага, зевка, посадки, сна и пробуждения. Новый контроллер завершает цикл шага перед остановкой. Из сна сначала идут потягивание и подъём с фонарём. Последняя команда сохраняется до завершения перехода. Режим «Сам по себе» чередует прогулку, отдых и сон; у границы сцены персонаж останавливается и разворачивается.

Ходьба использует одобренные 8 рисунков без новой перерисовки; доработаны длительности фаз, разгон/торможение и переходы. Новые позы сохраняют единый масштаб: сон уменьшает высоту позы, но не увеличивает голову. Дальнейшая ручная доводка пиксельной идентичности между разными действиями остаётся возможной; это самостоятельный прототип, а не обновление всей коллекции.

## Состояние публикации

Опубликованы только семь новых файлов отдельного каталога. Живой OBS, общий пакет pets-walk-fix, каталог магазина, backend и замороженный Twitch-фронт этим изменением не затронуты. В общий rollout этот прототип не включён.

Браузерные проверки локально и на публичной странице: walk → stop → yawn → sit → sleep → wake → rise → start, разворот после остановки, все 20 кадров, замедление, мобильная ширина 390px, reduced-motion без автостарта, отсутствие JS ошибок. Все семь публичных файлов совпали по SHA-256. Дополнительно проверены очередность команд и границы индексов кадров в самостоятельном тесте. Red test committed as ac4fef4 before implementation.

Визуально проверены сон и все кадры на светлом фоне. При упаковке обнаружено неравномерное расположение строк генератора: механическая нарезка теперь определяет прозрачные промежутки между строками, исключая попадание чужих ног в кадры сна.

## Файлы и воспроизведение

- Расширение/frontend/pet-assets/mage-behaviour-v1/source.png — финальный исходный рисунок.
- Расширение/frontend/pet-assets/mage-behaviour-v1/behaviour-12.png — 12 кадров, 3072×256.
- Расширение/frontend/pet-assets/mage-behaviour-v1/walk-8.png — 8 кадров, 2048×256.
- Там же manifest.json, animator.js, preview.js и preview.html.
- scripts/package-mage-behaviour.cjs — механическая упаковка через sharp.
- scripts/test-mage-behaviour.cjs и scripts/test-mage-behaviour-browser.cjs.

Использован встроенный imagegen, не CLI. Исходник генератора: C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-30738622-1e3e-4b5b-97e9-6f6613cf68dc.png.
Референс — механически выделенный первый кадр из предыдущей пробы: dist/pet-scenes-20260926/mage-identity.png.
Исходные изображения не удалены.

## Промпт генерации

Create a coherent CHARACTER ANIMATION SPRITE SHEET with EXACTLY TWELVE frames in a perfectly regular FOUR COLUMN by THREE ROW grid. Transparent true alpha background, no floor, no labels, no text, no borders. Canvas landscape 2048x1536 if possible. All poses must preserve identical character scale and head size; foot/seat ground baseline same position in each cell. Character always faces RIGHT, never mirrored. Give each cell equal generous margins.
REFERENCE is exact identity, colors, chunky pixel-art style, proportions and scale. Sleepy chibi boy wizard, huge floppy purple hat with bronze band/gold buckle and gold bell drooping to LEFT, same purple-brown hair, navy blue coat gold hems, gray pants brown boots, satchel behind on left hip, cyan glowing black metal lantern held in near hand. Consistency across poses is critical. Head/hat/coat dimensions must NOT change as he sits; sitting simply lowers upper body.
Frame mapping in reading order:
TOP ROW:
1 idle EXHALE: stands relaxed upright with both boots near each other, lantern hangs at his side, eyes half-open.
2 idle INHALE: SAME idle pose with extremely subtle chest rise, lantern delayed slightly, same feet and face. Only2-3 logical pixels change.
3 starting ANTICIPATION: feet still together, leans torso slightly toward RIGHT, near knee begins to bend, lantern lags backward.
4 first SHORT STEP: light near leg moves forward RIGHT heel touches ground, dark far leg behind LEFT, smaller stride than reference, body upright.
MIDDLE ROW:
5 stopping SHORT CONTACT: light near leg forward RIGHT supporting body, dark rear leg preparing to close, body leaning backward a tiny bit, lantern continues forward.
6 SETTLE: both boots close together again, knees soften, lantern almost resting, matches idle pose but a little lower.
7 SLEEPY YAWN: still standing, eyes closed, free hand near mouth, lantern held in other hand, hat droops.
8 SIT DOWN: bends knees deeply, lowers body and hat, sets lantern gently on ground at RIGHT next to him. The lantern stays within same cell.
BOTTOM ROW:
9 ASLEEP EXHALE: sits curled comfortably on ground, knees tucked inside coat, eyes closed, face visible below hat, lantern resting upright beside him at RIGHT. Same head size as standing poses. No Z letters.
10 ASLEEP INHALE: almost identical to9, very tiny shoulder/chest rise, SAME grounded lantern position and size.
11 WAKE AND STRETCH: still seated, eyes opening sleepily, stretches free arm upward under big hat, lantern stays beside him.
12 STAND UP: halfway rising, knees bent, has picked up lantern in near hand, face sleepy, leads naturally to standing idle1.
Pixel art must remain clean and detailed, crisp stepped outline no blurry glow. Lantern cyan interior only, no environment light cloud. No extra props, duplicated limbs or alternate characters. Exactly12 distinct correctly located frames with identical character design.

## Промпт коррекции

Correct ONE cell only in this 4-column3-row12-frame sprite sheet: TOP ROW THIRD CELL, the leaning-forward anticipation pose. The wizard is missing his lantern there. Add the same black metal cyan-glowing lantern, held by its top handle in his near/right visible hand beside the front/right of his coat. Let it trail slightly behind the forward lean. Same lantern size and design as top-row cell1. Preserve the hand grip and both arms, no extra hand. The lantern must remain visibly connected to his hand and be wholly inside cell3. Keep the other11 cells exactly as they are, as well as this cell's face, hat, legs, body pose and colors. Transparent true alpha background, preserve4x3grid and dimensions, no new background or outline. Do not remove or alter any other lantern.
