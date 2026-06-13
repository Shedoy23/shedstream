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
