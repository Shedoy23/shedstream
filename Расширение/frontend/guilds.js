// guilds.js — UI для гильдий (Phase 3, 2026-05-11)
//
// 3 view states:
//   no-guild  → browse list + create form
//   in-guild  → my guild dashboard (members, balance, contribute, skills)
//   guild-info → detail view конкретной гильдии (если кликнул из browse)

let _guildsSkillsConfig = null;

async function openGuildsModal() {
    if (!isAuthUser()) {
        showNotification('⚠️ Войдите через Twitch', 'warning');
        return;
    }
    _renderGuildsModal();
    await _loadSkillsConfig();
    await _refreshMyGuildView();
}

function _renderGuildsModal() {
    let modal = document.getElementById('guilds-modal');
    if (modal) modal.remove();
    modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'guilds-modal';
    modal.innerHTML = `
        <div class="modal-content" style="max-width:480px;max-height:90vh;overflow-y:auto;">
            <h2>⚔️ Гильдии</h2>
            <div id="guilds-content"><div class="loading">Загрузка...</div></div>
            <button class="modal-btn cancel" data-action="close-modal" style="margin-top:10px;">Закрыть</button>
        </div>
    `;
    (document.getElementById('overlay-panel') || document.body).appendChild(modal);
}

async function _loadSkillsConfig() {
    if (_guildsSkillsConfig) return;
    try {
        const r = await fetch(`${API_URL}/api/guild/skills/config`);
        const data = await r.json();
        if (data.success) _guildsSkillsConfig = data.skills;
    } catch (e) { /* silent */ }
}

async function _refreshMyGuildView() {
    try {
        const headers = { 'X-Twitch-JWT': authToken || '' };
        const r = await fetch(`${API_URL}/api/guild/my`, { headers });
        const data = await r.json();
        if (!data.success) {
            _renderGuildsError('Ошибка загрузки');
            return;
        }
        if (data.in_guild) {
            _renderMyGuild(data.guild);
        } else {
            await _renderBrowseGuilds();
        }
    } catch (e) {
        _renderGuildsError('Ошибка сети');
    }
}

async function _renderBrowseGuilds() {
    const el = document.getElementById('guilds-content');
    if (!el) return;
    // Load top guilds list
    let guilds = [];
    try {
        const headers = { 'X-Twitch-JWT': authToken || '' };
        const r = await fetch(`${API_URL}/api/guild/list`, { headers });
        const data = await r.json();
        if (data.success) guilds = data.guilds || [];
    } catch (e) { /* silent */ }

    const listHtml = guilds.length ? guilds.map((g, i) => `
        <div data-guild-row="${g.guild_id}"
             style="background:#1a1a1c;border:1px solid #3a3a3e;border-radius:8px;
                    padding:10px;margin-bottom:6px;cursor:pointer;transition:border-color .15s;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div style="font-weight:700;font-size:14px;">
                    ${i < 3 ? ['🥇','🥈','🥉'][i] : '🛡️'} ${escapeHtml(g.name)}
                </div>
                <div style="font-size:11px;color:#fbbf24;">${g.balance.toLocaleString('ru-RU')}💎</div>
            </div>
            ${g.tagline ? `<div style="font-size:11px;color:#adadb8;margin-top:3px;">${escapeHtml(g.tagline)}</div>` : ''}
            <div style="font-size:10px;color:#adadb8;margin-top:4px;">
                👑 @${escapeHtml(g.master)} • 👥 ${g.member_count}
            </div>
        </div>
    `).join('') : '<div style="color:#adadb8;text-align:center;padding:12px;">Ещё нет гильдий на канале</div>';

    el.innerHTML = `
        <details open style="margin-bottom:14px;background:#1a1a1c;border-radius:8px;padding:10px 12px;">
            <summary style="cursor:pointer;font-weight:700;">⚔️ Создать свою гильдию (${corePrice('guild_create_cost', 100000).toLocaleString('ru-RU')}💎)</summary>
            <div style="margin-top:10px;">
                <input id="guild-create-name" class="modal-input" placeholder="Имя гильдии (3-30 символов)" maxlength="30">
                <input id="guild-create-tagline" class="modal-input" placeholder="Девиз (до 80 символов, опц.)" maxlength="80" style="margin-top:6px;">
                <button class="modal-btn" id="guild-create-btn" style="margin-top:8px;">⚔️ Создать (100k💎)</button>
            </div>
        </details>
        <div style="font-size:12px;color:#adadb8;margin-bottom:6px;">🏆 Топ гильдий канала</div>
        <div id="guilds-list">${listHtml}</div>
    `;

    document.getElementById('guild-create-btn').addEventListener('click', _createGuild);

    el.querySelectorAll('[data-guild-row]').forEach(row => {
        const gid = parseInt(row.dataset.guildRow, 10);
        row.addEventListener('mouseenter', () => row.style.borderColor = '#9147ff');
        row.addEventListener('mouseleave', () => row.style.borderColor = '#3a3a3e');
        row.addEventListener('click', () => _openGuildInfo(gid));
    });
}

async function _createGuild() {
    const name = document.getElementById('guild-create-name').value.trim();
    const tagline = document.getElementById('guild-create-tagline').value.trim();
    if (name.length < 3 || name.length > 30) {
        showNotification('Имя 3-30 символов', 'error');
        return;
    }
    try {
        const r = await fetch(`${API_URL}/api/guild/create`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ name, tagline }),
        });
        const data = await r.json();
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) {
            if (typeof loadUserData === 'function') loadUserData();
            await _refreshMyGuildView();
        }
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    }
}

async function _openGuildInfo(guildId) {
    try {
        const headers = { 'X-Twitch-JWT': authToken || '' };
        const r = await fetch(`${API_URL}/api/guild/${guildId}`, { headers });
        const data = await r.json();
        if (!data.success || !data.guild) {
            showNotification(data.message || 'Не найдено', 'error');
            return;
        }
        _renderGuildInfo(data.guild);
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    }
}

function _renderGuildInfo(g) {
    const el = document.getElementById('guilds-content');
    if (!el) return;
    const membersHtml = g.members.map(m => {
        const roleIcon = m.role === 'master' ? '👑' : m.role === 'officer' ? '🎖️' : '👤';
        return `<div style="display:flex;justify-content:space-between;padding:3px 0;">
            <span>${roleIcon} @${escapeHtml(m.username)}</span>
            <span style="color:#adadb8;font-size:11px;">${m.role}</span>
        </div>`;
    }).join('');
    const contribsHtml = (g.top_contributors || []).map(c => `
        <div style="display:flex;justify-content:space-between;padding:2px 0;font-size:11px;">
            <span>@${escapeHtml(c.username)}</span>
            <span style="color:#fbbf24;">${c.total.toLocaleString('ru-RU')}💎</span>
        </div>
    `).join('') || '<div style="color:#adadb8;font-size:11px;">пока никто не накидал</div>';

    el.innerHTML = `
        <div style="background:linear-gradient(135deg,rgba(145,71,255,.18),rgba(145,71,255,.06));
                    border:1px solid rgba(145,71,255,.5);border-radius:10px;padding:14px;margin-bottom:10px;">
            <div style="font-size:18px;font-weight:800;">🛡️ ${escapeHtml(g.name)}</div>
            ${g.tagline ? `<div style="font-size:12px;color:#adadb8;margin-top:4px;">"${escapeHtml(g.tagline)}"</div>` : ''}
            <div style="display:flex;justify-content:space-between;margin-top:10px;font-size:12px;">
                <span>👑 @${escapeHtml(g.master)}</span>
                <span style="color:#fbbf24;">${g.balance.toLocaleString('ru-RU')}💎</span>
            </div>
        </div>
        <div style="font-size:12px;color:#adadb8;margin-bottom:4px;">👥 Состав (${g.members.length})</div>
        <div style="background:#1a1a1c;border-radius:6px;padding:8px;margin-bottom:10px;max-height:160px;overflow-y:auto;">
            ${membersHtml}
        </div>
        <div style="font-size:12px;color:#adadb8;margin-bottom:4px;">💰 Топ-5 вкладчиков</div>
        <div style="background:#1a1a1c;border-radius:6px;padding:8px;margin-bottom:10px;">
            ${contribsHtml}
        </div>
        <button class="modal-btn" id="guild-join-btn">⚔️ Вступить</button>
        <button class="modal-btn cancel" id="guild-back-btn" style="margin-top:6px;">← Назад</button>
    `;
    document.getElementById('guild-join-btn').addEventListener('click', () => _joinGuild(g.guild_id));
    document.getElementById('guild-back-btn').addEventListener('click', _refreshMyGuildView);
}

async function _joinGuild(guildId) {
    try {
        const r = await fetch(`${API_URL}/api/guild/join`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ guild_id: guildId }),
        });
        const data = await r.json();
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) await _refreshMyGuildView();
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    }
}

function _renderMyGuild(g) {
    const el = document.getElementById('guilds-content');
    if (!el) return;
    const isMaster = g.my_role === 'master';
    const skills = _guildsSkillsConfig || [];

    const skillsHtml = skills.map(s => {
        const currentLevel = g.skills[s.skill_key] || 0;
        const isMax = currentLevel >= s.max_level;
        const nextCost = isMax ? null : s.cost_per_level[currentLevel];
        const canAfford = !isMax && g.balance >= nextCost;
        const upgradeBtn = isMaster && !isMax
            ? `<button data-upgrade-skill="${s.skill_key}"
                       class="small-btn" style="margin-left:auto;
                       ${canAfford ? '' : 'opacity:.5;cursor:not-allowed;'}"
                       ${canAfford ? '' : 'disabled'}>
                  Lv${currentLevel+1} — ${nextCost.toLocaleString('ru-RU')}💎
              </button>`
            : isMax ? `<span style="color:#4ade80;font-size:11px;margin-left:auto;">MAX</span>` : '';
        return `
            <div style="background:#1a1a1c;border-radius:6px;padding:8px;margin-bottom:6px;">
                <div style="display:flex;align-items:center;gap:6px;">
                    <div style="flex:1;">
                        <div style="font-size:13px;font-weight:600;">${escapeHtml(s.name)}
                            <span style="color:#9147ff;">Lv.${currentLevel}/${s.max_level}</span>
                        </div>
                        <div style="font-size:10px;color:#adadb8;">${escapeHtml(s.description)}</div>
                    </div>
                    ${upgradeBtn}
                </div>
            </div>
        `;
    }).join('');

    el.innerHTML = `
        <div style="background:linear-gradient(135deg,rgba(145,71,255,.22),rgba(145,71,255,.08));
                    border:1px solid rgba(145,71,255,.55);border-radius:10px;padding:14px;margin-bottom:10px;">
            <div style="font-size:20px;font-weight:800;">${isMaster ? '👑 ' : '🛡️ '}${escapeHtml(g.name)}</div>
            ${g.tagline ? `<div style="font-size:12px;color:#adadb8;margin-top:4px;">"${escapeHtml(g.tagline)}"</div>` : ''}
            <div style="display:flex;justify-content:space-between;margin-top:10px;font-size:12px;">
                <span>👥 ${g.member_count} участников</span>
                <span style="color:#fbbf24;font-weight:700;">${g.balance.toLocaleString('ru-RU')}💎</span>
            </div>
            <div style="font-size:11px;color:#adadb8;margin-top:4px;">Master: @${escapeHtml(g.master)}</div>
        </div>

        <details style="margin-bottom:10px;background:#1a1a1c;border-radius:6px;padding:8px 10px;">
            <summary style="cursor:pointer;font-weight:600;font-size:12px;">💰 Внести в общую копилку</summary>
            <div style="margin-top:8px;display:flex;gap:6px;">
                <input id="guild-contrib-amt" type="number" class="modal-input" style="flex:1;margin:0;" placeholder="Сумма (мин. ${corePrice('voting_min_pledge', 100)}💎)" min="${corePrice('voting_min_pledge', 100)}">
                <button class="modal-btn" style="width:auto;padding:8px 14px;margin:0;" id="guild-contrib-btn">📥</button>
            </div>
        </details>

        <details style="margin-bottom:10px;background:#1a1a1c;border-radius:6px;padding:8px 10px;">
            <summary style="cursor:pointer;font-weight:600;font-size:12px;">⬆️ Прокачка (${skills.length} ветки)</summary>
            <div style="margin-top:8px;">${skillsHtml}</div>
        </details>

        <button class="modal-btn" id="guild-detail-btn">📖 Подробнее (участники, лидерборд)</button>
        ${isMaster
            ? `<button class="modal-btn" style="background:#3a1a1a;color:#f87171;border:1px solid #f87171;margin-top:6px;" id="guild-disband-btn">
                  🏴 Расформировать
              </button>`
            : `<button class="modal-btn cancel" id="guild-leave-btn" style="margin-top:6px;">👋 Покинуть</button>`
        }
    `;

    document.getElementById('guild-contrib-btn').addEventListener('click', () => _contributeToGuild());
    document.getElementById('guild-detail-btn').addEventListener('click', () => _openGuildInfo(g.guild_id));
    if (isMaster) {
        document.getElementById('guild-disband-btn').addEventListener('click', _disbandGuild);
        el.querySelectorAll('[data-upgrade-skill]').forEach(btn => {
            const sk = btn.dataset.upgradeSkill;
            btn.addEventListener('click', () => _upgradeSkill(sk));
        });
    } else {
        document.getElementById('guild-leave-btn').addEventListener('click', _leaveGuild);
    }
}

async function _contributeToGuild() {
    const amt = parseInt(document.getElementById('guild-contrib-amt').value);
    if (!amt || amt < 100) {
        showNotification(`Минимум ${corePrice('voting_min_pledge', 100)}💎`, 'error');
        return;
    }
    try {
        const r = await fetch(`${API_URL}/api/guild/contribute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ amount: amt }),
        });
        const data = await r.json();
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) {
            if (typeof loadUserData === 'function') loadUserData();
            await _refreshMyGuildView();
        }
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    }
}

async function _upgradeSkill(skillKey) {
    try {
        const r = await fetch(`${API_URL}/api/guild/upgrade-skill`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ skill_key: skillKey }),
        });
        const data = await r.json();
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) await _refreshMyGuildView();
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    }
}

async function _leaveGuild() {
    showConfirm('👋 Покинуть гильдию', 'Точно? Заново вступать придётся через приглашение.', async () => {
        try {
            const r = await fetch(`${API_URL}/api/guild/leave`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            });
            const data = await r.json();
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) await _refreshMyGuildView();
        } catch (e) {
            showNotification('Ошибка сети', 'error');
        }
    });
}

async function _disbandGuild() {
    showConfirm('🏴 Расформирование', 'Balance потеряется. Точно?', async () => {
        try {
            const r = await fetch(`${API_URL}/api/guild/disband`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            });
            const data = await r.json();
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) await _refreshMyGuildView();
        } catch (e) {
            showNotification('Ошибка сети', 'error');
        }
    });
}

function _renderGuildsError(msg) {
    const el = document.getElementById('guilds-content');
    if (el) el.innerHTML = `<div style="color:#f87171;text-align:center;padding:14px;">${msg}</div>`;
}

window.openGuildsModal = openGuildsModal;
