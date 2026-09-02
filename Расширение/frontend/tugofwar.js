// tugofwar.js — «Перетягивание каната». Заменяет кубики (решение владельца 2026-09-01).
//
// Что здесь важно и почему именно так:
//
//  * ВСЕ числа и тексты правил приходят с сервера (`rules` в ответе статуса).
//    Во фронте их копий нет намеренно: фронт замерзает на CDN Twitch до
//    следующего ревью, а правила раунда — это то, что ревьюер обязан увидеть
//    точным. Захотим поменять цену тапа — меняем на бэкенде и деплоим за минуты.
//  * Правила показываются ДО того, как зритель выберет сторону. Это блокер №3
//    комплаенс-ревью: «Publish official rules in the mobile Extension before
//    joining». Поэтому блок с правилами раскрыт на экране выбора стороны, а не
//    спрятан за ссылкой.
//  * Ни одного расчёта исхода тут нет. Клиент шлёт КОЛИЧЕСТВО тапов, сервер сам
//    считает их цену по опубликованной формуле. Иначе автокликер и правленый
//    клиент решали бы раунд.

let _tugPoll = null;
let _tugState = null;

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
            <h2>🪢 Перетягивание каната</h2>
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
        const r = await fetch(`${API_URL}/api/tugofwar/status`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        _tugState = await r.json();
        _renderTugBody();
    } catch (e) {
        console.warn('[TUG refresh]', e);
    }
}

// Полоса каната. pos приходит с сервера в пределах ±rope_limit; здесь только
// перевод в проценты для отрисовки — это показ, а не логика.
function _tugRopeHtml(pos, limit, sideA, sideB) {
    const clamped = Math.max(-limit, Math.min(limit, Number(pos) || 0));
    const pct = 50 + (clamped / (limit || 1)) * 50;
    return `
        <div style="margin:8px 0 10px;">
            <div style="display:flex;justify-content:space-between;font-size:11px;color:#adadb8;">
                <span>${escapeHtml(sideA)}</span><span>${escapeHtml(sideB)}</span>
            </div>
            <div style="position:relative;height:14px;background:#2a2a2d;border-radius:7px;margin-top:4px;">
                <div style="position:absolute;left:50%;top:-3px;width:2px;height:20px;background:#5a5a5e;"></div>
                <div style="position:absolute;left:${pct}%;top:-4px;transform:translateX(-50%);
                            font-size:16px;line-height:22px;">🪢</div>
            </div>
        </div>`;
}

function _tugRulesHtml(rules) {
    if (!rules) return '';
    return `
        <details style="margin:8px 0;padding:8px;background:#1a1a1c;border-radius:6px;
                        font-size:11px;color:#8a8a8e;" open>
            <summary style="cursor:pointer;color:#adadb8;">📜 Правила раунда</summary>
            <div style="margin-top:6px;line-height:1.5;">
                <p style="margin:0 0 6px;">Участие бесплатное, покупка не требуется.</p>
                <p style="margin:0 0 6px;">${escapeHtml(rules.formula_ru || '')}</p>
                <p style="margin:0 0 6px;">${escapeHtml(rules.reward_ru || '')}</p>
                <p style="margin:0;">Ничья остаётся ничьёй — победитель не разыгрывается.
                Организатор — стример этого канала. Apple и Twitch не являются
                спонсорами и в конкурсе не участвуют.</p>
            </div>
        </details>`;
}

function _renderTugBody() {
    const body = document.getElementById('tug-body');
    if (!body || !_tugState) return;
    const rules = _tugState.rules || {};
    const rnd = _tugState.round;

    if (!rnd) {
        const last = _tugState.last;
        const lastLine = last
            ? `<div style="font-size:11px;color:#adadb8;margin-top:6px;">Прошлый раунд:
               ${last.result === 'draw' ? 'ничья'
                : 'победила сторона «' + escapeHtml(last.result === 'a' ? last.side_a : last.side_b) + '»'}</div>`
            : '';
        body.innerHTML = `
            <div style="font-size:12px;color:#adadb8;">Раунд ещё не запущен — стример
            начнёт его сам.</div>${lastLine}${_tugRulesHtml(rules)}`;
        return;
    }

    const me = rnd.me;
    let controls = '';

    if (rnd.status === 'join') {
        controls = me
            ? `<div style="font-size:12px;color:#3fb950;">Ты за «${escapeHtml(me.side === 'a' ? rnd.side_a : rnd.side_b)}». Ждём старта тяги…</div>`
            : `<div style="display:flex;gap:8px;">
                   <button class="modal-btn" data-tug-side="a" style="flex:1;">${escapeHtml(rnd.side_a)}</button>
                   <button class="modal-btn" data-tug-side="b" style="flex:1;">${escapeHtml(rnd.side_b)}</button>
               </div>`;
    } else if (rnd.status === 'pull') {
        controls = me
            ? `<button class="modal-btn" id="tug-pull" style="width:100%;font-size:15px;padding:12px;">🪢 Тяни!</button>
               <div style="font-size:11px;color:#adadb8;margin-top:4px;">Твои тапы: ${me.taps}</div>`
            : `<div style="font-size:12px;color:#f0883e;">Ты не выбрал сторону до закрытия приёма — в этом раунде уже не поучаствовать.</div>`;
    } else {
        controls = `<div style="font-size:13px;">${rnd.result === 'draw' ? '🤝 Ничья'
            : '🏆 Победила сторона «' + escapeHtml(rnd.result === 'a' ? rnd.side_a : rnd.side_b) + '»'}</div>`;
    }

    const phase = rnd.status === 'join' ? 'Приём заявок'
        : (rnd.status === 'pull' ? 'Тянем!' : 'Раунд окончен');

    body.innerHTML = `
        <div style="font-size:12px;color:#adadb8;">${phase}${
            rnd.status === 'finished' ? '' : ` · осталось ${rnd.seconds_left}с`}</div>
        ${_tugRopeHtml(rnd.pos, rules.rope_limit || 10000, rnd.side_a, rnd.side_b)}
        <div style="font-size:11px;color:#adadb8;margin-bottom:8px;">
            В командах: ${rnd.team_a || 0} против ${rnd.team_b || 0}
        </div>
        ${controls}
        ${_tugRulesHtml(rules)}`;

    body.querySelectorAll('[data-tug-side]').forEach(btn => {
        btn.addEventListener('click', () => _tugJoin(btn.dataset.tugSide));
    });
    const pullBtn = document.getElementById('tug-pull');
    if (pullBtn) pullBtn.addEventListener('click', _tugPull);
}

async function _tugJoin(side) {
    try {
        const r = await fetch(`${API_URL}/api/tugofwar/join`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ side }),
        });
        const d = await r.json();
        // Причину отказа печатаем как есть: фронт заморожен, а бэкенд может
        // вернуть текст, которого этот код ещё не знает (CLAUDE.md, «Тонкий фронт»).
        showNotification((d.success ? '✅ ' : '❌ ') + (d.message || ''),
                         d.success ? 'success' : 'warning');
        await _tugRefresh();
    } catch (e) {
        showNotification('❌ Сеть недоступна', 'warning');
    }
}

// Тапы копятся локально и уходят пачкой раз в секунду: так канат двигается
// плавно, а сервер не получает запрос на каждое нажатие. Сколько тапов зачлось,
// решает сервер — он же режет пачку по своему пределу.
let _tugPending = 0;
let _tugFlush = null;

function _tugPull() {
    _tugPending += 1;
    const rope = document.querySelector('#tug-body [style*="🪢"]');
    if (rope) rope.style.transform = 'translateX(-50%) scale(1.15)';
    if (_tugFlush) return;
    _tugFlush = setTimeout(async () => {
        const taps = _tugPending;
        _tugPending = 0;
        _tugFlush = null;
        if (!taps) return;
        try {
            const r = await fetch(`${API_URL}/api/tugofwar/pull`, {
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
