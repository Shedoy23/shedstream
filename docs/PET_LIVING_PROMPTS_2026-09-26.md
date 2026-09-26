# Living pets — image generation prompts (2026-09-26)

Built-in imagegen, transparent backgrounds. Selected sheets are copied into `Расширение/frontend/pet-assets/living-pets-v1/assets/<id>/source-*.png`. Packing performs only cropping, nearest-neighbour scaling and atlas assembly. Mage uses the previously approved prototype; see PET_MAGE_BEHAVIOUR_2026-09-26.md. Refinements below record attempted art direction; final selected PNGs are authoritative.

## wayfarer

### walk

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-fc8120d0-cbd1-4763-8815-96f1f9cb067e.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet with EXACTLY8 frames in FOUR columns by TWO rows, chronological left-to-right top then bottom. TRUE TRANSPARENT alpha background. Equal cell spacing, large clear transparent gutters. All8 face RIGHT. Same character size, head and clothing proportions in every frame. No text, labels, floor, shadows, halo or extra props. Reference is exact character identity.
For walking characters: a full genuine8phase walking loop with alternating NEAR and FAR legs. Consistent natural lighting identifies legs: NEAR leg is LIGHTER and crosses in FRONT at hip, FAR leg darker and behind. Do not repeat the top row in the bottom row.
TOP ROW: 1 near LIGHT leg forward RIGHT heel strike, far DARK back LEFT toe. 2 near LIGHT planted forward right bearing weight bent knee, far DARK back heel lifts. 3 near LIGHT support under hip, FAR dark bent knee passes forward with foot hovering. 4 near LIGHT toe behind left, FAR dark knee lifted ahead right.
BOTTOM ROW: 5 near LIGHT leg goes BACK TO IMAGE LEFT and MUST CROSS IN FRONT of far DARK leg going forward RIGHT heel strike. 6 near LIGHT leg stays BACK LEFT with heel lifted and crosses in foreground, far DARK leg planted forward RIGHT supports weight. 7 FAR DARK support under hip, NEAR LIGHT knee bent passes forward with foot off ground. 8 FAR DARK leg back LEFT toe, NEAR LIGHT knee lifted ahead RIGHT preparing frame1.
Frames1/5 and2/6 MUST have opposite anatomical leg overlap, not only different stance. Passing frames3/7 have close horizontal feet, lifted knees. Legs attach plausibly to pelvis/chest. Small weight bob and natural secondary motion. Upperbody identity stable.
IDENTITY: Small chibi boy wayfarer, olive-green hood and flowing green cloak, brown boots and brown-gray trousers, leather backpack with rolled bedroll, wooden mug carried in near hand. Near trouser leg LIGHT warm gray-brown, far leg DARK brown.
MOTION CHARACTER: cloak hem and bedroll lag, mug stays level, calm purposeful hiking stride

#### Refinement 1

Repair ONLY LEGS in this8frame4x2 walk sheet. Keep heads, torso, hands, props and exact grid unchanged. Natural colors: Small chibi boy wayfarer, olive-green hood and flowing green cloak, brown boots and brown-gray trousers, leather backpack with rolled bedroll, wooden mug carried in near hand. Near trouser leg LIGHT warm gray-brown, far leg DARK brown.
Frames1/2 (top-left two) remain unchanged with LIGHT near leg forward RIGHT.
Frames3/4 (top-right two): LIGHT near leg supports under/behind hip LEFT. FAR DARK leg is raised forward RIGHT with bent knee off ground. Do not put the light near leg up in this half.
Frames5/6 (bottom-left two): the SAME LIGHT near foreground leg goes BACK LEFT, crossing visibly in FRONT of far leg at pelvis. The FAR DARK leg goes forward RIGHT, heel/flat planted. Frame5 is wide contact, frame6 compressed down pose with near back heel raised. These must be the OPPOSITE leg overlap from frames1/2, not same leg again.
Frames7/8 (bottom-right two): DARK far leg supports under/behind hip LEFT. LIGHT near leg is raised forward RIGHT, knee bent and foot off ground, preparing frame1.
Near leg stays lighter, far leg darker in all8. Attached anatomically, exactly2 legs, no extra limbs. Keep creature haunches/boots/pants natural per identity. No changes above waist. Transparent alpha, no new effects.

#### Refinement 2

Edit FIRST sprite sheet: ONLY bottom-left cell(frame5) legs. Copy the leg overlap from SECOND reference: the LIGHT gray-brown NEAR leg angles down BACK LEFT crossing in front, the DARK FAR leg goes down FORWARD RIGHT. Main foreground knee/boot is at LEFT, dark foot at RIGHT. Same stance width as current frame5. Keep frame5 upperbody and allother7cells EXACTLY unchanged. True transparent4x2 sheet. Do not change mug/backpack.

#### Refinement 3

Edit FIRST image, a 4 columns x2 rows transparent sprite sheet. ONLY fix leg anatomy in BOTTOM LEFT cell (frame5), leaving all other7 sprites identical. Copy leg ordering from SECOND reference. Frame5 LIGHT taupe foreground leg must slope down LEFT from hip and its boot be at far LEFT under backpack. DARK brown background leg slopes down RIGHT and its boot at far RIGHT under mug. Foreground leg crosses IN FRONT at hip. Reference2 explicitly shows correct opposite stride. Keep frame5 upperbody/backpack/mug and proportions exactly. No text, no backdrop, real transparency.

#### Refinement 4

One tiny localized correction to this transparent4x2 walk sheet. TOP RIGHT sprite(frame4) only: the raised forward RIGHT leg must be DARK BROWN (far leg), and the planted LEFT leg must be LIGHT TAUPE (near leg). Match the depth shading and ordering of the legs in frame3 immediately to its left. Preserve exact leg positions, body, mug, hood, backpack. ALL OTHER7cells remain identical including corrected bottomleft. Background transparent.

### behaviour

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-fc58ded0-7351-4b51-a838-8b4255e0c296.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet EXACTLY12 frames in FOUR columns by THREE rows, chronological row-major. TRUE alpha transparent background. Four equal columns, three clearly separated rows with WIDE empty gutters; no artwork crossing cells. Same character scale and head size in every pose, seated characters must be shorter without shrinking/enlarging head. All face RIGHT with same view as reference. No text, labels, borders, ground, stray shadows, invented props except specifically described sleep props. Keep props visibly attached to hands while standing and grounded only when sitting.
Frame order TOP ROW: 1 relaxed standing/hover idle EXHALE;2 same idle subtle INHALE;3 anticipation to start, feet together leaning right (ghost prepares hover);4 first SHORT STEP, near LIGHT forward right far DARK back left (ghost glides slightly).
MIDDLE ROW:5 stopping SHORT CONTACT, near LIGHT right/front far DARK left/back, torso slows (ghost settles);6 feet close settled relaxed idle (ghost calmhover);7 character-specific pre-sleep yawn;8 lowering into seated/sleep pose, placing carried props beside character.
BOTTOM ROW:9 ASLEEP EXHALE;10 almost same ASLEEP INHALE with tiny shoulder/chest movement, props on ground stay fixed;11 WAKE stretching/peeking still seated;12 halfway STANDING UP retrieving carried props, leading naturally to idle1 (ghost rises with mug).
The entire sequence must preserve clothes, identity and carried accessories. Do not omit an item from a transition, and never duplicate arms. Natural character-specific behavior below overrides human anatomy for creatures.
IDENTITY: Small chibi boy wayfarer, olive-green hood and flowing green cloak, brown boots and brown-gray trousers, leather backpack with rolled bedroll, wooden mug carried in near hand. Near trouser leg LIGHT warm gray-brown, far leg DARK brown.
SLEEP STORY: takes a tiny last sip, sits on backpack with mug safely on ground at RIGHT, curls into green cloak with backpack as pillow. On wake stretches and picks up mug and backpack.
MOTION CHARACTER: cloak hem and bedroll lag, mug stays level, calm purposeful hiking stride

#### Refinement 1

Fix this4x3 twelve-frame sheet: in TOP ROW THIRD cell (anticipation) add the SAME wooden mug held visibly in the near hand in front of belly on RIGHT as in top row1. It must never disappear. Remove any floating letters/Z or stray symbols near sleeping head in bottom rowfirstcell and yawn scene. Keep steam only attached to actual mug. All other poses and character design remain identical, true alpha, no background, no text.

## crimson_knight

### walk

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-1a547f89-f37a-4e81-bbb0-7b3615e0869e.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet with EXACTLY8 frames in FOUR columns by TWO rows, chronological left-to-right top then bottom. TRUE TRANSPARENT alpha background. Equal cell spacing, large clear transparent gutters. All8 face RIGHT. Same character size, head and clothing proportions in every frame. No text, labels, floor, shadows, halo or extra props. Reference is exact character identity.
For walking characters: a full genuine8phase walking loop with alternating NEAR and FAR legs. Consistent natural lighting identifies legs: NEAR leg is LIGHTER and crosses in FRONT at hip, FAR leg darker and behind. Do not repeat the top row in the bottom row.
TOP ROW: 1 near LIGHT leg forward RIGHT heel strike, far DARK back LEFT toe. 2 near LIGHT planted forward right bearing weight bent knee, far DARK back heel lifts. 3 near LIGHT support under hip, FAR dark bent knee passes forward with foot hovering. 4 near LIGHT toe behind left, FAR dark knee lifted ahead right.
BOTTOM ROW: 5 near LIGHT leg goes BACK TO IMAGE LEFT and MUST CROSS IN FRONT of far DARK leg going forward RIGHT heel strike. 6 near LIGHT leg stays BACK LEFT with heel lifted and crosses in foreground, far DARK leg planted forward RIGHT supports weight. 7 FAR DARK support under hip, NEAR LIGHT knee bent passes forward with foot off ground. 8 FAR DARK leg back LEFT toe, NEAR LIGHT knee lifted ahead RIGHT preparing frame1.
Frames1/5 and2/6 MUST have opposite anatomical leg overlap, not only different stance. Passing frames3/7 have close horizontal feet, lifted knees. Legs attach plausibly to pelvis/chest. Small weight bob and natural secondary motion. Upperbody identity stable.
IDENTITY: Small chibi boy knight, shiny silver segmented armor, open helmet shows face, red cape, red shield with gold lion on RIGHT/forward side, sheathed sword at waist. Near leg BRIGHT silver foreground plate, far leg DARK steel shadow plate.
MOTION CHARACTER: solid heavy armored stride with subtle weight compression, red cape trails, shield moves little

#### Refinement 1

Repair ONLY LEGS in this8frame4x2 walk sheet. Keep heads, torso, hands, props and exact grid unchanged. Natural colors: Small chibi boy knight, shiny silver segmented armor, open helmet shows face, red cape, red shield with gold lion on RIGHT/forward side, sheathed sword at waist. Near leg BRIGHT silver foreground plate, far leg DARK steel shadow plate.
Frames1/2 (top-left two) remain unchanged with LIGHT near leg forward RIGHT.
Frames3/4 (top-right two): LIGHT near leg supports under/behind hip LEFT. FAR DARK leg is raised forward RIGHT with bent knee off ground. Do not put the light near leg up in this half.
Frames5/6 (bottom-left two): the SAME LIGHT near foreground leg goes BACK LEFT, crossing visibly in FRONT of far leg at pelvis. The FAR DARK leg goes forward RIGHT, heel/flat planted. Frame5 is wide contact, frame6 compressed down pose with near back heel raised. These must be the OPPOSITE leg overlap from frames1/2, not same leg again.
Frames7/8 (bottom-right two): DARK far leg supports under/behind hip LEFT. LIGHT near leg is raised forward RIGHT, knee bent and foot off ground, preparing frame1.
Near leg stays lighter, far leg darker in all8. Attached anatomically, exactly2 legs, no extra limbs. Keep creature haunches/boots/pants natural per identity. No changes above waist. Transparent alpha, no new effects.

#### Refinement 2

Fix ONE cell only TOP RIGHT(frame4). It currently raises the bright near knee incorrectly. Make the planted/support leg at image LEFT BRIGHT SILVER near leg, and the raised forward knee/boot at image RIGHT DARK STEEL far leg. Keep exact stance but switch correct depth shading and hip overlap. Near thigh overlaps far thigh. Same colors/legidentity as frame3 immediately to its left. Other7cells and allupperbody unchanged. True alpha4x2sheet.

### behaviour

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-5b305699-7287-4502-92e2-41d09b35dd7a.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet EXACTLY12 frames in FOUR columns by THREE rows, chronological row-major. TRUE alpha transparent background. Four equal columns, three clearly separated rows with WIDE empty gutters; no artwork crossing cells. Same character scale and head size in every pose, seated characters must be shorter without shrinking/enlarging head. All face RIGHT with same view as reference. No text, labels, borders, ground, stray shadows, invented props except specifically described sleep props. Keep props visibly attached to hands while standing and grounded only when sitting.
Frame order TOP ROW: 1 relaxed standing/hover idle EXHALE;2 same idle subtle INHALE;3 anticipation to start, feet together leaning right (ghost prepares hover);4 first SHORT STEP, near LIGHT forward right far DARK back left (ghost glides slightly).
MIDDLE ROW:5 stopping SHORT CONTACT, near LIGHT right/front far DARK left/back, torso slows (ghost settles);6 feet close settled relaxed idle (ghost calmhover);7 character-specific pre-sleep yawn;8 lowering into seated/sleep pose, placing carried props beside character.
BOTTOM ROW:9 ASLEEP EXHALE;10 almost same ASLEEP INHALE with tiny shoulder/chest movement, props on ground stay fixed;11 WAKE stretching/peeking still seated;12 halfway STANDING UP retrieving carried props, leading naturally to idle1 (ghost rises with mug).
The entire sequence must preserve clothes, identity and carried accessories. Do not omit an item from a transition, and never duplicate arms. Natural character-specific behavior below overrides human anatomy for creatures.
IDENTITY: Small chibi boy knight, shiny silver segmented armor, open helmet shows face, red cape, red shield with gold lion on RIGHT/forward side, sheathed sword at waist. Near leg BRIGHT silver foreground plate, far leg DARK steel shadow plate.
SLEEP STORY: yawns behind gauntlet, sits with red shield propped beside him at RIGHT and helmet visor lowered, naps upright leaning on shield. Wakes lifting visor, rises lifting shield.
MOTION CHARACTER: solid heavy armored stride with subtle weight compression, red cape trails, shield moves little

## colony_engineer

### walk

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-8cceceef-a51c-4bad-96a9-78d6491b1aca.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet with EXACTLY8 frames in FOUR columns by TWO rows, chronological left-to-right top then bottom. TRUE TRANSPARENT alpha background. Equal cell spacing, large clear transparent gutters. All8 face RIGHT. Same character size, head and clothing proportions in every frame. No text, labels, floor, shadows, halo or extra props. Reference is exact character identity.
For walking characters: a full genuine8phase walking loop with alternating NEAR and FAR legs. Consistent natural lighting identifies legs: NEAR leg is LIGHTER and crosses in FRONT at hip, FAR leg darker and behind. Do not repeat the top row in the bottom row.
TOP ROW: 1 near LIGHT leg forward RIGHT heel strike, far DARK back LEFT toe. 2 near LIGHT planted forward right bearing weight bent knee, far DARK back heel lifts. 3 near LIGHT support under hip, FAR dark bent knee passes forward with foot hovering. 4 near LIGHT toe behind left, FAR dark knee lifted ahead right.
BOTTOM ROW: 5 near LIGHT leg goes BACK TO IMAGE LEFT and MUST CROSS IN FRONT of far DARK leg going forward RIGHT heel strike. 6 near LIGHT leg stays BACK LEFT with heel lifted and crosses in foreground, far DARK leg planted forward RIGHT supports weight. 7 FAR DARK support under hip, NEAR LIGHT knee bent passes forward with foot off ground. 8 FAR DARK leg back LEFT toe, NEAR LIGHT knee lifted ahead RIGHT preparing frame1.
Frames1/5 and2/6 MUST have opposite anatomical leg overlap, not only different stance. Passing frames3/7 have close horizontal feet, lifted knees. Legs attach plausibly to pelvis/chest. Small weight bob and natural secondary motion. Upperbody identity stable.
IDENTITY: Small chibi young engineer with spiky brown hair, orange goggles on forehead, orange vest over cream shirt, teal-blue work pants with tan knee patch, brown gloves and boots, compact backpack, large steel wrench held in near hand. Near leg lighter TEAL with tan patch, far leg DARK navy teal.
MOTION CHARACTER: springy work boots, backpack and wrench respond subtly to steps
Final constraints: NO blurry glow, NO smoky background, NO backdrop colour whatsoever, only character with clear empty alpha. In anticipation frame3 ALL carried items must remain visibly in the SAME hands; do not hide or delete them.

#### Refinement 1

Repair ONLY LEGS in this8frame4x2 walk sheet. Keep heads, torso, hands, props and exact grid unchanged. Natural colors: Small chibi young engineer with spiky brown hair, orange goggles on forehead, orange vest over cream shirt, teal-blue work pants with tan knee patch, brown gloves and boots, compact backpack, large steel wrench held in near hand. Near leg lighter TEAL with tan patch, far leg DARK navy teal.
Frames1/2 (top-left two) remain unchanged with LIGHT near leg forward RIGHT.
Frames3/4 (top-right two): LIGHT near leg supports under/behind hip LEFT. FAR DARK leg is raised forward RIGHT with bent knee off ground. Do not put the light near leg up in this half.
Frames5/6 (bottom-left two): the SAME LIGHT near foreground leg goes BACK LEFT, crossing visibly in FRONT of far leg at pelvis. The FAR DARK leg goes forward RIGHT, heel/flat planted. Frame5 is wide contact, frame6 compressed down pose with near back heel raised. These must be the OPPOSITE leg overlap from frames1/2, not same leg again.
Frames7/8 (bottom-right two): DARK far leg supports under/behind hip LEFT. LIGHT near leg is raised forward RIGHT, knee bent and foot off ground, preparing frame1.
Near leg stays lighter, far leg darker in all8. Attached anatomically, exactly2 legs, no extra limbs. Keep creature haunches/boots/pants natural per identity. No changes above waist. Transparent alpha, no new effects.

### behaviour

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-c993f59e-fe54-41eb-93d2-1f3f1ab7f68e.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet EXACTLY12 frames in FOUR columns by THREE rows, chronological row-major. TRUE alpha transparent background. Four equal columns, three clearly separated rows with WIDE empty gutters; no artwork crossing cells. Same character scale and head size in every pose, seated characters must be shorter without shrinking/enlarging head. All face RIGHT with same view as reference. No text, labels, borders, ground, stray shadows, invented props except specifically described sleep props. Keep props visibly attached to hands while standing and grounded only when sitting.
Frame order TOP ROW: 1 relaxed standing/hover idle EXHALE;2 same idle subtle INHALE;3 anticipation to start, feet together leaning right (ghost prepares hover);4 first SHORT STEP, near LIGHT forward right far DARK back left (ghost glides slightly).
MIDDLE ROW:5 stopping SHORT CONTACT, near LIGHT right/front far DARK left/back, torso slows (ghost settles);6 feet close settled relaxed idle (ghost calmhover);7 character-specific pre-sleep yawn;8 lowering into seated/sleep pose, placing carried props beside character.
BOTTOM ROW:9 ASLEEP EXHALE;10 almost same ASLEEP INHALE with tiny shoulder/chest movement, props on ground stay fixed;11 WAKE stretching/peeking still seated;12 halfway STANDING UP retrieving carried props, leading naturally to idle1 (ghost rises with mug).
The entire sequence must preserve clothes, identity and carried accessories. Do not omit an item from a transition, and never duplicate arms. Natural character-specific behavior below overrides human anatomy for creatures.
IDENTITY: Small chibi young engineer with spiky brown hair, orange goggles on forehead, orange vest over cream shirt, teal-blue work pants with tan knee patch, brown gloves and boots, compact backpack, large steel wrench held in near hand. Near leg lighter TEAL with tan patch, far leg DARK navy teal.
SLEEP STORY: rubs eyes with free glove, sits using toolbag/backpack as cushion, puts wrench beside him, sleeps with goggles lowered, wakes adjusting goggles and picking up wrench.
MOTION CHARACTER: springy work boots, backpack and wrench respond subtly to steps
Final constraints: NO blurry glow, NO smoky background, NO backdrop colour whatsoever, only character with clear empty alpha. In anticipation frame3 ALL carried items must remain visibly in the SAME hands; do not hide or delete them.

## shadow_rogue

### walk

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-4bcbf4c9-2f83-430e-89a7-6fa70ff76fda.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet with EXACTLY8 frames in FOUR columns by TWO rows, chronological left-to-right top then bottom. TRUE TRANSPARENT alpha background. Equal cell spacing, large clear transparent gutters. All8 face RIGHT. Same character size, head and clothing proportions in every frame. No text, labels, floor, shadows, halo or extra props. Reference is exact character identity.
For walking characters: a full genuine8phase walking loop with alternating NEAR and FAR legs. Consistent natural lighting identifies legs: NEAR leg is LIGHTER and crosses in FRONT at hip, FAR leg darker and behind. Do not repeat the top row in the bottom row.
TOP ROW: 1 near LIGHT leg forward RIGHT heel strike, far DARK back LEFT toe. 2 near LIGHT planted forward right bearing weight bent knee, far DARK back heel lifts. 3 near LIGHT support under hip, FAR dark bent knee passes forward with foot hovering. 4 near LIGHT toe behind left, FAR dark knee lifted ahead right.
BOTTOM ROW: 5 near LIGHT leg goes BACK TO IMAGE LEFT and MUST CROSS IN FRONT of far DARK leg going forward RIGHT heel strike. 6 near LIGHT leg stays BACK LEFT with heel lifted and crosses in foreground, far DARK leg planted forward RIGHT supports weight. 7 FAR DARK support under hip, NEAR LIGHT knee bent passes forward with foot off ground. 8 FAR DARK leg back LEFT toe, NEAR LIGHT knee lifted ahead RIGHT preparing frame1.
Frames1/5 and2/6 MUST have opposite anatomical leg overlap, not only different stance. Passing frames3/7 have close horizontal feet, lifted knees. Legs attach plausibly to pelvis/chest. Small weight bob and natural secondary motion. Upperbody identity stable.
IDENTITY: Small chibi hooded rogue boy, charcoal black hood, red scarf and short red cape, gray pants brown boots, small curved dagger held down and BACK in near hand, leather pouches. Near leg LIGHT gray foreground, far leg DARK charcoal.
MOTION CHARACTER: quiet soft cautious footfalls, scarf trails, dagger points safely down/back
Final constraints: NO blurry glow, NO smoky background, NO backdrop colour whatsoever, only character with clear empty alpha. In anticipation frame3 ALL carried items must remain visibly in the SAME hands; do not hide or delete them.

#### Refinement 1

Precision repair of this8frame4column2row walk cycle. Preserve ALL heads, faces, upper bodies, accessories, size and grid. Edit ONLY the legs below the coat/hips. Use the original character natural colors.
Identity/leg materials: Small chibi hooded rogue boy, charcoal black hood, red scarf and short red cape, gray pants brown boots, small curved dagger held down and BACK in near hand, leather pouches. Near leg LIGHT gray foreground, far leg DARK charcoal.
The same NEAR leg must always have a LIGHTER surface and overlap the FAR DARKER leg at the hip. Correct the following cells:
Top row cells1/2 remain exactly unchanged: light near leg is forward RIGHT.
Top row cells3/4: LIGHT near leg is the supporting straight leg under/behind hip to LEFT. The lifted bent knee and foot ahead to RIGHT is the DARK FAR leg, visibly occluded behind near thigh. Do not raise the near leg in this half.
Bottom row cell1 (frame5): LIGHT foreground NEAR leg stretches BACK diagonally to image LEFT toe, from right-side hip down LEFT crossing IN FRONT of the DARK far leg which stretches FORWARD RIGHT heel. This MUST be opposite to top row cell1.
Bottom row cell2(frame6): SAME LIGHT foreground leg remains BACK LEFT with heel lifted, while DARK far leg is planted forward RIGHT supporting weight. Do not switch light leg forward here.
Bottom row cells3/4: FAR DARK leg supports vertically under/behind hip LEFT. LIGHT NEAR knee now raises FORWARD RIGHT, bent with foot off ground, preparing top-left contact. Passing cell3 has closer feet; cell4 knee is more forward.
Keep exactly TWO legs attached to body, plausible root/feline/humanoid anatomy per character, no duplicates. No other costume changes. Preserve transparency, no smoke or glow. No letters or marks.

### behaviour

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-453cd81f-a3dc-4afc-9e27-9721e81c99d1.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet EXACTLY12 frames in FOUR columns by THREE rows, chronological row-major. TRUE alpha transparent background. Four equal columns, three clearly separated rows with WIDE empty gutters; no artwork crossing cells. Same character scale and head size in every pose, seated characters must be shorter without shrinking/enlarging head. All face RIGHT with same view as reference. No text, labels, borders, ground, stray shadows, invented props except specifically described sleep props. Keep props visibly attached to hands while standing and grounded only when sitting.
Frame order TOP ROW: 1 relaxed standing/hover idle EXHALE;2 same idle subtle INHALE;3 anticipation to start, feet together leaning right (ghost prepares hover);4 first SHORT STEP, near LIGHT forward right far DARK back left (ghost glides slightly).
MIDDLE ROW:5 stopping SHORT CONTACT, near LIGHT right/front far DARK left/back, torso slows (ghost settles);6 feet close settled relaxed idle (ghost calmhover);7 character-specific pre-sleep yawn;8 lowering into seated/sleep pose, placing carried props beside character.
BOTTOM ROW:9 ASLEEP EXHALE;10 almost same ASLEEP INHALE with tiny shoulder/chest movement, props on ground stay fixed;11 WAKE stretching/peeking still seated;12 halfway STANDING UP retrieving carried props, leading naturally to idle1 (ghost rises with mug).
The entire sequence must preserve clothes, identity and carried accessories. Do not omit an item from a transition, and never duplicate arms. Natural character-specific behavior below overrides human anatomy for creatures.
IDENTITY: Small chibi hooded rogue boy, charcoal black hood, red scarf and short red cape, gray pants brown boots, small curved dagger held down and BACK in near hand, leather pouches. Near leg LIGHT gray foreground, far leg DARK charcoal.
SLEEP STORY: looks around sleepily, sheathes dagger, crouches then sits curled in cloak with hood down over eyes, sleeps cautiously. Wakes peeking from hood, rises and draws the same small dagger downward.
MOTION CHARACTER: quiet soft cautious footfalls, scarf trails, dagger points safely down/back
Final constraints: NO blurry glow, NO smoky background, NO backdrop colour whatsoever, only character with clear empty alpha. In anticipation frame3 ALL carried items must remain visibly in the SAME hands; do not hide or delete them.

## rain_fisher

### walk

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-d6d258f2-9322-4d48-a577-1e9f6c20dc3f.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet with EXACTLY8 frames in FOUR columns by TWO rows, chronological left-to-right top then bottom. TRUE TRANSPARENT alpha background. Equal cell spacing, large clear transparent gutters. All8 face RIGHT. Same character size, head and clothing proportions in every frame. No text, labels, floor, shadows, halo or extra props. Reference is exact character identity.
For walking characters: a full genuine8phase walking loop with alternating NEAR and FAR legs. Consistent natural lighting identifies legs: NEAR leg is LIGHTER and crosses in FRONT at hip, FAR leg darker and behind. Do not repeat the top row in the bottom row.
TOP ROW: 1 near LIGHT leg forward RIGHT heel strike, far DARK back LEFT toe. 2 near LIGHT planted forward right bearing weight bent knee, far DARK back heel lifts. 3 near LIGHT support under hip, FAR dark bent knee passes forward with foot hovering. 4 near LIGHT toe behind left, FAR dark knee lifted ahead right.
BOTTOM ROW: 5 near LIGHT leg goes BACK TO IMAGE LEFT and MUST CROSS IN FRONT of far DARK leg going forward RIGHT heel strike. 6 near LIGHT leg stays BACK LEFT with heel lifted and crosses in foreground, far DARK leg planted forward RIGHT supports weight. 7 FAR DARK support under hip, NEAR LIGHT knee bent passes forward with foot off ground. 8 FAR DARK leg back LEFT toe, NEAR LIGHT knee lifted ahead RIGHT preparing frame1.
Frames1/5 and2/6 MUST have opposite anatomical leg overlap, not only different stance. Passing frames3/7 have close horizontal feet, lifted knees. Legs attach plausibly to pelvis/chest. Small weight bob and natural secondary motion. Upperbody identity stable.
IDENTITY: Small chibi fisher boy in yellow rain hat and yellow coat, dark olive green trousers and brown boots, fishing rod with redwhite bobber in forward hand, small blue silver fish carried in rear/near hand. Near leg LIGHT moss olive, far leg DARK olive.
MOTION CHARACTER: easy strolling stride, coat hem and bobber sway with delayed small motion, always keeps rod and fish
Use real alpha transparency, completely empty surrounding pixels with NO smoky glow. Every carried prop must be clearly present in frame3 anticipation and all standing poses.

#### Refinement 1

Repair bottom row first TWO cells (frames5/6) ONLY in this4x2 walk sheet. Keep upper bodies, heads, fish and rods unchanged. The LIGHT OLIVE near trouser leg must extend BACK to image LEFT, with its brown boot at LEFT and knee crossing in FRONT at pelvis. The DARK OLIVE far leg goes FORWARD to image RIGHT with a dark boot planted. These must be opposite to top row1/2. In bottomrow3/4 lighter near knee lifts forward and darker far leg supports, keep that. Preserve true alpha and all8 cells. No extra legs.

#### Refinement 2

Repair bottom row first TWO cells (frames5/6) ONLY in this4x2 walk sheet. Keep upper bodies, heads, fish and rods unchanged. The LIGHT OLIVE near trouser leg must extend BACK to image LEFT, with its brown boot at LEFT and knee crossing in FRONT at pelvis. The DARK OLIVE far leg goes FORWARD to image RIGHT with a dark boot planted. These must be opposite to top row1/2. In bottomrow3/4 lighter near knee lifts forward and darker far leg supports, keep that. Preserve true alpha and all8 cells. No extra legs.

#### Refinement 3

Edit FIRST image, 4columns x2rows transparent walk sprite sheet. Correct leg layering in bottom row cells1 and2 ONLY (frames5and6). Use SECOND image as exact stance reference. The lighter olive foreground leg stretches BACK LEFT under the backpack, overlaps dark leg at crotch, brown foreground boot on LEFT. The darker shadowed leg stretches FORWARD RIGHT under rod and its boot on RIGHT. In frame6 lower the body slightly and bend bothknees maintaining this opposite leg order. Currently these frames repeat top row foot order; actually REDRAW crotch/leg overlap to change which leg passes IN FRONT. All other6cells and upper bodies in all8cells unchanged. Transparent background.

#### Refinement 4

One tiny localized correction to transparent4x2 walk sheet. TOP row sprites3and4: raised bent RIGHT leg is the FAR leg and must be DARK OLIVE with dark boot, behind the planted LEFT leg which is LIGHT OLIVE with lighter brown boot. Swap the current leg depth shading in these TWO sprites only without changing their positions or shapes. In BOTTOM row sprites5and6 shade forward RIGHT leg DARK OLIVE so rear LEFT near leg is clearly lighter, and its crossing edge is in foreground. Preserve all8upper bodies, faces, rod and fish, and allotherposes. True transparent background.

### behaviour

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-000eb23d-6cbb-4b31-8f16-afc32994c8d5.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet EXACTLY12 frames in FOUR columns by THREE rows, chronological row-major. TRUE alpha transparent background. Four equal columns, three clearly separated rows with WIDE empty gutters; no artwork crossing cells. Same character scale and head size in every pose, seated characters must be shorter without shrinking/enlarging head. All face RIGHT with same view as reference. No text, labels, borders, ground, stray shadows, invented props except specifically described sleep props. Keep props visibly attached to hands while standing and grounded only when sitting.
Frame order TOP ROW: 1 relaxed standing/hover idle EXHALE;2 same idle subtle INHALE;3 anticipation to start, feet together leaning right (ghost prepares hover);4 first SHORT STEP, near LIGHT forward right far DARK back left (ghost glides slightly).
MIDDLE ROW:5 stopping SHORT CONTACT, near LIGHT right/front far DARK left/back, torso slows (ghost settles);6 feet close settled relaxed idle (ghost calmhover);7 character-specific pre-sleep yawn;8 lowering into seated/sleep pose, placing carried props beside character.
BOTTOM ROW:9 ASLEEP EXHALE;10 almost same ASLEEP INHALE with tiny shoulder/chest movement, props on ground stay fixed;11 WAKE stretching/peeking still seated;12 halfway STANDING UP retrieving carried props, leading naturally to idle1 (ghost rises with mug).
The entire sequence must preserve clothes, identity and carried accessories. Do not omit an item from a transition, and never duplicate arms. Natural character-specific behavior below overrides human anatomy for creatures.
IDENTITY: Small chibi fisher boy in yellow rain hat and yellow coat, dark olive green trousers and brown boots, fishing rod with redwhite bobber in forward hand, small blue silver fish carried in rear/near hand. Near leg LIGHT moss olive, far leg DARK olive.
SLEEP STORY: yawns, settles seated with fishing rod leaned beside him at RIGHT and fish resting in a small bucket at his feet, hat over eyes while sleeping. Wakes lifting hat and picking up same rod and fish.
MOTION CHARACTER: easy strolling stride, coat hem and bobber sway with delayed small motion, always keeps rod and fish
Use real alpha transparency, completely empty surrounding pixels with NO smoky glow. Every carried prop must be clearly present in frame3 anticipation and all standing poses.

#### Refinement 1

Preserve this4x3 twelve-frame sheet except sleep prop continuity. Remove the metal bucket from all cells where it appears (middle-row last and allbottom-row cells). Instead, the SAME small blue-silver fish lies directly beside the seated fisher at RIGHT, near the leaning fishing rod in sleep cells8-11. In lastcell12 he has picked up fish and rod exactly as idle1, with NO bucket remaining. Allfaces/poses/clothes unchanged. Keep only the original rod and fish; no new props. Transparent alpha.

## necro_cat

### walk

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-8f00a063-32c7-414a-9db1-b70bec643187.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet with EXACTLY8 frames in FOUR columns by TWO rows, chronological left-to-right top then bottom. TRUE TRANSPARENT alpha background. Equal cell spacing, large clear transparent gutters. All8 face RIGHT. Same character size, head and clothing proportions in every frame. No text, labels, floor, shadows, halo or extra props. Reference is exact character identity.
For walking characters: a full genuine8phase walking loop with alternating NEAR and FAR legs. Consistent natural lighting identifies legs: NEAR leg is LIGHTER and crosses in FRONT at hip, FAR leg darker and behind. Do not repeat the top row in the bottom row.
TOP ROW: 1 near LIGHT leg forward RIGHT heel strike, far DARK back LEFT toe. 2 near LIGHT planted forward right bearing weight bent knee, far DARK back heel lifts. 3 near LIGHT support under hip, FAR dark bent knee passes forward with foot hovering. 4 near LIGHT toe behind left, FAR dark knee lifted ahead right.
BOTTOM ROW: 5 near LIGHT leg goes BACK TO IMAGE LEFT and MUST CROSS IN FRONT of far DARK leg going forward RIGHT heel strike. 6 near LIGHT leg stays BACK LEFT with heel lifted and crosses in foreground, far DARK leg planted forward RIGHT supports weight. 7 FAR DARK support under hip, NEAR LIGHT knee bent passes forward with foot off ground. 8 FAR DARK leg back LEFT toe, NEAR LIGHT knee lifted ahead RIGHT preparing frame1.
Frames1/5 and2/6 MUST have opposite anatomical leg overlap, not only different stance. Passing frames3/7 have close horizontal feet, lifted knees. Legs attach plausibly to pelvis/chest. Small weight bob and natural secondary motion. Upperbody identity stable.
IDENTITY: Cute small upright walking black cat necromancer, lime green eyes, purple hood and cloak, tiny satchel with glowing green vial, skull-topped wooden staff held forward RIGHT, skeletal mouse familiar stays near feet. Near hind leg LIGHT charcoal fur with visible paw, far leg nearly BLACK. Keep cat feline feet, no human boots.
MOTION CHARACTER: feline bipedal padding stride, tail curls and sways, staff carried consistently, skeletal mouse trots near feet
Use real alpha transparency, completely empty surrounding pixels with NO smoky glow. Every carried prop must be clearly present in frame3 anticipation and all standing poses.

#### Refinement 1

Precision repair of this8frame4column2row walk cycle. Preserve ALL heads, faces, upper bodies, accessories, size and grid. Edit ONLY the legs below the coat/hips. Use the original character natural colors.
Identity/leg materials: Cute small upright walking black cat necromancer, lime green eyes, purple hood and cloak, tiny satchel with glowing green vial, skull-topped wooden staff held forward RIGHT, skeletal mouse familiar stays near feet. Near hind leg LIGHT charcoal fur with visible paw, far leg nearly BLACK. Keep cat feline feet, no human boots.
The same NEAR leg must always have a LIGHTER surface and overlap the FAR DARKER leg at the hip. Correct the following cells:
Top row cells1/2 remain exactly unchanged: light near leg is forward RIGHT.
Top row cells3/4: LIGHT near leg is the supporting straight leg under/behind hip to LEFT. The lifted bent knee and foot ahead to RIGHT is the DARK FAR leg, visibly occluded behind near thigh. Do not raise the near leg in this half.
Bottom row cell1 (frame5): LIGHT foreground NEAR leg stretches BACK diagonally to image LEFT toe, from right-side hip down LEFT crossing IN FRONT of the DARK far leg which stretches FORWARD RIGHT heel. This MUST be opposite to top row cell1.
Bottom row cell2(frame6): SAME LIGHT foreground leg remains BACK LEFT with heel lifted, while DARK far leg is planted forward RIGHT supporting weight. Do not switch light leg forward here.
Bottom row cells3/4: FAR DARK leg supports vertically under/behind hip LEFT. LIGHT NEAR knee now raises FORWARD RIGHT, bent with foot off ground, preparing top-left contact. Passing cell3 has closer feet; cell4 knee is more forward.
Keep exactly TWO legs attached to body, plausible root/feline/humanoid anatomy per character, no duplicates. No other costume changes. Preserve transparency, no smoke or glow. No letters or marks. Also restore the tiny skeletal mouse next to the forward foot in bottom-right frame8, consistent with other7 cells; it must not disappear.

### behaviour

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-6dd43da8-1db7-435b-a09e-2eef04afb12c.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet EXACTLY12 frames in FOUR columns by THREE rows, chronological row-major. TRUE alpha transparent background. Four equal columns, three clearly separated rows with WIDE empty gutters; no artwork crossing cells. Same character scale and head size in every pose, seated characters must be shorter without shrinking/enlarging head. All face RIGHT with same view as reference. No text, labels, borders, ground, stray shadows, invented props except specifically described sleep props. Keep props visibly attached to hands while standing and grounded only when sitting.
Frame order TOP ROW: 1 relaxed standing/hover idle EXHALE;2 same idle subtle INHALE;3 anticipation to start, feet together leaning right (ghost prepares hover);4 first SHORT STEP, near LIGHT forward right far DARK back left (ghost glides slightly).
MIDDLE ROW:5 stopping SHORT CONTACT, near LIGHT right/front far DARK left/back, torso slows (ghost settles);6 feet close settled relaxed idle (ghost calmhover);7 character-specific pre-sleep yawn;8 lowering into seated/sleep pose, placing carried props beside character.
BOTTOM ROW:9 ASLEEP EXHALE;10 almost same ASLEEP INHALE with tiny shoulder/chest movement, props on ground stay fixed;11 WAKE stretching/peeking still seated;12 halfway STANDING UP retrieving carried props, leading naturally to idle1 (ghost rises with mug).
The entire sequence must preserve clothes, identity and carried accessories. Do not omit an item from a transition, and never duplicate arms. Natural character-specific behavior below overrides human anatomy for creatures.
IDENTITY: Cute small upright walking black cat necromancer, lime green eyes, purple hood and cloak, tiny satchel with glowing green vial, skull-topped wooden staff held forward RIGHT, skeletal mouse familiar stays near feet. Near hind leg LIGHT charcoal fur with visible paw, far leg nearly BLACK. Keep cat feline feet, no human boots.
SLEEP STORY: cat yawns, sets skull staff beside him at RIGHT, curls into purple cloak with skeletal mouse tucked against paws. Sleeps tail curled, wakes cat stretching front paw then stands and retrieves staff.
MOTION CHARACTER: feline bipedal padding stride, tail curls and sways, staff carried consistently, skeletal mouse trots near feet
Use real alpha transparency, completely empty surrounding pixels with NO smoky glow. Every carried prop must be clearly present in frame3 anticipation and all standing poses.

## chest_mimic

### walk

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-916e480d-655f-426d-b6b5-04ef2de5a9e1.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet with EXACTLY8 frames in FOUR columns by TWO rows, chronological left-to-right top then bottom. TRUE TRANSPARENT alpha background. Equal cell spacing, large clear transparent gutters. All8 face RIGHT. Same character size, head and clothing proportions in every frame. No text, labels, floor, shadows, halo or extra props. Reference is exact character identity.
For walking characters: a full genuine8phase walking loop with alternating NEAR and FAR legs. Consistent natural lighting identifies legs: NEAR leg is LIGHTER and crosses in FRONT at hip, FAR leg darker and behind. Do not repeat the top row in the bottom row.
TOP ROW: 1 near LIGHT leg forward RIGHT heel strike, far DARK back LEFT toe. 2 near LIGHT planted forward right bearing weight bent knee, far DARK back heel lifts. 3 near LIGHT support under hip, FAR dark bent knee passes forward with foot hovering. 4 near LIGHT toe behind left, FAR dark knee lifted ahead right.
BOTTOM ROW: 5 near LIGHT leg goes BACK TO IMAGE LEFT and MUST CROSS IN FRONT of far DARK leg going forward RIGHT heel strike. 6 near LIGHT leg stays BACK LEFT with heel lifted and crosses in foreground, far DARK leg planted forward RIGHT supports weight. 7 FAR DARK support under hip, NEAR LIGHT knee bent passes forward with foot off ground. 8 FAR DARK leg back LEFT toe, NEAR LIGHT knee lifted ahead RIGHT preparing frame1.
Frames1/5 and2/6 MUST have opposite anatomical leg overlap, not only different stance. Passing frames3/7 have close horizontal feet, lifted knees. Legs attach plausibly to pelvis/chest. Small weight bob and natural secondary motion. Upperbody identity stable.
IDENTITY: Cute wooden treasure chest mimic, gold metal bands and central latch, hinged partly open lid, big ivory teeth, one amber eye in dark mouth, long red tongue, two brown clawed monster legs under chest. No arms. Near leg LIGHT warm brown with ivory claws in foreground, far leg DARK brown shadow. Both feet remain physically attached to bottom of chest.
MOTION CHARACTER: comical heavy waddle using two alternating attached legs, chest rocks subtly, tongue and lid lag; no detached extra feet
True empty alpha, no surrounding glow or background. Pay special attention to natural NON-HUMAN root/monster legs and consistent accessories in anticipation pose3.

#### Refinement 1

Correct only BOTTOM ROW legs in this4x2 sheet. First2 bottom cells: NEAR lighter brown clawed leg attached to FRONT-facing right underside of chest must angle BACK LEFT and overlap IN FRONT of other leg. FAR darker brown leg attached to far underside goes FORWARD RIGHT. Feet reach opposite directions, connected by visible diagonal calves, exactly2 attached legs. Bottom3/4: far DARK leg planted under chest, near LIGHT leg lifted forward with bent knee. Keep chest, lid, tongue, eye, wood, claws style exactly. All8 cells with real alpha.

### behaviour

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-500e3a3b-7757-4714-b667-6e1b25a1d802.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet EXACTLY12 frames in FOUR columns by THREE rows, chronological row-major. TRUE alpha transparent background. Four equal columns, three clearly separated rows with WIDE empty gutters; no artwork crossing cells. Same character scale and head size in every pose, seated characters must be shorter without shrinking/enlarging head. All face RIGHT with same view as reference. No text, labels, borders, ground, stray shadows, invented props except specifically described sleep props. Keep props visibly attached to hands while standing and grounded only when sitting.
Frame order TOP ROW: 1 relaxed standing/hover idle EXHALE;2 same idle subtle INHALE;3 anticipation to start, feet together leaning right (ghost prepares hover);4 first SHORT STEP, near LIGHT forward right far DARK back left (ghost glides slightly).
MIDDLE ROW:5 stopping SHORT CONTACT, near LIGHT right/front far DARK left/back, torso slows (ghost settles);6 feet close settled relaxed idle (ghost calmhover);7 character-specific pre-sleep yawn;8 lowering into seated/sleep pose, placing carried props beside character.
BOTTOM ROW:9 ASLEEP EXHALE;10 almost same ASLEEP INHALE with tiny shoulder/chest movement, props on ground stay fixed;11 WAKE stretching/peeking still seated;12 halfway STANDING UP retrieving carried props, leading naturally to idle1 (ghost rises with mug).
The entire sequence must preserve clothes, identity and carried accessories. Do not omit an item from a transition, and never duplicate arms. Natural character-specific behavior below overrides human anatomy for creatures.
IDENTITY: Cute wooden treasure chest mimic, gold metal bands and central latch, hinged partly open lid, big ivory teeth, one amber eye in dark mouth, long red tongue, two brown clawed monster legs under chest. No arms. Near leg LIGHT warm brown with ivory claws in foreground, far leg DARK brown shadow. Both feet remain physically attached to bottom of chest.
SLEEP STORY: lid yawns wide with tongue, knees fold and chest rests on ground, lid closes nearly shut and tongue tucked, sleeps closed with tiny breathing lid movement. Wakes by opening lid and one eye, legs extend to stand.
MOTION CHARACTER: comical heavy waddle using two alternating attached legs, chest rocks subtly, tongue and lid lag; no detached extra feet
True empty alpha, no surrounding glow or background. Pay special attention to natural NON-HUMAN root/monster legs and consistent accessories in anticipation pose3.

## mushroom_grandpa

### walk

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-49486501-bc7a-41ed-b1ab-d1c001b38a97.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet with EXACTLY8 frames in FOUR columns by TWO rows, chronological left-to-right top then bottom. TRUE TRANSPARENT alpha background. Equal cell spacing, large clear transparent gutters. All8 face RIGHT. Same character size, head and clothing proportions in every frame. No text, labels, floor, shadows, halo or extra props. Reference is exact character identity.
For walking characters: a full genuine8phase walking loop with alternating NEAR and FAR legs. Consistent natural lighting identifies legs: NEAR leg is LIGHTER and crosses in FRONT at hip, FAR leg darker and behind. Do not repeat the top row in the bottom row.
TOP ROW: 1 near LIGHT leg forward RIGHT heel strike, far DARK back LEFT toe. 2 near LIGHT planted forward right bearing weight bent knee, far DARK back heel lifts. 3 near LIGHT support under hip, FAR dark bent knee passes forward with foot hovering. 4 near LIGHT toe behind left, FAR dark knee lifted ahead right.
BOTTOM ROW: 5 near LIGHT leg goes BACK TO IMAGE LEFT and MUST CROSS IN FRONT of far DARK leg going forward RIGHT heel strike. 6 near LIGHT leg stays BACK LEFT with heel lifted and crosses in foreground, far DARK leg planted forward RIGHT supports weight. 7 FAR DARK support under hip, NEAR LIGHT knee bent passes forward with foot off ground. 8 FAR DARK leg back LEFT toe, NEAR LIGHT knee lifted ahead RIGHT preparing frame1.
Frames1/5 and2/6 MUST have opposite anatomical leg overlap, not only different stance. Passing frames3/7 have close horizontal feet, lifted knees. Legs attach plausibly to pelvis/chest. Small weight bob and natural secondary motion. Upperbody identity stable.
IDENTITY: Tiny elderly woodland mushroom grandpa, large red mushroom cap with cream spots and little sprout, white mustache long white beard, mossy green hair, brown bark cloak, rootlike brown feet and green hands, copper watering can held forward RIGHT. Near root leg LIGHT golden bark and green moss cuff, far leg DARK brown bark.
MOTION CHARACTER: slow gentle creaky root steps, beard and cap softly respond; cap design same spots
True empty alpha, no surrounding glow or background. Pay special attention to natural NON-HUMAN root/monster legs and consistent accessories in anticipation pose3.

#### Refinement 1

Precision repair of this8frame4column2row walk cycle. Preserve ALL heads, faces, upper bodies, accessories, size and grid. Edit ONLY the legs below the coat/hips. Use the original character natural colors.
Identity/leg materials: Tiny elderly woodland mushroom grandpa, large red mushroom cap with cream spots and little sprout, white mustache long white beard, mossy green hair, brown bark cloak, rootlike brown feet and green hands, copper watering can held forward RIGHT. Near root leg LIGHT golden bark and green moss cuff, far leg DARK brown bark.
The same NEAR leg must always have a LIGHTER surface and overlap the FAR DARKER leg at the hip. Correct the following cells:
Top row cells1/2 remain exactly unchanged: light near leg is forward RIGHT.
Top row cells3/4: LIGHT near leg is the supporting straight leg under/behind hip to LEFT. The lifted bent knee and foot ahead to RIGHT is the DARK FAR leg, visibly occluded behind near thigh. Do not raise the near leg in this half.
Bottom row cell1 (frame5): LIGHT foreground NEAR leg stretches BACK diagonally to image LEFT toe, from right-side hip down LEFT crossing IN FRONT of the DARK far leg which stretches FORWARD RIGHT heel. This MUST be opposite to top row cell1.
Bottom row cell2(frame6): SAME LIGHT foreground leg remains BACK LEFT with heel lifted, while DARK far leg is planted forward RIGHT supporting weight. Do not switch light leg forward here.
Bottom row cells3/4: FAR DARK leg supports vertically under/behind hip LEFT. LIGHT NEAR knee now raises FORWARD RIGHT, bent with foot off ground, preparing top-left contact. Passing cell3 has closer feet; cell4 knee is more forward.
Keep exactly TWO legs attached to body, plausible root/feline/humanoid anatomy per character, no duplicates. No other costume changes. Preserve transparency, no smoke or glow. No letters or marks.

### behaviour

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-da79b3fb-4b6d-42e0-90ac-10acaa003d72.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet EXACTLY12 frames in FOUR columns by THREE rows, chronological row-major. TRUE alpha transparent background. Four equal columns, three clearly separated rows with WIDE empty gutters; no artwork crossing cells. Same character scale and head size in every pose, seated characters must be shorter without shrinking/enlarging head. All face RIGHT with same view as reference. No text, labels, borders, ground, stray shadows, invented props except specifically described sleep props. Keep props visibly attached to hands while standing and grounded only when sitting.
Frame order TOP ROW: 1 relaxed standing/hover idle EXHALE;2 same idle subtle INHALE;3 anticipation to start, feet together leaning right (ghost prepares hover);4 first SHORT STEP, near LIGHT forward right far DARK back left (ghost glides slightly).
MIDDLE ROW:5 stopping SHORT CONTACT, near LIGHT right/front far DARK left/back, torso slows (ghost settles);6 feet close settled relaxed idle (ghost calmhover);7 character-specific pre-sleep yawn;8 lowering into seated/sleep pose, placing carried props beside character.
BOTTOM ROW:9 ASLEEP EXHALE;10 almost same ASLEEP INHALE with tiny shoulder/chest movement, props on ground stay fixed;11 WAKE stretching/peeking still seated;12 halfway STANDING UP retrieving carried props, leading naturally to idle1 (ghost rises with mug).
The entire sequence must preserve clothes, identity and carried accessories. Do not omit an item from a transition, and never duplicate arms. Natural character-specific behavior below overrides human anatomy for creatures.
IDENTITY: Tiny elderly woodland mushroom grandpa, large red mushroom cap with cream spots and little sprout, white mustache long white beard, mossy green hair, brown bark cloak, rootlike brown feet and green hands, copper watering can held forward RIGHT. Near root leg LIGHT golden bark and green moss cuff, far leg DARK brown bark.
SLEEP STORY: yawns into beard, places copper watering can beside him at RIGHT, settles crosslegged into bark cloak under mushroom cap, beard rests on lap asleep. Wakes stretching mossy arms, rises and picks up can.
MOTION CHARACTER: slow gentle creaky root steps, beard and cap softly respond; cap design same spots
True empty alpha, no surrounding glow or background. Pay special attention to natural NON-HUMAN root/monster legs and consistent accessories in anticipation pose3.

## baker_dragon

### walk

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-97f6a46c-340a-4e06-a62f-74850ddbcb38.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet with EXACTLY8 frames in FOUR columns by TWO rows, chronological left-to-right top then bottom. TRUE TRANSPARENT alpha background. Equal cell spacing, large clear transparent gutters. All8 face RIGHT. Same character size, head and clothing proportions in every frame. No text, labels, floor, shadows, halo or extra props. Reference is exact character identity.
For walking characters: a full genuine8phase walking loop with alternating NEAR and FAR legs. Consistent natural lighting identifies legs: NEAR leg is LIGHTER and crosses in FRONT at hip, FAR leg darker and behind. Do not repeat the top row in the bottom row.
TOP ROW: 1 near LIGHT leg forward RIGHT heel strike, far DARK back LEFT toe. 2 near LIGHT planted forward right bearing weight bent knee, far DARK back heel lifts. 3 near LIGHT support under hip, FAR dark bent knee passes forward with foot hovering. 4 near LIGHT toe behind left, FAR dark knee lifted ahead right.
BOTTOM ROW: 5 near LIGHT leg goes BACK TO IMAGE LEFT and MUST CROSS IN FRONT of far DARK leg going forward RIGHT heel strike. 6 near LIGHT leg stays BACK LEFT with heel lifted and crosses in foreground, far DARK leg planted forward RIGHT supports weight. 7 FAR DARK support under hip, NEAR LIGHT knee bent passes forward with foot off ground. 8 FAR DARK leg back LEFT toe, NEAR LIGHT knee lifted ahead RIGHT preparing frame1.
Frames1/5 and2/6 MUST have opposite anatomical leg overlap, not only different stance. Passing frames3/7 have close horizontal feet, lifted knees. Legs attach plausibly to pelvis/chest. Small weight bob and natural secondary motion. Upperbody identity stable.
IDENTITY: Cute plump orange baby dragon standing on two hind legs, cream horns and belly, small turquoise wings, white baker apron with bread emblem, holds round baked loaf in both small front paws, orange tail with cream tip extends BACK LEFT. Near hind leg BRIGHT orange foreground with pale claws, far hind leg DARK burnt orange. Feline-like chunky haunch shape, no human pants or boots.
MOTION CHARACTER: cheerful plump dragon waddle with true alternating hind legs, tail and wings lag, loaf held in same front paws
Keep alpha clear, no background or environment glow. Do not lose carried props in anticipation frame3. For frog/dragon ensure light near leg is BACK LEFT in bottom-row first2 cells while DARK far leg is FRONT RIGHT.

#### Refinement 1

Repair ONLY LEGS in this8frame4x2 walk sheet. Keep heads, torso, hands, props and exact grid unchanged. Natural colors: Cute plump orange baby dragon standing on two hind legs, cream horns and belly, small turquoise wings, white baker apron with bread emblem, holds round baked loaf in both small front paws, orange tail with cream tip extends BACK LEFT. Near hind leg BRIGHT orange foreground with pale claws, far hind leg DARK burnt orange. Feline-like chunky haunch shape, no human pants or boots.
Frames1/2 (top-left two) remain unchanged with LIGHT near leg forward RIGHT.
Frames3/4 (top-right two): LIGHT near leg supports under/behind hip LEFT. FAR DARK leg is raised forward RIGHT with bent knee off ground. Do not put the light near leg up in this half.
Frames5/6 (bottom-left two): the SAME LIGHT near foreground leg goes BACK LEFT, crossing visibly in FRONT of far leg at pelvis. The FAR DARK leg goes forward RIGHT, heel/flat planted. Frame5 is wide contact, frame6 compressed down pose with near back heel raised. These must be the OPPOSITE leg overlap from frames1/2, not same leg again.
Frames7/8 (bottom-right two): DARK far leg supports under/behind hip LEFT. LIGHT near leg is raised forward RIGHT, knee bent and foot off ground, preparing frame1.
Near leg stays lighter, far leg darker in all8. Attached anatomically, exactly2 legs, no extra limbs. Keep creature haunches/boots/pants natural per identity. No changes above waist. Transparent alpha, no new effects.

#### Refinement 2

Fix ONE cell only, BOTTOM LEFT(frame5). Redraw its hindlegs: the large BRIGHT orange NEAR haunch should turn BACKWARDS under tail, with its BRIGHT orange near foot at IMAGE LEFT. This near haunch crosses IN FRONT of and hides the root of the other leg. A smaller DARK burnt-orange FAR leg emerges from under apron and reaches FORWARD to IMAGE RIGHT with dark orange foot. No large bright diagonal leg reaching forward right in this cell. Exactly2 anatomically attached dragon legs. Allupperbody and other7cells unchanged. Alpha transparent4x2grid.

### behaviour

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-0bd4ca1d-2f0c-4441-8e21-e6b75d386bc9.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet EXACTLY12 frames in FOUR columns by THREE rows, chronological row-major. TRUE alpha transparent background. Four equal columns, three clearly separated rows with WIDE empty gutters; no artwork crossing cells. Same character scale and head size in every pose, seated characters must be shorter without shrinking/enlarging head. All face RIGHT with same view as reference. No text, labels, borders, ground, stray shadows, invented props except specifically described sleep props. Keep props visibly attached to hands while standing and grounded only when sitting.
Frame order TOP ROW: 1 relaxed standing/hover idle EXHALE;2 same idle subtle INHALE;3 anticipation to start, feet together leaning right (ghost prepares hover);4 first SHORT STEP, near LIGHT forward right far DARK back left (ghost glides slightly).
MIDDLE ROW:5 stopping SHORT CONTACT, near LIGHT right/front far DARK left/back, torso slows (ghost settles);6 feet close settled relaxed idle (ghost calmhover);7 character-specific pre-sleep yawn;8 lowering into seated/sleep pose, placing carried props beside character.
BOTTOM ROW:9 ASLEEP EXHALE;10 almost same ASLEEP INHALE with tiny shoulder/chest movement, props on ground stay fixed;11 WAKE stretching/peeking still seated;12 halfway STANDING UP retrieving carried props, leading naturally to idle1 (ghost rises with mug).
The entire sequence must preserve clothes, identity and carried accessories. Do not omit an item from a transition, and never duplicate arms. Natural character-specific behavior below overrides human anatomy for creatures.
IDENTITY: Cute plump orange baby dragon standing on two hind legs, cream horns and belly, small turquoise wings, white baker apron with bread emblem, holds round baked loaf in both small front paws, orange tail with cream tip extends BACK LEFT. Near hind leg BRIGHT orange foreground with pale claws, far hind leg DARK burnt orange. Feline-like chunky haunch shape, no human pants or boots.
SLEEP STORY: yawns showing tiny teeth, sets loaf safely on folded apron beside him, curls into tail with wings folded and loaf hugged to belly asleep, wakes stretching little wings, rises cradling loaf.
MOTION CHARACTER: cheerful plump dragon waddle with true alternating hind legs, tail and wings lag, loaf held in same front paws
Keep alpha clear, no background or environment glow. Do not lose carried props in anticipation frame3. For frog/dragon ensure light near leg is BACK LEFT in bottom-row first2 cells while DARK far leg is FRONT RIGHT.

## blanket_ghost

### walk

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-cd39621e-1531-4d56-b23b-9d990a81838b.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet with EXACTLY8 frames in FOUR columns by TWO rows, chronological left-to-right top then bottom. TRUE TRANSPARENT alpha background. Equal cell spacing, large clear transparent gutters. All8 face RIGHT. Same character size, head and clothing proportions in every frame. No text, labels, floor, shadows, halo or extra props. Reference is exact character identity.
For walking characters: a full genuine8phase walking loop with alternating NEAR and FAR legs. Consistent natural lighting identifies legs: NEAR leg is LIGHTER and crosses in FRONT at hip, FAR leg darker and behind. Do not repeat the top row in the bottom row.
TOP ROW: 1 near LIGHT leg forward RIGHT heel strike, far DARK back LEFT toe. 2 near LIGHT planted forward right bearing weight bent knee, far DARK back heel lifts. 3 near LIGHT support under hip, FAR dark bent knee passes forward with foot hovering. 4 near LIGHT toe behind left, FAR dark knee lifted ahead right.
BOTTOM ROW: 5 near LIGHT leg goes BACK TO IMAGE LEFT and MUST CROSS IN FRONT of far DARK leg going forward RIGHT heel strike. 6 near LIGHT leg stays BACK LEFT with heel lifted and crosses in foreground, far DARK leg planted forward RIGHT supports weight. 7 FAR DARK support under hip, NEAR LIGHT knee bent passes forward with foot off ground. 8 FAR DARK leg back LEFT toe, NEAR LIGHT knee lifted ahead RIGHT preparing frame1.
Frames1/5 and2/6 MUST have opposite anatomical leg overlap, not only different stance. Passing frames3/7 have close horizontal feet, lifted knees. Legs attach plausibly to pelvis/chest. Small weight bob and natural secondary motion. Upperbody identity stable.
IDENTITY: Cute cream-white little ghost with two dark oval eyes, wrapped in teal navy checkered fringed blanket, holds small brown hot tea mug forward RIGHT with faint curl of steam. NO legs, NO feet, NO knees, floats on softly scalloped ghost hem.
MOTION CHARACTER: smooth8frame hover loop, rise/crest/fall/trough spread across8 frames, blanket fringe and steam gently trail; no walking feet
IMPORTANT OVERRIDE: ghost has absolutely NO LEGS. Replace the8 leg phase instructions with continuous sinusoidal hovering: middle, rising, high, descending, middle, falling, low, rising. Only ghost and blanket deform subtly. Same mug held throughout.
Keep alpha clear, no background or environment glow. Do not lose carried props in anticipation frame3. For frog/dragon ensure light near leg is BACK LEFT in bottom-row first2 cells while DARK far leg is FRONT RIGHT.

### behaviour

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-11d5c71a-65ab-4935-9a54-d8237dd95ced.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet EXACTLY12 frames in FOUR columns by THREE rows, chronological row-major. TRUE alpha transparent background. Four equal columns, three clearly separated rows with WIDE empty gutters; no artwork crossing cells. Same character scale and head size in every pose, seated characters must be shorter without shrinking/enlarging head. All face RIGHT with same view as reference. No text, labels, borders, ground, stray shadows, invented props except specifically described sleep props. Keep props visibly attached to hands while standing and grounded only when sitting.
Frame order TOP ROW: 1 relaxed standing/hover idle EXHALE;2 same idle subtle INHALE;3 anticipation to start, feet together leaning right (ghost prepares hover);4 first SHORT STEP, near LIGHT forward right far DARK back left (ghost glides slightly).
MIDDLE ROW:5 stopping SHORT CONTACT, near LIGHT right/front far DARK left/back, torso slows (ghost settles);6 feet close settled relaxed idle (ghost calmhover);7 character-specific pre-sleep yawn;8 lowering into seated/sleep pose, placing carried props beside character.
BOTTOM ROW:9 ASLEEP EXHALE;10 almost same ASLEEP INHALE with tiny shoulder/chest movement, props on ground stay fixed;11 WAKE stretching/peeking still seated;12 halfway STANDING UP retrieving carried props, leading naturally to idle1 (ghost rises with mug).
The entire sequence must preserve clothes, identity and carried accessories. Do not omit an item from a transition, and never duplicate arms. Natural character-specific behavior below overrides human anatomy for creatures.
IDENTITY: Cute cream-white little ghost with two dark oval eyes, wrapped in teal navy checkered fringed blanket, holds small brown hot tea mug forward RIGHT with faint curl of steam. NO legs, NO feet, NO knees, floats on softly scalloped ghost hem.
SLEEP STORY: eyes droop, lowers floating body near ground and puts tea mug beside him at RIGHT, wraps blanket around himself like a little sleeping mound with closed eyes, breaths subtly; wakes peeking out of plaid blanket and picks up tea, floats up.
MOTION CHARACTER: smooth8frame hover loop, rise/crest/fall/trough spread across8 frames, blanket fringe and steam gently trail; no walking feet
Keep alpha clear, no background or environment glow. Do not lose carried props in anticipation frame3. For frog/dragon ensure light near leg is BACK LEFT in bottom-row first2 cells while DARK far leg is FRONT RIGHT.

## frog_samurai

### walk

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-6ba7f2cc-efc8-4d3a-b210-c161bd40671b.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet with EXACTLY8 frames in FOUR columns by TWO rows, chronological left-to-right top then bottom. TRUE TRANSPARENT alpha background. Equal cell spacing, large clear transparent gutters. All8 face RIGHT. Same character size, head and clothing proportions in every frame. No text, labels, floor, shadows, halo or extra props. Reference is exact character identity.
For walking characters: a full genuine8phase walking loop with alternating NEAR and FAR legs. Consistent natural lighting identifies legs: NEAR leg is LIGHTER and crosses in FRONT at hip, FAR leg darker and behind. Do not repeat the top row in the bottom row.
TOP ROW: 1 near LIGHT leg forward RIGHT heel strike, far DARK back LEFT toe. 2 near LIGHT planted forward right bearing weight bent knee, far DARK back heel lifts. 3 near LIGHT support under hip, FAR dark bent knee passes forward with foot hovering. 4 near LIGHT toe behind left, FAR dark knee lifted ahead right.
BOTTOM ROW: 5 near LIGHT leg goes BACK TO IMAGE LEFT and MUST CROSS IN FRONT of far DARK leg going forward RIGHT heel strike. 6 near LIGHT leg stays BACK LEFT with heel lifted and crosses in foreground, far DARK leg planted forward RIGHT supports weight. 7 FAR DARK support under hip, NEAR LIGHT knee bent passes forward with foot off ground. 8 FAR DARK leg back LEFT toe, NEAR LIGHT knee lifted ahead RIGHT preparing frame1.
Frames1/5 and2/6 MUST have opposite anatomical leg overlap, not only different stance. Passing frames3/7 have close horizontal feet, lifted knees. Legs attach plausibly to pelvis/chest. Small weight bob and natural secondary motion. Upperbody identity stable.
IDENTITY: Cute upright green frog samurai, huge bright eye, broad straw conical hat, navy kimono tied with orange-red belt, sheathed katana extends BACK LEFT at waist, bare webbed frog feet. Near leg BRIGHT lime green foreground, far leg DARK olive green. Keep webbed toes and bent frog anatomy, no human shoes.
MOTION CHARACTER: disciplined soft bipedal frog stride, webbed toes flex, knees pass clearly, straw hat and sheathed sword maintain size
Keep alpha clear, no background or environment glow. Do not lose carried props in anticipation frame3. For frog/dragon ensure light near leg is BACK LEFT in bottom-row first2 cells while DARK far leg is FRONT RIGHT.

#### Refinement 1

Fix bottom row SECOND cell ONLY (frame6) of this4x2 walking sheet. Make the BACKWARD leg to image LEFT the LIGHT LIME near foreground leg, crossing in FRONT of far thigh at pelvis, heel lifted. Make the FORWARD leg to image RIGHT the DARK OLIVE far leg with webbed foot planted. Match same light-left/dark-right leg overlap as bottomrowFIRST cell. Keep allother7cells exact. Preserve frog anatomy and webbed feet, allupperbody, hat, belt, sword, true alpha.

### behaviour

Selected source: `C:\Users\Edward\.codex\generated_images\01a0da0a-ca14-7101-bd7d-54096c1dedc1\exec-f3cfd7b3-14ad-40e8-8689-8bfa7af9e8df.png`

#### Initial prompt

Create ONE clean pixel-art sprite sheet EXACTLY12 frames in FOUR columns by THREE rows, chronological row-major. TRUE alpha transparent background. Four equal columns, three clearly separated rows with WIDE empty gutters; no artwork crossing cells. Same character scale and head size in every pose, seated characters must be shorter without shrinking/enlarging head. All face RIGHT with same view as reference. No text, labels, borders, ground, stray shadows, invented props except specifically described sleep props. Keep props visibly attached to hands while standing and grounded only when sitting.
Frame order TOP ROW: 1 relaxed standing/hover idle EXHALE;2 same idle subtle INHALE;3 anticipation to start, feet together leaning right (ghost prepares hover);4 first SHORT STEP, near LIGHT forward right far DARK back left (ghost glides slightly).
MIDDLE ROW:5 stopping SHORT CONTACT, near LIGHT right/front far DARK left/back, torso slows (ghost settles);6 feet close settled relaxed idle (ghost calmhover);7 character-specific pre-sleep yawn;8 lowering into seated/sleep pose, placing carried props beside character.
BOTTOM ROW:9 ASLEEP EXHALE;10 almost same ASLEEP INHALE with tiny shoulder/chest movement, props on ground stay fixed;11 WAKE stretching/peeking still seated;12 halfway STANDING UP retrieving carried props, leading naturally to idle1 (ghost rises with mug).
The entire sequence must preserve clothes, identity and carried accessories. Do not omit an item from a transition, and never duplicate arms. Natural character-specific behavior below overrides human anatomy for creatures.
IDENTITY: Cute upright green frog samurai, huge bright eye, broad straw conical hat, navy kimono tied with orange-red belt, sheathed katana extends BACK LEFT at waist, bare webbed frog feet. Near leg BRIGHT lime green foreground, far leg DARK olive green. Keep webbed toes and bent frog anatomy, no human shoes.
SLEEP STORY: closes eyes to meditate, sits crosslegged and rests sheathed katana beside him, nods asleep beneath straw hat, breathes gently, wakes with attentive blink and stretch, stands and takes sheathed katana.
MOTION CHARACTER: disciplined soft bipedal frog stride, webbed toes flex, knees pass clearly, straw hat and sheathed sword maintain size
Keep alpha clear, no background or environment glow. Do not lose carried props in anticipation frame3. For frog/dragon ensure light near leg is BACK LEFT in bottom-row first2 cells while DARK far leg is FRONT RIGHT.
