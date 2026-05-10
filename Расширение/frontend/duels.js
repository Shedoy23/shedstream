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

                <!-- Создать дуэль -->
                <div style="margin-bottom:16px;">
                    <p style="color:#adadb8;font-size:13px;margin-bottom:8px;">Выходи на арену — выбери ход и ставку. Противник не увидит твой выбор!</p>
                    ${_rpsPickerHtml('create')}
                    <input type="number" id="duel-amount" class="modal-input" placeholder="Ставка (мин. 50)" min="50">
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
            btn.addEventListener('click', () => _openAcceptModal(btn.dataset.acceptDuel, btn.dataset.amount));
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
                <div style="color:#adadb8;font-size:13px;">💰 Ставка: ${d.amount}💎</div>
                ${isMine
                    ? '<div style="color:#9147ff;font-size:12px;margin-top:5px;">Твоя дуэль — ждём соперника...</div>'
                    : `<button class="small-btn" data-accept-duel="${d.duel_id}" data-amount="${d.amount}" style="margin-top:7px;">⚔️ Принять вызов</button>`
                }
            </div>
        `;
    }).join('');
}

function _openAcceptModal(duelId, amount) {
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
            <p style="color:#adadb8;font-size:13px;margin-bottom:10px;">Ставка: <b>${amount}💎</b>. Выбери ход — противник не увидит его до результата.</p>
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

    const amount = parseInt(document.getElementById('duel-amount')?.value);
    if (!amount || amount < 50) { showNotification('❌ Минимальная ставка 50💎', 'error'); return; }

    try {
        const res  = await fetch(`${API_URL}/api/duel/create`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ creator: userLogin, target: '', amount, move: _selectedDuelMove }),
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


// ===== КСЕНОТИП =====
