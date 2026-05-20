// dice.js — Dice match UI (Phase 5.2, 2026-05-11)
//
// Два режима:
//   1. Vs Bot — instant single-click roll (без ELO, для расслабона)
//   2. PvP — через matchmaking queue + roll button после match
//
// Compliance UI (см. COMPLIANCE_REWORK_PLAN.md §3 lexicon scrub):
//   - Лексика: "Бросок", "Roll", "Match" — нейтральные слова
//   - Animation: dice rolling 0.8s — простой emoji shuffle

const DICE_GAME_TYPE = 'dice';
// Phase C (2026-05-17): PubSub realtime push для match_state. Polling
// fallback для queue tick: 3s → 15s.
const DICE_POLL_INTERVAL_MS = 15000;

let _dicePollId = null;
let _diceCurrentRoomId = null;
let _diceMoveLocked = false;
let _diceLastState = null;
let _diceRealtimeUnsub = null;

const _DICE_EMOJI = ['⚀', '⚁', '⚂', '⚃', '⚄', '⚅'];

async function openDiceModal() {
    if (!isAuthUser()) {
        showNotification('⚠️ Войдите через Twitch', 'warning');
        return;
    }
    _renderDiceModal();
    await _diceRefreshStatus();
    _startDicePolling();
    _subscribeDiceRealtime();
}

function _subscribeDiceRealtime() {
    if (!window.RealtimeBus || _diceRealtimeUnsub) return;
    _diceRealtimeUnsub = window.RealtimeBus.subscribe('match_state', function (data) {
        if (!_diceCurrentRoomId || data.room_id !== _diceCurrentRoomId) return;
        if (data.game !== DICE_GAME_TYPE) return;
        _diceRefreshStatus();
    });
}

function _unsubscribeDiceRealtime() {
    if (_diceRealtimeUnsub) { _diceRealtimeUnsub(); _diceRealtimeUnsub = null; }
}

function _renderDiceModal() {
    let modal = document.getElementById('dice-modal');
    if (modal) modal.remove();
    modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'dice-modal';
    modal.innerHTML = `
        <div class="modal-content" style="max-width:400px;">
            <h2 style="display:flex;align-items:center;justify-content:space-between;">
                <span>🎲 Кубики</span>
                <span id="dice-elo-badge" style="font-size:12px;color:#adadb8;font-weight:500;">—</span>
            </h2>
            <div id="dice-content" style="min-height:280px;">
                <div class="loading">Загрузка...</div>
            </div>
            <details style="margin-top:10px;background:#1a1a1c;border-radius:6px;padding:8px 12px;">
                <summary style="cursor:pointer;font-size:12px;color:#adadb8;">🏆 Лидерборд сезона</summary>
                <div id="dice-leaderboard" style="margin-top:8px;font-size:12px;">
                    <div class="loading">Загрузка...</div>
                </div>
            </details>
            <button class="modal-btn cancel" id="dice-close-btn" style="margin-top:10px;">Закрыть</button>
        </div>
    `;
    (document.getElementById('overlay-panel') || document.body).appendChild(modal);
    document.getElementById('dice-close-btn').addEventListener('click', () => {
        _stopDicePolling();
        _unsubscribeDiceRealtime();
        _diceCurrentRoomId = null;
        modal.remove();
    });
    _loadDiceLeaderboard();
}

async function _loadDiceLeaderboard() {
    try {
        const headers = { 'X-Twitch-JWT': authToken || '' };
        const r = await fetch(`${API_URL}/api/dice/leaderboard`, { headers });
        const data = await r.json();
        const el = document.getElementById('dice-leaderboard');
        if (!el || !data.success) return;
        const rows = data.leaderboard || [];
        if (!rows.length) {
            el.innerHTML = '<div style="color:#adadb8;">Никто ещё не играл в PvP</div>';
            return;
        }
        const medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣'];
        el.innerHTML = rows.map(r => `
            <div style="display:flex;justify-content:space-between;padding:3px 0;">
                <span>${medals[r.rank-1] || r.rank} ${escapeHtml(r.username)}</span>
                <span style="color:#fbbf24;">${r.elo} ELO${r.win_streak>=2?' 🔥'+r.win_streak:''}</span>
            </div>
        `).join('');
    } catch (e) { /* silent */ }
}

async function _diceRefreshStatus() {
    try {
        const headers = { 'X-Twitch-JWT': authToken || '' };
        const r = await fetch(`${API_URL}/api/match/queue/status?game_type=${DICE_GAME_TYPE}`, { headers });
        const data = await r.json();
        if (!data.success) { _renderDiceIdle(); return; }

        const status = data.status;
        if (status === 'idle') {
            _renderDiceIdle();
        } else if (status === 'queued') {
            _renderDiceQueued(data);
        } else if (status === 'matched' || status === 'in_room') {
            if (data.room_id) {
                _diceCurrentRoomId = data.room_id;
                await _diceRefreshRoom(data.room_id);
            } else _renderDiceIdle();
        }
    } catch (e) {
        console.error('[dice] status fetch failed:', e);
    }
}

function _renderDiceIdle() {
    const el = document.getElementById('dice-content');
    if (!el) return;
    el.innerHTML = `
        <div style="text-align:center;padding:20px 10px;">
            <div style="font-size:56px;margin-bottom:14px;letter-spacing:8px;">🎲 🎲</div>
            <div style="font-size:13px;color:#adadb8;margin-bottom:18px;">
                Простой бросок 2d6. Выше сумма = победа.<br>
                Vs Bot — для расслабона. Vs Player — за ELO.
            </div>
            <button class="modal-btn" id="dice-bot-btn" style="margin-bottom:8px;">
                🤖 Бросок против бота
            </button>
            <button class="modal-btn" id="dice-pvp-btn">
                ⚔️ Найти противника (PvP)
            </button>
        </div>
    `;
    document.getElementById('dice-bot-btn').addEventListener('click', _dicePlayVsBot);
    document.getElementById('dice-pvp-btn').addEventListener('click', _diceFindOpponent);
}

function _renderDiceQueued(data) {
    const el = document.getElementById('dice-content');
    if (!el) return;
    const pos = data.queue_position || 1;
    const elo = data.elo_at_queue || 1100;
    el.innerHTML = `
        <div style="text-align:center;padding:30px 10px;">
            <div style="font-size:48px;margin-bottom:10px;">⏳</div>
            <div style="font-size:16px;font-weight:700;color:#fbbf24;margin-bottom:6px;">
                Ищем противника...
            </div>
            <div style="font-size:13px;color:#adadb8;margin-bottom:18px;">
                Позиция: ${pos} • ELO: ${elo}
            </div>
            <button class="modal-btn" style="background:#3a1a1a;color:#f87171;border:1px solid #f87171;" id="dice-cancel-btn">
                ❌ Отменить поиск
            </button>
            <div style="font-size:11px;color:#adadb8;margin-top:14px;">
                💡 Слишком долго? Сыграй против бота —
                <button id="dice-fallback-bot" style="background:none;border:none;color:#9147ff;cursor:pointer;text-decoration:underline;font-size:11px;padding:0;">
                    нажми сюда
                </button>
            </div>
        </div>
    `;
    document.getElementById('dice-cancel-btn').addEventListener('click', _diceCancelQueue);
    document.getElementById('dice-fallback-bot').addEventListener('click', async () => {
        await _diceCancelQueue();
        await _dicePlayVsBot();
    });
}

async function _dicePlayVsBot() {
    if (_diceMoveLocked) return;
    _diceMoveLocked = true;
    const el = document.getElementById('dice-content');

    // Animation: dice rolling
    if (el) {
        el.innerHTML = `
            <div style="text-align:center;padding:50px 10px;">
                <div id="dice-rolling-anim" style="font-size:72px;letter-spacing:12px;">🎲 🎲</div>
                <div style="font-size:14px;color:#adadb8;margin-top:18px;">Бросаем...</div>
            </div>
        `;
        _animateDiceRolling('dice-rolling-anim', 600);
    }

    try {
        const r = await fetch(`${API_URL}/api/dice/play-vs-bot`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({}),
        });
        const data = await r.json();
        if (!data.success) {
            showNotification(data.message || 'Не удалось', 'error');
            _renderDiceIdle();
            return;
        }

        // Wait for animation to finish
        await new Promise(res => setTimeout(res, 700));

        if (el) {
            const yourDice = data.your_roll.map(d => _DICE_EMOJI[d-1]).join(' ');
            const botDice = data.bot_roll.map(d => _DICE_EMOJI[d-1]).join(' ');
            const resultColor = data.outcome === 'win' ? '#4ade80'
                              : data.outcome === 'loss' ? '#f87171'
                              : '#fbbf24';
            const resultText = data.outcome === 'win' ? '🎉 Победа!'
                             : data.outcome === 'loss' ? '😢 Поражение'
                             : '🤝 Ничья';
            el.innerHTML = `
                <div style="text-align:center;padding:20px 10px;">
                    <div style="font-size:13px;color:#adadb8;margin-bottom:6px;">Ты</div>
                    <div style="font-size:56px;letter-spacing:8px;margin-bottom:4px;">${yourDice}</div>
                    <div style="font-size:18px;font-weight:700;color:#9147ff;">${data.your_sum}</div>
                    <div style="font-size:20px;color:#adadb8;margin:10px 0;">vs</div>
                    <div style="font-size:13px;color:#adadb8;margin-bottom:6px;">🤖 Бот</div>
                    <div style="font-size:56px;letter-spacing:8px;margin-bottom:4px;">${botDice}</div>
                    <div style="font-size:18px;font-weight:700;color:#9147ff;">${data.bot_sum}</div>
                    <div style="font-size:22px;font-weight:800;color:${resultColor};margin-top:16px;">
                        ${resultText}
                    </div>
                    <button class="modal-btn" id="dice-bot-again-btn" style="margin-top:14px;">
                        🔄 Ещё раз
                    </button>
                    <button class="modal-btn" id="dice-back-pvp-btn" style="margin-top:6px;">
                        ⚔️ Сыграть с игроком (PvP)
                    </button>
                </div>
            `;
            document.getElementById('dice-bot-again-btn').addEventListener('click', _dicePlayVsBot);
            document.getElementById('dice-back-pvp-btn').addEventListener('click', _renderDiceIdle);
        }
        showNotification(data.message, data.outcome === 'win' ? 'success' :
                                       data.outcome === 'draw' ? 'info' : 'error');
    } catch (e) {
        showNotification('Ошибка сети', 'error');
        _renderDiceIdle();
    } finally {
        _diceMoveLocked = false;
    }
}

async function _diceFindOpponent() {
    try {
        const r = await fetch(`${API_URL}/api/match/queue`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ game_type: DICE_GAME_TYPE }),
        });
        const data = await r.json();
        if (!data.success) {
            showNotification(data.message || 'Не удалось встать в очередь', 'error');
            return;
        }
        showNotification('⏳ В очереди!', 'info');
        await _diceRefreshStatus();
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    }
}

async function _diceCancelQueue() {
    try {
        const r = await fetch(`${API_URL}/api/match/queue/cancel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ game_type: DICE_GAME_TYPE }),
        });
        await r.json();
        await _diceRefreshStatus();
    } catch (e) { /* silent */ }
}

async function _diceRefreshRoom(roomId) {
    try {
        const headers = { 'X-Twitch-JWT': authToken || '' };
        const r = await fetch(`${API_URL}/api/match/room/${roomId}/state`, { headers });
        const data = await r.json();
        if (!data.success || !data.room) {
            _diceCurrentRoomId = null;
            _renderDiceIdle();
            return;
        }
        _diceLastState = data.room;
        _renderDicePvP(data.room);
    } catch (e) {
        console.error('[dice] room fetch failed:', e);
    }
}

function _renderDicePvP(room) {
    const el = document.getElementById('dice-content');
    if (!el) return;
    const state = room.state || {};
    const rolls = state.rolls || {a: null, b: null};
    const youAre = room.you_are;
    const yourRoll = rolls[youAre];
    const oppRoll = rolls[youAre === 'a' ? 'b' : 'a'];
    const opponent = room.opponent;
    const finished = room.status !== 'active';

    // ELO badge
    const eloBadge = document.getElementById('dice-elo-badge');
    if (eloBadge) {
        const myElo = youAre === 'a' ? room.player_a_elo : room.player_b_elo;
        eloBadge.textContent = `${myElo} ELO`;
    }

    let headerHtml;
    if (finished) {
        if (room.winner === userLogin) {
            headerHtml = `<div style="font-size:20px;font-weight:800;color:#4ade80;">🎉 Победа!</div>`;
        } else if (room.outcome === 'draw') {
            headerHtml = `<div style="font-size:20px;font-weight:800;color:#fbbf24;">🤝 Ничья</div>`;
        } else {
            headerHtml = `<div style="font-size:20px;font-weight:800;color:#f87171;">😢 Поражение</div>`;
        }
    } else if (!yourRoll) {
        headerHtml = `<div style="font-size:16px;font-weight:700;color:#9147ff;">Твой бросок!</div>`;
    } else if (!oppRoll) {
        headerHtml = `<div style="font-size:16px;color:#adadb8;">⏳ Ждём @${escapeHtml(opponent)}...</div>`;
    } else {
        headerHtml = `<div style="font-size:16px;color:#adadb8;">Подсчёт...</div>`;
    }

    const yourDiceDisplay = yourRoll
        ? `<div style="font-size:48px;letter-spacing:6px;">${yourRoll.map(d => _DICE_EMOJI[d-1]).join(' ')}</div>
           <div style="font-size:18px;font-weight:700;color:#9147ff;">= ${yourRoll[0]+yourRoll[1]}</div>`
        : `<div style="font-size:48px;letter-spacing:6px;color:#3a3a3e;">🎲 🎲</div>
           <div style="font-size:13px;color:#adadb8;">не бросал</div>`;

    const oppDiceDisplay = oppRoll
        ? `<div style="font-size:48px;letter-spacing:6px;">${oppRoll.map(d => _DICE_EMOJI[d-1]).join(' ')}</div>
           <div style="font-size:18px;font-weight:700;color:#9147ff;">= ${oppRoll[0]+oppRoll[1]}</div>`
        : `<div style="font-size:48px;letter-spacing:6px;color:#3a3a3e;">🎲 🎲</div>
           <div style="font-size:13px;color:#adadb8;">не бросал</div>`;

    el.innerHTML = `
        <div style="text-align:center;margin-bottom:14px;">${headerHtml}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px;">
            <div style="background:#1f1a30;border:1px solid #3d3d3f;border-radius:8px;padding:12px;">
                <div style="font-size:11px;color:#adadb8;margin-bottom:4px;">Ты</div>
                ${yourDiceDisplay}
            </div>
            <div style="background:#1a1f30;border:1px solid #3d3d3f;border-radius:8px;padding:12px;">
                <div style="font-size:11px;color:#adadb8;margin-bottom:4px;">@${escapeHtml(opponent || '?')}</div>
                ${oppDiceDisplay}
            </div>
        </div>
        ${!finished && !yourRoll ? '<button class="modal-btn" id="dice-roll-btn">🎲 БРОСИТЬ КУБИКИ</button>' : ''}
        ${finished ? '<button class="modal-btn" id="dice-new-game-btn">⚔️ Сыграть ещё</button>' : ''}
    `;

    if (!finished && !yourRoll) {
        document.getElementById('dice-roll-btn').addEventListener('click', _diceRollPvP);
    }
    if (finished) {
        // Sprint 5.24 fix: останавливаем polling чтобы бэк не «выпиннул»
        // result screen когда зачистит finished room (через 15s polling
        // получали null → авто-переход в idle). Юзер сам жмёт «Сыграть
        // ещё» → restart polling под новую очередь.
        _stopDicePolling();
        document.getElementById('dice-new-game-btn').addEventListener('click', async () => {
            _diceCurrentRoomId = null;
            _renderDiceIdle();
            _loadDiceLeaderboard();
            if (typeof loadUserData === 'function') setTimeout(loadUserData, 500);
            _startDicePolling();
        });
    }
}

async function _diceRollPvP() {
    if (_diceMoveLocked || !_diceCurrentRoomId) return;
    _diceMoveLocked = true;

    // Анимация бросания
    const rollBtn = document.getElementById('dice-roll-btn');
    if (rollBtn) {
        rollBtn.disabled = true;
        rollBtn.textContent = '🎲 Бросаем...';
    }

    try {
        const r = await fetch(`${API_URL}/api/dice/roll`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ room_id: _diceCurrentRoomId }),
        });
        const data = await r.json();
        if (!data.success) {
            showNotification(data.message || 'Не удалось бросить', 'error');
            return;
        }
        // Refresh room — но БД уже обновлена через ответ
        const updatedRoom = {
            ..._diceLastState,
            state: data.state,
            status: data.finished ? 'finished' : 'active',
            winner: data.winner,
            outcome: data.outcome,
        };
        _renderDicePvP(updatedRoom);

        if (data.finished) {
            showNotification(data.message, data.winner === userLogin ? 'success' :
                                          data.outcome === 'draw' ? 'info' : 'error');
            _loadDiceLeaderboard();
        }
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    } finally {
        setTimeout(() => { _diceMoveLocked = false; }, 600);
    }
}

function _animateDiceRolling(elementId, durationMs) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const start = Date.now();
    const interval = setInterval(() => {
        if (Date.now() - start >= durationMs) {
            clearInterval(interval);
            return;
        }
        const d1 = _DICE_EMOJI[Math.floor(Math.random() * 6)];
        const d2 = _DICE_EMOJI[Math.floor(Math.random() * 6)];
        el.textContent = `${d1} ${d2}`;
    }, 80);
}

function _startDicePolling() {
    _stopDicePolling();
    _dicePollId = setInterval(async () => {
        if (_diceCurrentRoomId) {
            await _diceRefreshRoom(_diceCurrentRoomId);
        } else {
            await _diceRefreshStatus();
        }
    }, DICE_POLL_INTERVAL_MS);
}

function _stopDicePolling() {
    if (_dicePollId) {
        clearInterval(_dicePollId);
        _dicePollId = null;
    }
}

window.openDiceModal = openDiceModal;
