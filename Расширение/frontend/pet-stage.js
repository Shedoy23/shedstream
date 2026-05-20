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

    // ── Inline SVG creature (post-hatch) ─────────────────────────────────────
    // Дизайн: универсальный фиолетовый blob с лицом. Кросс-возрастной
    // (узнаваемый и для детей и для взрослой аудитории), не привязан к
    // конкретному животному (cat/dog могут оттолкнуть фанатов другого).
    // Eyes простые точки чтобы очки сверху ложились читаемо.
    const CREATURE_SVG = `
        <svg viewBox="0 0 180 180" xmlns="http://www.w3.org/2000/svg"
             class="pet-stage__creature">
            <defs>
                <radialGradient id="pet-body-grad" cx="38%" cy="32%" r="70%">
                    <stop offset="0%"   stop-color="#d8b4fe"/>
                    <stop offset="60%"  stop-color="#a855f7"/>
                    <stop offset="100%" stop-color="#6b21a8"/>
                </radialGradient>
                <radialGradient id="pet-cheek-grad" cx="50%" cy="50%" r="50%">
                    <stop offset="0%"   stop-color="#fb7185" stop-opacity="0.8"/>
                    <stop offset="100%" stop-color="#fb7185" stop-opacity="0"/>
                </radialGradient>
            </defs>
            <!-- Body — округлый blob -->
            <ellipse cx="90" cy="100" rx="60" ry="62"
                     fill="url(#pet-body-grad)"
                     stroke="#4c1d95" stroke-width="1.5"/>
            <!-- Highlight на животе -->
            <ellipse cx="90" cy="125" rx="32" ry="14"
                     fill="#ffffff" opacity="0.13"/>
            <!-- Cheeks (за глазами для теплоты) -->
            <ellipse cx="62"  cy="106" rx="9" ry="5" fill="url(#pet-cheek-grad)"/>
            <ellipse cx="118" cy="106" rx="9" ry="5" fill="url(#pet-cheek-grad)"/>
            <!-- Eyes (whites) -->
            <ellipse cx="72"  cy="88" rx="9.5" ry="10" fill="white"/>
            <ellipse cx="108" cy="88" rx="9.5" ry="10" fill="white"/>
            <!-- Pupils -->
            <ellipse cx="74"  cy="90" rx="4.5" ry="5" fill="#1a1a1c"/>
            <ellipse cx="110" cy="90" rx="4.5" ry="5" fill="#1a1a1c"/>
            <!-- Pupil shines -->
            <circle cx="75.5"  cy="88" r="1.6" fill="white"/>
            <circle cx="111.5" cy="88" r="1.6" fill="white"/>
            <!-- Mouth -->
            <path d="M 80 112 Q 90 119 100 112"
                  stroke="#1a1a1c" stroke-width="2.5"
                  fill="none" stroke-linecap="round"/>
        </svg>
    `;

    // ── Item renderer ─────────────────────────────────────────────────────────
    // Item может содержать svg_path (inline SVG) или fallback на emoji.
    // svg_path — относительный path внутри 180×180 viewBox, или полный
    // svg-тег. Сейчас фиксируем как inline SVG (если есть) либо просто emoji.
    function _renderItem(item) {
        if (!item) return '';
        if (item.svg_path) {
            // svg_path = либо целый <svg>...</svg>, либо path-content.
            // Если начинается с <svg → используем как есть; иначе wrapping
            // в стандартный 180×180 viewBox.
            const sp = item.svg_path.trim();
            if (sp.startsWith('<svg')) return sp;
            return `<svg viewBox="0 0 180 180" xmlns="http://www.w3.org/2000/svg">${sp}</svg>`;
        }
        return _esc(item.emoji || '');
    }

    // ── Public render ─────────────────────────────────────────────────────────
    /**
     * @param {object} pet       — {pet_type, name, ...}
     * @param {object} equipped  — {slot: item, ...}
     * @param {object} [opts]    — {size: 180, className: ''}
     * @returns {string} innerHTML
     */
    function renderHtml(pet, equipped, opts) {
        pet      = pet      || {pet_type: 'egg'};
        equipped = equipped || {};
        opts     = opts     || {};
        const size       = opts.size || 180;
        const className  = opts.className || '';
        const hatched    = pet.pet_type && pet.pet_type !== 'egg';

        const bg  = equipped.background;
        const aura = equipped.aura;
        const head = equipped.head;
        const face = equipped.face;
        const body = equipped.body;
        const acc  = equipped.accessory;

        // background — большой blurred emoji за всем
        const bgHtml = bg
            ? `<div class="pet-stage__bg">${_renderItem(bg)}</div>`
            : '';
        // aura — пульсирующее свечение
        const auraHtml = aura
            ? `<div class="pet-stage__aura">${_renderItem(aura)}</div>`
            : '';

        // Pre-hatch — только яйцо, items не показываем (юзер ещё не купил
        // ничего — у egg'а нет эквипа). Багаж backwards-compat: если у
        // незарасклюнутого pet'а каким-то образом всплыли equip'ы — игнор.
        if (!hatched) {
            return `
                <div class="pet-stage ${className}" style="--pet-stage-size:${size}px;">
                    ${bgHtml}
                    ${auraHtml}
                    <div class="pet-stage__egg">🥚</div>
                </div>
            `;
        }

        // Post-hatch — full creature stack
        return `
            <div class="pet-stage pet-stage--hatched ${className}"
                 style="--pet-stage-size:${size}px;">
                ${bgHtml}
                ${auraHtml}
                <div class="pet-stage__base">${CREATURE_SVG}</div>
                ${body ? `<div class="pet-stage__slot pet-stage__slot--body">${_renderItem(body)}</div>` : ''}
                ${face ? `<div class="pet-stage__slot pet-stage__slot--face">${_renderItem(face)}</div>` : ''}
                ${head ? `<div class="pet-stage__slot pet-stage__slot--head">${_renderItem(head)}</div>` : ''}
                ${acc  ? `<div class="pet-stage__slot pet-stage__slot--accessory">${_renderItem(acc)}</div>`  : ''}
            </div>
        `;
    }

    function _esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
            '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
        }[c]));
    }

    global.PetStage = {
        renderHtml: renderHtml,
        escapeHtml: _esc,
        CREATURE_SVG: CREATURE_SVG,
    };
})(typeof window !== 'undefined' ? window : globalThis);
