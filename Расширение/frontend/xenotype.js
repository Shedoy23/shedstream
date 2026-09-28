async function openXenotypeModal() {
    if (!isAuthUser()) { showNotification('⚠️ Войдите через Twitch', 'warning'); return; }

    const existing = document.getElementById('xenotype-modal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'xenotype-modal';
    modal.innerHTML = `
        <div class="modal-content">
            <h2>🧬 Выбор ксенотипа</h2>
            <div style="color:#adadb8;font-size:12px;margin-bottom:10px;">
                Ксенотип заменяет все текущие ксеногены новым набором.
                Эндогены (врождённые) остаются.
            </div>
            <div style="background:#2d2d2f;border-radius:6px;padding:8px 10px;margin-bottom:12px;font-size:11px;color:#adadb8;">
                💡 Текущий ксенотип: <b style="color:#efeff1;" id="xt-current-name">—</b>
            </div>
            <input type="text" id="xt-search" placeholder="🔍 Поиск ксенотипа..."
                style="width:100%;background:#2d2d2f;border:1px solid #3d3d3f;border-radius:8px;
                       padding:8px 12px;color:#efeff1;font-size:13px;outline:none;margin-bottom:10px;box-sizing:border-box;"
                >
            <div id="xt-list" style="max-height:340px;overflow-y:auto;">
                <div style="text-align:center;color:#adadb8;padding:20px;">Загрузка...</div>
            </div>
            <button class="modal-btn cancel" data-close-self-modal style="margin-top:10px;">Закрыть</button>
        </div>`;
    (document.getElementById('overlay-panel') || document.body).appendChild(modal);
    modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });

    // Показываем текущий ксенотип
    if (window._lastPawnData?.xenotype?.name) {
        const el = document.getElementById('xt-current-name');
        if (el) el.textContent = window._lastPawnData.xenotype.name;
    }

    // Загружаем каталог ксенотипов
    try {
        const r = await fetch(`${API_URL}/api/rimworld/catalog?category=xenotype&username=${encodeURIComponent(userLogin)}`, {
            headers: {'X-Twitch-JWT': authToken || ''}
        });
        const d = await r.json();
        window._xenotypeCatalog = d.items || [];
        renderXenotypeList(window._xenotypeCatalog);
    } catch(e) {
        const list = document.getElementById('xt-list');
        if (list) list.innerHTML = '<div style="color:#f87171;text-align:center;padding:16px;">❌ Ошибка загрузки каталога</div>';
    }
}

function filterXenotypes(query) {
    const items = window._xenotypeCatalog || [];
    const q = query.toLowerCase().trim();
    renderXenotypeList(q ? items.filter(x => (x.label||x.def_name||'').toLowerCase().includes(q)) : items);
}

function renderXenotypeList(items) {
    const list = document.getElementById('xt-list');
    if (!list) return;

    const rawPts = document.getElementById('points')?.textContent || '0';
    const userPoints = parseInt(rawPts.replace(/[^0-9]/g, '')) || 0;

    if (!items || items.length === 0) {
        list.innerHTML = '<div style="color:#adadb8;text-align:center;padding:16px;">Ничего не найдено</div>';
        return;
    }

    list.innerHTML = items.map(xeno => {
        const price    = xeno.price || 0;
        const canAfford = userPoints >= price;
        const genes    = xeno.genes || [];
        const geneCount = genes.length;
        const hasArchite = xeno.has_archite;
        const sourceMod = xeno.source_mod || 'Vanilla';
        const tooltip  = xeno.tooltip || xeno.description || '';

        // Бейдж сложности
        const archBadge = hasArchite
            ? '<span style="font-size:9px;background:#3a1a3a;color:#c084fc;border:1px solid #c084fc;border-radius:3px;padding:1px 4px;margin-left:4px;">👁 архит.</span>'
            : '';
        const modBadge = sourceMod && sourceMod !== 'Vanilla' && sourceMod !== 'Core'
            ? `<span style="font-size:9px;color:#adadb8;margin-left:4px;">[${escapeHtml(sourceMod)}]</span>`
            : '';

        return `<div style="background:#2d2d2f;border-radius:8px;padding:9px 12px;margin-bottom:6px;">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
                <div style="flex:1;min-width:0;">
                    <div style="font-size:12px;font-weight:700;margin-bottom:2px;">
                        ${escapeHtml(xeno.label || xeno.def_name)}${archBadge}${modBadge}
                    </div>
                    <div style="font-size:10px;color:#adadb8;margin-bottom:4px;">
                        ${geneCount} ген${geneCount===1?'':geneCount<5?'а':'ов'}
                        ${tooltip ? ' ・ <span style="color:#9147ff;cursor:pointer;" data-action="toggle-next">подробнее ▼</span>' : ''}
                    </div>
                    ${tooltip ? `<div style="display:none;font-size:10px;color:#adadb8;white-space:pre-line;margin-bottom:4px;padding:6px;background:#1f1f23;border-radius:5px;">${escapeHtml(tooltip)}</div>` : ''}
                    ${geneCount > 0 ? `<div style="font-size:10px;color:#9147ff;">
                        ${genes.slice(0,5).map(g => escapeHtml(g)).join(' ・ ')}${geneCount > 5 ? ` <span style="color:#adadb8;">+${geneCount-5}</span>` : ''}
                    </div>` : ''}
                </div>
                <div style="flex-shrink:0;text-align:right;">
                    <div style="font-size:13px;font-weight:800;color:#9147ff;margin-bottom:4px;">${price.toLocaleString()}💎</div>
                    <button data-buy-xenotype="${(xeno.def_name||'').replace(/\\/g, '\\\\').replace(/'/g, "\\'")}" data-xeno-label="${(xeno.label || xeno.def_name || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'")}" data-xeno-price="${price}"
                        style="font-size:10px;padding:4px 10px;background:${canAfford?'#9147ff':'#2d2d2f'};
                            color:${canAfford?'white':'#555'};border:1px solid ${canAfford?'#9147ff':'#3d3d3f'};
                            border-radius:6px;cursor:${canAfford?'pointer':'not-allowed'};"
                        ${!canAfford ? 'disabled' : ''}>
                        ${canAfford ? '✅ Выбрать' : 'Мало 💎'}
                    </button>
                </div>
            </div>
        </div>`;
    }).join('');
    list.querySelectorAll('[data-buy-xenotype]').forEach(btn => {
        btn.addEventListener('click', () => {
            buyXenotype(btn.dataset.buyXenotype, btn.dataset.xenoLabel, parseInt(btn.dataset.xenoPrice));
        });
    });
}

async function buyXenotype(defName, label, price) {
    const rawPts = document.getElementById('points')?.textContent || '0';
    const userPoints = parseInt(rawPts.replace(/[^0-9]/g, '')) || 0;
    if (userPoints < price) { showNotification('❌ Недостаточно очков', 'error'); return; }

    showConfirm('🧬 Сменить ксенотип',
        `Установить ксенотип <b>${escapeHtml(label)}</b> за <b style="color:#9147ff;">${price.toLocaleString()}💎</b>?<br>
        <span style="font-size:11px;color:#f59e0b;">⚠️ Все текущие ксеногены будут заменены!</span>`,
        async () => {
            try {
                const r = await fetch(`${API_URL}/api/rimworld/buy-item`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
                    body: JSON.stringify({ username: userLogin, item_def: defName, def_name: defName })
                });
                const d = await r.json();
                showNotification(d.message || (d.success ? '🧬 Ксенотип устанавливается!' : '❌ Ошибка'), d.success ? 'success' : 'error');
                if (d.success) {
                    document.getElementById('xenotype-modal')?.remove();
                    loadUserData();
                    startPawnRefresh();
                }
            } catch(e) { showNotification('❌ Ошибка', 'error'); }
        }
    );
}

// ===== СТРАСТЬ (ОГОНЬКИ) =====
async function openNeuroModal() {
    if (!isAuthUser()) { showNotification('⚠️ Войдите через Twitch', 'warning'); return; }
    const existing = document.getElementById('neuro-modal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'neuro-modal';
    modal.innerHTML = `
        <div class="modal-content">
            <h2>🧠 Нейротренеры</h2>
            <div style="color:#adadb8;font-size:12px;margin-bottom:10px;">Прокачка навыков пешки</div>
            <input type="text" id="neuro-modal-search" placeholder="🔍 Поиск..."
                style="width:100%;background:#2d2d2f;border:1px solid #3d3d3f;border-radius:7px;padding:6px 10px;color:#efeff1;font-size:12px;outline:none;margin-bottom:8px;">
            <div id="neuro-modal-list" style="max-height:340px;overflow-y:auto;">
                <div style="text-align:center;color:#adadb8;padding:20px;">Загрузка...</div>
            </div>
            <button class="modal-btn cancel" data-close-self-modal style="margin-top:12px;">Закрыть</button>
        </div>`;
    (document.getElementById('overlay-panel') || document.body).appendChild(modal);
    modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });

    try {
        // 2026-07-24: тянули ВЕСЬ каталог (~2.2 МБ, 2559 позиций), чтобы отобрать
        // из него 12 нейротренеров. Бэкенд умеет фильтровать по категории —
        // просим сразу нужное (так же, как строкой 40 для ксенотипов).
        const usernameParam = userLogin ? `&username=${encodeURIComponent(userLogin)}` : '';
        const r = await fetch(`${API_URL}/api/rimworld/catalog?category=neurotrainer${usernameParam}`, {
            headers: {'X-Twitch-JWT': authToken || ''}
        });
        const data = await r.json();
        modal._neuroItems = (data.items || [])
            .filter(i => (i.category || i.type) === 'neurotrainer')
            .map(i => ({ ...i, name: i.name || i.label || i.def_name || '', def: i.def_name || i.def || '' }));
        _renderNeuroModalList('');
    } catch(e) {
        const list = document.getElementById('neuro-modal-list');
        if (list) list.innerHTML = '<div style="color:#f87171;text-align:center;padding:16px;">❌ Ошибка загрузки</div>';
    }
}

function _filterNeuroModal(q) { _renderNeuroModalList(q.trim().toLowerCase()); }

function _renderNeuroModalList(q) {
    const modal = document.getElementById('neuro-modal');
    const list = document.getElementById('neuro-modal-list');
    if (!modal || !list) return;
    let items = modal._neuroItems || [];
    if (q) items = items.filter(i => i.name.toLowerCase().includes(q) || i.def.toLowerCase().includes(q));
    if (!items.length) { list.innerHTML = '<div style="text-align:center;color:#adadb8;padding:20px;">Нет навыков в каталоге</div>'; return; }
    const userPts = parseInt((document.getElementById('points')?.textContent || '0').replace(/[^0-9]/g,'')) || 0;
    list.innerHTML = items.map(item => {
        const price = item.price || item.cost || 0;
        const canBuy = userPts >= price;
        return `<div class="shop-item">
            <div class="shop-item-icon">🧠</div>
            <div class="shop-item-info" style="min-width:0;">
                <div class="shop-item-name">${escapeHtml(item.name)}</div>
                <div class="shop-item-cat">${price}💎</div>
            </div>
            <button class="shop-buy-btn" ${canBuy?'':'disabled'} data-buy-neuro="${escapeHtml(item.def)}" data-price="${price}">${canBuy?'Купить':'🔒'}</button>
        </div>`;
    }).join('');
    list.querySelectorAll('[data-buy-neuro]').forEach(btn => {
        btn.addEventListener('click', () => _buyNeuroFromModal(btn.dataset.buyNeuro, parseInt(btn.dataset.price)));
    });
}

async function _buyNeuroFromModal(itemDef, price) {
    if (!checkCooldown('buyNeuro_' + itemDef, 3000)) return;
    try {
        const r = await fetch(`${API_URL}/api/rimworld/train-skill`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
            body: JSON.stringify({ username: userLogin, item_def: itemDef })
        });
        const d = await r.json();
        showNotification(d.message, d.success ? 'success' : 'error');
        if (d.success) { loadUserData(); _renderNeuroModalList(document.getElementById('neuro-modal-search')?.value||''); }
    } catch(e) { showNotification('❌ Ошибка', 'error'); }
}

async function openPassionModal() {
    if (!isAuthUser()) { showNotification('⚠️ Войдите через Twitch', 'warning'); return; }

    const existing = document.getElementById('passion-modal');
    if (existing) existing.remove();

    // Показываем заглушку пока грузим
    const modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'passion-modal';
    modal.innerHTML = `
        <div class="modal-content">
            <h2>🔥 Огоньки страсти</h2>
            <div style="color:#adadb8;font-size:12px;margin-bottom:12px;">
                Страсть ускоряет прокачку навыка: ⭐ +35% опыта, 🔥 +100% опыта.
            </div>
            <div id="passion-skills-list" style="max-height:320px;overflow-y:auto;">
                <div style="text-align:center;color:#adadb8;padding:20px;">Загрузка...</div>
            </div>
            <button class="modal-btn cancel" data-close-self-modal style="margin-top:12px;">Закрыть</button>
        </div>`;
    (document.getElementById('overlay-panel') || document.body).appendChild(modal);
    modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });

    try {
        const r = await fetch(`${API_URL}/api/rimworld/pawn-skills/${encodeURIComponent(userLogin)}`, {
            headers: {'X-Twitch-JWT': authToken || ''}
        });
        const d = await r.json();
        const list = document.getElementById('passion-skills-list');
        if (!list) return;

        if (!d.skills || d.skills.length === 0) {
            list.innerHTML = `<div style="text-align:center;color:#f87171;padding:16px;">${d.error || 'Нет данных — создай пешку сначала!'}</div>`;
            return;
        }

        list.innerHTML = d.skills.map(skill => {
            const passion = skill.passion ?? 0;
            const icon    = passion === 2 ? '🔥' : passion === 1 ? '⭐' : '—';
            const disabled = skill.is_disabled;
            const upPrice  = skill.upgrade_price;
            const rstPrice = skill.reset_price;
            const nextIcon = passion === 0 ? '⭐' : passion === 1 ? '🔥' : null;

            const upgradeBtn = !disabled && nextIcon && upPrice != null
                ? `<button data-buy-passion="${skill.def_name}" data-target="${passion + 1}"
                    style="font-size:10px;padding:2px 8px;background:#1a2a1a;color:#4ade80;border:1px solid #4ade80;border-radius:4px;cursor:pointer;margin-left:4px;">
                    ${nextIcon} ${upPrice}💎</button>`
                : '';
            const resetBtn = !disabled && rstPrice != null
                ? `<button data-reset-passion="${skill.def_name}" data-reset-price="${rstPrice}"
                    style="font-size:10px;padding:2px 6px;background:#2a1a1a;color:#f87171;border:1px solid #f87171;border-radius:4px;cursor:pointer;margin-left:4px;"
                    title="Сбросить страсть">↩ ${rstPrice}💎</button>`
                : '';

            const disabledBadge = disabled
                ? `<span style="font-size:9px;background:#3a1a1a;color:#f87171;border:1px solid #f87171;
                        border-radius:3px;padding:1px 5px;margin-left:6px;">✖ недоступен</span>`
                : '';
            const maxBadge = !disabled && !upgradeBtn && !resetBtn
                ? `<span style="font-size:10px;color:#555;">макс. 🔥</span>`
                : '';

            return `<div style="display:flex;justify-content:space-between;align-items:center;
                        background:#2d2d2f;border-radius:6px;padding:7px 10px;margin-bottom:4px;
                        ${disabled ? 'opacity:0.55;' : ''}">
                <div style="display:flex;align-items:center;gap:8px;flex:1;min-width:0;">
                    <span style="font-size:18px;width:22px;text-align:center;flex-shrink:0;">${icon}</span>
                    <div style="min-width:0;">
                        <div style="font-size:12px;font-weight:600;display:flex;align-items:center;flex-wrap:wrap;gap:4px;">
                            ${escapeHtml(localizeSkill(skill))}${disabledBadge}
                        </div>
                        <div style="font-size:10px;color:#adadb8;">Ур. ${skill.level}</div>
                    </div>
                </div>
                <div style="display:flex;align-items:center;flex-shrink:0;margin-left:8px;">
                    ${upgradeBtn}${resetBtn}${maxBadge}
                </div>
            </div>`;
        }).join('');
        list.querySelectorAll('[data-buy-passion]').forEach(btn => {
            btn.addEventListener('click', () => buyPassion(btn.dataset.buyPassion, parseInt(btn.dataset.target)));
        });
        list.querySelectorAll('[data-reset-passion]').forEach(btn => {
            btn.addEventListener('click', () => resetPassion(btn.dataset.resetPassion, btn.dataset.resetPrice));
        });
    } catch(e) {
        const list = document.getElementById('passion-skills-list');
        if (list) list.innerHTML = `<div style="color:#f87171;text-align:center;padding:16px;">❌ Ошибка загрузки</div>`;
    }
}

async function buyPassion(skillDef, targetPassion) {
    const icons = { 1: '⭐', 2: '🔥' };
    try {
        const r = await fetch(`${API_URL}/api/rimworld/buy-passion`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
            body: JSON.stringify({ username: userLogin, skill_def: skillDef, passion: targetPassion })
        });
        const d = await r.json();
        showNotification(d.message, d.success ? 'success' : 'error');
            if (d.success) {
                loadUserData();
                // Обновляем модал через 2с после синхронизации пешки
                setTimeout(() => openPassionModal(), 2000);
                startPawnRefresh();
            }
    } catch(e) { showNotification('❌ Ошибка', 'error'); }
}

// price — та же цена, что на кнопке (с бэка). Раньше здесь стояли жёсткие 300💎:
// кнопка показывала одно, подтверждение другое, списывалось третье.
async function resetPassion(skillDef, price) {
    const priceTxt = (price != null && price !== '') ? `${price}💎` : 'текущую цену';
    showConfirm('↩ Сброс страсти', `Сбросить страсть до нуля? Это стоит <b>${priceTxt}</b>.`, async () => {
        try {
            const r = await fetch(`${API_URL}/api/rimworld/reset-passion`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
                body: JSON.stringify({ username: userLogin, skill_def: skillDef })
            });
            const d = await r.json();
            showNotification(d.message, d.success ? 'success' : 'error');
            if (d.success) {
                loadUserData();
                setTimeout(() => openPassionModal(), 2000);
                startPawnRefresh();
            }
        } catch(e) { showNotification('❌ Ошибка', 'error'); }
    });
}

// ===== ОБЩИЕ ФУНКЦИИ =====
