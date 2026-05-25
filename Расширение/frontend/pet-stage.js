// pet-stage.js — Sprint 5.21 (2026-05-20) shared pet rendering.
//
// До 5.21: pets.js модалка и overlay.html рендерили pet'а как стек emoji
// (head + pet_emoji + accessory в одной строке). Шапка просто рядом
// с яйцом, очки и шарф оба «accessory» рендерились в одной точке.
//
// Sprint 5.21: универсальный creature (inline SVG) + 6 семантических
// slots (head/face/body/accessory/background/aura), каждый item рендерится
// в правильной CSS-позиции. Pre-hatch (pet_type='egg') показываем 🥚 —
// post-hatch SVG-creature с надетыми items.
//
// Public API:
//   PetStage.renderHtml(pet, equipped, opts?) → string (innerHTML)
//   PetStage.escapeHtml(s) → safe text
//
// Используется:
//   - pets.js  (extension.html + mobile.html → JWT-auth modal)
//   - overlay.html  (active viewers strip без auth)

(function (global) {
    'use strict';

    // ── Pixel-art PNG creature (Sprint 5.28, 2026-05-24) ────────────────────
    // До 5.28: inline SVG blob с ellipses (smooth slime). Items от Claude
    // Design были pixel-art и плохо ложились на smooth творение.
    //
    // 5.28: переход на pixel-art creature от PixelLab — 104×104 PNG с
    // 8-direction rotation. Два варианта (kimono dressed / underwear base).
    // CSS image-rendering: pixelated сохраняет chunky pixels при scaling
    // с 104px source до 64-180px рендера.
    //
    // Pet-asset path: frontend/pet-assets/v2/{variant}/{direction}.png
    // где variant = 'kimono' | 'underwear', direction = 'south' | 'east' | ...
    //
    // Backward-compat: CREATURE_SVG экспорт — старый код может его звать,
    // возвращаем wrapper image вместо SVG.
    const PET_ASSET_BASE = 'pet-assets/v2';
    const DEFAULT_VARIANT = 'kimono';   // default: dressed character (не «голый младенец»)
    const DEFAULT_DIRECTION = 'south';

    function _buildCreatureImg(variant, direction) {
        variant   = variant   || DEFAULT_VARIANT;
        direction = direction || DEFAULT_DIRECTION;
        const src = `${PET_ASSET_BASE}/${variant}/${direction}.png`;
        return `<img src="${src}" class="pet-stage__creature"
                     alt="pet creature" draggable="false"/>`;
    }
    const CREATURE_SVG = _buildCreatureImg();  // backward-compat экспорт

    // ── Item renderer ─────────────────────────────────────────────────────────
    // Sprint 5.28: emoji fallback УБРАН. Items рендерятся ТОЛЬКО как
    // pixel-art assets:
    //   - item.svg_path → inline SVG (от Claude Design)
    //   - item.png_path → PNG <img> (от PixelLab generations)
    // Item с одним только emoji полем НЕ рендерится (silently ignored).
    // Это потому что pixel-art creature + Unicode emoji ставят визуальный
    // диссонанс — кепка-emoji флоатит над pixel-головой неконсистентно.
    //
    // Каждый item — full 180×180 (или 104×104) overlay. Position анкоров
    // baked-in в самом sprite'е, slot CSS даёт только z-stack и full-cover.
    function _renderItem(item) {
        if (!item) return '';
        if (item.svg_path) {
            const sp = item.svg_path.trim();
            if (sp.startsWith('<svg')) return sp;
            return `<svg viewBox="0 0 180 180" xmlns="http://www.w3.org/2000/svg">${sp}</svg>`;
        }
        if (item.png_path) {
            return `<img src="${item.png_path}" class="pet-stage__item-img"
                         alt="" draggable="false"/>`;
        }
        // Emoji-only items не рендерятся в pixel-art эстетике.
        return '';
    }

    // ── Public render ─────────────────────────────────────────────────────────
    /**
     * @param {object} pet       — {pet_type, name, ...}
     * @param {object} equipped  — {slot: item, ...}
     * @param {object} [opts]    — {size: 180, className: '', variant: 'kimono', direction: 'south'}
     * @returns {string} innerHTML
     */
    function renderHtml(pet, equipped, opts) {
        pet      = pet      || {pet_type: 'egg'};
        equipped = equipped || {};
        opts     = opts     || {};
        const size       = opts.size || 180;
        const className  = opts.className || '';
        const direction  = opts.direction || DEFAULT_DIRECTION;
        const hatched    = pet.pet_type && pet.pet_type !== 'egg';

        const bg  = equipped.background;
        const aura = equipped.aura;
        const head = equipped.head;
        const face = equipped.face;
        const body = equipped.body;
        const acc  = equipped.accessory;

        // Sprint 5.28: body slot может содержать SKIN-item (skin_kimono/skin_underwear),
        // который меняет character variant вместо overlay-рендера. Convention по
        // item_id префиксу 'skin_'. Если найден — extract variant name + НЕ рендерим
        // body как item-слой (он становится частью creature'а сам).
        let variant = opts.variant || DEFAULT_VARIANT;
        let bodySkinOverride = false;
        if (body && typeof body.item_id === 'string' && body.item_id.startsWith('skin_')) {
            const v = body.item_id.slice(5);  // 'skin_kimono' → 'kimono'
            if (v === 'kimono' || v === 'underwear') {
                variant = v;
                bodySkinOverride = true;
            }
        }

        // Sprint 5.22 patch: background теперь = окрас creature'а (CSS-класс
        // .pet-stage--{bg_item_id} переопределяет --pet-body-* переменные).
        // Старый bg-emoji слой убран — конфликтовал с аурой визуально.
        const bgClass = bg && bg.item_id ? `pet-stage--${bg.item_id}` : '';
        // aura — 6 particle на clock-позициях со staggered pulse.
        const auraHtml = aura
            ? `<div class="pet-stage__aura">${_renderAuraParticles(aura)}</div>`
            : '';

        // Pre-hatch — только яйцо, items не показываем (юзер ещё не купил
        // ничего — у egg'а нет эквипа). Багаж backwards-compat: если у
        // незарасклюнутого pet'а каким-то образом всплыли equip'ы — игнор.
        if (!hatched) {
            return `
                <div class="pet-stage ${bgClass} ${className}" style="--pet-stage-size:${size}px;">
                    ${auraHtml}
                    <div class="pet-stage__egg">🥚</div>
                </div>
            `;
        }

        // Post-hatch — full creature stack
        const creatureImg = _buildCreatureImg(variant, direction);
        // Если body — skin-override, не рендерим его как item-слой (variant уже
        // отражён в creature itself). Иначе обычный body item overlay.
        const bodyItemHtml = (body && !bodySkinOverride)
            ? `<div class="pet-stage__slot pet-stage__slot--body">${_renderItem(body)}</div>`
            : '';
        return `
            <div class="pet-stage pet-stage--hatched ${bgClass} ${className}"
                 style="--pet-stage-size:${size}px;">
                ${auraHtml}
                <div class="pet-stage__base">${creatureImg}</div>
                ${bodyItemHtml}
                ${face ? `<div class="pet-stage__slot pet-stage__slot--face">${_renderItem(face)}</div>` : ''}
                ${head ? `<div class="pet-stage__slot pet-stage__slot--head">${_renderItem(head)}</div>` : ''}
                ${acc  ? `<div class="pet-stage__slot pet-stage__slot--accessory">${_renderItem(acc)}</div>`  : ''}
            </div>
        `;
    }

    // Sprint 5.22 patch: render 6 копий aura content'а как particles
    // с CSS-классами .pet-stage__aura-particle--n0..n5. Каждая получает
    // свою позицию + animation-delay из CSS.
    function _renderAuraParticles(aura) {
        const content = _renderItem(aura);
        let html = '';
        for (let i = 0; i < 6; i++) {
            html += `<span class="pet-stage__aura-particle pet-stage__aura-particle--n${i}">${content}</span>`;
        }
        return html;
    }

    function _esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
            '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
        }[c]));
    }

    global.PetStage = {
        renderHtml: renderHtml,
        escapeHtml: _esc,
        CREATURE_SVG: CREATURE_SVG,           // legacy export (now returns img tag)
        buildCreatureImg: _buildCreatureImg,  // (variant, direction) → img html
        VARIANTS:   ['kimono', 'underwear'],
        DIRECTIONS: ['south', 'south-east', 'east', 'north-east',
                     'north', 'north-west', 'west', 'south-west'],
    };
})(typeof window !== 'undefined' ? window : globalThis);
