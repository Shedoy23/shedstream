// voting.js — Voting events UI (Phase 4, 2026-05-11)
//
// View states:
//   - waiting   → pool progress bar + leaderboard (no event yet)
//   - active    → options list + bid form + top bidders
//   - finished  → результат + winner

// Phase C (2026-05-17): PubSub realtime push покрывает vote_started/tick/ended.
// Polling остаётся как fallback на случай потери delivery: 4s → 30s
// (Twitch PubSub не гарантирует доставку, но 99%+ обычно proходит).
const VOTING_POLL_INTERVAL_MS = 30000;
let _votingPollId = null;
let _votingBidLocked = false;
let _votingUnsubs = [];  // RealtimeBus unsubscribers — освобождаются при close
let _votingTimerId = null;       // 1-сек тик обратного отсчёта (иначе таймер «висел»)
let _votingEndsAt = null;        // Date конца текущего раунда
let _votingResultActive = false; // показан экран победителя — poll (30с) не затирает

async function openVotingModal() {
    if (!isAuthUser()) {
        showNotification('⚠️ Войдите через Twitch', 'warning');
        return;
    }
    _renderVotingModal();
    await _refreshVoting();
    _startVotingPolling();
    _subscribeVotingRealtime();
}

function _subscribeVotingRealtime() {
    if (!window.RealtimeBus) return;
    // Все три события: started/tick/ended → trigger refresh.
    // Можно было применять envelope.data напрямую (less roundtrip), но
    // _refreshVoting единственный canonical render path — меньше risk
    // дивергенции UI vs server state.
    _votingUnsubs.push(window.RealtimeBus.subscribe('vote_started', function () { _votingResultActive = false; _refreshVoting(); }));
    _votingUnsubs.push(window.RealtimeBus.subscribe('vote_tick', _refreshVoting));
    _votingUnsubs.push(window.RealtimeBus.subscribe('vote_ended', _onVoteEnded));
}

function _unsubscribeVotingRealtime() {
    for (let i = 0; i < _votingUnsubs.length; i++) {
        try { _votingUnsubs[i](); } catch (e) {}
    }
    _votingUnsubs = [];
}

function _renderVotingModal() {
    let modal = document.getElementById('voting-modal');
    if (modal) modal.remove();
    modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'voting-modal';
    modal.innerHTML = `
        <div class="modal-content" style="max-width:480px;max-height:90vh;overflow-y:auto;">
            <h2>🗳️ Голосование за стримера</h2>
            <div id="voting-content"><div class="loading">Загрузка...</div></div>
            <button class="modal-btn cancel" id="voting-close-btn" style="margin-top:10px;">Закрыть</button>
        </div>
    `;
    (document.getElementById('overlay-panel') || document.body).appendChild(modal);
    document.getElementById('voting-close-btn').addEventListener('click', () => {
        _stopVotingPolling();
        _stopVotingTimer();
        _unsubscribeVotingRealtime();
        _votingResultActive = false;
        modal.remove();
    });
}

async function _refreshVoting() {
    try {
        const headers = { 'X-Twitch-JWT': authToken || '' };
        const r = await fetch(`${API_URL}/api/voting/status`, { headers });
        const data = await r.json();
        if (!data.success) {
            _renderVotingError(data.message || 'Ошибка');
            return;
        }
        if (data.active_event) {
            _votingResultActive = false;
            _renderActiveVoting(data);
        } else if (_votingResultActive) {
            // держим экран победителя — не затираем копилкой на следующем poll'е
        } else {
            _renderWaitingState(data);
        }
    } catch (e) {
        _renderVotingError('Ошибка сети');
    }
}

function _renderWaitingState(data) {
    _stopVotingTimer();
    const el = document.getElementById('voting-content');
    if (!el) return;
    const pct = data.pool_pct || 0;
    const cur = data.pool_units || 0;
    const max = data.threshold || 1000;

    const noTemplateMsg = !data.has_default_template
        ? `<div style="background:#3a1a1a;border:1px solid #f87171;border-radius:6px;padding:8px;margin-top:10px;font-size:11px;color:#f87171;">
              ⚠️ Стример ещё не настроил шаблоны голосований.
              Когда копилка дойдёт до конца — ничего не запустится.
           </div>`
        : '';

    el.innerHTML = `
        <div style="text-align:center;padding:14px 10px;">
            <div style="font-size:56px;margin-bottom:8px;">🗳️</div>
            <div style="font-size:14px;color:#adadb8;margin-bottom:14px;">
                Активного голосования сейчас нет. Копилка наполняется<br>
                просмотром (+1 unit / мин активного зрителя) и чатом (+5 / msg).
            </div>
            <div style="background:#1a1a1c;border-radius:8px;padding:12px;margin-bottom:10px;">
                <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:6px;">
                    <span>Копилка</span>
                    <span style="color:#fbbf24;">${cur.toLocaleString('ru-RU')} / ${max.toLocaleString('ru-RU')}</span>
                </div>
                <div style="background:#3a3a3e;border-radius:4px;height:10px;overflow:hidden;">
                    <div style="background:linear-gradient(90deg,#9147ff,#fbbf24);
                                width:${pct}%;height:100%;transition:width .3s;"></div>
                </div>
                <div style="font-size:11px;color:#adadb8;margin-top:6px;">${pct}% до автостарта</div>
            </div>
            ${noTemplateMsg}
        </div>
    `;
}

function _renderActiveVoting(data) {
    const el = document.getElementById('voting-content');
    if (!el) return;
    const event = data.active_event;
    const endsAt = new Date(event.ends_at);
    const now = new Date();
    const remainingMs = Math.max(0, endsAt.getTime() - now.getTime());
    const remainingSec = Math.floor(remainingMs / 1000);
    const remainingMin = Math.floor(remainingSec / 60);
    const remainingSecOnly = remainingSec % 60;

    const totalPool = event.total_pool || 0;
    const opts = event.options || [];
    const sortedOpts = [...opts].sort((a, b) => b.pool - a.pool);
    const winner = sortedOpts[0];

    const optsHtml = sortedOpts.map((o, i) => {
        const pct = totalPool > 0 ? Math.round(o.pool / totalPool * 100) : 0;
        const isLeading = i === 0 && o.pool > 0;
        return `
            <div style="background:${isLeading ? 'rgba(251,191,36,.15)' : '#1a1a1c'};
                        border:1px solid ${isLeading ? 'rgba(251,191,36,.5)' : '#3a3a3e'};
                        border-radius:8px;padding:10px;margin-bottom:6px;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <div style="flex:1;">
                        <div style="font-weight:700;font-size:13px;">
                            ${isLeading ? '👑 ' : ''}${escapeHtml(o.label)}
                        </div>
                        ${o.description ? `<div style="font-size:11px;color:#adadb8;margin-top:2px;">${escapeHtml(o.description)}</div>` : ''}
                    </div>
                    <button class="small-btn" data-vote-option="${o.id}" style="margin-left:8px;">
                        Голосовать
                    </button>
                </div>
                <div style="background:#3a3a3e;border-radius:3px;height:6px;overflow:hidden;margin-top:8px;">
                    <div style="background:${isLeading ? '#fbbf24' : '#9147ff'};
                                width:${pct}%;height:100%;transition:width .3s;"></div>
                </div>
                <div style="display:flex;justify-content:space-between;font-size:11px;color:#adadb8;margin-top:4px;">
                    <span>${o.pool.toLocaleString('ru-RU')}💎</span>
                    <span>${pct}%</span>
                </div>
            </div>
        `;
    }).join('');

    const topBidsHtml = (data.top_bidders || []).map((b, i) => {
        const medal = ['🥇','🥈','🥉'][i] || `${i+1}.`;
        return `<div style="display:flex;justify-content:space-between;font-size:11px;padding:2px 0;">
            <span>${medal} @${escapeHtml(b.username)}</span>
            <span style="color:#fbbf24;">${b.total.toLocaleString('ru-RU')}💎</span>
        </div>`;
    }).join('');

    // «Народный выбор игры» (open mode): зритель может предложить свою игру.
    const proposeHtml = event.allow_proposals ? `
        <button class="modal-btn" id="voting-propose-btn" style="margin-top:10px;width:100%;">➕ Предложить свою игру</button>
        <div style="font-size:10px;color:#7a7a85;text-align:center;margin-top:4px;">
            💎 виртуальны. Вклад спишется, только если стример одобрит игру. Возврата нет.
        </div>` : '';
    const optsBlock = sortedOpts.length ? optsHtml
        : `<div style="text-align:center;color:#adadb8;font-size:12px;padding:12px;">Пока нет вариантов${event.allow_proposals ? ' — предложи игру первым!' : ''}</div>`;

    el.innerHTML = `
        <div style="background:linear-gradient(135deg,rgba(145,71,255,.18),rgba(251,191,36,.08));
                    border:1px solid rgba(145,71,255,.5);border-radius:10px;padding:12px;margin-bottom:12px;">
            <div style="font-size:15px;font-weight:800;">⚡ «${escapeHtml(event.template_name || 'Голосование')}»</div>
            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px;font-size:12px;">
                <span style="color:#adadb8;">⏰ Осталось: <b id="voting-timer" style="color:#fbbf24;">${_fmtRemain(remainingMs)}</b></span>
                <span style="color:#fbbf24;">💰 ${totalPool.toLocaleString('ru-RU')}💎</span>
            </div>
        </div>
        <div style="font-size:12px;color:#adadb8;margin-bottom:4px;">Варианты (клик чтобы выбрать):</div>
        <div id="voting-options-list">${optsBlock}</div>
        ${proposeHtml}
        ${topBidsHtml ? `
            <details style="margin-top:10px;background:#1a1a1c;border-radius:6px;padding:8px 10px;">
                <summary style="cursor:pointer;font-size:11px;color:#adadb8;">🏆 Топ-вкладчиков</summary>
                <div style="margin-top:6px;">${topBidsHtml}</div>
            </details>
        ` : ''}
    `;

    // Bind vote buttons
    el.querySelectorAll('[data-vote-option]').forEach(btn => {
        const optId = parseInt(btn.dataset.voteOption, 10);
        btn.addEventListener('click', () => _promptBidAmount(optId, opts.find(o => o.id === optId)));
    });

    const proposeBtn = document.getElementById('voting-propose-btn');
    if (proposeBtn) proposeBtn.addEventListener('click', _promptProposeGame);

    _votingEndsAt = endsAt;
    _startVotingTimer();  // посекундный отсчёт (не ждём 30с-poll / realtime-тик)
}

function _promptBidAmount(optionId, option) {
    let bidModal = document.getElementById('voting-bid-modal');
    if (bidModal) bidModal.remove();
    bidModal = document.createElement('div');
    bidModal.className = 'modal active';
    bidModal.id = 'voting-bid-modal';
    bidModal.innerHTML = `
        <div class="modal-content" style="max-width:340px;">
            <h2>🗳️ Голосую за</h2>
            <div style="background:#1a1a1c;border-radius:8px;padding:10px;margin-bottom:10px;">
                <div style="font-weight:700;">${escapeHtml(option?.label || '?')}</div>
                ${option?.description ? `<div style="font-size:11px;color:#adadb8;margin-top:2px;">${escapeHtml(option.description)}</div>` : ''}
            </div>
            <input id="voting-bid-amount" type="number" class="modal-input" placeholder="Сумма (мин. 50💎)" min="50">
            <div style="display:flex;gap:4px;margin-bottom:10px;">
                <button class="quick-vote" data-quick="50">50💎</button>
                <button class="quick-vote" data-quick="500">500💎</button>
                <button class="quick-vote" data-quick="5000">5k💎</button>
                <button class="quick-vote" data-quick="50000">50k💎</button>
            </div>
            <button class="modal-btn" id="voting-bid-confirm-btn">✅ Голосовать</button>
            <button class="modal-btn cancel" id="voting-bid-cancel-btn" style="margin-top:6px;">Отмена</button>
        </div>
    `;
    (document.getElementById('overlay-panel') || document.body).appendChild(bidModal);

    bidModal.querySelectorAll('[data-quick]').forEach(qb => {
        qb.addEventListener('click', () => {
            document.getElementById('voting-bid-amount').value = qb.dataset.quick;
        });
    });
    document.getElementById('voting-bid-confirm-btn').addEventListener('click', async () => {
        const amt = parseInt(document.getElementById('voting-bid-amount').value);
        if (!amt || amt < 50) {
            showNotification('Минимум 50💎', 'error');
            return;
        }
        await _placeBid(optionId, amt);
        bidModal.remove();
    });
    document.getElementById('voting-bid-cancel-btn').addEventListener('click', () => bidModal.remove());
}

async function _placeBid(optionId, amount) {
    if (_votingBidLocked) return;
    _votingBidLocked = true;
    try {
        const r = await fetch(`${API_URL}/api/voting/bid`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ option_id: optionId, amount }),
        });
        const data = await r.json();
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) {
            if (typeof loadUserData === 'function') loadUserData();
            await _refreshVoting();
        }
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    } finally {
        setTimeout(() => { _votingBidLocked = false; }, 500);
    }
}

// «Народный выбор игры»: зритель предлагает свою игру + вклад. Compliance:
// вклад спишется ТОЛЬКО если стример одобрит; крустики виртуальны; возврата нет.
function _promptProposeGame() {
    let m = document.getElementById('voting-propose-modal');
    if (m) m.remove();
    m = document.createElement('div');
    m.className = 'modal active';
    m.id = 'voting-propose-modal';
    m.innerHTML = `
        <div class="modal-content" style="max-width:340px;">
            <h2>➕ Предложить игру</h2>
            <div style="font-size:11px;color:#adadb8;margin-bottom:8px;">
                Стример решит, добавить ли её в голосование. Вклад спишется, только если одобрит.
            </div>
            <input id="voting-propose-label" type="text" class="modal-input" placeholder="Название игры" maxlength="60">
            <input id="voting-propose-pledge" type="number" class="modal-input" placeholder="Твой вклад (мин. 100💎)" min="100" style="margin-top:6px;">
            <div style="display:flex;gap:4px;margin:8px 0;">
                <button class="quick-vote" data-qp="100">100💎</button>
                <button class="quick-vote" data-qp="500">500💎</button>
                <button class="quick-vote" data-qp="5000">5k💎</button>
                <button class="quick-vote" data-qp="50000">50k💎</button>
            </div>
            <div style="font-size:10px;color:#7a7a85;margin-bottom:8px;">
                💎 крустики виртуальны, ценности вне расширения не имеют. Вклад необратим, возврата нет.
            </div>
            <button class="modal-btn" id="voting-propose-confirm">📨 Отправить на одобрение</button>
            <button class="modal-btn cancel" id="voting-propose-cancel" style="margin-top:6px;">Отмена</button>
        </div>
    `;
    (document.getElementById('overlay-panel') || document.body).appendChild(m);

    m.querySelectorAll('[data-qp]').forEach(qb => {
        qb.addEventListener('click', () => {
            document.getElementById('voting-propose-pledge').value = qb.dataset.qp;
        });
    });
    document.getElementById('voting-propose-confirm').addEventListener('click', async () => {
        const label = (document.getElementById('voting-propose-label').value || '').trim();
        const pledge = parseInt(document.getElementById('voting-propose-pledge').value);
        if (label.length < 2) { showNotification('Введи название игры', 'error'); return; }
        if (!pledge || pledge < 100) { showNotification('Минимальный вклад 100💎', 'error'); return; }
        await _proposeGame(label, pledge);
        m.remove();
    });
    document.getElementById('voting-propose-cancel').addEventListener('click', () => m.remove());
}

async function _proposeGame(label, pledge) {
    if (_votingBidLocked) return;
    _votingBidLocked = true;
    try {
        const r = await fetch(`${API_URL}/api/voting/propose`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ label, pledge }),
        });
        const data = await r.json();
        // Платно + отложенный исход → тост от бэка («отправлено на одобрение, спишется если одобрят»).
        showNotification(data.message, data.success ? 'success' : 'error');
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    } finally {
        setTimeout(() => { _votingBidLocked = false; }, 500);
    }
}

function _renderVotingError(msg) {
    const el = document.getElementById('voting-content');
    if (el) el.innerHTML = `<div style="color:#f87171;text-align:center;padding:14px;">${msg}</div>`;
}

function _startVotingPolling() {
    _stopVotingPolling();
    _votingPollId = setInterval(_refreshVoting, VOTING_POLL_INTERVAL_MS);
}

function _stopVotingPolling() {
    if (_votingPollId) {
        clearInterval(_votingPollId);
        _votingPollId = null;
    }
}

// ── Обратный отсчёт (1с) ──────────────────────────────────────────────────
function _fmtRemain(ms) {
    const s = Math.max(0, Math.floor(ms / 1000));
    return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')}`;
}
function _votingTick() {
    const el = document.getElementById('voting-timer');
    if (!el || !_votingEndsAt) { _stopVotingTimer(); return; }
    const ms = _votingEndsAt.getTime() - Date.now();
    el.textContent = _fmtRemain(ms);
    if (ms <= 0) { _stopVotingTimer(); _refreshVoting(); }  // добьём финал, если realtime потерялся
}
function _startVotingTimer() {
    _stopVotingTimer();
    _votingTick();
    _votingTimerId = setInterval(_votingTick, 1000);
}
function _stopVotingTimer() {
    if (_votingTimerId) { clearInterval(_votingTimerId); _votingTimerId = null; }
}

// ── Экран победителя (vote_ended) ─────────────────────────────────────────
function _onVoteEnded(data) {
    _votingResultActive = true;
    _stopVotingTimer();
    _renderFinishedState(data && data.winner);
}
function _renderFinishedState(winner) {
    const el = document.getElementById('voting-content');
    if (!el) return;
    const body = winner
        ? `<div style="font-size:56px;margin-bottom:6px;">🏆</div>
           <div style="font-size:13px;color:#adadb8;margin-bottom:4px;">Победила игра</div>
           <div style="font-size:20px;font-weight:800;color:#fbbf24;margin-bottom:6px;">${escapeHtml(winner.label)}</div>
           <div style="font-size:12px;color:#adadb8;">${(winner.pool || 0).toLocaleString('ru-RU')}💎 вложено</div>`
        : `<div style="font-size:56px;margin-bottom:6px;">🗳️</div>
           <div style="font-size:15px;font-weight:700;color:#adadb8;">Раунд завершён — никто не вложил</div>`;
    el.innerHTML = `
        <div style="text-align:center;padding:22px 10px;">
            ${body}
            <button class="modal-btn" id="voting-result-dismiss" style="margin-top:16px;">← К копилке</button>
        </div>
    `;
    const b = document.getElementById('voting-result-dismiss');
    if (b) b.addEventListener('click', () => { _votingResultActive = false; _refreshVoting(); });
}

window.openVotingModal = openVotingModal;
