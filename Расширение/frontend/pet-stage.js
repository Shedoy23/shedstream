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
    // Sprint 5.22 patch (2026-05-20): body color через CSS variables
    // (--pet-body-{mid,stroke}). Background slot не рендерится отдельным
    // слоем, а добавляет CSS-класс .pet-stage--{item_id} который
    // переопределяет переменные → creature перекрашивается.
    //
    // Использован solid fill (не gradient) потому что несколько inline-SVG
    // с одинаковым gradient ID де-дуплицируются браузером и все ссылаются
    // на первое определение → cross-stage цвет ломается. «Глубину» даёт
    // highlight + shadow ellipses поверх плоского fill.
    function _buildCreatureSvg() {
        return `
            <svg viewBox="0 0 180 180" xmlns="http://www.w3.org/2000/svg"
                 class="pet-stage__creature">
                <!-- Body — solid mid цвет + highlight + shadow для объёма -->
                <ellipse cx="90" cy="100" rx="60" ry="62"
                         style="fill: var(--pet-body-mid, #a855f7);
                                stroke: var(--pet-body-stroke, #4c1d95);"
                         stroke-width="1.5"/>
                <!-- Highlight (light top-left) -->
                <ellipse cx="72" cy="75" rx="28" ry="20"
                         style="fill: var(--pet-body-light, #d8b4fe);"
                         opacity="0.45"/>
                <!-- Shadow (dark bottom-right) -->
                <ellipse cx="110" cy="135" rx="38" ry="22"
                         style="fill: var(--pet-body-dark, #6b21a8);"
                         opacity="0.35"/>
                <!-- Belly highlight (subtle white) -->
                <ellipse cx="90" cy="128" rx="30" ry="12"
                         fill="#ffffff" opacity="0.10"/>
                <!-- Cheeks (за глазами для теплоты) — solid pink с opacity -->
                <ellipse cx="62"  cy="106" rx="9" ry="5" fill="#fb7185" opacity="0.55"/>
                <ellipse cx="118" cy="106" rx="9" ry="5" fill="#fb7185" opacity="0.55"/>
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
    }
    const CREATURE_SVG = _buildCreatureSvg();  // backward-compat экспорт

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
        return `
            <div class="pet-stage pet-stage--hatched ${bgClass} ${className}"
                 style="--pet-stage-size:${size}px;">
                ${auraHtml}
                <div class="pet-stage__base">${CREATURE_SVG}</div>
                ${body ? `<div class="pet-stage__slot pet-stage__slot--body">${_renderItem(body)}</div>` : ''}
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
        CREATURE_SVG: CREATURE_SVG,
    };
})(typeof window !== 'undefined' ? window : globalThis);
