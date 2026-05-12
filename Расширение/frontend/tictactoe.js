// tictactoe.js — TicTacToe MVP UI (Phase 5.1, 2026-05-11)
//
// Flow:
//   1. Click action-card "Крестики-нолики" → openTicTacToeModal()
//   2. fetch /api/match/queue/status?game_type=tictactoe
//      - 'idle' → показываем "Найти противника" кнопку
//      - 'queued' → "⏳ Ищем... позиция N в очереди" + polling
//      - 'matched' / 'in_room' → board UI с polling
//      - 'finished' → result screen
//   3. Click "Найти противника" → POST /api/match/queue
//   4. Polling /queue/status каждые 3 сек пока 'queued'
//   5. После 'matched' → polling /match/room/{id}/state + UI board
//   6. Click cell (своя очередь) → POST /api/tictactoe/move
//   7. После finished → показать результат + Close

const TTT_GAME_TYPE = 'tictactoe';
const TTT_POLL_INTERVAL_MS = 3000;     // queue / room polling
const TTT_MOVE_COOLDOWN_MS = 600;      // защита от двойного click

let _tttPollId = null;
let _tttCurrentRoomId = null;
let _tttMoveLocked = false;
let _tttLastState = null;

async function openTicTacToeModal() {
    if (!isAuthUser()) {
        showNotification('⚠️ Войдите через Twitch', 'warning');
        return;
    }
    _renderTttModal();
    await _tttRefreshStatus();
    _startTttPolling();
}

function _renderTttModal() {
    let modal = document.getElementById('ttt-modal');
    if (modal) modal.remove();
    modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'ttt-modal';
    modal.innerHTML = `
        <div class="modal-content" style="max-width:380px;">
            <h2 style="display:flex;align-items:center;justify-content:space-between;">
                <span>❌⭕ Крестики-нолики</span>
                <span id="ttt-elo-badge" style="font-size:12px;color:#adadb8;font-weight:500;">—</span>
            </h2>
            <div id="ttt-content" style="min-height:280px;">
                <div class="loading">Загрузка...</div>
            </div>
            <details style="margin-top:10px;background:#1a1a1c;border-radius:6px;padding:8px 12px;">
                <summary style="cursor:pointer;font-size:12px;color:#adadb8;">🏆 Лидерборд сезона</summary>
                <div id="ttt-leaderboard" style="margin-top:8px;font-size:12px;">
                    <div class="loading">Загрузка...</div>
                </div>
            </details>
            <button class="modal-btn cancel" data-action="close-modal" id="ttt-close-btn" style="margin-top:10px;">Закрыть</button>
        </div>
    `;
    (document.getElementById('overlay-panel') || document.body).appendChild(modal);

    // Listener для close — отменяет polling
    document.getElementById('ttt-close-btn').addEventListener('click', () => {
        _stopTttPolling();
        _tttCurrentRoomId = null;
        modal.remove();
    });

    _loadTttLeaderboard();
}

async function _loadTttLeaderboard() {
    try {
        const headers = { 'X-Twitch-JWT': authToken || '' };
        const r = await fetch(`${API_URL}/api/tictactoe/leaderboard`, { headers });
        const data = await r.json();
        const el = document.getElementById('ttt-leaderboard');
        if (!el || !data.success) return;
        const rows = data.leaderboard || [];
        if (!rows.length) {
            el.innerHTML = '<div style="color:#adadb8;">Никто ещё не играл</div>';
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

async function _tttRefreshStatus() {
    try {
        const headers = { 'X-Twitch-JWT': authToken || '' };
        const r = await fetch(`${API_URL}/api/match/queue/status?game_type=${TTT_GAME_TYPE}`, { headers });
        const data = await r.json();
        if (!data.success) {
            _renderTttIdle();
            return;
        }

        const status = data.status;
        if (status === 'idle') {
            _renderTttIdle();
        } else if (status === 'queued') {
            _renderTttQueued(data);
        } else if (status === 'matched' || status === 'in_room') {
            const roomId = data.room_id;
            if (roomId) {
                _tttCurrentRoomId = roomId;
                await _tttRefreshRoom(roomId);
            } else {
                _renderTttIdle();
            }
        }
    } catch (e) {
        console.error('[ttt] status fetch failed:', e);
    }
}

function _renderTttIdle() {
    const el = document.getElementById('ttt-content');
    if (!el) return;
    el.innerHTML = `
        <div style="text-align:center;padding:30px 10px;">
            <div style="font-size:64px;margin-bottom:14px;">❌⭕</div>
            <div style="font-size:14px;color:#adadb8;margin-bottom:18px;">
                3×3 grid, два игрока ходят по очереди.<br>
                Награды только за ELO + sезонный топ.
            </div>
            <button class="modal-btn" id="ttt-find-btn">⚔️ Найти противника</button>
        </div>
    `;
    document.getElementById('ttt-find-btn').addEventListener('click', _tttFindOpponent);
}

function _renderTttQueued(data) {
    const el = document.getElementById('ttt-content');
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
                Позиция в очереди: ${pos}<br>
                Твой ELO: ${elo}
            </div>
            <button class="modal-btn" style="background:#3a1a1a;color:#f87171;border:1px solid #f87171;" id="ttt-cancel-btn">
                ❌ Отменить поиск
            </button>
        </div>
    `;
    document.getElementById('ttt-cancel-btn').addEventListener('click', _tttCancelQueue);
}

async function _tttFindOpponent() {
    try {
        const r = await fetch(`${API_URL}/api/match/queue`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ game_type: TTT_GAME_TYPE }),
        });
        const data = await r.json();
        if (!data.success) {
            showNotification(data.message || 'Не удалось встать в очередь', 'error');
            return;
        }
        showNotification('⏳ В очереди!', 'info');
        await _tttRefreshStatus();
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    }
}

async function _tttCancelQueue() {
    try {
        const r = await fetch(`${API_URL}/api/match/queue/cancel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ game_type: TTT_GAME_TYPE }),
        });
        const data = await r.json();
        showNotification(data.message || 'Вышел из очереди', data.success ? 'info' : 'error');
        await _tttRefreshStatus();
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    }
}

async function _tttRefreshRoom(roomId) {
    try {
        const headers = { 'X-Twitch-JWT': authToken || '' };
        const r = await fetch(`${API_URL}/api/match/room/${roomId}/state`, { headers });
        const data = await r.json();
        if (!data.success || !data.room) {
            // Room уже закрыт / cleanup'нут
            _tttCurrentRoomId = null;
            _renderTttIdle();
            return;
        }
        _tttLastState = data.room;
        _renderTttBoard(data.room);
    } catch (e) {
        console.error('[ttt] room fetch failed:', e);
    }
}

function _renderTttBoard(room) {
    const el = document.getElementById('ttt-content');
    if (!el) return;

    const state = room.state || {};
    const board = state.board || ['', '', '', '', '', '', '', '', ''];
    const youAre = room.you_are; // 'a' | 'b'
    const opponent = room.opponent;
    const myMark = youAre === 'a' ? '❌' : '⭕';
    const oppMark = youAre === 'a' ? '⭕' : '❌';
    const myTurn = state.next_turn === youAre;
    const finished = room.status !== 'active';

    // Header
    let headerHtml;
    if (finished) {
        if (room.winner === userLogin) {
            headerHtml = `<div style="font-size:18px;font-weight:800;color:#4ade80;">🎉 Победа!</div>`;
        } else if (room.outcome === 'draw') {
            headerHtml = `<div style="font-size:18px;font-weight:800;color:#fbbf24;">🤝 Ничья</div>`;
        } else {
            headerHtml = `<div style="font-size:18px;font-weight:800;color:#f87171;">😢 Поражение</div>`;
        }
    } else if (myTurn) {
        headerHtml = `<div style="font-size:16px;font-weight:700;color:#9147ff;">Твой ход (${myMark})</div>`;
    } else {
        headerHtml = `<div style="font-size:16px;color:#adadb8;">Ход @${escapeHtml(opponent)} (${oppMark})...</div>`;
    }

    // Board
    const cellsHtml = board.map((mark, i) => {
        let display = '';
        let bg = '#1a1a1c';
        let cursor = 'default';
        if (mark === 'a') { display = '❌'; bg = '#2a1a3a'; }
        else if (mark === 'b') { display = '⭕'; bg = '#1a2a3a'; }
        else if (myTurn && !finished) {
            cursor = 'pointer';
        }
        return `
            <div data-ttt-cell="${i}"
                 style="background:${bg};border:2px solid #3a3a3e;border-radius:8px;
                        aspect-ratio:1;display:flex;align-items:center;justify-content:center;
                        font-size:42px;cursor:${cursor};transition:all .15s;
                        ${myTurn && !mark && !finished ? 'opacity:1;' : ''}">
                ${display}
            </div>
        `;
    }).join('');

    el.innerHTML = `
        <div style="text-align:center;margin-bottom:14px;">
            ${headerHtml}
            <div style="font-size:12px;color:#adadb8;margin-top:4px;">
                @${escapeHtml(userLogin || '?')} ${myMark} vs ${oppMark} @${escapeHtml(opponent || '?')}
            </div>
        </div>
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:14px;max-width:280px;margin-left:auto;margin-right:auto;">
            ${cellsHtml}
        </div>
        ${finished ? `
            <button class="modal-btn" id="ttt-new-game-btn">⚔️ Сыграть ещё</button>
        ` : ''}
    `;

    // ELO badge update
    const eloBadge = document.getElementById('ttt-elo-badge');
    if (eloBadge) {
        const myElo = youAre === 'a' ? room.player_a_elo : room.player_b_elo;
        eloBadge.textContent = `${myElo} ELO`;
    }

    // Bind cell clicks (только если my turn + не finished)
    if (myTurn && !finished) {
        el.querySelectorAll('[data-ttt-cell]').forEach(cell => {
            const idx = parseInt(cell.dataset.tttCell, 10);
            if (board[idx]) return; // already taken
            cell.addEventListener('mouseenter', () => {
                cell.style.transform = 'scale(1.05)';
                cell.style.borderColor = '#9147ff';
            });
            cell.addEventListener('mouseleave', () => {
                cell.style.transform = '';
                cell.style.borderColor = '#3a3a3e';
            });
            cell.addEventListener('click', () => _tttMakeMove(idx));
        });
    }

    if (finished) {
        const newGameBtn = document.getElementById('ttt-new-game-btn');
        if (newGameBtn) {
            newGameBtn.addEventListener('click', async () => {
                _tttCurrentRoomId = null;
                _renderTttIdle();
                // Refresh leaderboard — обновился после finalize
                _loadTttLeaderboard();
                // Refresh balance — если был sезонный prize
                if (typeof loadUserData === 'function') setTimeout(loadUserData, 500);
            });
        }
    }
}

async function _tttMakeMove(cell) {
    if (_tttMoveLocked) return;
    if (!_tttCurrentRoomId) return;
    _tttMoveLocked = true;

    try {
        const r = await fetch(`${API_URL}/api/tictactoe/move`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ room_id: _tttCurrentRoomId, cell }),
        });
        const data = await r.json();

        if (!data.success) {
            showNotification(data.message || 'Не удалось сделать ход', 'error');
            return;
        }

        // Optimistically render новое состояние
        const updatedRoom = {
            ..._tttLastState,
            state: data.state,
            status: data.status,
            winner: data.winner,
            outcome: data.outcome,
        };
        _renderTttBoard(updatedRoom);

        if (data.finished) {
            showNotification(data.message, data.winner === userLogin ? 'success' :
                                          data.outcome === 'draw' ? 'info' : 'error');
            _loadTttLeaderboard();
            if (typeof loadUserData === 'function') setTimeout(loadUserData, 500);
        }
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    } finally {
        setTimeout(() => { _tttMoveLocked = false; }, TTT_MOVE_COOLDOWN_MS);
    }
}

function _startTttPolling() {
    _stopTttPolling();
    _tttPollId = setInterval(async () => {
        if (_tttCurrentRoomId) {
            // В матче — poll'имся за state (для увидеть opponent's ходы)
            await _tttRefreshRoom(_tttCurrentRoomId);
        } else {
            // Не в матче — poll'имся за queue status (для увидеть matched)
            await _tttRefreshStatus();
        }
    }, TTT_POLL_INTERVAL_MS);
}

function _stopTttPolling() {
    if (_tttPollId) {
        clearInterval(_tttPollId);
        _tttPollId = null;
    }
}

// Global
window.openTicTacToeModal = openTicTacToeModal;
