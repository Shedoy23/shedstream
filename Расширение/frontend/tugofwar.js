// tugofwar.js — «Канат»: дуэль 1 на 1 с рейтингом и сезоном. Заменил кубики.
//
// Устроен по принципу остальных игр: общая очередь подбора (game_type='tug'),
// комната на двоих, ELO, сезонные призы топ-3.
//
// Что здесь важно:
//  * ВСЕ числа и тексты правил приходят с сервера (`rules` в ответе статуса).
//    Копий во фронте нет намеренно: фронт замерзает на CDN Twitch до следующего
//    ревью, а правила матча ревьюер обязан увидеть точными.
//  * Исход не считается на клиенте. Клиент шлёт КОЛИЧЕСТВО тапов, цену им
//    назначает сервер по опубликованной формуле — иначе правленый клиент решал
//    бы матч.

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

function _renderTugModal() {
    let modal = document.getElementById('tug-modal');
    if (modal) modal.remove();
    modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'tug-modal';
    modal.innerHTML = `
        <div class="modal-content" style="max-width:420px;">
            <h2>🪢 Канат — дуэль</h2>
            <div id="tug-body"><div class="loading">Загрузка…</div></div>
            <button class="modal-btn cancel" id="tug-close">Закрыть</button>
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
        _renderTugBody();
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

function _tugRulesHtml(rules) {
    if (!rules) return '';
    return `
        <details style="margin:8px 0;padding:8px;background:#1a1a1c;border-radius:6px;
                        font-size:11px;color:#8a8a8e;">
            <summary style="cursor:pointer;color:#adadb8;">📜 Правила</summary>
            <div style="margin-top:6px;line-height:1.5;">
                <p style="margin:0 0 6px;">${escapeHtml(rules.formula_ru || '')}</p>
                <p style="margin:0 0 6px;">${escapeHtml(rules.reward_ru || '')}</p>
                <p style="margin:0;">Организатор — стример этого канала. Apple и Twitch
                не являются спонсорами и в конкурсе не участвуют.</p>
            </div>
        </details>`;
}

function _tugBoardHtml(rows, endsAt) {
    if (!rows || !rows.length) return '';
    const items = rows.map((r, i) =>
        `<li>${['🥇', '🥈', '🥉'][i] || (i + 1) + '.'} ${escapeHtml(r.username)} — ${r.elo}</li>`).join('');
    let ends = '';
    if (endsAt) {
        try {
            ends = `<div style="font-size:10px;color:#8a8a8e;margin-top:4px;">Сезон до ${
                new Date(endsAt).toLocaleDateString('ru-RU')}</div>`;
        } catch (e) { ends = ''; }
    }
    return `
        <details style="margin-top:8px;font-size:11px;color:#adadb8;">
            <summary style="cursor:pointer;">🏆 Рейтинг сезона</summary>
            <ol style="margin:6px 0 0 16px;padding:0;">${items}</ol>${ends}
        </details>`;
}

function _renderTugBody() {
    const body = document.getElementById('tug-body');
    if (!body || !_tugState) return;
    const rules = _tugState.rules || {};
    const room = _tugState.room;
    const tail = _tugRulesHtml(rules) +
                 _tugBoardHtml(_tugState.leaderboard, _tugState.season_ends_at);

    if (room && room.status === 'active') {
        body.innerHTML = `
            <div style="font-size:12px;color:#adadb8;">Соперник:
                <b>${escapeHtml(room.opponent || '?')}</b> · осталось ${room.seconds_left}с</div>
            ${_tugRopeHtml(room.pos, rules.rope_limit || 10000, room.my_side)}
            <button class="modal-btn" id="tug-pull" style="width:100%;font-size:15px;padding:12px;">🪢 Тяни!</button>
            <div style="font-size:11px;color:#adadb8;margin-top:4px;">Твои тапы: ${room.my_taps}</div>
            ${tail}`;
        const pullBtn = document.getElementById('tug-pull');
        if (pullBtn) pullBtn.addEventListener('click', _tugPull);
        return;
    }

    if (room && room.status === 'finished') {
        const mine = room.my_side;
        const text = room.outcome === 'draw' ? '🤝 Ничья'
            : ((room.outcome === 'win_a' && mine === 'a') || (room.outcome === 'win_b' && mine === 'b')
                ? '🏆 Ты победил' : '😐 Соперник оказался упорнее');
        body.innerHTML = `
            <div style="font-size:14px;margin-bottom:6px;">${text}</div>
            <button class="modal-btn" id="tug-find" style="width:100%;">Найти нового соперника</button>
            ${tail}`;
        const f = document.getElementById('tug-find');
        if (f) f.addEventListener('click', _tugFindOpponent);
        return;
    }

    if (_tugQueued) {
        body.innerHTML = `
            <div style="font-size:12px;color:#adadb8;">⏳ Ищем соперника…</div>
            <button class="modal-btn cancel" id="tug-cancel" style="width:100%;margin-top:8px;">Отменить</button>
            ${tail}`;
        const c = document.getElementById('tug-cancel');
        if (c) c.addEventListener('click', _tugCancelQueue);
        return;
    }

    body.innerHTML = `
        <div style="font-size:12px;color:#adadb8;">Дуэль на канате: кто перетянет за
            ${rules.match_sec || 45} секунд. Участие бесплатное.</div>
        <button class="modal-btn" id="tug-find" style="width:100%;margin-top:8px;">Найти соперника</button>
        ${tail}`;
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
