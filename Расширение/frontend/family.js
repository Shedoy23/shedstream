async function openFamily() {
    if (!isAuthUser()) return showNotification('⚠️ Войдите через Twitch', 'warning');
    
    const modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'family-modal';
    modal.innerHTML = `<div class="modal-content"><h2>💍 Семья</h2><div id="family-content">Загрузка...</div>
        <button class="modal-btn cancel" data-action="close-modal" style="margin-top:10px;">Закрыть</button></div>`;
    (document.getElementById("overlay-panel") || document.body).appendChild(modal);

    try {
        const r = await fetch(`${API_URL}/api/marriage/status/${userLogin}`, { headers: { 'X-Twitch-JWT': authToken || '' } });
        const data = await r.json();
        const content = document.getElementById('family-content');
        
        if (data.married) {
            // Уже в браке. Phase 1.G (2026-05-10): family_balance + withdraw
            // удалены, marriage теперь чисто social.
            content.innerHTML = `
                <div style="text-align:center;padding:10px 0;">
                    <div style="font-size:32px;margin-bottom:8px;">💑</div>
                    <div style="font-size:15px;font-weight:700;">Ты в браке с <span style="color:#f72585;">${escapeHtml(data.partner)}</span></div>
                    <button class="modal-btn" style="background:#3a1a1a;color:#f87171;border:1px solid #f87171;margin-top:12px;" data-action="divorce-family">💔 Развестись</button>
                </div>`;
        } else {
            // Нет пары — проверяем входящие предложения
            let proposals = [];
            try {
                const pr = await fetch(`${API_URL}/api/marriage/proposals/${encodeURIComponent(userLogin)}`, { headers: { 'X-Twitch-JWT': authToken || '' } });
                const pd = await pr.json();
                proposals = Array.isArray(pd.proposals) ? pd.proposals : [];
            } catch (e) { console.warn('[family] proposals fetch failed:', e); }

            await fetchOnlineUsers();
            const opts = _onlineUsers.length
                ? _onlineUsers.map(u => `<option value="${escapeHtml(u)}">${escapeHtml(u)}</option>`).join('')
                : '<option disabled>Нет зрителей онлайн</option>';
            content.innerHTML = `
                <div style="text-align:center;">
                    ${proposals.length ? `<div style="margin-bottom:12px;background:#2d2d2f;padding:10px;border-radius:8px;text-align:left;">
                        <div style="font-size:12px;color:#ffd700;margin-bottom:6px;">💌 Входящие предложения:</div>
                        ${proposals.map(u => `<div style="margin-bottom:8px;">
                            <div style="font-size:14px;font-weight:600;margin-bottom:5px;word-break:break-all;">💍 @${escapeHtml(u)} <span style="font-weight:400;font-size:11px;color:#adadb8;">— предлагает брак</span></div>
                            <div style="display:flex;gap:6px;">
                                <button class="modal-btn" style="flex:1;padding:5px 10px;font-size:12px;margin:0;" data-accept-family="${encodeURIComponent(u)}">Принять</button>
                                <button class="modal-btn cancel" style="flex:1;padding:5px 10px;font-size:12px;margin:0;" data-reject-family="${encodeURIComponent(u)}">Отклонить</button>
                            </div>
                        </div>`).join('')}
                    </div>` : ''}
                    <div style="font-size:11px;color:#adadb8;margin-bottom:12px;">Брак — это статус и социальная связь.</div>
                    <select id="family-target" class="modal-input" style="margin-bottom:10px;">
                        <option value="">— выбери зрителя —</option>${opts}
                    </select>
                    <button class="modal-btn" data-action="propose-family">💍 Предложить</button>
                </div>`;
        }
    } catch(e) {
        document.getElementById('family-content').innerHTML = '<div style="color:#f87171">Ошибка загрузки</div>';
    }
}

window.proposeFamily = async function() {
    const target = document.getElementById('family-target')?.value;
    if (!target || target === userLogin) return showNotification('❌ Выбери другого зрителя', 'error');
    try {
        const r = await fetch(`${API_URL}/api/marriage/propose`, {
            method: 'POST', headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
            body: JSON.stringify({ username: userLogin, target })
        });
        const d = await r.json();
        showNotification(d.message, d.success ? 'success' : 'error');
        if (d.success) closeModal();
    } catch { showNotification('❌ Ошибка сети', 'error'); }
};

window.acceptFamilyProposal = async function(fromUser) {
    try {
        const r = await fetch(`${API_URL}/api/marriage/accept`, {
            method: 'POST', headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
            body: JSON.stringify({ username: userLogin, from_user: fromUser })
        });
        const d = await r.json();
        showNotification(d.message, d.success ? 'success' : 'error');
        if (d.success) { closeModal(); loadUserData(); }
    } catch { showNotification('❌ Ошибка', 'error'); }
};

// Sprint 5.20: симметричный reject — DELETE предложения от конкретного proposer'а.
// Модалка перерисовывается чтобы убрать отклонённую строку из списка.
window.rejectFamilyProposal = async function(fromUser) {
    try {
        const r = await fetch(`${API_URL}/api/marriage/reject`, {
            method: 'POST', headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
            body: JSON.stringify({ from_user: fromUser })
        });
        const d = await r.json();
        showNotification(d.message, d.success ? 'success' : 'error');
        if (d.success) {
            // Перерисовываем модалку с обновлённым списком предложений
            const existing = document.getElementById('family-modal');
            if (existing) existing.remove();
            openFamily();
        }
    } catch { showNotification('❌ Ошибка', 'error'); }
};

// withdrawFamily удалён 2026-05-10 (Phase 1.G compliance rework)

window.divorceFamily = async function() {
    showConfirm('💔 Развод', 'Подача заявления стоит 500💎. Продолжить?', async () => {
        try {
            const r = await fetch(`${API_URL}/api/marriage/divorce`, {
                method: 'POST', headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
                body: JSON.stringify({ username: userLogin })
            });
            const d = await r.json();
            showNotification(d.message, d.success ? 'success' : 'error');
            if (d.success) { closeModal(); loadUserData(); }
        } catch { showNotification('❌ Ошибка', 'error'); }
    });
};





// Добавьте эту функцию в viewer.js
function showLastWinner(winnerData) {
    if (!winnerData || !winnerData.has_winner) return;
    
    // Создаём модальное окно с победителем
    const modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'rulection-winner-modal';
    modal.innerHTML = `
        <div class="modal-content" style="max-width:320px; text-align:center;">
            <h2 style="color:#ffd700; margin-bottom:16px;">🎉 ИВЕНТ ЗАВЕРШЁН!</h2>
            <div style="font-size:48px; margin-bottom:16px;">🏆</div>
            <div style="font-size:18px; font-weight:700; margin-bottom:8px;">
                Лучший участник: <span style="color:#9147ff;">${escapeHtml(winnerData.winner)}</span>
            </div>
            <div style="background:#2d2d2f; border-radius:12px; padding:16px; margin:16px 0;">
                <div style="color:#adadb8; font-size:13px; margin-bottom:4px;">🎁 Награда</div>
                <div style="font-size:24px; font-weight:900; color:#ffd700;">${winnerData.prize?.value || 0}💎</div>
                <div style="font-size:12px; color:#adadb8; margin-top:8px;">
                    ✨ Предмет: ${escapeHtml(winnerData.prize?.name || '—')}
                </div>
            </div>
            <button class="modal-btn" data-close-self-modal style="background:#9147ff;">
                ✅ Отлично!
            </button>
        </div>
    `;
    (document.getElementById("overlay-panel") || document.body).appendChild(modal);
    
    // Автоматически убрать через 10 секунд
    setTimeout(() => {
        const m = document.getElementById('rulection-winner-modal');
        if (m) m.remove();
    }, 10000);
}

// Модифицируйте функцию loadRulection():
async function loadRulection() {
    try {
        const r = await fetch(`${API_URL}/api/event/status`);
        if (!r.ok) {
            const errText = await r.text();
            const now = Date.now();
            if (now - _lastRulectionErrorTs > 10000) {
                console.error('Рулекцион API error:', r.status, errText);
                _lastRulectionErrorTs = now;
            }
            return;
        }
        const d = await r.json();

        // Проверяем, есть ли информация о последнем победителе
        if (d.last_winner && d.last_winner.has_winner) {
            // Проверяем, не показывали ли уже это окно
            const lastWinnerId = `winner_${d.last_winner.winner}_${d.last_winner.ended_at}`;
            if (!_shownWinners.has(lastWinnerId)) {
                showLastWinner(d.last_winner);
                _shownWinners.add(lastWinnerId);
                // Чистим старые записи если больше 5
                if (_shownWinners.size > 5) {
                    const first = _shownWinners.values().next().value;
                    _shownWinners.delete(first);
                }
            }
        }

        // Обновляем бейдж
        const badge = document.getElementById('rulection-pool-badge');
        if (badge) badge.textContent = (d.pool || 0).toLocaleString() + '💎';


        const poolSection = document.getElementById('rulection-pool-section');
        const activeSection = document.getElementById('rulection-active-section');

        if (d.active_event) {
            _rulectionIsEvent = true; // переключаем polling на быстрый режим
            // Показываем активный ивент
            if (poolSection) poolSection.style.display = 'none';
            if (activeSection) activeSection.style.display = 'block';

            const ev = d.active_event;
            const nameEl = document.getElementById('rulection-event-type-name');
            const descEl = document.getElementById('rulection-event-type-desc');
            const prizeEl = document.getElementById('rulection-prize-name');
            const partsEl = document.getElementById('rulection-participants');

            if (nameEl) nameEl.textContent = ev.type_name;
            if (descEl) descEl.textContent = ev.type_desc;
            if (prizeEl) prizeEl.textContent = ev.prize.name;
            if (partsEl) partsEl.textContent = ev.participants;

            // Таблица участников
            const bidsEl = document.getElementById('rulection-bids-list');
            if (bidsEl) {
                if (!ev.bids || ev.bids.length === 0) {
                    bidsEl.innerHTML = '<div style="color:#adadb8;text-align:center;padding:8px;">Участников пока нет — будь первым!</div>';
                } else {
                    bidsEl.innerHTML = ev.bids.map((b, i) => {
                        const isMe = b.username === userLogin;
                        const medal = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : `${i+1}.`;
                        const chanceOrLead = (i === 0 ? '<span style="color:#ffd700;">лидер</span>' : '');
                        return `<div style="display:flex;justify-content:space-between;padding:4px 6px;border-radius:4px;${isMe?'background:#2d2d2f;font-weight:700;':''}">
                            <span>${medal} ${escapeHtml(b.username)}${isMe?' 👈':''}</span>
                            <span>${b.amount.toLocaleString()}💎 ${chanceOrLead}</span>
                        </div>`;
                    }).join('');
                }
            }

            // Таймер
            _startRulectionTimer(ev.time_left);

        } else {
            _rulectionIsEvent = false; // переключаем polling на медленный режим
            // Показываем копилку
            if (poolSection) poolSection.style.display = 'block';
            if (activeSection) activeSection.style.display = 'none';
            _stopRulectionTimer();

            // Обновляем прогресс-бары
            const ptsPct = d.pool_pct_points || 0;

            const el = (id) => document.getElementById(id);
            if (el('rulection-pts-bar')) el('rulection-pts-bar').style.width = ptsPct + '%';
            if (el('rulection-pts-pct')) el('rulection-pts-pct').textContent = ptsPct + '%';
            if (el('rulection-pts-val')) el('rulection-pts-val').textContent = (d.pool || 0).toLocaleString();
            // donation-бар удалён 2026-07-02 (B1) — донаты вырезаны, поля были dead/no-op.

            // Топ контрибьюторов
            const topEl = el('rulection-top-contributors');
            if (topEl && d.top_contributors && d.top_contributors.length > 0) {
                topEl.innerHTML = '🏆 Топ: ' + d.top_contributors
                    .map(c => `<b>${escapeHtml(c.username || '')}</b> ${(c.amount || 0).toLocaleString()}💎`)
                    .join(' ・ ');
            }
        }
    } catch(e) {
        const now = Date.now();
        if (now - _lastRulectionErrorTs > 10000) {
            console.error('Рулекцион:', e);
            _lastRulectionErrorTs = now;
        }
    }
}

// ── Глобальный polling рулекциона ──────────────────────────────────────────────────────
// Работает независимо от активной вкладки.
// Интервал адаптивный: 4с во время ивента (таймер тикает), 10с в режиме копилки.
let _rulectionPollId  = null;
let _rulectionIsEvent = false; // true когда ивент активен

function _startRulectionPolling() {
    if (_rulectionPollId) return; // уже запущен
    _rulectionPollId = setInterval(_rulectionPollTick, _rulectionPollInterval());
}

function _rulectionPollInterval() {
    // Во время активного ивента опрашиваем чаще — вклады меняются быстро
    return _rulectionIsEvent ? 4000 : 10000;
}

async function _rulectionPollTick() {
    await loadRulection();
    // Перезапускаем с правильным интервалом если режим сменился
    if (_rulectionPollId) {
        clearInterval(_rulectionPollId);
        _rulectionPollId = setInterval(_rulectionPollTick, _rulectionPollInterval());
    }
}

function _stopRulectionPolling() {
    if (_rulectionPollId) {
        clearInterval(_rulectionPollId);
        _rulectionPollId = null;
    }
}

function _startRulectionTimer(seconds) {
    _stopRulectionTimer();
    let left = seconds;
    const timerEl = document.getElementById('rulection-timer');
    if (!timerEl) return;
    timerEl.textContent = _fmtTime(left);
    _rulectionTimerInterval = setInterval(() => {
        left--;
        if (timerEl) timerEl.textContent = _fmtTime(left);
        if (left <= 0) {
            _stopRulectionTimer();
            showNotification('⏰ Рулекцион завершён!', 'info');
            setTimeout(loadRulection, 2000);
        }
    }, 1000);
}

function _stopRulectionTimer() {
    if (_rulectionTimerInterval) {
        clearInterval(_rulectionTimerInterval);
        _rulectionTimerInterval = null;
    }
}

function _fmtTime(s) {
    const m = Math.floor(Math.max(0, s) / 60);
    const sec = Math.max(0, s) % 60;
    return `${m}:${sec.toString().padStart(2, '0')}`;
}

async function contributeToPool() {
    if (!checkCooldown('contribute', 3000)) return;
    const amount = parseInt(document.getElementById('rulection-contribute-amt')?.value);
    if (!amount || amount < 100) {
        showNotification('❌ Минимум 100💎', 'error');
        return;
    }
    try {
        const r = await fetch(`${API_URL}/api/event/contribute`, {
            method: 'POST',
            headers: {'Content-Type':'application/json', 'X-Twitch-JWT': authToken || ''},
            body: JSON.stringify({username: userLogin, amount})
        });
        const d = await r.json();
        showNotification(d.message, d.success ? 'success' : 'error');
        if (d.success) {
            loadUserData();
            loadRulection();
            if (d.event_started) {
                showNotification('🎡 РУЛЕКЦИОН АКТИВИРОВАН!', 'success');
            }
        }
    } catch(e) {
        showNotification('❌ Ошибка', 'error');
    }
}

async function placeBidEvent() {
    if (!checkCooldown('bid', 3000)) return;
    const amount = parseInt(document.getElementById('rulection-bid-amt')?.value);
    if (!amount || amount < 100) {
        showNotification('❌ Минимум 100💎', 'error');
        return;
    }
    try {
        const r = await fetch(`${API_URL}/api/event/bid`, {
            method: 'POST',
            headers: {'Content-Type':'application/json', 'X-Twitch-JWT': authToken || ''},
            body: JSON.stringify({username: userLogin, amount})
        });
        const d = await r.json();
        showNotification(d.message, d.success ? 'success' : 'error');
        if (d.success) {
            loadUserData();
            loadRulection();
        }
    } catch(e) {
        showNotification('❌ Ошибка', 'error');
    }
}

// ===== ДУЭЛИ =====
