# Колдунчик: восьмикадровая проба

Сгенерировано встроенным imagegen. Отдельный прототип, не включён в живой оверлей. Механическая упаковка сохраняет единый масштаб и опорную линию; пропорции и стык цикла ещё требуют доводки. Последовательные коррекции убрали повтор ведущей ноги в нижнем ряду.

Предпросмотр: https://shedoy23.ru/pet-assets/mage-walk-study-v1/preview.html

Файлы: `Расширение/frontend/pet-assets/mage-walk-study-v1/{source.png,walk-8.png,manifest.json,preview.html}`. Упаковка: `scripts/package-mage-walk-study.cjs`. Сравнение использует прежний двухкадровый цикл с тем же временем полного шага.

Исходник: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-eefda373-b220-455b-926a-b3bae4d4bddd.png`.

## Генерация

Create a production sprite sheet of ONE continuous 8-frame WALK CYCLE for the exact sleepy purple lantern mage in the reference. Transparent background with true alpha. EXACT layout: FOUR equal columns by TWO equal rows, total eight cells, chronological row-major order. Wide canvas 2048x1024 preferred. Each character stays centered at the exact same scale in its cell, ground at same relative y, clear margins. No text, labels, borders, floor, shadows or effects outside the sprite.
Identity: tiny chibi pixel-art boy wizard with oversize floppy purple pointed hat, gold buckle and dangling gold bell, purple brown hair, sleepy eyes, navy/purple gold-trimmed coat, brown shoes, small brown satchel, cyan lantern carried in the near hand. Preserve the original chunky outlined pixel art, silhouette and proportions exactly. All eight images face RIGHT, camera true side with slight face 3/4 as reference.
This is NOT eight similar poses. Animate a physically coherent full stride. Near leg is visibly lighter, far leg darker throughout. Must alternate the SAME near leg:
1 CONTACT: near bright boot extended FORWARD to image RIGHT heel contacts ground, far dark boot BACK left toe.
2 DOWN: near bright foot plants under front/right, knee compresses, pelvis slightly down, far heel lifts.
3 PASS: near bright leg planted under hip, far dark knee passes forward bent with foot off ground. Feet close together horizontally.
4 UP: near bright support leg behind hip on toe at left, far dark knee lifted forwards right. Pelvis highest.
5 OPPOSITE CONTACT: near bright leg stretches BACK to image LEFT toe, far dark leg stretches FORWARD right heel. THIS IS THE OPPOSITE LEG OVERLAP TO FRAME 1.
6 DOWN: far dark foot plants front/right, near bright heel lifts back/left, pelvis down.
7 PASS: far dark leg planted under hip, near bright knee passes forward bent. Feet close together horizontally.
8 UP: far dark support leg behind hip on left toe, near bright knee lifted forward right, preparing frame1.
Upper body/head/hands remain consistent across all8, no morphing faces or changes of clothing. Subtle natural pelvis bob only 2-3 logical pixels, hat tip and bell lag slightly behind body's bob, coat hem responds to steps, lantern swings gently like a weighted pendulum with delayed motion. Near hand keeps holding SAME lantern. No sleep, greeting, magic, turning or extra actions. Closed loop frame8->1. EXACTLY eight distinct sequential frames in a uniform4x2 sheet.

## Коррекция второй половины

Edit FIRST image, an 8-frame4x2 sprite sheet. SECOND image is ONLY a reference for the opposite leg overlap.
Keep the entire top row untouched. Keep every head, hat, torso, lantern, hand, bag and coat untouched in the bottom row too.
Correct ONLY the leg drawing and occlusion in the BOTTOM ROW to make the other half of the walking cycle, NOT a repeated top row.
In bottom row cells1 and2 the LEFTWARD BACK LEG must be the visible NEAR foreground leg in LIGHTER gray pants and lighter warm brown boot. Its diagonal from right hip down towards image LEFT crosses IN FRONT of the other leg. The RIGHTWARD front foot belongs to the DARKER FAR leg; dark charcoal pant, dark brown boot, obscured by near leg at hip. Look at second reference for this opposite contact.
Bottom row cell3: foreground LIGHTER near knee is raised towards RIGHT, foreground boot is bent back under knee hovering above ground; DARK far leg is vertical supporting the body. This MUST reverse the overlaps and shading from top row cell3.
Bottom row cell4: LIGHT near knee lifted FORWARD RIGHT with boot under knee off ground, DARK far leg extends BACK LEFT to a toe on ground. This leads into top row cell1's near-leg heel strike.
Natural muted clothing colours only, SAME grey pants and brown boots; no colored diagrams, extra limbs or additional props. Keep all8 identities, scale, grid and alpha exactly. Real transparent background. Output complete corrected4x2 eight-frame sheet.

## Коррекция шестого кадра

Precision correction to this 4-column2-row eight-frame walk sheet. Change ONLY legs in bottom row SECOND column (frame6). Everything else stays identical including other seven cells and the entire upper body of frame6. In frame6 the near LIGHT GRAY pant leg with gold cuff must angle BACK DOWN LEFT from pelvis, its BROWN back boot with heel lifted and toe near ground on image LEFT, crossing in front of far leg at hip. The far DARK CHARCOAL pant leg must extend FORWARD DOWN RIGHT, bent slightly with dark brown foot planted flat on ground at RIGHT supporting weight. This is a DOWN/compression pose immediately after bottom-left frame5, with the SAME near/back far/front leg overlap as frame5. Do NOT put the light gray near leg forward/right. Keep exact8frame4x2sheet dimensions, same pixelart, real transparent background.

## Проверки

В браузере проверены все восемь кадров, воспроизведение, замедление, разворот и ширина 390px. Кадры осмотрены на светлом фоне. Это проверка прототипа, не доказательство готовности к включению для всей коллекции. Живой OBS, серверная логика и Twitch-кандидат не изменялись.
