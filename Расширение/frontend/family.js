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
    showConfirm('💔 Развод', `Подача заявления стоит ${corePrice('divorce_cost', 500)}💎. Продолжить?`, async () => {
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





// Здесь до 2026-07-29 жил «рулекцион»: копилка + аукцион (showLastWinner,
// loadRulection, опрос, таймер, contributeToPool, placeBidEvent).
// Механика переписана в голосование за игру (voting.js) — оно и живёт в панели.
// Код рисовал в элементы rulection-pool-section / rulection-active-section /
// rulection-pool-badge, которых НЕТ ни в extension.html, ни в mobile.html:
// опрос крутился, данные приходили, показывать их было некуда. Эндпоинты
// /api/event/* при этом списывали крустики и вырезаны вместе с этим кодом.
