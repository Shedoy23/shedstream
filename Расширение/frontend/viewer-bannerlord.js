// viewer-bannerlord.js — Bannerlord-специфичный код, вынесенный из viewer.js (ROADMAP 2.4).
//
// Грузится ПОСЛЕ viewer.js — использует его CORE-глобалы (API_URL, authToken,
// escapeHtml, showNotification, _bannerlordBuyAction, _bannerlordTournament и пр.
// state-переменные), которые к моменту парса этого файла уже определены.
// В core ОСТАЮТСЯ: switchIntegrationModule, _startBannerlordPolling/_stopBannerlordPolling
// (зовутся при переключении модуля) + _bannerlordBuyAction-диспетчер (пока).
// Поведение НЕ менялось — только перенос. По одному куску за сессию.
//
// Чанк 1 (2026-06-13): Турнир зрителей (loadBannerlordTournament + render + predict).

// ===== Sprint 5.3: Турнир зрителей (BLT-style) =====
async function loadBannerlordTournament() {
    const body = document.getElementById('bannerlord-tournament-body');
    const badge = document.getElementById('bannerlord-tournament-status');
    if (!body || !badge) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/tournament`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        const data = await r.json();
        if (!data.success) {
            body.innerHTML = `<div style="color:#f87171;padding:8px;font-size:12px;">${escapeHtml(data.message || 'ошибка')}</div>`;
            return;
        }
        _bannerlordTournament = data;
        _renderBannerlordTournament(data);
    } catch (e) {
        // silent
    }
}

function _renderBannerlordTournament(data) {
    const body = document.getElementById('bannerlord-tournament-body');
    const badge = document.getElementById('bannerlord-tournament-status');
    if (!body || !badge) return;

    const state = data.state || {};
    const queue = data.queue || [];
    const cfg = data.config || {};
    // Sprint 5.28: цена в крустиках. Backend шлёт config.join_price (default 1000).
    const joinPrice = (cfg.join_price ?? 1000);
    const joinPriceText = joinPrice.toLocaleString('ru-RU');

    // Status badge
    if (state.status === 'running') {
        badge.textContent = `⚔️ раунд ${(state.current_round || 0) + 1}/4`;
        badge.style.color = '#fbbf24';
    } else {
        badge.textContent = `idle (${queue.length})`;
        badge.style.color = '#9ca3af';
    }

    if (state.status === 'running') {
        // RUNNING — участники + прогноз победителя (бесплатно)
        const participants = state.participants || [];
        const myBet = data.my_bet;

        let participantsHtml;
        if (myBet) {
            participantsHtml = `
                <div style="font-size:12px;color:#34d399;padding:6px;background:rgba(52,211,153,0.1);border-radius:4px;margin-bottom:6px;">
                    🔮 Твой прогноз: <b>${escapeHtml(myBet.target)}</b>
                </div>`;
        } else {
            participantsHtml = `
                <div style="font-size:11px;color:#adadb8;margin-bottom:4px;">🔮 Угадай победителя — бесплатно, за верный прогноз бонус:</div>
                <div style="display:grid;grid-template-columns:1fr auto;gap:4px;align-items:center;">
                    ${participants.map(p => `
                        <span style="font-size:12px;">⚔️ ${escapeHtml(p)}</span>
                        <button class="extra-btn bnr-predict-btn" data-target="${escapeHtml(p)}"
                                style="font-size:11px;padding:3px 8px;">Прогноз</button>
                    `).join('')}
                </div>`;
        }

        body.innerHTML = `
            <div style="padding:8px;">
                <div style="font-size:12px;color:#fbbf24;font-weight:700;margin-bottom:6px;">
                    🏆 Турнир идёт — раунд ${(state.current_round || 0) + 1}/4
                </div>
                ${participantsHtml}
                ${state.last_winner ? `<div style="font-size:11px;color:#adadb8;margin-top:6px;">Прошлый победитель: <b>${escapeHtml(state.last_winner)}</b></div>` : ''}
            </div>`;

        // Bind prediction buttons
        body.querySelectorAll('.bnr-predict-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const target = btn.getAttribute('data-target');
                _promptBannerlordPredict(target);
            });
        });
        return;
    }

    // IDLE — show queue + join button
    const inQueue = !!data.in_queue;

    const queueHtml = queue.length === 0
        ? '<div style="font-size:11px;color:#9ca3af;padding:4px 0;">очередь пуста</div>'
        : `<div style="font-size:11px;color:#adadb8;margin:4px 0 2px 0;">В очереди (${queue.length}/16):</div>` +
          queue.map((q, i) => `
            <div style="display:flex;justify-content:space-between;font-size:11px;padding:1px 6px;
                        ${q.username === data.my_username ? 'background:rgba(251,191,36,0.1);' : ''}">
                <span>${i + 1}. ${escapeHtml(q.username)}</span>
                <span style="color:#9ca3af;">${q.class_key || ''}</span>
            </div>`).join('');

    const joinBtnHtml = inQueue
        ? `<div style="font-size:12px;color:#34d399;text-align:center;padding:6px;background:rgba(52,211,153,0.1);border-radius:4px;margin-top:6px;">
                ✅ Ты в очереди, ждём пока стример запустит турнир
           </div>`
        : `<button class="extra-btn" id="bnr-join-tournament-btn"
                  title="${joinPrice > 0 ? `Списывает ${joinPriceText} крустиков` : 'Бесплатно'}"
                  style="margin-top:6px;width:100%;font-size:12px;padding:8px;">
                ⚔️ Вступить в турнир${joinPrice > 0 ? ` (${joinPriceText}💎)` : ' (бесплатно)'}
           </button>`;

    body.innerHTML = `
        <div style="padding:8px;">
            <div style="font-size:11px;color:#adadb8;margin-bottom:4px;">
                Когда стример запустит — все из очереди дерутся, победитель получает ${TOURNAMENT_PRIZE_GOLD.toLocaleString('ru-RU')}💰 + XP + приз. Раундовые победители получают ${TOURNAMENT_ROUND_GOLD.toLocaleString('ru-RU')}💰.
            </div>
            ${queueHtml}
            ${joinBtnHtml}
            ${state.last_winner ? `<div style="font-size:11px;color:#adadb8;margin-top:6px;text-align:center;">🏆 Прошлый победитель: <b>${escapeHtml(state.last_winner)}</b></div>` : ''}
        </div>`;

    const joinBtn = document.getElementById('bnr-join-tournament-btn');
    if (joinBtn) {
        joinBtn.dataset.bnrCd = 'hero.join_tournament';   // кулдаун на кнопке
        joinBtn.addEventListener('click', () => {
            // Sprint 5.28: backend сам ставит price=1000💎; шлём 0 — он перепишет.
            _bannerlordBuyAction('hero.join_tournament', { price: 0 });
        });
    }
}

const TOURNAMENT_PRIZE_GOLD = 50000;
const TOURNAMENT_ROUND_GOLD = 10000;

function _promptBannerlordPredict(target) {
    // Подтверждение прогноза победителя — бесплатно, без ставки.
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;z-index:9999;';
    overlay.innerHTML = `
        <div style="background:#18181b;border:1px solid #3d3d3f;border-radius:8px;padding:20px;max-width:320px;">
            <h3 style="margin:0 0 12px 0;font-size:14px;color:#efeff1;">🔮 Прогноз: победит @${escapeHtml(target)}?</h3>
            <div style="font-size:11px;color:#adadb8;margin-bottom:12px;">
                Бесплатно — крустики не тратятся. Угадаешь победителя турнира — получишь бонус.
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                <button class="extra-btn" id="bnr-predict-confirm" style="font-size:12px;padding:8px;">Сделать прогноз</button>
                <button class="extra-btn" id="bnr-predict-cancel" style="font-size:12px;padding:8px;background:#3d3d3f;">Отмена</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);

    document.getElementById('bnr-predict-confirm').addEventListener('click', () => {
        overlay.remove();
        _bannerlordBuyAction('tournament.bet', { target });
    });
    document.getElementById('bnr-predict-cancel').addEventListener('click', () => overlay.remove());
    overlay.addEventListener('click', e => {
        if (e.target === overlay) overlay.remove();
    });
}


// ===== Sprint 5.8: Focus / Attribute investments (Hero.Gold cost) — split чанк 2 (2026-06-13) =====
// NB: BNR_SKILL_LABELS_RU также используется hero-card в viewer.js (пока в core) —
// она ссылается на эту консту кросс-файлово в рантайме (top-level const видна всем
// классическим скриптам). Когда hero-card переедет сюда — связь станет внутрифайловой.
const BNR_SKILLS = [
    'OneHanded', 'TwoHanded', 'Polearm', 'Bow', 'Crossbow', 'Throwing',
    'Athletics', 'Riding', 'Crafting', 'Scouting', 'Tactics', 'Roguery',
    'Charm', 'Leadership', 'Trade', 'Steward', 'Medicine', 'Engineering',
];
const BNR_SKILL_LABELS_RU = {
    OneHanded: 'Одноручное', TwoHanded: 'Двуручное', Polearm: 'Древковое',
    Bow: 'Лук', Crossbow: 'Арбалет', Throwing: 'Метательное',
    Athletics: 'Атлетика', Riding: 'Верховая езда', Crafting: 'Кузнечное',
    Scouting: 'Разведка', Tactics: 'Тактика', Roguery: 'Бесчестие',
    Charm: 'Обаяние', Leadership: 'Лидерство', Trade: 'Торговля',
    Steward: 'Управление', Medicine: 'Медицина', Engineering: 'Инженерия',
};
const BNR_ATTRIBUTES = ['Vigor', 'Control', 'Endurance', 'Cunning', 'Social', 'Intelligence'];
const BNR_ATTR_LABELS_RU = {
    Vigor: 'Сила', Control: 'Точность',
    Endurance: 'Выносливость', Cunning: 'Хитрость',
    Social: 'Социальность', Intelligence: 'Интеллект',
};
// Sprint 5.17: vanilla Bannerlord skill→attribute mapping. Атрибут даёт
// +1 cap к skill за каждое очко (max 30 cap при attr=10).
const BNR_ATTR_TO_SKILLS = {
    Vigor:        ['OneHanded', 'TwoHanded', 'Polearm'],
    Control:      ['Bow', 'Crossbow', 'Throwing'],
    Endurance:    ['Riding', 'Athletics', 'Crafting'],
    Cunning:      ['Scouting', 'Tactics', 'Roguery'],
    Social:       ['Charm', 'Leadership', 'Trade'],
    Intelligence: ['Steward', 'Medicine', 'Engineering'],
};
const BNR_ATTR_ICONS = {
    Vigor: '💪', Control: '🎯', Endurance: '⛰️',
    Cunning: '🦊', Social: '💬', Intelligence: '📚',
};
const BNR_FOCUS_TIER_COSTS = [30000, 40000, 50000, 60000, 75000];
const BNR_ATTRIBUTE_COST = 50000;

// Sprint 5.8 → 5.8c: ранее был renderBannerlordProgressionHtml (dropdown в shop)
// + _bindBannerlordProgression. Удалено в 5.8c — invest-кнопки перенесены
// внутрь progression-секции (per-row + buttons). См. loadBannerlordProgression.

// Sprint 5.8: Progression modal — отображает все скиллы (level + focus stars)
// + 6 атрибутов. Открывается по кнопке "🎯 Прогрессия" в hero card.
function loadBannerlordProgression() {
    const slot = document.getElementById('bnr-progression-slot');
    if (!slot) return;
    const data = _bannerlordLastHero;
    if (!data || !data.has_hero) { _smartInnerHTML(slot, ''); return; }
    const skills = data.skills || [];
    const attrs = data.attributes || {};

    // Sprint 5.27v: runtime canary — словить contract drift сразу. Если
    // backend начнёт отдавать другой shape (e.g. изменится capitalization
    // или ключи), DevTools console сразу покажет проблему вместо тихого
    // "0/10 везде". Это профилактика для skills/equipment/etc. в будущем.
    const attrKeys = Object.keys(attrs);
    if (attrKeys.length > 0 && BNR_ATTRIBUTES.every(k =>
            attrs[k] === undefined && attrs[k.toLowerCase()] === undefined)) {
        console.warn('[BNR contract drift] attributes object has keys but ' +
                     'none match expected:', attrKeys,
                     'expected one of:', BNR_ATTRIBUTES);
    }

    // Build skill lookup
    const skillsByKey = {};
    for (const s of skills) skillsByKey[s.skill_key] = s;

    // Helper: render одну skill row
    function _renderSkillRow(key) {
        const s = skillsByKey[key] || { skill_key: key, level: 0, focus: 0 };
        const focus = s.focus || 0;
        const focusStars = '★'.repeat(focus) + '☆'.repeat(5 - focus);
        const label = BNR_SKILL_LABELS_RU[key] || key;
        const lvlColor = s.level >= 100 ? '#fbbf24' : (s.level >= 50 ? '#34d399' : '#efeff1');
        const maxed = focus >= 5;
        const nextCost = maxed ? 0 : BNR_FOCUS_TIER_COSTS[focus];
        const btnTitle = maxed
            ? 'F5 максимум'
            : `+1 focus в ${label} → F${focus + 1}. Списать ${nextCost.toLocaleString('ru-RU')}💰 динаров.`;
        return `
            <div style="display:flex;justify-content:space-between;align-items:center;
                        padding:3px 6px 3px 14px;font-size:11px;gap:8px;
                        border-bottom:1px solid rgba(255,255,255,0.05);">
                <span style="color:#efeff1;flex:1;">└ ${escapeHtml(label)}</span>
                <span style="color:#fbbf24;font-family:monospace;letter-spacing:1px;">${focusStars}</span>
                <span style="color:${lvlColor};min-width:30px;text-align:right;
                             font-family:monospace;font-weight:700;">${s.level || 0}</span>
                <button class="small-btn bnr-prog-focus-btn"
                        data-skill="${escapeHtml(key)}"
                        ${maxed ? 'disabled' : ''}
                        title="${escapeHtml(btnTitle)}"
                        style="padding:2px 8px;font-size:11px;background:#3d3d3f;
                               color:#fbbf24;font-weight:700;
                               ${maxed ? 'opacity:0.3;cursor:not-allowed;' : ''}">
                    🎯+
                </button>
            </div>`;
    }

    // Render: attribute header + nested skills (Sprint 5.17 group-by-attribute)
    // Sprint 5.27u: case-insensitive lookup — backend хранит attribute keys в
    // lowercase (engine StringId), frontend BNR_ATTRIBUTES в PascalCase.
    // Без fallback'а на toLowerCase() все viewer'ы видели 0/10 несмотря на
    // корректные value в БД.
    const groupedRows = BNR_ATTRIBUTES.map(attrKey => {
        const val = attrs[attrKey] ?? attrs[attrKey.toLowerCase()] ?? 0;
        const filled = '●'.repeat(val) + '○'.repeat(10 - val);
        const attrLabel = BNR_ATTR_LABELS_RU[attrKey] || attrKey;
        const attrIcon = BNR_ATTR_ICONS[attrKey] || '·';
        const valColor = val >= 8 ? '#fbbf24' : (val >= 5 ? '#34d399' : '#efeff1');
        const maxed = val >= 10;
        const btnTitle = maxed
            ? '10/10 максимум'
            : `+1 в ${attrLabel} → ${val + 1}/10. Списать ${BNR_ATTRIBUTE_COST.toLocaleString('ru-RU')}💰 динаров.`;

        const childSkills = (BNR_ATTR_TO_SKILLS[attrKey] || []).map(_renderSkillRow).join('');

        return `
            <div style="background:rgba(147,197,253,0.06);border-top:1px solid rgba(147,197,253,0.15);
                        padding:5px 6px;display:flex;justify-content:space-between;
                        align-items:center;font-size:11px;gap:8px;font-weight:700;">
                <span style="color:#93c5fd;flex:1;">${attrIcon} ${escapeHtml(attrLabel)}</span>
                <span style="color:#93c5fd;font-family:monospace;letter-spacing:1px;font-weight:400;">${filled}</span>
                <span style="color:${valColor};min-width:36px;text-align:right;
                             font-family:monospace;">${val}/10</span>
                <button class="small-btn bnr-prog-attr-btn"
                        data-attr="${escapeHtml(attrKey)}"
                        ${maxed ? 'disabled' : ''}
                        title="${escapeHtml(btnTitle)}"
                        style="padding:2px 8px;font-size:11px;background:#3d3d3f;
                               color:#93c5fd;font-weight:700;
                               ${maxed ? 'opacity:0.3;cursor:not-allowed;' : ''}">
                    💪+
                </button>
            </div>
            ${childSkills}`;
    }).join('');

    const html = `
        <div style="font-size:11px;color:#adadb8;margin-bottom:6px;line-height:1.4;">
            💪 Атрибут (50K💰) — cap трёх скиллов · 🎯 Фокус (30-75K💰) — скорость скилла.
        </div>
        <div>${groupedRows}</div>`;
    if (!_smartInnerHTML(slot, html)) return;   // repaint+rebind лишь при изменении

    slot.querySelectorAll('.bnr-prog-focus-btn').forEach(btn => {
        btn.dataset.bnrCd = 'hero.add_focus';
        btn.addEventListener('click', () => {
            _bannerlordBuyAction('hero.add_focus', { skill_key: btn.getAttribute('data-skill'), amount: 1 });
            if (typeof loadBannerlordHero === 'function') loadBannerlordHero();
        });
    });
    slot.querySelectorAll('.bnr-prog-attr-btn').forEach(btn => {
        btn.dataset.bnrCd = 'hero.add_attribute';
        btn.addEventListener('click', () => {
            _bannerlordBuyAction('hero.add_attribute', { attribute_key: btn.getAttribute('data-attr'), amount: 1 });
            if (typeof loadBannerlordHero === 'function') loadBannerlordHero();
        });
    });
}

// ===== Workshops (мастерские, пассивный доход) — split чанк 3 (2026-06-13) =====
// _BNR_WORKSHOP_TYPES + loadBannerlordWorkshops + _renderBuyWorkshopInline.
// Core-хелперы (_bnr*, _bannerlordBuyAction, _bnrFetchSettlements) — forward; callers рантайм.
// Sprint 5.33 WORKSHOP-FIX (2026-05-28): IDs aligned с engine spworkshops.xml.
// Раньше silversmith/wood_workshop возвращали MBObjectManager null →
// мод REFUSE'нул с refund. Engine использует silversmithy + wood_WorkshopType
// (последнее — TaleWorlds vanilla typo, не наш). Все ID проверены против
// SandBox/ModuleData/spworkshops.xml для 1.3.15.
const _BNR_WORKSHOP_TYPES = [
    { id: 'brewery',          name: 'Пивоварня',         emoji: '🍺' },
    { id: 'smithy',           name: 'Кузница',           emoji: '⚒' },
    { id: 'wool_weavery',     name: 'Шерстяная ткацкая', emoji: '🐑' },
    { id: 'linen_weavery',    name: 'Льняная ткацкая',   emoji: '🌾' },
    { id: 'tannery',          name: 'Дубильня',          emoji: '🐄' },
    { id: 'pottery_shop',     name: 'Гончарня',          emoji: '🏺' },
    { id: 'olive_press',      name: 'Маслодавильня',     emoji: '🫒' },
    { id: 'wine_press',       name: 'Винодельня',        emoji: '🍷' },
    { id: 'velvet_weavery',   name: 'Бархатная ткацкая', emoji: '👘' },
    { id: 'silversmithy',     name: 'Серебряных дел',    emoji: '🥈' },
    { id: 'wood_WorkshopType', name: 'Древоделия',       emoji: '🪵' },
];

async function loadBannerlordWorkshops() {
    const slot = document.getElementById('bnr-workshops-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/my-workshops`, {
            headers: { 'X-Twitch-JWT': authToken || '' }
        }).then(r => r.json()).catch(() => ({success: false}));

        // FLICKER-FIX v6 (2026-05-29): skip update на backend error — last good
        // render остаётся. Иначе section мерцает каждые ~8s при transient blip.
        if (!r || r.success === false) return;

        const workshops = Array.isArray(r.workshops) ? r.workshops : [];
        const maxWorkshops = r.max_workshops || 3;

        // Sprint 5.33 CURRENCY-1 — clear price display + Hero.Gold visible.
        const WORKSHOP_CRUSTIC = 2500;     // 2026-05-29: чистая 💎 (цена поднята 1000→2500)
        const WORKSHOP_DINAR_EST = 0;      // капитал НЕ списывался — миф убран
        const wsAfford = _bnrAfford(WORKSHOP_CRUSTIC, WORKSHOP_DINAR_EST);

        // FLICKER-FIX v4: НЕ показываем live balance strip в header.
        // Balance меняется каждый poll → html string differs → cache miss →
        // repaint каждые 8s — видимый flicker. Balance виден в buy modal
        // и в main extension header (там обновляется ниже poll throttle).
        let html = `
            <div style="background:#1a2008;border:1px solid #65a30d;border-radius:4px;
                        padding:8px;font-size:11px;color:#d9f99d;">
                <div style="font-size:12px;font-weight:700;color:#84cc16;margin-bottom:4px;">
                    🏭 Мои мастерские (${workshops.length}/${maxWorkshops})
                </div>
                <div style="font-size:9px;color:#9ca3af;margin-bottom:6px;">
                    Пассивный доход в 💰 динарах — копятся в Hero.Gold (на gear/smith/marriage)
                </div>`;

        if (workshops.length > 0) {
            html += `<div style="display:flex;flex-direction:column;gap:4px;margin-bottom:6px;">`;
            for (const w of workshops) {
                const typeEntry = _BNR_WORKSHOP_TYPES.find(t => t.id === w.workshop_type)
                                  || { emoji: '🏭', name: w.workshop_type_name || w.workshop_type };
                html += `
                    <div data-workshop-id="${w.id}"
                         style="background:#0a1308;padding:6px 8px;border-radius:3px;
                                display:flex;justify-content:space-between;align-items:center;">
                        <div style="flex:1;">
                            <div style="color:#d9f99d;font-size:11px;">
                                ${typeEntry.emoji} <strong>${escapeHtml(typeEntry.name)}</strong>
                                <span style="color:#9ca3af;"> · ${escapeHtml(w.settlement_name || w.settlement_id)}</span>
                            </div>
                            <div style="font-size:10px;color:#65a30d;margin-top:2px;">
                                <span style="color:#9ca3af;">Заработано:</span>
                                <span style="color:#fbbf24;font-weight:700;">💰 ${(w.total_profit || 0).toLocaleString('ru-RU')}</span>
                            </div>
                        </div>
                        <button class="bnr-ws-sell small-btn"
                                title="Продать (50% refund от engine)"
                                style="font-size:9px;padding:2px 6px;background:#9a3412;
                                       color:#fed7aa;">💸 Продать</button>
                    </div>`;
            }
            html += `</div>`;
        }

        if (workshops.length < maxWorkshops) {
            const btnBg = wsAfford.ok ? '#65a30d' : '#3f3f0b';
            const btnOpacity = wsAfford.ok ? '1' : '0.65';
            // 2026-06-07 — покупка мастерской инлайн (lazy <details>): radio-тип +
            // <select>-город переживают 8s-poll (форма рендерится при раскрытии).
            html += `
                <details data-bnr-details="ws-buy" ${_bnrDetailsAttr('ws-buy')}>
                    <summary title="${escapeHtml(_bnrAffordTooltip(WORKSHOP_CRUSTIC, WORKSHOP_DINAR_EST))}"
                             style="list-style:none;cursor:pointer;width:100%;
                                    font-size:11px;padding:6px;background:${btnBg};box-sizing:border-box;
                                    color:#fff;font-weight:700;opacity:${btnOpacity};
                                    border-radius:3px;text-align:center;">
                        🏭 Купить мастерскую — ${_bnrPriceHtml(WORKSHOP_CRUSTIC, WORKSHOP_DINAR_EST)}
                    </summary>
                    <div id="bnr-ws-buy-slot" style="padding-top:6px;"></div>
                </details>`;
        } else {
            html += `
                <div style="font-size:10px;color:#6b7280;text-align:center;">
                    Лимит мастерских (${maxWorkshops}/${maxWorkshops})
                </div>`;
        }
        html += `</div>`;
        // 2026-06-07 FLICKER — пока форма покупки раскрыта, НЕ перерисовываем секцию
        // (иначе тик дохода стирает выбор/ввод). Возобновится когда юзер закроет форму.
        if (slot.querySelector('[data-bnr-details="ws-buy"]')?.open) return;
        // FLICKER-FIX: dedupe — skip rebind если HTML identical (избежать
        // double-handlers на sell/buy buttons).
        if (!_smartInnerHTML(slot, html)) return;

        // Bind sell buttons.
        slot.querySelectorAll('.bnr-ws-sell').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const parent = e.target.closest('[data-workshop-id]');
                if (!parent) return;
                if (!await _bnrConfirm('Продать мастерскую? Получишь ~50% refund.')) return;
                const wsId = parseInt(parent.dataset.workshopId, 10);
                await _bannerlordBuyAction('hero.sell_workshop', { workshop_id: wsId });
                setTimeout(loadBannerlordWorkshops, 1500);
            });
        });

        const _wsDet = slot.querySelector('[data-bnr-details="ws-buy"]');
        if (_wsDet) {
            _wsDet.addEventListener('toggle', () => { if (_wsDet.open) _renderBuyWorkshopInline(); });
            if (_wsDet.open) _renderBuyWorkshopInline();
        }
    } catch (e) {
        // FLICKER-FIX v6 — НЕ clear на exception. Last good render survives.
        console.warn('[FE-SHOP] loadWorkshops failed (keeping last render):', e);
    }
}

// удалена: инлайн lazy-форма покупки мастерской (_renderBuyWorkshopInline).
function _renderBuyWorkshopInline() {
    const slot = document.getElementById('bnr-ws-buy-slot');
    if (!slot) return;
    slot.innerHTML = `
        <div style="background:#1a2008;border:1px solid #65a30d;border-radius:4px;
                    padding:10px;color:#d9f99d;">
            <div style="display:flex;gap:6px;font-size:11px;margin-bottom:10px;
                        background:#0a1308;padding:6px 8px;border-radius:3px;">
                <div style="flex:1;">
                    <div style="color:#9ca3af;font-size:9px;">Стоимость:</div>
                    <div style="font-size:13px;font-weight:700;">
                        ${_bnrPriceHtml(1000, 20000)}
                    </div>
                </div>
                <div style="flex:1;border-left:1px solid #1f2937;padding-left:8px;">
                    <div style="color:#9ca3af;font-size:9px;">У тебя:</div>
                    <div style="font-size:11px;">
                        <span style="color:#a5f3fc;">💎 ${(_cachedUserPoints||0).toLocaleString('ru-RU')}</span>
                        <span style="color:#6b7280;">|</span>
                        <span style="color:#fbbf24;">💰 ${((_bannerlordLastHero?.hero?.gold)||0).toLocaleString('ru-RU')}</span>
                    </div>
                </div>
            </div>
            <div style="font-size:10px;color:#9ca3af;margin-bottom:10px;line-height:1.4;">
                <div>💎 — entry fee, списывается с твоего 💎 балланса</div>
                <div>💰 — initial capital, списывается с Hero.Gold (engine)</div>
                <div>📈 Профит копится в Hero.Gold (динары — на gear/smith/marriage)</div>
            </div>
            <label style="font-size:11px;color:#d9f99d;display:block;margin-bottom:4px;">
                Тип мастерской:
            </label>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:3px;margin-bottom:10px;">
                ${_BNR_WORKSHOP_TYPES.map((t, i) => `
                    <label style="display:flex;align-items:center;gap:4px;
                                  background:#0a1308;padding:5px 6px;border-radius:3px;
                                  cursor:pointer;font-size:10px;">
                        <input type="radio" name="bnr-ws-type" value="${t.id}"
                               data-name="${escapeHtml(t.name)}" ${i === 0 ? 'checked' : ''}>
                        <span style="color:#d9f99d;">${t.emoji} ${escapeHtml(t.name)}</span>
                    </label>
                `).join('')}
            </div>
            <label style="font-size:11px;color:#d9f99d;display:block;margin-bottom:4px;">
                Town (выбери из engine catalog):
            </label>
            <div id="bnr-ws-town-slot" style="margin-bottom:10px;">
                <div style="font-size:11px;color:#9ca3af;padding:6px;">
                    ⏳ Загружается список городов...
                </div>
            </div>
            <button id="bnr-ws-buy-confirm" class="extra-btn"
                    style="width:100%;font-size:11px;padding:6px;
                           background:#65a30d;color:#fff;font-weight:700;">
                🏭 Купить — ${_bnrPriceHtml(1000, 20000)}
            </button>
        </div>`;
    // CATALOG-3: load real engine towns в dropdown
    _bnrFetchSettlements().then(byType => {
        const townSlot = document.getElementById('bnr-ws-town-slot');
        if (townSlot) {
            townSlot.innerHTML = _bnrRenderSettlementSelect(byType.town || [],
                { id: 'bnr-ws-town' });
        }
    });
    document.getElementById('bnr-ws-buy-confirm')?.addEventListener('click', async () => {
        const typeSel = slot.querySelector('input[name="bnr-ws-type"]:checked');
        const townSel = document.getElementById('bnr-ws-town');
        const townId = (townSel?.value || '').trim();
        const townName = townSel?.tagName === 'SELECT'
            ? (townSel.options[townSel.selectedIndex]?.dataset?.name || townId)
            : townId;
        if (!typeSel) {
            showNotification('Выбери тип мастерской', 'warning');
            return;
        }
        if (!townId) {
            showNotification('Выбери town из списка', 'warning');
            return;
        }
        // 2026-06-07 FLICKER — закрыть форму ДО refresh, иначе freeze-guard
        // заблокирует перерисовку секции (и даёт мгновенный фидбек на клик).
        document.querySelector('[data-bnr-details="ws-buy"]')?.removeAttribute('open');
        await _bannerlordBuyAction('hero.buy_workshop', {
            settlement_id:      townId,
            settlement_name:    townName,
            workshop_type:      typeSel.value,
            workshop_type_name: typeSel.dataset.name,
        });
        setTimeout(loadBannerlordWorkshops, 2000);
    });
}

// ===== Fiefs / Caravans / Inheritance (пассивный доход) — split чанк 4 (2026-06-13) =====
// loadBannerlordFiefs, loadBannerlordCaravans(+_renderBuyCaravanInline),
// loadBannerlordCaravanRescues, loadBannerlordInheritance. Core _bnr* forward; callers рантайм.
// Sprint 5.33 (BLT-parity FIEF) — Fief tribute passive income panel.
// Read-only view (owned fiefs come from in-game ownership). Active feature:
// tribute_boost — 2000💎 → 7-day +50% multiplier на один fief.

async function loadBannerlordFiefs() {
    const slot = document.getElementById('bnr-fiefs-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/my-fiefs`, {
            headers: { 'X-Twitch-JWT': authToken || '' }
        }).then(r => r.json()).catch(() => ({success: false}));

        // FLICKER-FIX v6 (2026-05-29): skip update на backend error — last good
        // render остаётся видимым через transient blips.
        if (!r || r.success === false) return;

        const fiefs = Array.isArray(r.fiefs) ? r.fiefs : [];
        // FLICKER-FIX v6: при genuine empty state (0 fiefs) — render stable
        // placeholder через _smartInnerHTML вместо slot.innerHTML='' (последний
        // вариант → repaint каждый poll → flicker). _smartInnerHTML dedupe
        // identical HTML → repaint только при изменении.
        if (fiefs.length === 0) {
            _smartInnerHTML(slot, '');  // dedupe even empty
            return;
        }

        const typeEmoji = { town: '🏛', castle: '🏰', village: '🏘' };
        const typeLabel = { town: 'Город', castle: 'Замок', village: 'Деревня' };
        const boostPct  = Math.round(((r.boost_mult || 1.5) - 1) * 100);
        const boostDays = r.boost_days || 7;

        // FLICKER-FIX v4: balance strip убран.
        let html = `
            <div style="background:#1a1308;border:1px solid #b45309;border-radius:4px;
                        padding:8px;font-size:11px;color:#fed7aa;">
                <div style="font-size:12px;font-weight:700;color:#f59e0b;margin-bottom:4px;">
                    👑 Мои владения
                </div>
                <div style="font-size:9px;color:#9ca3af;margin-bottom:6px;">
                    Tribute passive в 💰 динарах — копятся в Hero.Gold
                </div>
                <div style="display:flex;flex-direction:column;gap:4px;margin-bottom:6px;">
                ${fiefs.map(f => {
                    const emoji = typeEmoji[f.fief_type] || '🏛';
                    const lbl   = typeLabel[f.fief_type] || f.fief_type;
                    return `
                    <div data-fief-id="${f.id}"
                         style="background:#0f0805;padding:6px 8px;border-radius:3px;
                                display:flex;justify-content:space-between;align-items:center;
                                ${f.boost_active ? 'border:1px solid #facc15;' : ''}">
                        <div style="flex:1;">
                            <div style="color:#fed7aa;font-size:11px;">
                                ${emoji} <strong>${escapeHtml(f.fief_name || f.fief_id)}</strong>
                                <span style="color:#9ca3af;font-size:10px;"> · ${lbl}</span>
                                ${f.boost_active ? '<span style="color:#facc15;font-size:9px;font-weight:700;"> ⚡ BOOST</span>' : ''}
                            </div>
                            <div style="font-size:10px;margin-top:2px;">
                                <span style="color:#9ca3af;">Заработано:</span>
                                <span style="color:#fbbf24;font-weight:700;">💰 ${(f.total_collected_dinars || 0).toLocaleString('ru-RU')}</span>
                            </div>
                        </div>
                        ${/* Sprint 5.33 DECOUPLE-1: Tribute boost deprecated —
                            бустер 💎-output смысла не имеет когда 💎 output = 0. */ ''}
                    </div>`;
                }).join('')}
                </div>
                <div style="font-size:9px;color:#6b7280;text-align:center;">
                    Динары → Hero.Gold (на gear/smith). 💎 не выдаётся пассивно.
                </div>
            </div>`;
        // FLICKER-FIX: skip rebind при identical HTML.
        if (!_smartInnerHTML(slot, html)) return;

        slot.querySelectorAll('.bnr-fief-boost').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const parent = e.target.closest('[data-fief-id]');
                if (!parent) return;
                if (!await _bnrConfirm(`Купить boost +${boostPct}% на ${boostDays} дней? (2000💎)`)) return;
                const fiefRowId = parseInt(parent.dataset.fiefId, 10);
                await _bannerlordBuyAction('hero.tribute_boost', {
                    fief_id_internal: fiefRowId,
                });
                setTimeout(loadBannerlordFiefs, 1200);
            });
        });
    } catch (e) {
        // FLICKER-FIX v6 — НЕ clear на exception. Last good render остаётся.
        console.warn('[FE-FIEF] loadFiefs failed (keeping last render):', e);
    }
}

// ───────────────────────────────────────────────────────────────────────────
// Sprint 5.33 (BLT-parity CARAVAN) — Mobile passive income trilogy closer.
// SHOP = static personal | FIEF = territorial | CARAVAN = mobile с риском.
// Caravan может быть destroyed бандитами → rescue pool (parallel to ransom).

async function loadBannerlordCaravans() {
    const slot = document.getElementById('bnr-caravans-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/my-caravans`, {
            headers: { 'X-Twitch-JWT': authToken || '' }
        }).then(r => r.json()).catch(() => ({success: false}));

        // FLICKER-FIX v6 (2026-05-29): skip update на backend error — last good
        // render остаётся видимым. Иначе section мерцает каждые ~8s при transient blip.
        if (!r || r.success === false) return;

        const caravans = Array.isArray(r.caravans) ? r.caravans : [];
        const maxC = r.max_caravans || 2;

        // Sprint 5.33 CURRENCY-1 — clear price display + Hero.Gold visible.
        const CARAVAN_CRUSTIC = 4000;      // 2026-05-29: чистая 💎 (цена поднята 1500→4000)
        const CARAVAN_DINAR   = 0;         // 15K капитал НЕ списывался — миф убран
        const cAfford = _bnrAfford(CARAVAN_CRUSTIC, CARAVAN_DINAR);

        // FLICKER-FIX v4: balance strip убран (см. workshops комментарий).
        let html = `
            <div style="background:#1a1820;border:1px solid #7c3aed;border-radius:4px;
                        padding:8px;font-size:11px;color:#ddd6fe;">
                <div style="font-size:12px;font-weight:700;color:#a78bfa;margin-bottom:4px;">
                    🐪 Мои караваны (${caravans.filter(c => c.status === 'active').length}/${maxC})
                </div>
                <div style="font-size:9px;color:#9ca3af;margin-bottom:6px;">
                    Mobile passive в 💰 динарах — копятся в Hero.Gold. ⚠ Бандиты могут уничтожить.
                </div>`;

        if (caravans.length > 0) {
            html += `<div style="display:flex;flex-direction:column;gap:4px;margin-bottom:6px;">`;
            for (const c of caravans) {
                const isDest = c.status === 'destroyed';
                html += `
                    <div data-caravan-id="${c.id}"
                         style="background:${isDest ? '#2a0a0a' : '#0f0d18'};
                                padding:6px 8px;border-radius:3px;
                                display:flex;justify-content:space-between;align-items:center;
                                ${isDest ? 'border:1px solid #b91c1c;' : ''}">
                        <div style="flex:1;">
                            <div style="color:${isDest ? '#fecaca' : '#ddd6fe'};font-size:11px;">
                                ${isDest ? '💀' : '🐪'} <strong>${escapeHtml(c.home_settlement_name || 'Caravan')}</strong>
                                ${isDest ? '<span style="color:#fb7185;font-size:9px;font-weight:700;"> УНИЧТОЖЕН</span>' : ''}
                            </div>
                            <div style="font-size:10px;margin-top:2px;">
                                <span style="color:#9ca3af;">Заработано:</span>
                                <span style="color:${isDest ? '#fb7185' : '#fbbf24'};font-weight:700;">💰 ${(c.total_collected_dinars || 0).toLocaleString('ru-RU')}</span>
                            </div>
                        </div>
                        ${!isDest ? `
                            <button class="bnr-caravan-sell small-btn"
                                    title="Продать (engine handles refund)"
                                    style="font-size:9px;padding:2px 6px;background:#5b21b6;
                                           color:#ddd6fe;">💸 Продать</button>
                        ` : ''}
                    </div>`;
            }
            html += `</div>`;
        }

        const activeCount = caravans.filter(c => c.status === 'active').length;
        if (activeCount < maxC) {
            const btnBg = cAfford.ok ? '#7c3aed' : '#2d1b5a';
            const btnOpacity = cAfford.ok ? '1' : '0.65';
            // 2026-06-07 — покупка каравана инлайн (lazy <details>): <select>-город
            // переживает 8s-poll (форма рендерится при раскрытии).
            html += `
                <details data-bnr-details="caravan-buy" ${_bnrDetailsAttr('caravan-buy')}>
                    <summary title="${escapeHtml(_bnrAffordTooltip(CARAVAN_CRUSTIC, CARAVAN_DINAR))}"
                             style="list-style:none;cursor:pointer;width:100%;
                                    font-size:11px;padding:6px;background:${btnBg};box-sizing:border-box;
                                    color:#fff;font-weight:700;opacity:${btnOpacity};
                                    border-radius:3px;text-align:center;">
                        🐪 Купить караван — ${_bnrPriceHtml(CARAVAN_CRUSTIC, CARAVAN_DINAR)}
                    </summary>
                    <div id="bnr-caravan-buy-slot" style="padding-top:6px;"></div>
                </details>`;
        } else {
            html += `
                <div style="font-size:10px;color:#6b7280;text-align:center;">
                    Лимит караванов (${maxC}/${maxC})
                </div>`;
        }
        html += `</div>`;
        // 2026-06-07 FLICKER — пока форма покупки раскрыта, НЕ перерисовываем секцию
        // (иначе тик дохода стирает выбор города). Возобновится при закрытии формы.
        if (slot.querySelector('[data-bnr-details="caravan-buy"]')?.open) return;
        // FLICKER-FIX: skip rebind при identical HTML.
        if (!_smartInnerHTML(slot, html)) return;

        slot.querySelectorAll('.bnr-caravan-sell').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const parent = e.target.closest('[data-caravan-id]');
                if (!parent) return;
                if (!await _bnrConfirm('Продать караван?')) return;
                const cId = parseInt(parent.dataset.caravanId, 10);
                await _bannerlordBuyAction('hero.sell_caravan', { caravan_id: cId });
                setTimeout(loadBannerlordCaravans, 1500);
            });
        });
        const _carDet = slot.querySelector('[data-bnr-details="caravan-buy"]');
        if (_carDet) {
            _carDet.addEventListener('toggle', () => { if (_carDet.open) _renderBuyCaravanInline(); });
            if (_carDet.open) _renderBuyCaravanInline();
        }
    } catch (e) {
        // FLICKER-FIX v6 — НЕ clear на exception. Last good render остаётся.
        console.warn('[FE-CARAVAN] loadCaravans failed (keeping last render):', e);
    }
}

// удалена: инлайн lazy-форма покупки каравана (_renderBuyCaravanInline).
function _renderBuyCaravanInline() {
    const slot = document.getElementById('bnr-caravan-buy-slot');
    if (!slot) return;
    slot.innerHTML = `
        <div style="background:#1a1820;border:1px solid #7c3aed;border-radius:4px;
                    padding:10px;color:#ddd6fe;">
            <div style="display:flex;gap:6px;font-size:11px;margin-bottom:10px;
                        background:#0f0d18;padding:6px 8px;border-radius:3px;">
                <div style="flex:1;">
                    <div style="color:#9ca3af;font-size:9px;">Стоимость:</div>
                    <div style="font-size:13px;font-weight:700;">
                        ${_bnrPriceHtml(1500, 15000)}
                    </div>
                </div>
                <div style="flex:1;border-left:1px solid #1f2937;padding-left:8px;">
                    <div style="color:#9ca3af;font-size:9px;">У тебя:</div>
                    <div style="font-size:11px;">
                        <span style="color:#a5f3fc;">💎 ${(_cachedUserPoints||0).toLocaleString('ru-RU')}</span>
                        <span style="color:#6b7280;">|</span>
                        <span style="color:#fbbf24;">💰 ${((_bannerlordLastHero?.hero?.gold)||0).toLocaleString('ru-RU')}</span>
                    </div>
                </div>
            </div>
            <div style="font-size:10px;color:#9ca3af;margin-bottom:10px;line-height:1.4;">
                <div>💎 — entry fee, списывается с твоего 💎 балланса</div>
                <div>💰 — capital (15K), списывается с Hero.Gold (engine)</div>
                <div>📈 Profit копится в Hero.Gold (динары на gear/smith/marriage)</div>
                <div style="color:#fb7185;">⚠ Бандиты могут уничтожить — viewers собирают rescue pool</div>
            </div>
            <label style="font-size:11px;color:#ddd6fe;display:block;margin-bottom:4px;">
                Home town (выбери из engine catalog):
            </label>
            <div id="bnr-caravan-home-slot" style="margin-bottom:10px;">
                <div style="font-size:11px;color:#9ca3af;padding:6px;">
                    ⏳ Загружается список городов...
                </div>
            </div>
            <button id="bnr-caravan-buy-confirm" class="extra-btn"
                    style="width:100%;font-size:11px;padding:6px;
                           background:#7c3aed;color:#fff;font-weight:700;">
                🐪 Купить — ${_bnrPriceHtml(1500, 15000)}
            </button>
        </div>`;
    // CATALOG-3: load real engine towns в caravan home dropdown
    _bnrFetchSettlements().then(byType => {
        const homeSlot = document.getElementById('bnr-caravan-home-slot');
        if (homeSlot) {
            homeSlot.innerHTML = _bnrRenderSettlementSelect(byType.town || [],
                { id: 'bnr-caravan-home' });
            // Re-style the <select> для caravan theme
            const sel = document.getElementById('bnr-caravan-home');
            if (sel && sel.tagName === 'SELECT') {
                sel.style.background = '#0f0d18';
                sel.style.color = '#ddd6fe';
                sel.style.borderColor = '#7c3aed';
            }
        }
    });
    document.getElementById('bnr-caravan-buy-confirm')?.addEventListener('click', async () => {
        const homeSel = document.getElementById('bnr-caravan-home');
        const home = (homeSel?.value || '').trim();
        const homeName = homeSel?.tagName === 'SELECT'
            ? (homeSel.options[homeSel.selectedIndex]?.dataset?.name || home)
            : home;
        if (!home) {
            showNotification('Выбери home town из списка', 'warning');
            return;
        }
        // 2026-06-07 FLICKER — закрыть форму ДО refresh (иначе freeze-guard
        // заблокирует перерисовку) + мгновенный фидбек на клик.
        document.querySelector('[data-bnr-details="caravan-buy"]')?.removeAttribute('open');
        await _bannerlordBuyAction('hero.buy_caravan', {
            home_settlement_id:   home,
            home_settlement_name: homeName,
        });
        setTimeout(loadBannerlordCaravans, 2000);
    });
}

// ─── Caravan rescue pool ──────────────────────────────────────────────────────
async function loadBannerlordCaravanRescues() {
    const slot = document.getElementById('bnr-caravan-rescue-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/caravan-rescues`, {
            headers: { 'X-Twitch-JWT': authToken || '' }
        }).then(r => r.json()).catch(() => ({success: false}));
        const rescues = (r.success && Array.isArray(r.rescues)) ? r.rescues : [];
        if (rescues.length === 0) { slot.innerHTML = ''; return; }

        let html = `
            <div style="background:#2a0a0a;border:1px solid #b91c1c;border-radius:4px;
                        padding:8px;font-size:11px;color:#fecaca;">
                <div style="font-size:12px;font-weight:700;color:#fb7185;margin-bottom:6px;">
                    💀 Уничтоженные караваны — соберём rescue?
                </div>
                <div style="display:flex;flex-direction:column;gap:4px;">
                ${rescues.map(rs => {
                    const pct = Math.min(100, Math.floor(100 * (rs.pool_total || 0) / Math.max(1, rs.rescue_cost)));
                    return `
                    <div data-caravan-id="${rs.caravan_id}"
                         style="background:#0f0505;padding:6px 8px;border-radius:3px;">
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
                            <span style="color:#fecaca;font-size:11px;">
                                🐪 @${escapeHtml(rs.owner)} <span style="color:#9ca3af;">— ${escapeHtml(rs.home_name || '?')}</span>
                            </span>
                            <button class="bnr-caravan-rescue-pay small-btn"
                                    title="Вложить 500💎 в pool rescue"
                                    style="font-size:9px;padding:2px 6px;background:#b91c1c;
                                           color:#fee2e2;">💰 +500💎</button>
                        </div>
                        <div style="background:#1a0505;height:5px;border-radius:2px;overflow:hidden;">
                            <div style="background:linear-gradient(90deg,#fb7185,#a78bfa);
                                        height:100%;width:${pct}%;transition:width 0.3s;"></div>
                        </div>
                        <div style="font-size:9px;color:#9ca3af;margin-top:2px;">
                            ${rs.pool_total || 0} / ${rs.rescue_cost}💎 pool
                            ${rs.contributors > 0 ? ` · ${rs.contributors} участников` : ''}
                        </div>
                    </div>`;
                }).join('')}
                </div>
            </div>`;
        // FLICKER-FIX: skip rebind при identical HTML.
        if (!_smartInnerHTML(slot, html)) return;

        slot.querySelectorAll('.bnr-caravan-rescue-pay').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const parent = e.target.closest('[data-caravan-id]');
                if (!parent) return;
                const cId = parseInt(parent.dataset.caravanId, 10);
                await _bannerlordBuyAction('hero.pay_caravan_rescue', { caravan_id: cId });
                setTimeout(loadBannerlordCaravanRescues, 1200);
                setTimeout(loadBannerlordCaravans, 1500);
            });
        });
    } catch (e) {
        console.warn('[FE-CARAVAN-RESCUE] loadRescues failed (keeping last render)', e);
    }
}

// ───────────────────────────────────────────────────────────────────────────
// Sprint 5.33 (BLT-parity HERITAGE) — Inheritance log section.
// Когда viewer умирает + heir активируется, parent's workshops/caravans/fiefs
// transfer'ятся к heir engine-side (mod ActivateHeirHandler). Backend logs
// каждый asset в bannerlord_inheritance_log — frontend показывает recent
// inheritance события для transparency + dopamine.

async function loadBannerlordInheritance() {
    const slot = document.getElementById('bnr-inheritance-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/inheritance-log?limit=15`, {
            headers: { 'X-Twitch-JWT': authToken || '' }
        }).then(r => r.json()).catch(() => ({success: false}));
        const items = (r.success && Array.isArray(r.items)) ? r.items : [];
        if (items.length === 0) { slot.innerHTML = ''; return; }

        const typeEmoji = { workshop: '🏭', caravan: '🐪', fief: '🏛' };
        const typeColor = { workshop: '#84cc16', caravan: '#a78bfa', fief: '#f59e0b' };

        // Group by inherited_at date (день).
        const groups = new Map();
        for (const it of items) {
            const day = (it.inherited_at || '').substring(0, 10);
            if (!groups.has(day)) groups.set(day, []);
            groups.get(day).push(it);
        }

        let html = `
            <div style="background:#1a1614;border:1px solid #92400e;border-radius:4px;
                        padding:8px;font-size:11px;color:#fde68a;">
                <div style="font-size:12px;font-weight:700;color:#facc15;margin-bottom:6px;">
                    ⚱ Наследие — переходило к моим heir'ам
                </div>`;
        for (const [day, dayItems] of groups) {
            const totalValue = dayItems.reduce((s, x) => s + (x.total_value || 0), 0);
            html += `
                <div style="margin-bottom:6px;">
                    <div style="font-size:10px;color:#fbbf24;font-weight:700;margin-bottom:3px;">
                        ${escapeHtml(day || 'recent')}
                        ${totalValue > 0 ? `<span style="color:#9ca3af;font-weight:normal;">
                            — ${totalValue.toLocaleString('ru-RU')} дин. total</span>` : ''}
                    </div>
                    <div style="display:flex;flex-direction:column;gap:2px;">
                    ${dayItems.map(it => {
                        const emoji = typeEmoji[it.asset_type] || '⚱';
                        const color = typeColor[it.asset_type] || '#fde68a';
                        return `
                            <div style="background:#0f0c0a;padding:4px 6px;border-radius:3px;
                                        font-size:10px;border-left:2px solid ${color};">
                                ${emoji} <span style="color:${color};">${escapeHtml(it.asset_name || it.asset_type)}</span>
                                ${(it.total_value || 0) > 0 ? `<span style="color:#9ca3af;float:right;">
                                    ${it.total_value.toLocaleString('ru-RU')} дин.</span>` : ''}
                            </div>`;
                    }).join('')}
                    </div>
                </div>`;
        }
        html += `
                <div style="font-size:9px;color:#6b7280;text-align:center;margin-top:3px;">
                    Empire transcends death — assets re-claimed engine-side
                </div>
            </div>`;
        // FLICKER-FIX: dedupe (no bindings here, just paint).
        _smartInnerHTML(slot, html);
    } catch (e) {
        console.warn('[FE-HERITAGE] loadInheritance failed (keeping last render)', e);
    }
}

// ===== Vassals / Party orders / Diplomacy / Ransom — split чанк 5 (2026-06-13) =====
// loadBannerlordVassals(+_renderCreateVassalInline), loadBannerlordPartyOrders(+_renderPartyOrderInline),
// _BNR_POLICIES + loadBannerlordDiplomacy(+_renderMakePeaceInline), loadBannerlordRansomPool.
// Core _bnr*/_smartInnerHTML forward; callers рантайм (loadBannerlordHero у clan-leader).
// Sprint 5.33 (BLT-parity VAS) — Vassal sub-clan management.
// Viewer-leader клана может выделить взрослого ребёнка (heir) в собственный
// vassal-clan. Прогрессия sub-clan'ов = long-term retention для donator'ов.
async function loadBannerlordVassals() {
    const slot = document.getElementById('bnr-vassals-slot');
    if (!slot) return;
    try {
        const [vassR, heirsR] = await Promise.all([
            fetch(`${API_URL}/api/bannerlord/vassals`, {
                headers: { 'X-Twitch-JWT': authToken || '' }
            }).then(r => r.json()).catch(() => ({success: false})),
            fetch(`${API_URL}/api/bannerlord/eligible-heirs`, {
                headers: { 'X-Twitch-JWT': authToken || '' }
            }).then(r => r.json()).catch(() => ({success: false})),
        ]);
        const vassals = (vassR.success && Array.isArray(vassR.vassals))
            ? vassR.vassals : [];
        const eligible = (heirsR.success && Array.isArray(heirsR.heirs))
            ? heirsR.heirs : [];

        // Hide section если нет vassals и нет eligible heirs.
        if (vassals.length === 0 && eligible.length === 0) {
            slot.innerHTML = '';
            return;
        }
        console.info('[FE-VAS] loaded vassals=%d eligible=%d',
                     vassals.length, eligible.length);

        let html = `
            <div style="background:#1a1f2e;border:1px solid #1e40af;border-radius:4px;
                        padding:8px;font-size:11px;color:#bfdbfe;">
                <div style="font-size:12px;font-weight:700;color:#60a5fa;margin-bottom:6px;">
                    🏰 Вассальные кланы
                </div>`;
        if (vassals.length > 0) {
            html += `
                <div style="display:flex;flex-direction:column;gap:3px;margin-bottom:6px;">
                    ${vassals.map(v => `
                        <div data-vassal-id="${v.id}"
                             data-vassal-name="${escapeHtml(v.vassal_name)}"
                             style="display:flex;justify-content:space-between;align-items:center;
                                    background:#0f1730;padding:4px 6px;border-radius:3px;">
                            <span style="color:#dbeafe;font-size:11px;">🏰 ${escapeHtml(v.vassal_name)}</span>
                            <button class="bnr-vas-rename small-btn"
                                    title="Переименовать (100💎)"
                                    style="font-size:9px;padding:2px 5px;background:#1e3a8a;color:#bfdbfe;">✏</button>
                        </div>
                    `).join('')}
                </div>`;
        }
        if (eligible.length > 0 && vassals.length < 5) {
            // 2026-06-07 — создание вассала инлайн (lazy <details>): <select>-наследник
            // + text-имя переживают 8s-poll (форма рендерится при раскрытии).
            html += `
                <details data-bnr-details="vas-create" ${_bnrDetailsAttr('vas-create')}>
                    <summary title="Выделить взрослого ребёнка в собственный sub-clan (250K💰 у героя)"
                             style="list-style:none;cursor:pointer;width:100%;
                                    font-size:11px;padding:6px;background:#1e3a8a;box-sizing:border-box;
                                    color:#fff;font-weight:700;border-radius:3px;text-align:center;">
                        🏰 Создать вассала (250K💰) — ${eligible.length} наследников доступно
                    </summary>
                    <div id="bnr-vas-create-slot" style="padding-top:6px;"></div>
                </details>`;
        } else if (vassals.length >= 5) {
            html += `
                <div style="font-size:10px;color:#6b7280;text-align:center;">
                    Максимум вассалов (5/5)
                </div>`;
        }
        html += `</div>`;
        // 2026-06-07 FLICKER — пока форма создания вассала раскрыта, НЕ перерисовываем
        // секцию (иначе repaint стирает выбор наследника / ввод имени).
        if (slot.querySelector('[data-bnr-details="vas-create"]')?.open) return;
        // FLICKER-FIX: skip rebind при identical HTML.
        if (!_smartInnerHTML(slot, html)) return;

        // Bind rename buttons
        slot.querySelectorAll('.bnr-vas-rename').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const parent = e.target.closest('[data-vassal-id]');
                if (!parent) return;
                const id = parseInt(parent.dataset.vassalId, 10);
                const oldName = parent.dataset.vassalName || '';
                const newName = window.prompt(`Новое имя для «${oldName}»:`, oldName);
                if (!newName || newName === oldName) return;
                await _bannerlordBuyAction('hero.rename_vassal', {
                    vassal_id: id,
                    new_name: newName,
                });
                setTimeout(loadBannerlordVassals, 1500);
            });
        });

        // Bind create — lazy inline форма (heir select + name) при раскрытии.
        const _vasDet = slot.querySelector('[data-bnr-details="vas-create"]');
        if (_vasDet) {
            _vasDet.addEventListener('toggle', () => { if (_vasDet.open) _renderCreateVassalInline(eligible); });
            if (_vasDet.open) _renderCreateVassalInline(eligible);
        }
    } catch (e) {
        console.warn('[FE-VAS] loadVassals failed (keeping last render)', e);
    }
}

// удалена: инлайн lazy-форма вассала (_renderCreateVassalInline) вместо модалки.
function _renderCreateVassalInline(eligibleHeirs) {
    const slot = document.getElementById('bnr-vas-create-slot');
    if (!slot) return;
    if (!eligibleHeirs || eligibleHeirs.length === 0) { slot.innerHTML = ''; return; }
    slot.innerHTML = `
        <div style="background:#1a1f2e;border:1px solid #1e40af;border-radius:4px;
                    padding:10px;color:#bfdbfe;">
            <div style="font-size:11px;color:#9ca3af;margin-bottom:8px;">
                Выдели взрослого наследника в собственный sub-clan.
                Он станет лидером, ваш клан получает 25% от его доходов.
            </div>
            <label style="font-size:11px;color:#dbeafe;display:block;margin-bottom:4px;">
                Наследник:
            </label>
            <select id="bnr-vas-heir-pick"
                    style="width:100%;padding:6px;font-size:12px;background:#0f1730;
                           color:#dbeafe;border:1px solid #1e40af;margin-bottom:8px;">
                ${eligibleHeirs.map(h =>
                    `<option value="${escapeHtml(h.hero_id)}">${escapeHtml(h.name)}</option>`
                ).join('')}
            </select>
            <label style="font-size:11px;color:#dbeafe;display:block;margin-bottom:4px;">
                Имя нового клана:
            </label>
            <input id="bnr-vas-name-input" type="text" maxlength="50"
                   placeholder="Дом ..." value=""
                   style="width:100%;padding:6px;font-size:12px;background:#0f1730;
                          color:#dbeafe;border:1px solid #1e40af;margin-bottom:10px;
                          box-sizing:border-box;">
            <button id="bnr-vas-confirm" class="extra-btn"
                    style="width:100%;font-size:11px;padding:6px;
                           background:#1e40af;color:#fff;font-weight:700;">
                🏰 Создать (250K💰)
            </button>
        </div>`;
    document.getElementById('bnr-vas-confirm')?.addEventListener('click', async () => {
        const heirId = document.getElementById('bnr-vas-heir-pick')?.value;
        const name = document.getElementById('bnr-vas-name-input')?.value?.trim();
        if (!heirId || !name || name.length < 2) {
            showNotification('Выбери наследника и имя (≥2 символа)', 'warning');
            return;
        }
        // 2026-06-07 FLICKER — закрыть форму ДО refresh (иначе freeze-guard
        // заблокирует перерисовку) + мгновенный фидбек на клик.
        document.querySelector('[data-bnr-details="vas-create"]')?.removeAttribute('open');
        await _bannerlordBuyAction('hero.create_vassal_clan', {
            heir_hero_id: heirId,
            vassal_name: name,
        });
        setTimeout(loadBannerlordVassals, 2000);  // engine apply takes ~1s
    });
}

// ───────────────────────────────────────────────────────────────────────────
// Sprint 5.33 (BLT-parity SIEGE) — Party orders panel.
// Viewer-leader партии может выдать своей MobileParty стратегический приказ:
// siege / defend / raid / garrison / patrol. Backend хранит active order
// (UNIQUE per viewer), mod выставляет engine SetMove* API.
async function loadBannerlordPartyOrders() {
    const slot = document.getElementById('bnr-party-orders-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/party-orders`, {
            headers: { 'X-Twitch-JWT': authToken || '' }
        }).then(r => r.json()).catch(() => ({success: false}));

        // FLICKER-FIX v6 (2026-05-29): на backend error НЕ clear slot — оставляем
        // last known good render видимым. Иначе при transient network blip
        // секция мерцает blank → render → blank каждые несколько секунд.
        if (!r || r.success === false) return;

        const active = r.active ? r.active : null;

        const orderEmoji = {
            siege: '🏰', defend: '🛡', raid: '🔥',
            garrison: '🏛', patrol: '🐎',
        };
        const orderLabel = {
            siege: 'Осада', defend: 'Защита', raid: 'Грабёж',
            garrison: 'Гарнизон', patrol: 'Патруль',
        };

        let html = `
            <div style="background:#2a1a0a;border:1px solid #92400e;border-radius:4px;
                        padding:8px;font-size:11px;color:#fed7aa;">
                <div style="font-size:12px;font-weight:700;color:#fb923c;margin-bottom:6px;">
                    ⚔ Приказы моего отряда на карте
                </div>`;

        // 2026-06-10 — текущий отряд (число воинов + задача движка) из hero-state push.
        const pinfo = (_bannerlordLastHero?.hero?.party_info) || null;
        const taskLabel = {
            GoToSettlement: 'идёт в поселение', BesiegeSettlement: 'осаждает',
            RaidSettlement: 'грабит', DefendSettlement: 'защищает',
            PatrolAroundPoint: 'патрулирует', Hold: 'стоит на месте',
            EngageParty: 'преследует отряд', GoToPoint: 'движется',
            FleeToPoint: 'отступает', GoAroundParty: 'маневрирует',
            JoinArmy: 'идёт в армию', EscortParty: 'сопровождает',
        };
        if (pinfo) {
            const taskTxt = taskLabel[pinfo.task] || pinfo.task || '—';
            const tgtTxt  = pinfo.target ? ` → ${escapeHtml(pinfo.target)}` : '';
            const armyTxt = pinfo.in_army ? ' · <span style="color:#fbbf24;">в армии</span>' : '';
            html += `
                <div style="background:#1a0f08;padding:6px 8px;border-radius:3px;margin-bottom:6px;font-size:11px;">
                    <span style="color:#9ca3af;">Отряд:</span>
                    <strong style="color:#fed7aa;">${pinfo.size} 🪖</strong>
                    <span style="color:#9ca3af;"> · задача:</span>
                    <strong style="color:#fed7aa;">${taskTxt}${tgtTxt}</strong>${armyTxt}
                </div>`;
        } else {
            html += `
                <div style="font-size:10px;color:#6b7280;margin-bottom:6px;">
                    Нет отряда на карте (герой без партии — создай отряд в Династии)
                </div>`;
        }

        if (active) {
            const emoji = orderEmoji[active.order_type] || '⚔';
            const lbl = orderLabel[active.order_type] || active.order_type;
            html += `
                <div style="background:#1a0f08;padding:6px 8px;border-radius:3px;
                            margin-bottom:6px;display:flex;justify-content:space-between;
                            align-items:center;">
                    <span style="color:#fed7aa;font-size:11px;">
                        ${emoji} <strong>${lbl}</strong>
                        <span style="color:#9ca3af;"> →
                            ${escapeHtml(active.target_settlement_name || active.target_settlement_id)}
                        </span>
                    </span>
                    <button id="bnr-order-cancel" class="extra-btn"
                            title="Отменить приказ (бесплатно)"
                            style="font-size:9px;padding:2px 6px;background:#2d2d3f;
                                   color:#fed7aa;">🏳 Отменить</button>
                </div>`;
        } else {
            html += `
                <div style="font-size:10px;color:#9ca3af;margin-bottom:6px;text-align:center;">
                    Партия действует автономно
                </div>`;
        }

        // 2026-06-07 — назначение приказа инлайн (lazy <details>): radio-приказ +
        // text-поле поселения переживают 8s-poll (форма рендерится при раскрытии,
        // не на каждом тике — иначе введённый текст стирался бы).
        html += `
            <details data-bnr-details="party-order" ${_bnrDetailsAttr('party-order')}>
                <summary style="list-style:none;cursor:pointer;width:100%;
                           font-size:11px;padding:6px;background:#92400e;box-sizing:border-box;
                           color:#fff;font-weight:700;border-radius:3px;text-align:center;">
                    ⚔ ${active ? 'Изменить приказ' : 'Назначить приказ'} (500💎)
                </summary>
                <div id="bnr-party-order-slot" style="padding-top:6px;"></div>
            </details>
            </div>`;
        // 2026-06-07 FLICKER — пока раскрыта форма приказа (radio + text-поселение),
        // НЕ перерисовываем секцию: смена active-order между poll'ами стёрла бы ввод.
        if (slot.querySelector('[data-bnr-details="party-order"]')?.open) return;
        // FLICKER-FIX: skip rebind при identical HTML.
        if (!_smartInnerHTML(slot, html)) return;

        // Bind buttons.
        document.getElementById('bnr-order-cancel')?.addEventListener('click', async () => {
            await _bannerlordBuyAction('hero.party_order_release', {});
            setTimeout(loadBannerlordPartyOrders, 1500);
        });
        const _poDet = slot.querySelector('[data-bnr-details="party-order"]');
        if (_poDet) {
            _poDet.addEventListener('toggle', () => { if (_poDet.open) _renderPartyOrderInline(active); });
            if (_poDet.open) _renderPartyOrderInline(active);
        }
    } catch (e) {
        // FLICKER-FIX v6 — НЕ clear на network exception. Last good render
        // остаётся видимым пока poll не recover'нет.
        console.warn('[FE-SIEGE] loadPartyOrders failed (keeping last render):', e);
    }
}

// удалена: инлайн lazy-форма приказа (_renderPartyOrderInline) вместо модалки.
function _renderPartyOrderInline(currentActive) {
    const slot = document.getElementById('bnr-party-order-slot');
    if (!slot) return;
    const preType = currentActive?.order_type || 'siege';
    const preName = currentActive?.target_settlement_name || '';
    const preId = currentActive?.target_settlement_id || '';

    const orderOptions = [
        { v: 'siege',    e: '🏰', l: 'Осада',     desc: 'Атаковать поселение врага' },
        { v: 'defend',   e: '🛡', l: 'Защита',    desc: 'Защищать поселение' },
        { v: 'raid',     e: '🔥', l: 'Грабёж',    desc: 'Налёт на деревню (требуется война)' },
        { v: 'garrison', e: '🏛', l: 'Гарнизон',  desc: 'Войти в поселение и стоять' },
        { v: 'patrol',   e: '🐎', l: 'Патруль',   desc: 'Патрулировать вокруг поселения' },
    ];

    slot.innerHTML = `
        <div style="background:#1a1208;border:1px solid #92400e;border-radius:4px;
                    padding:10px;color:#fed7aa;">
            <div style="font-size:11px;color:#9ca3af;margin-bottom:10px;">
                Партия следует приказу пока активен. Заменяет предыдущий.
                Sieges/raids требуют состояния войны с владельцем цели.
            </div>
            <div style="display:flex;flex-direction:column;gap:4px;margin-bottom:10px;">
                ${orderOptions.map(o => `
                    <label style="display:flex;align-items:center;gap:6px;
                                  background:#0f0805;padding:5px 8px;border-radius:3px;
                                  cursor:pointer;font-size:11px;">
                        <input type="radio" name="bnr-order-type" value="${o.v}"
                               ${o.v === preType ? 'checked' : ''}>
                        <span style="color:#fed7aa;">
                            ${o.e} <strong>${o.l}</strong>
                            <span style="color:#6b7280;font-size:10px;"> — ${o.desc}</span>
                        </span>
                    </label>
                `).join('')}
            </div>
            <label style="font-size:11px;color:#fed7aa;display:block;margin-bottom:4px;">
                Поселение (название или ID):
            </label>
            <input id="bnr-order-target-name" type="text" maxlength="80"
                   placeholder="например: Lycaron / Sargot / Marunath"
                   value="${escapeHtml(preName || preId)}"
                   style="width:100%;padding:6px;font-size:12px;background:#0f0805;
                          color:#fed7aa;border:1px solid #92400e;margin-bottom:6px;
                          box-sizing:border-box;">
            <div style="font-size:9px;color:#6b7280;margin-bottom:10px;">
                Mod ищет по точному ID или fuzzy-name match (≥3 символа).
                ⚠ Только лидер клана может выдавать приказы своей партии.
            </div>
            <button id="bnr-order-confirm" class="extra-btn"
                    style="width:100%;font-size:11px;padding:6px;
                           background:#92400e;color:#fff;font-weight:700;">
                ⚔ Выдать приказ (500💎)
            </button>
        </div>`;
    document.getElementById('bnr-order-confirm')?.addEventListener('click', async () => {
        const orderType = slot.querySelector('input[name="bnr-order-type"]:checked')?.value;
        const tgtRaw = (document.getElementById('bnr-order-target-name')?.value || '').trim();
        if (!orderType || !tgtRaw || tgtRaw.length < 3) {
            showNotification('Выбери приказ и укажи цель (≥3 символа)', 'warning');
            return;
        }
        // 2026-06-07 FLICKER — закрыть форму ДО refresh (иначе freeze-guard
        // заблокирует перерисовку) + мгновенный фидбек на клик.
        document.querySelector('[data-bnr-details="party-order"]')?.removeAttribute('open');
        await _bannerlordBuyAction('hero.party_order_set', {
            order_type:              orderType,
            target_settlement_id:    tgtRaw,
            target_settlement_name:  tgtRaw,
        });
        setTimeout(loadBannerlordPartyOrders, 2000);
    });
}

// ───────────────────────────────────────────────────────────────────────────
// Sprint 5.33 (BLT-parity DIPLO) — Kingdom politics panel.
// King/clan-leader может купить enact политики (toggle add/remove) для своего
// kingdom'а или предложить peace с enemy. Все viewers могут chip in в ransom
// pool captured heroes (отдельная section).

// Curated set vanilla 1.3.x policies — popular & impactful. Mod валидирует
// PolicyObject.StringId через MBObjectManager.GetObject<PolicyObject>.
const _BNR_POLICIES = [
    { id: 'forgiveness_of_debts', name: 'Forgiveness of Debts',
      desc: 'Loyalty +1, Tax -10%. Дёшево, но кланы недовольны.' },
    { id: 'land_grants', name: 'Land Grants',
      desc: 'Clan tier влияет на fief share. Поддержка крупных кланов.' },
    { id: 'precarial_land_tenure', name: 'Precarial Land Tenure',
      desc: 'Notables +5 power per fief. Влияние стороннее.' },
    { id: 'royal_guard', name: 'Royal Guard',
      desc: 'Король получает +50 кавалерии. Силовая опора трона.' },
    { id: 'sacred_majesty', name: 'Sacred Majesty',
      desc: 'King influence +2/day, others -1. Авторитарный режим.' },
    { id: 'trial_by_jury', name: 'Trial by Jury',
      desc: 'Loyalty +0.5, Security +1. Народная популярность.' },
    { id: 'imperial_towns', name: 'Imperial Towns',
      desc: 'Town prosperity +5%. Городам — вино!' },
    { id: 'noble_retinues', name: 'Noble Retinues',
      desc: 'Clan +10 party size. Большие армии.' },
    { id: 'lords_privy_council', name: 'Lords Privy Council',
      desc: 'Lords +1 influence/day. Феодальная демократия.' },
    { id: 'state_pilgrims', name: 'State Pilgrims',
      desc: 'Town loyalty +1.5 in same culture. Культурный буст.' },
    { id: 'serfdom', name: 'Serfdom',
      desc: 'Village hearth +10%. Низшие классы работают за двоих.' },
    { id: 'citizenship', name: 'Citizenship',
      desc: 'Town loyalty +1 в same culture. Гражданская честь.' },
];

async function loadBannerlordDiplomacy() {
    const slot = document.getElementById('bnr-diplo-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/kingdom-state`, {
            headers: { 'X-Twitch-JWT': authToken || '' }
        }).then(r => r.json()).catch(() => ({success: false}));
        if (r.success === false) return;  // AUDIT fix: keep last on transient fail
        if (!r.has_hero) { _smartInnerHTML(slot, ''); return; }  // genuine — no hero
        if (!r.kingdom_id) {
            slot.innerHTML = `
                <div style="background:#1a1208;border:1px solid #92400e;border-radius:4px;
                            padding:6px;font-size:10px;color:#9ca3af;text-align:center;">
                    🏛 Политика kingdom'а доступна когда герой вступит в королевство
                </div>`;
            return;
        }
        const canEnact = r.is_king || r.is_clan_leader;
        const canMakePeace = r.is_king;

        let html = `
            <div style="background:#1a1208;border:1px solid #92400e;border-radius:4px;
                        padding:8px;font-size:11px;color:#fed7aa;">
                <div style="font-size:12px;font-weight:700;color:#fb923c;margin-bottom:6px;">
                    🏛 Политика — ${escapeHtml(r.kingdom_name || r.kingdom_id)}
                    ${r.is_king ? '<span style="color:#fbbf24;font-size:9px;"> 👑 КОРОЛЬ</span>' : ''}
                </div>`;

        if ((r.policies_enacted || []).length > 0) {
            html += `
                <div style="font-size:10px;color:#9ca3af;margin-bottom:3px;">Активные политики:</div>
                <div style="display:flex;flex-wrap:wrap;gap:3px;margin-bottom:6px;">
                    ${r.policies_enacted.map(p => `
                        <span style="background:#0f0805;padding:2px 5px;border-radius:3px;
                                     font-size:10px;color:#fed7aa;border:1px solid #92400e;">
                            ${escapeHtml(p.policy_name || p.policy_id)}
                        </span>
                    `).join('')}
                </div>`;
        }

        if ((r.policies_pending || []).length > 0) {
            html += `
                <div style="font-size:10px;color:#fbbf24;margin-bottom:3px;">⏳ На обсуждении:</div>
                <div style="display:flex;flex-wrap:wrap;gap:3px;margin-bottom:6px;">
                    ${r.policies_pending.map(p => `
                        <span style="background:#1a1208;padding:2px 5px;border-radius:3px;
                                     font-size:10px;color:#fbbf24;border:1px dashed #92400e;">
                            ${escapeHtml(p.policy_name || p.policy_id)}
                        </span>
                    `).join('')}
                </div>`;
        }

        if (canEnact) {
            // 2026-06-07 — активация политики инлайн (style A): каждая политика —
            // кликабельная строка, действие срабатывает сразу (toggle add/remove).
            // Список — внутри lazy <details> чтобы не разворачивать всю секцию.
            const _enactedIds = new Set((r.policies_enacted || []).map(p => p.policy_id));
            const _pendingIds = new Set((r.policies_pending || []).map(p => p.policy_id));
            html += `
                <details data-bnr-details="diplo-policy" ${_bnrDetailsAttr('diplo-policy')} style="margin-bottom:4px;">
                    <summary style="list-style:none;cursor:pointer;width:100%;
                               font-size:11px;padding:6px;background:#92400e;box-sizing:border-box;
                               color:#fff;font-weight:700;border-radius:3px;text-align:center;">
                        📜 Активировать политику (1500💎)
                    </summary>
                    <div style="font-size:9px;color:#9ca3af;margin:6px 0 4px;">
                        Клик по политике = toggle (активна → отозвать). 1500💎 за действие.
                    </div>
                    <div style="display:flex;flex-direction:column;gap:3px;">
                        ${_BNR_POLICIES.map(p => {
                            const active = _enactedIds.has(p.id);
                            const pending = _pendingIds.has(p.id);
                            return `
                            <div class="bnr-diplo-policy-row" data-policy-id="${p.id}"
                                 data-policy-name="${escapeHtml(p.name)}"
                                 ${pending ? 'data-policy-pending="1"' : ''}
                                 style="background:${active ? '#1a2008' : '#0f0805'};
                                        padding:5px 8px;border-radius:3px;
                                        cursor:${pending ? 'not-allowed' : 'pointer'};
                                        ${pending ? 'opacity:0.5;' : ''}
                                        border:1px solid ${active ? '#4ade80' : '#1a1208'};">
                                ${active ? '<span style="color:#4ade80;">✓ </span>' : ''}
                                <strong style="color:#fed7aa;font-size:11px;">${escapeHtml(p.name)}</strong>
                                ${pending ? '<span style="color:#fbbf24;font-size:9px;"> (на обсуждении)</span>' : ''}
                                <div style="font-size:10px;color:#9ca3af;margin-top:2px;">
                                    ${escapeHtml(p.desc)}
                                </div>
                            </div>`;
                        }).join('')}
                    </div>
                </details>`;
        }
        if (canMakePeace) {
            // 2026-06-07 — предложение peace инлайн (lazy <details>): target kingdom
            // (text) + tribute (number) переживают 8s-poll, форма рендерится при
            // раскрытии.
            html += `
                <details data-bnr-details="diplo-peace" ${_bnrDetailsAttr('diplo-peace')}>
                    <summary style="list-style:none;cursor:pointer;width:100%;
                               font-size:11px;padding:6px;background:#1e3a5f;box-sizing:border-box;
                               color:#fff;font-weight:700;border-radius:3px;text-align:center;">
                        🕊 Предложить peace (2000💎)
                    </summary>
                    <div id="bnr-diplo-peace-slot" style="padding-top:6px;"></div>
                </details>`;
        }
        // Backlog #1 (BLT-RC22 C.5) — kingdom tax: king задаёт ставку. Вассальные
        // кланы королевства ежедневно платят % дневной прибыли в казну короля.
        if (r.is_king) {
            const curTax = r.kingdom_tax_pct || 0;
            const presets = [0, 10, 25, 50];
            html += `
                <div style="margin-top:6px;border-top:1px solid #3d2a0a;padding-top:6px;">
                    <div style="font-size:10px;color:#fbbf24;margin-bottom:3px;">
                        👑 Налог королевства: <b>${curTax}%</b>
                        <span style="color:#9ca3af;font-size:9px;"> — % дневной прибыли вассалов → тебе</span>
                    </div>
                    <div style="display:flex;gap:3px;">
                        ${presets.map(p => `
                            <button class="bnr-tax-btn extra-btn" data-tax-pct="${p}"
                                    style="flex:1;font-size:10px;padding:4px;
                                           background:${p === curTax ? '#b45309' : '#2d2d3f'};
                                           color:#fed7aa;font-weight:${p === curTax ? '700' : '400'};">
                                ${p}%
                            </button>`).join('')}
                    </div>
                </div>`;
        }
        html += `</div>`;
        // 2026-06-07 FLICKER — пока раскрыта форма peace (text target + number tribute),
        // НЕ перерисовываем секцию: смена kingdom-state между poll'ами стёрла бы ввод.
        // diplo-policy НЕ морозим — это click-list (style A), без in-progress state.
        if (slot.querySelector('[data-bnr-details="diplo-peace"]')?.open) return;
        // FLICKER-FIX: skip rebind при identical HTML.
        if (!_smartInnerHTML(slot, html)) return;

        // 2026-06-07 — клик по строке политики = toggle enact/revoke сразу (style A).
        slot.querySelectorAll('.bnr-diplo-policy-row').forEach(row => {
            row.addEventListener('click', async () => {
                if (row.dataset.policyPending) return;  // на обсуждении — нельзя
                await _bannerlordBuyAction('hero.enact_policy', {
                    policy_id:   row.dataset.policyId,
                    policy_name: row.dataset.policyName,
                });
                setTimeout(loadBannerlordDiplomacy, 2000);
            });
        });
        // 2026-06-07 — peace инлайн lazy-форма (text+tribute переживают poll).
        const _peaceDet = slot.querySelector('[data-bnr-details="diplo-peace"]');
        if (_peaceDet) {
            _peaceDet.addEventListener('toggle', () => { if (_peaceDet.open) _renderMakePeaceInline(); });
            if (_peaceDet.open) _renderMakePeaceInline();
        }
        slot.querySelectorAll('.bnr-tax-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const pct = parseInt(btn.dataset.taxPct, 10) || 0;
                await _bannerlordBuyAction('kingdom.set_tax_rate', { tax_rate_pct: pct });
                setTimeout(loadBannerlordDiplomacy, 1200);
            });
        });
    } catch (e) {
        console.warn('[FE-DIPLO] loadDiplomacy failed (keeping last render)', e);
    }
}

// удалена: инлайн-список политик (строки в loadBannerlordDiplomacy, style A).

// удалена: инлайн lazy-форма peace (_renderMakePeaceInline) вместо модалки.
function _renderMakePeaceInline() {
    const slot = document.getElementById('bnr-diplo-peace-slot');
    if (!slot) return;
    slot.innerHTML = `
        <div style="background:#0f1730;border:1px solid #1e40af;border-radius:4px;
                    padding:10px;color:#bfdbfe;">
            <div style="font-size:11px;color:#9ca3af;margin-bottom:10px;">
                Мод resolve'ит target kingdom по name или StringId.
                Tribute может быть отрицательным (они платят нам).
            </div>
            <label style="font-size:11px;color:#dbeafe;display:block;margin-bottom:4px;">
                Target kingdom (название или ID):
            </label>
            <input id="bnr-peace-target" type="text" maxlength="80"
                   placeholder="например: Vlandia / Sturgia / Aserai"
                   style="width:100%;padding:6px;font-size:12px;background:#0a0f1a;
                          color:#bfdbfe;border:1px solid #1e40af;margin-bottom:8px;
                          box-sizing:border-box;">
            <label style="font-size:11px;color:#dbeafe;display:block;margin-bottom:4px;">
                Tribute (золото/день, можно отрицательное):
            </label>
            <input id="bnr-peace-tribute" type="number" value="0"
                   min="-10000" max="10000" step="100"
                   style="width:100%;padding:6px;font-size:12px;background:#0a0f1a;
                          color:#bfdbfe;border:1px solid #1e40af;margin-bottom:10px;
                          box-sizing:border-box;">
            <button id="bnr-peace-confirm" class="extra-btn"
                    style="width:100%;font-size:11px;padding:6px;
                           background:#1e40af;color:#fff;font-weight:700;">
                🕊 Заключить (2000💎)
            </button>
        </div>`;
    document.getElementById('bnr-peace-confirm')?.addEventListener('click', async () => {
        const tgt = (document.getElementById('bnr-peace-target')?.value || '').trim();
        const trb = parseInt(document.getElementById('bnr-peace-tribute')?.value || '0', 10) || 0;
        if (!tgt || tgt.length < 2) {
            showNotification('Укажи target kingdom (≥2 символа)', 'warning');
            return;
        }
        // 2026-06-07 FLICKER — закрыть форму ДО refresh (иначе freeze-guard
        // заблокирует перерисовку) + мгновенный фидбек на клик.
        document.querySelector('[data-bnr-details="diplo-peace"]')?.removeAttribute('open');
        await _bannerlordBuyAction('hero.make_peace', {
            target_kingdom_id:   tgt,
            target_kingdom_name: tgt,
            offered_tribute:     trb,
        });
        setTimeout(loadBannerlordDiplomacy, 2000);
    });
}

// ─── Ransom pool section — captured viewers + chip-in button ──────────────────
async function loadBannerlordRansomPool() {
    const slot = document.getElementById('bnr-ransom-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/ransom-pool`, {
            headers: { 'X-Twitch-JWT': authToken || '' }
        }).then(r => r.json()).catch(() => ({success: false}));
        const captures = (r.success && Array.isArray(r.captures)) ? r.captures : [];
        if (captures.length === 0) { slot.innerHTML = ''; return; }

        let html = `
            <div style="background:#2a0a0a;border:1px solid #b91c1c;border-radius:4px;
                        padding:8px;font-size:11px;color:#fecaca;">
                <div style="font-size:12px;font-weight:700;color:#fb7185;margin-bottom:6px;">
                    ⛓ В плену — собираем выкуп
                </div>
                <div style="display:flex;flex-direction:column;gap:4px;">
                ${captures.map(c => {
                    const pct = Math.min(100, Math.floor(100 * (c.pool_total || 0) / Math.max(1, c.ransom_cost)));
                    return `
                    <div data-captured="${escapeHtml(c.captured_hero)}"
                         style="background:#0f0505;padding:6px 8px;border-radius:3px;">
                        <div style="display:flex;justify-content:space-between;
                                    align-items:center;margin-bottom:3px;">
                            <span style="color:#fecaca;font-size:11px;">
                                ⛓ @${escapeHtml(c.captured_hero)}
                                <span style="color:#9ca3af;font-size:10px;">
                                    T${c.gear_tier || 1} · lvl ${c.level || 0}
                                </span>
                            </span>
                            <button class="bnr-ransom-pay small-btn"
                                    title="Внести 500💎 в pool выкупа"
                                    style="font-size:9px;padding:2px 6px;background:#b91c1c;
                                           color:#fee2e2;">💰 +500💎</button>
                        </div>
                        <div style="background:#1a0505;height:5px;border-radius:2px;overflow:hidden;">
                            <div style="background:linear-gradient(90deg,#fb7185,#fbbf24);
                                        height:100%;width:${pct}%;transition:width 0.3s;"></div>
                        </div>
                        <div style="font-size:9px;color:#9ca3af;margin-top:2px;">
                            ${c.pool_total || 0} / ${c.ransom_cost}💎 pool
                            ${c.contributors > 0 ? ` · ${c.contributors} участников` : ''}
                        </div>
                    </div>`;
                }).join('')}
                </div>
            </div>`;
        // FLICKER-FIX: skip rebind при identical HTML.
        if (!_smartInnerHTML(slot, html)) return;

        slot.querySelectorAll('.bnr-ransom-pay').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const parent = e.target.closest('[data-captured]');
                if (!parent) return;
                const captured = parent.dataset.captured;
                await _bannerlordBuyAction('hero.pay_ransom', {
                    captured_hero: captured,
                });
                setTimeout(loadBannerlordRansomPool, 1200);
            });
        });
    } catch (e) {
        console.warn('[FE-RANSOM] loadRansom failed (keeping last render)', e);
    }
}
