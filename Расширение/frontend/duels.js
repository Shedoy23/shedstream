// ===== ДУЭЛИ =====

let _selectedDuelMove = null;  // ход при создании
let _pendingAcceptId   = null; // duel_id при принятии

function _rpsPickerHtml(idPrefix) {
    return `
        <div style="display:flex;gap:10px;justify-content:center;margin:12px 0;" id="${idPrefix}-picker">
            <button class="rps-btn" data-move="rock"     style="font-size:26px;background:#2d2d2f;border:2px solid transparent;border-radius:10px;padding:8px 14px;cursor:pointer;" title="Камень">🪨</button>
            <button class="rps-btn" data-move="scissors" style="font-size:26px;background:#2d2d2f;border:2px solid transparent;border-radius:10px;padding:8px 14px;cursor:pointer;" title="Ножницы">✂️</button>
            <button class="rps-btn" data-move="paper"    style="font-size:26px;background:#2d2d2f;border:2px solid transparent;border-radius:10px;padding:8px 14px;cursor:pointer;" title="Бумага">📄</button>
        </div>
        <div id="${idPrefix}-move-label" style="text-align:center;font-size:12px;color:#adadb8;margin-bottom:8px;">Ход не выбран</div>
    `;
}

function _bindRpsPicker(idPrefix, onSelect) {
    document.querySelectorAll(`#${idPrefix}-picker .rps-btn`).forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll(`#${idPrefix}-picker .rps-btn`).forEach(b => {
                b.style.border = '2px solid transparent';
                b.style.background = '#2d2d2f';
            });
            btn.style.border = '2px solid #9147ff';
            btn.style.background = '#3d2d5f';
            const moveNames = { rock: '🪨 Камень', scissors: '✂️ Ножницы', paper: '📄 Бумага' };
            const label = document.getElementById(`${idPrefix}-move-label`);
            if (label) label.textContent = `Выбрано: ${moveNames[btn.dataset.move]}`;
            onSelect(btn.dataset.move);
        });
    });
}

async function openDuels() {
    if (!isAuthUser()) { showNotification('⚠️ Войдите через Twitch для участия', 'warning'); return; }
    _selectedDuelMove = null;
    _pendingAcceptId  = null;

    try {
        const [listRes, lbRes] = await Promise.all([
            fetch(`${API_URL}/api/duel/list?username=${userLogin}`),
            fetch(`${API_URL}/api/duel/leaderboard`),
        ]);
        const listData = await listRes.json();
        const lbData   = await lbRes.json();

        const modal = document.createElement('div');
        modal.className = 'modal active';
        modal.id = 'duels-modal';
        modal.innerHTML = `
            <div class="modal-content" style="max-width:460px;">
                <h2>⚔️ Дуэли</h2>

                <!-- Sprint 5.24b: matchmaking — best-of-3 RPS через очередь -->
                <button class="modal-btn" id="duel-find-btn"
                        style="margin-bottom:14px;background:#5a2c9d;border-color:#9147ff;">
                    🔎 Найти соперника (BO3)
                </button>

                <!-- Создать дуэль (invite-flow, legacy) -->
                <div style="margin-bottom:16px;">
                    <p style="color:#adadb8;font-size:13px;margin-bottom:8px;">Или классическая дуэль с одного раунда — выбери ход:</p>
                    ${_rpsPickerHtml('create')}
                    <button class="modal-btn" data-action="create-duel">⚔️ Выйти на арену</button>
                </div>

                <!-- Активные дуэли -->
                <div style="max-height:180px;overflow-y:auto;margin-bottom:16px;">
                    <h3 style="margin-bottom:8px;">Активные дуэли:</h3>
                    <div id="duels-list">${_renderDuelsList(listData.duels || [])}</div>
                </div>

                <!-- Лидерборд -->
                <div>
                    <h3 style="margin-bottom:6px;">🏆 Сезон #${lbData.season_id || 1} — Топ-5</h3>
                    ${_renderSeasonEnd(lbData.ends_at)}
                    <div>${_renderLeaderboard(lbData.leaderboard || [])}</div>
                </div>

                <button class="modal-btn cancel" data-action="close-modal" style="margin-top:14px;">Закрыть</button>
            </div>
        `;

        (document.getElementById("overlay-panel") || document.body).appendChild(modal);

        _bindRpsPicker('create', move => { _selectedDuelMove = move; });

        document.querySelectorAll('[data-accept-duel]').forEach(btn => {
            btn.addEventListener('click', () => _openAcceptModal(btn.dataset.acceptDuel));
        });

        // Sprint 5.24b: matchmaking — best-of-3 RPS через очередь
        document.getElementById('duel-find-btn')?.addEventListener('click', () => {
            document.getElementById('duels-modal')?.remove();
            openRpsMatchmaking();
        });

    } catch (e) {
        showNotification('❌ Ошибка загрузки дуэлей', 'error');
    }
}

function _renderSeasonEnd(endsAt) {
    if (!endsAt) return '';
    try {
        const d = new Date(endsAt);
        const fmt = d.toLocaleDateString('ru-RU', { day:'2-digit', month:'2-digit', year:'numeric' });
        return `<div style="color:#adadb8;font-size:11px;margin-bottom:8px;">Сезон заканчивается: ${fmt} • Призы: 🥇1 000 000💎 🥈500 000💎 🥉350 000💎</div>`;
    } catch { return ''; }
}

function _renderLeaderboard(rows) {
    if (!rows.length) return '<p style="color:#adadb8;font-size:13px;text-align:center;">Ещё никто не дрался</p>';
    const medals = ['🥇','🥈','🥉','4️⃣','5️⃣'];
    return rows.map(r => `
        <div style="display:flex;justify-content:space-between;align-items:center;background:#2d2d2f;border-radius:6px;padding:8px 12px;margin-bottom:5px;">
            <span style="font-size:15px;">${medals[r.rank-1] || r.rank} <b>${escapeHtml(r.username)}</b></span>
            <span style="color:#f6ad55;font-size:13px;">${r.elo} ELO${r.win_streak >= 2 ? ` 🔥${r.win_streak}` : ''}</span>
        </div>
    `).join('');
}

function _renderDuelsList(duels) {
    if (!duels.length) return '<p style="color:#adadb8;text-align:center;font-size:13px;">Нет активных дуэлей</p>';
    return duels.map(d => {
        const isMine = d.creator === userLogin;
        return `
            <div style="background:#2d2d2f;border-radius:8px;padding:10px;margin-bottom:7px;border-left:3px solid ${isMine ? '#9147ff' : '#f6ad55'}">
                <div style="font-weight:600;">⚔️ @${escapeHtml(d.creator)} ищет противника</div>
                ${isMine
                    ? '<div style="color:#9147ff;font-size:12px;margin-top:5px;">Твоя дуэль — ждём соперника...</div>'
                    : `<button class="small-btn" data-accept-duel="${d.duel_id}" style="margin-top:7px;">⚔️ Принять вызов</button>`
                }
            </div>
        `;
    }).join('');
}

function _openAcceptModal(duelId) {
    _pendingAcceptId = duelId;
    let _acceptMove  = null;

    // Закрываем старый модал дуэлей
    document.getElementById('duels-modal')?.remove();

    const modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'accept-duel-modal';
    modal.innerHTML = `
        <div class="modal-content" style="max-width:340px;">
            <h2>⚔️ Принять вызов</h2>
            <p style="color:#adadb8;font-size:13px;margin-bottom:10px;">Выбери ход — противник не увидит его до результата. Награды только за ELO в сезоне.</p>
            ${_rpsPickerHtml('accept')}
            <button class="modal-btn" id="confirm-accept-btn">⚔️ Сразиться!</button>
            <button class="modal-btn cancel" data-action="close-modal">Отмена</button>
        </div>
    `;
    (document.getElementById("overlay-panel") || document.body).appendChild(modal);

    _bindRpsPicker('accept', move => { _acceptMove = move; });

    document.getElementById('confirm-accept-btn').addEventListener('click', async () => {
        if (!_acceptMove) { showNotification('❌ Выбери ход!', 'error'); return; }
        await _doAcceptDuel(duelId, _acceptMove);
    });
}

async function createDuel() {
    if (!checkCooldown('duel', 5000)) return;
    if (!_selectedDuelMove) { showNotification('❌ Выбери ход: 🪨 ✂️ 📄', 'error'); return; }

    // Phase 1.F (2026-05-10): amount убран — дуэль только за ELO.
    try {
        const res  = await fetch(`${API_URL}/api/duel/create`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ creator: userLogin, target: '', move: _selectedDuelMove }),
        });
        const data = await res.json();
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) closeModal();
    } catch (e) {
        showNotification('❌ Ошибка создания дуэли', 'error');
    }
}

async function _doAcceptDuel(duelId, move) {
    try {
        const res  = await fetch(`${API_URL}/api/duel/accept`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ duel_id: duelId, username: userLogin, move }),
        });
        const data = await res.json();
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) {
            closeModal();
            loadUserData();
        }
    } catch (e) {
        showNotification('❌ Ошибка принятия дуэли', 'error');
    }
}

// legacy — на случай если где-то вызывается напрямую
async function acceptDuel(duelId) {
    _openAcceptModal(duelId, '?');
}

// transferPoints + doTransfer удалены 2026-05-10 (Phase 1.D compliance rework — P2P transfer)


// ════════ Sprint 5.24b: RPS matchmaking + best-of-3 ════════
// Очередь по /api/match/queue с game_type=rps. После match — BO3 раунды
// через /api/rps/move + /api/rps/poll (lazy-expire таймер 10s/раунд).

const RPS_POLL_INTERVAL_MS = 2000;
const RPS_GAME_TYPE = 'rps';
let _rpsPollId = null;
let _rpsRoomId = null;
let _rpsMoveLock = false;

const _RPS_NAMES = { rock: '🪨 Камень', paper: '📄 Бумага', scissors: '✂️ Ножницы' };
const _RPS_EMOJI_ONLY = { rock: '🪨', paper: '📄', scissors: '✂️' };

async function openRpsMatchmaking() {
    if (!isAuthUser()) { showNotification('⚠️ Войдите через Twitch', 'warning'); return; }
    _rpsRoomId = null;
    _renderRpsModal();
    await _rpsRefreshStatus();
    _startRpsPolling();
}

function _renderRpsModal() {
    let modal = document.getElementById('rps-mm-modal');
    if (modal) modal.remove();
    modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'rps-mm-modal';
    modal.innerHTML = `
        <div class="modal-content" style="max-width:420px;">
            <h2 style="display:flex;align-items:center;justify-content:space-between;">
                <span>⚔️ Дуэль BO3</span>
                <span id="rps-elo-badge" style="font-size:12px;color:#adadb8;font-weight:500;">—</span>
            </h2>
            <div id="rps-content" style="min-height:280px;">
                <div class="loading">Загрузка...</div>
            </div>
            <button class="modal-btn cancel" id="rps-close-btn" style="margin-top:10px;">Закрыть</button>
        </div>
    `;
    (document.getElementById('overlay-panel') || document.body).appendChild(modal);
    document.getElementById('rps-close-btn').addEventListener('click', () => {
        _stopRpsPolling();
        _rpsRoomId = null;
        // Если в очереди — leave
        fetch(`${API_URL}/api/match/queue/leave`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
            body: JSON.stringify({game_type: RPS_GAME_TYPE}),
        }).catch(() => {});
        modal.remove();
    });
}

async function _rpsRefreshStatus() {
    try {
        const headers = { 'X-Twitch-JWT': authToken || '' };
        const r = await fetch(`${API_URL}/api/match/queue/status?game_type=${RPS_GAME_TYPE}`, { headers });
        const data = await r.json();
        if (!data.success) { _renderRpsIdle(); return; }
        if (data.status === 'idle')           { _renderRpsIdle(); return; }
        if (data.status === 'queued')         { _renderRpsQueued(data); return; }
        if (data.status === 'matched' || data.status === 'in_room') {
            if (data.room_id) {
                _rpsRoomId = data.room_id;
                await _rpsRefreshRoom(data.room_id);
            } else _renderRpsIdle();
        }
    } catch (e) { console.error('[rps] status fetch', e); }
}

async function _rpsRefreshRoom(roomId) {
    try {
        const headers = { 'X-Twitch-JWT': authToken || '' };
        const r = await fetch(`${API_URL}/api/rps/poll?room_id=${encodeURIComponent(roomId)}`, { headers });
        const data = await r.json();
        if (!data.success || !data.room) { _rpsRoomId = null; _renderRpsIdle(); return; }
        _renderRpsMatch(data.room);
    } catch (e) { console.error('[rps] room fetch', e); }
}

function _renderRpsIdle() {
    const el = document.getElementById('rps-content');
    if (!el) return;
    el.innerHTML = `
        <div style="text-align:center;padding:20px 10px;">
            <div style="font-size:42px;margin-bottom:8px;">⚔️</div>
            <div style="font-size:14px;color:#adadb8;margin-bottom:6px;">Best-of-3 камень/ножницы/бумага.</div>
            <div style="font-size:11px;color:#adadb8;margin-bottom:18px;">10 сек на ход. Не успел → засчитан loss за раунд.</div>
            <button class="modal-btn" id="rps-queue-btn" style="font-size:14px;">🔎 Найти соперника</button>
        </div>
    `;
    document.getElementById('rps-queue-btn').addEventListener('click', async () => {
        try {
            const r = await fetch(`${API_URL}/api/match/queue`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
                body: JSON.stringify({game_type: RPS_GAME_TYPE}),
            });
            const d = await r.json();
            if (!d.success) { showNotification(d.message || 'Не удалось встать в очередь', 'error'); return; }
            await _rpsRefreshStatus();
        } catch (e) { showNotification('Ошибка сети', 'error'); }
    });
}

function _renderRpsQueued(data) {
    const el = document.getElementById('rps-content');
    if (!el) return;
    el.innerHTML = `
        <div style="text-align:center;padding:20px 10px;">
            <div style="font-size:36px;margin-bottom:10px;">⏳</div>
            <div style="font-size:14px;font-weight:700;color:#9147ff;">Ищем соперника...</div>
            <div style="font-size:12px;color:#adadb8;margin-top:6px;">Позиция в очереди: ${data.queue_position || 1}</div>
            <div style="font-size:11px;color:#adadb8;margin-top:14px;">ELO: ${data.elo_at_queue || 1100}</div>
            <button class="modal-btn cancel" id="rps-leave-btn" style="margin-top:18px;">Отмена</button>
        </div>
    `;
    document.getElementById('rps-leave-btn').addEventListener('click', async () => {
        try {
            await fetch(`${API_URL}/api/match/queue/leave`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
                body: JSON.stringify({game_type: RPS_GAME_TYPE}),
            });
            await _rpsRefreshStatus();
        } catch (e) {}
    });
}

function _renderRpsMatch(room) {
    const el = document.getElementById('rps-content');
    if (!el) return;
    let state = room.state || {};
    if (state.version !== 2) {
        state = {
            version: 2, rounds_total: 3, current_round: 1,
            moves: {a: [null,null,null], b: [null,null,null]},
            round_outcomes: [null,null,null],
            wins: {a: 0, b: 0}, phase: 'moving', deadline_at: null,
        };
    }

    const youAre = room.you_are;
    const oppAre = youAre === 'a' ? 'b' : 'a';
    const opponent = room.opponent;
    const finished = room.status !== 'active' || state.phase === 'finished';

    const eloBadge = document.getElementById('rps-elo-badge');
    if (eloBadge) {
        const myElo = youAre === 'a' ? room.player_a_elo : room.player_b_elo;
        eloBadge.textContent = `${myElo} ELO`;
    }

    const yourWins = state.wins[youAre] || 0;
    const oppWins  = state.wins[oppAre]  || 0;
    const curRound = state.current_round || 1;
    const idx      = curRound - 1;
    const yourMoveThisRound = state.moves[youAre][idx];
    const oppMoveThisRound  = state.moves[oppAre][idx];

    // Header
    let headerHtml;
    if (finished) {
        const youWon = room.winner === userLogin;
        const isDraw = !room.winner;
        const color  = youWon ? '#4ade80' : isDraw ? '#fbbf24' : '#f87171';
        const text   = youWon ? '🎉 Победа!' : isDraw ? '🤝 Ничья' : '😢 Поражение';
        headerHtml = `<div style="font-size:22px;font-weight:800;color:${color};">${text}</div>
            <div style="font-size:13px;color:#adadb8;margin-top:4px;">${yourWins} : ${oppWins}</div>`;
    } else {
        headerHtml = `
            <div style="font-size:13px;color:#9147ff;font-weight:700;letter-spacing:1px;">
                РАУНД ${Math.min(curRound, state.rounds_total)} • BO3
            </div>
            <div style="font-size:11px;color:#adadb8;margin-top:2px;">
                Wins: <b style="color:#efeff1;">${yourWins}</b> vs <b style="color:#efeff1;">${oppWins}</b>
            </div>
        `;
    }

    // Round history boxes
    const boxes = [];
    for (let i = 0; i < state.rounds_total; i++) {
        const yourMove = state.moves[youAre][i];
        const oppMove  = state.moves[oppAre][i];
        const outcome  = state.round_outcomes[i];
        const isCur    = (i === idx) && !finished;
        let boxColor   = '#2d2d2f';
        let labelText  = `Р${i+1}`;
        if (outcome === youAre)      { boxColor = '#1a3320'; labelText = `Р${i+1} W`; }
        else if (outcome === oppAre) { boxColor = '#331a1a'; labelText = `Р${i+1} L`; }
        else if (outcome === 'draw') { boxColor = '#33291a'; labelText = `Р${i+1} =`; }
        const yourDisp = yourMove ? _RPS_EMOJI_ONLY[yourMove] : '—';
        // Hide opponent move until round resolved (blind)
        const oppDisp  = (oppMove && outcome) ? _RPS_EMOJI_ONLY[oppMove] : (oppMove ? '🔒' : '—');
        boxes.push(`
            <div style="background:${isCur ? '#1f1a30' : boxColor};
                        border:1px solid ${isCur ? '#9147ff' : '#3a3a3e'};
                        border-radius:6px;padding:6px;text-align:center;
                        ${isCur ? 'box-shadow:0 0 8px rgba(145,71,255,0.25);' : ''}">
                <div style="font-size:9px;color:#adadb8;">${labelText}</div>
                <div style="font-size:18px;">${yourDisp}</div>
                <div style="height:1px;background:#2d2d2f;margin:3px 0;"></div>
                <div style="font-size:18px;">${oppDisp}</div>
            </div>
        `);
    }
    const roundsHtml = `<div style="display:grid;grid-template-columns:repeat(${state.rounds_total},1fr);gap:6px;margin-bottom:12px;">${boxes.join('')}</div>`;

    // Timer
    let timerHtml = '';
    if (!finished && state.deadline_at) {
        const ms = new Date(state.deadline_at).getTime() - Date.now();
        const sec = Math.max(0, Math.ceil(ms / 1000));
        timerHtml = `<div style="text-align:center;font-size:11px;color:${sec<=3?'#f87171':'#adadb8'};margin-top:4px;">⏱️ ${sec}с</div>`;
    }

    // Action area
    let actionHtml = '';
    if (finished) {
        actionHtml = `<button class="modal-btn" id="rps-new-game-btn" style="margin-top:8px;">⚔️ Сыграть ещё</button>`;
    } else if (yourMoveThisRound) {
        actionHtml = `<div style="text-align:center;padding:14px 8px;color:#adadb8;font-size:13px;">
            Твой ход: <b style="color:#efeff1;">${_RPS_NAMES[yourMoveThisRound]}</b><br>
            ⏳ Ждём @${escapeHtml(opponent)}...
        </div>`;
    } else {
        actionHtml = `
            <div style="text-align:center;font-size:12px;color:#adadb8;margin-bottom:8px;">Выбирай ход (оппа не видишь):</div>
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;">
                <button class="modal-btn" data-rps-move="rock"     style="font-size:18px;padding:14px 0;">🪨</button>
                <button class="modal-btn" data-rps-move="paper"    style="font-size:18px;padding:14px 0;">📄</button>
                <button class="modal-btn" data-rps-move="scissors" style="font-size:18px;padding:14px 0;">✂️</button>
            </div>
        `;
    }

    el.innerHTML = `
        <div style="text-align:center;margin-bottom:10px;">${headerHtml}${timerHtml}</div>
        ${roundsHtml}
        ${actionHtml}
    `;

    el.querySelectorAll('[data-rps-move]').forEach(btn => {
        btn.addEventListener('click', () => _rpsMakeMove(btn.dataset.rpsMove));
    });

    const newGameBtn = document.getElementById('rps-new-game-btn');
    if (newGameBtn) {
        _stopRpsPolling();
        newGameBtn.addEventListener('click', async () => {
            _rpsRoomId = null;
            _renderRpsIdle();
            _startRpsPolling();
        });
    }
}

async function _rpsMakeMove(move) {
    if (_rpsMoveLock || !_rpsRoomId) return;
    _rpsMoveLock = true;
    try {
        const r = await fetch(`${API_URL}/api/rps/move`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
            body: JSON.stringify({room_id: _rpsRoomId, move}),
        });
        const d = await r.json();
        if (!d.success) {
            showNotification(d.message || 'Не удалось сходить', 'error');
            return;
        }
        await _rpsRefreshRoom(_rpsRoomId);
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    } finally {
        setTimeout(() => { _rpsMoveLock = false; }, 400);
    }
}

function _startRpsPolling() {
    _stopRpsPolling();
    _rpsPollId = setInterval(async () => {
        if (_rpsRoomId) await _rpsRefreshRoom(_rpsRoomId);
        else await _rpsRefreshStatus();
    }, RPS_POLL_INTERVAL_MS);
}

function _stopRpsPolling() {
    if (_rpsPollId) { clearInterval(_rpsPollId); _rpsPollId = null; }
}

window.openRpsMatchmaking = openRpsMatchmaking;


// ===== КСЕНОТИП =====
