// tugofwar.js — «Канат»: дуэль 1 на 1 с рейтингом и сезоном. Заменил кубики.
//
// Устроен по принципу остальных игр: общая очередь подбора (game_type='tug'),
// комната на двоих, ELO, сезонные призы топ-3.
//
// ## Почему модалка разделена на ОБОЛОЧКУ и #tug-content
//
// 2026-09-02, найдено владельцем на телефоне: раскрытые «Правила» закрывались
// сами через секунду. Причина не в «details», а в том, что опрос раз в 2 секунды
// переписывал innerHTML ВСЕГО тела модалки — вместе с блоками правил и рейтинга,
// и они возвращались в свёрнутое состояние.
//
// Крестики этого не делают: у них меняется только `#ttt-content`, а лидерборд
// живёт в оболочке рядом и не перерисовывается. Здесь теперь так же:
//   * оболочка (заголовок, правила, рейтинг, «Закрыть») рисуется ОДИН раз;
//   * `#tug-content` — единственное, что трогает опрос.
// Это не косметика: блок правил — наш ответ на требование ревью показывать
// правила ДО входа в матч. Правила, которые закрываются сами, — это правила,
// которых ревьюер не прочитал.
//
// Остальное как везде: ВСЕ числа и тексты правил приходят с сервера, исход
// считает сервер, клиент шлёт только количество тапов.

const TUG_GAME_TYPE = 'tug';

let _tugPoll = null;
let _tugState = null;
let _tugQueued = false;

async function openTugModal() {
    if (!isAuthUser()) {
        showNotification('⚠️ Войдите через Twitch', 'warning');
        return;
    }
    _renderTugModal();
    await _tugRefresh();
    _startTugPolling();
}

function _startTugPolling() {
    _stopTugPolling();
    _tugPoll = setInterval(_tugRefresh, 2000);
}

function _stopTugPolling() {
    if (_tugPoll) { clearInterval(_tugPoll); _tugPoll = null; }
}

// ── Оболочка. Рисуется ОДИН раз за открытие: всё, что здесь, переживает опрос.
function _renderTugModal() {
    let modal = document.getElementById('tug-modal');
    if (modal) modal.remove();
    modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'tug-modal';
    modal.innerHTML = `
        <div class="modal-content" style="max-width:400px;">
            <h2 style="display:flex;align-items:center;justify-content:space-between;">
                <span>🪢 Канат</span>
                <span id="tug-elo-badge" style="font-size:12px;color:#adadb8;font-weight:500;">—</span>
            </h2>
            <div id="tug-content" style="min-height:280px;">
                <div class="loading">Загрузка...</div>
            </div>
            <details style="margin-top:10px;background:#1a1a1c;border-radius:6px;padding:8px 12px;">
                <summary style="cursor:pointer;font-size:12px;color:#adadb8;">📜 Правила</summary>
                <div id="tug-rules" style="margin-top:8px;font-size:11px;color:#8a8a8e;line-height:1.5;">
                    <div class="loading">Загрузка...</div>
                </div>
            </details>
            <details style="margin-top:8px;background:#1a1a1c;border-radius:6px;padding:8px 12px;">
                <summary style="cursor:pointer;font-size:12px;color:#adadb8;">🏆 Рейтинг сезона</summary>
                <div id="tug-leaderboard" style="margin-top:8px;font-size:12px;">
                    <div class="loading">Загрузка...</div>
                </div>
            </details>
            <button class="modal-btn cancel" id="tug-close" style="margin-top:10px;">Закрыть</button>
        </div>`;
    document.body.appendChild(modal);
    document.getElementById('tug-close').addEventListener('click', () => {
        _stopTugPolling();
        modal.remove();
    });
}

async function _tugRefresh() {
    try {
        const headers = { 'X-Twitch-JWT': authToken || '' };
        const [sr, qr] = await Promise.all([
            fetch(`${API_URL}/api/tug/status`, { headers }),
            fetch(`${API_URL}/api/match/queue/status?game_type=${TUG_GAME_TYPE}`, { headers }),
        ]);
        _tugState = await sr.json();
        const q = await qr.json();
        _tugQueued = !!(q && (q.in_queue || q.queued));
        _renderTugContent();
        _renderTugSideBlocks();
    } catch (e) {
        console.warn('[TUG refresh]', e);
    }
}

// Полоса каната. pos приходит с сервера в пределах ±rope_limit; здесь только
// перевод в проценты для отрисовки — это показ, а не логика.
function _tugRopeHtml(pos, limit, me) {
    const clamped = Math.max(-limit, Math.min(limit, Number(pos) || 0));
    const mine = me === 'a' ? clamped : -clamped;
    const pct = 50 + (mine / (limit || 1)) * 50;
    return `
        <div style="margin:8px 0 10px;">
            <div style="display:flex;justify-content:space-between;font-size:11px;color:#adadb8;">
                <span>ты</span><span>соперник</span>
            </div>
            <div style="position:relative;height:14px;background:#2a2a2d;border-radius:7px;margin-top:4px;">
                <div style="position:absolute;left:50%;top:-3px;width:2px;height:20px;background:#5a5a5e;"></div>
                <div style="position:absolute;left:${100 - pct}%;top:-4px;transform:translateX(-50%);
                            font-size:16px;line-height:22px;">🪢</div>
            </div>
        </div>`;
}

// ── Блоки, которые НЕ перерисовываются целиком: обновляем только их нутро,
//    сами <details> остаются теми же элементами и не схлопываются.
function _renderTugSideBlocks() {
    if (!_tugState) return;
    const rules = _tugState.rules || {};

    const r = document.getElementById('tug-rules');
    if (r) {
        r.innerHTML = `
            <p style="margin:0 0 6px;">${escapeHtml(rules.formula_ru || '')}</p>
            <p style="margin:0 0 6px;">${escapeHtml(rules.reward_ru || '')}</p>
            <p style="margin:0;">Организатор — стример этого канала. Apple и Twitch
            не являются спонсорами и в конкурсе не участвуют.</p>`;
    }

    const lb = document.getElementById('tug-leaderboard');
    if (lb) {
        const rows = _tugState.leaderboard || [];
        let ends = '';
        if (_tugState.season_ends_at) {
            try {
                ends = `<div style="font-size:10px;color:#8a8a8e;margin-top:4px;">Сезон до ${
                    new Date(_tugState.season_ends_at).toLocaleDateString('ru-RU')}</div>`;
            } catch (e) { ends = ''; }
        }
        lb.innerHTML = rows.length
            ? `<ol style="margin:0 0 0 16px;padding:0;color:#adadb8;">${
                rows.map((x, i) => `<li>${['🥇', '🥈', '🥉'][i] || (i + 1) + '.'} ${
                    escapeHtml(x.username)} — ${x.elo} ELO</li>`).join('')}</ol>${ends}`
            : `<div style="color:#8a8a8e;">Пока никто не играл.</div>${ends}`;
    }

    const badge = document.getElementById('tug-elo-badge');
    if (badge) {
        const me = (_tugState.leaderboard || []).find(
            x => x.username === (window.userLogin || '').toLowerCase());
        badge.textContent = me ? me.elo + ' ELO' : '—';
    }
}

// ── Меняющаяся часть. Только она переписывается опросом.
function _renderTugContent() {
    const el = document.getElementById('tug-content');
    if (!el || !_tugState) return;
    const rules = _tugState.rules || {};
    const room = _tugState.room;

    if (room && room.status === 'active') {
        el.innerHTML = `
            <div style="font-size:12px;color:#adadb8;">Соперник:
                <b>${escapeHtml(room.opponent || '?')}</b> · осталось ${room.seconds_left}с</div>
            ${_tugRopeHtml(room.pos, rules.rope_limit || 10000, room.my_side)}
            <button class="modal-btn" id="tug-pull" style="width:100%;font-size:15px;padding:12px;">🪢 Тяни!</button>
            <div style="font-size:11px;color:#adadb8;margin-top:4px;">Твои тапы: ${room.my_taps}</div>`;
        const pullBtn = document.getElementById('tug-pull');
        if (pullBtn) pullBtn.addEventListener('click', _tugPull);
        return;
    }

    if (room && room.status === 'finished') {
        const mine = room.my_side;
        const text = room.outcome === 'draw' ? '🤝 Ничья'
            : ((room.outcome === 'win_a' && mine === 'a') || (room.outcome === 'win_b' && mine === 'b')
                ? '🏆 Ты победил' : '😐 Соперник оказался упорнее');
        el.innerHTML = `
            <div style="text-align:center;padding:30px 10px;">
                <div style="font-size:48px;margin-bottom:10px;">🪢</div>
                <div style="font-size:16px;margin-bottom:18px;">${text}</div>
                <button class="modal-btn" id="tug-find">⚔️ Найти противника</button>
            </div>`;
        const f = document.getElementById('tug-find');
        if (f) f.addEventListener('click', _tugFindOpponent);
        return;
    }

    if (_tugQueued) {
        el.innerHTML = `
            <div style="text-align:center;padding:30px 10px;">
                <div style="font-size:48px;margin-bottom:10px;">⏳</div>
                <div style="font-size:16px;font-weight:700;color:#fbbf24;margin-bottom:6px;">
                    Ищем противника...</div>
                <button class="modal-btn cancel" id="tug-cancel">Отменить</button>
            </div>`;
        const c = document.getElementById('tug-cancel');
        if (c) c.addEventListener('click', _tugCancelQueue);
        return;
    }

    el.innerHTML = `
        <div style="text-align:center;padding:30px 10px;">
            <div style="font-size:64px;margin-bottom:14px;">🪢</div>
            <div style="font-size:14px;color:#adadb8;margin-bottom:18px;">
                Двое тянут канат ${rules.match_sec || 45} секунд.<br>
                Награды только за ELO + сезонный топ.
            </div>
            <button class="modal-btn" id="tug-find">⚔️ Найти противника</button>
        </div>`;
    const f = document.getElementById('tug-find');
    if (f) f.addEventListener('click', _tugFindOpponent);
}

async function _tugFindOpponent() {
    try {
        const r = await fetch(`${API_URL}/api/match/queue`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ game_type: TUG_GAME_TYPE }),
        });
        const d = await r.json();
        // Причину отказа печатаем как есть: фронт заморожен, бэкенд может вернуть
        // текст, которого этот код не знает (CLAUDE.md, «Тонкий фронт»).
        if (d.message) showNotification((d.success ? '⏳ ' : '❌ ') + d.message,
                                        d.success ? 'info' : 'warning');
        await _tugRefresh();
    } catch (e) {
        showNotification('❌ Сеть недоступна', 'warning');
    }
}

async function _tugCancelQueue() {
    try {
        await fetch(`${API_URL}/api/match/queue/cancel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ game_type: TUG_GAME_TYPE }),
        });
        await _tugRefresh();
    } catch (e) {
        console.warn('[TUG cancel]', e);
    }
}

// Тапы копятся локально и уходят пачкой раз в секунду: канат двигается плавно, а
// сервер не получает запрос на каждое нажатие. Сколько зачлось — решает сервер.
let _tugPending = 0;
let _tugFlush = null;

function _tugPull() {
    _tugPending += 1;
    if (_tugFlush) return;
    _tugFlush = setTimeout(async () => {
        const taps = _tugPending;
        _tugPending = 0;
        _tugFlush = null;
        if (!taps) return;
        try {
            const r = await fetch(`${API_URL}/api/tug/pull`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
                body: JSON.stringify({ taps }),
            });
            const d = await r.json();
            if (!d.success && d.message) showNotification('❌ ' + d.message, 'warning');
            await _tugRefresh();
        } catch (e) {
            console.warn('[TUG pull]', e);
        }
    }, 1000);
}
