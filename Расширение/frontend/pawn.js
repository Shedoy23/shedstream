async function loadColonists() {
    const container = document.getElementById('colonists-list');
    const totalEl = document.getElementById('colonist-total');
    const aliveEl = document.getElementById('colonist-alive');
    const deadEl = document.getElementById('colonist-dead');

    try {
        const r = await fetch(`${API_URL}/api/rimworld/colonists`, {
            headers: {'X-Twitch-JWT': authToken || ''}
        });
        const data = await r.json();
        const colonists = data.colonists || [];

        const alive = colonists.filter(c => c.is_alive).length;
        const dead = colonists.length - alive;
        if (totalEl) totalEl.textContent = colonists.length;
        if (aliveEl) aliveEl.textContent = alive;
        if (deadEl) deadEl.textContent = dead;

        if (!container) return;
        if (colonists.length === 0) {
            container.innerHTML = '<div class="loading">🌌 Нет данных — запусти RimWorld</div>';
            return;
        }

        container.innerHTML = colonists.map(c => {
            const hc = c.is_alive
                ? (c.health > 60 ? '#4ade80' : c.health > 30 ? '#fbbf24' : '#f87171')
                : 'var(--dim)';
            const isMyPawn = c.username === userLogin;
            const resurrectBtn = (!c.is_alive && isMyPawn)
                ? `<button data-resurrect-pawn style="font-size:10px;padding:2px 8px;background:#1a1a3a;color:#9147ff;border:1px solid #9147ff;border-radius:4px;cursor:pointer;margin-top:4px;">✨ Воскресить 500💎</button>`
                : '';
            return `<div style="display:flex;align-items:center;gap:8px;padding:6px 10px;border-radius:6px;background:#1a1a1c;margin-bottom:4px;">
                <span style="font-size:16px;">${c.is_alive ? '❤️' : '💀'}</span>
                <div style="flex:1;">
                    <div style="font-size:12px;font-weight:600;">${escapeHtml(c.pawn_name)}${isMyPawn ? ' <span style="color:#9147ff;font-size:10px;">▶ ты</span>' : ''}</div>
                    <div style="font-size:11px;color:#adadb8;">${escapeHtml(c.username)} ・ ${c.health}% HP</div>
                    ${resurrectBtn}
                </div>
                <div style="width:32px;height:4px;background:#2d2d2f;border-radius:2px;">
                    <div style="height:100%;width:${c.health}%;background:${hc};border-radius:2px;"></div>
                </div>
            </div>`;
        }).join('');
        container.querySelectorAll('[data-resurrect-pawn]').forEach(btn => {
            btn.addEventListener('click', resurrectMyPawn);
        });
    } catch(e) {
        if (container) container.innerHTML = '<div class="loading">🌌 RimWorld не подключён</div>';
    }
}

// ===== ЗАГРУЗКА ПЕШКИ =====
async function loadMyPawn() {
    dbg('🔍 loadMyPawn вызван для:', userLogin);

    // Opaque ID: начинается с U и содержит заглавные буквы; Twitch логины — строчные
    if (!userLogin || userLogin === 'testuser' || /^U[a-zA-Z0-9]{8,}$/.test(userLogin)) {
        dbg('⏭️ Пропускаем - невалидный логин:', userLogin);
        return;
    }

    try {
        const url = `${API_URL}/api/rimworld/my-pawn/${userLogin}`;
        const response = await fetch(url, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        const data = await response.json();

        const pawnContainer = document.getElementById('my-pawn-card');
        if (!pawnContainer) return;

        const createBtn = document.getElementById('create-pawn-btn');
        const pawnActions = document.getElementById('pawn-actions');
        const btnHeal = document.getElementById('heal-pawn-btn');
        const btnResurrect = document.getElementById('btn-resurrect');

        if (data.exists) {
            const pawnData = {
                name:      data.pawn_name,
                alive:     data.is_alive,
                health:    data.health > 1 ? Math.round(data.health) : Math.round(data.health * 100),
                skills:    data.skills    || [],
                equipment: data.equipment || [],
                hediffs:   data.hediffs   || [],
                implants:  data.implants  || [],
                traits:    data.traits    || [],
                genes:     data.genes     || [],
                xenotype:  data.xenotype  || null,
            };
            window._lastPawnData = pawnData; // для openXenotypeModal и других модалов

            const statusColor = pawnData.alive ? '#4ade80' : '#f87171';
            const healthColor = pawnData.health > 60 ? '#4ade80' : pawnData.health > 30 ? '#fbbf24' : '#f87171';

            let html = `
                <div class="card-header">
                    <h3>${escapeHtml(pawnData.name)}</h3>
                    <span class="card-badge" style="color:${statusColor};">
                        ${pawnData.alive ? '❤️ Жив' : '💀 Мёртв'}
                    </span>
                </div>
                <div style="background:#3d3d3f;border-radius:8px;padding:10px;margin-bottom:12px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                        <span style="color:#adadb8;font-size:13px;">Здоровье</span>
                        <span style="font-weight:bold;color:${healthColor};">${pawnData.health}%</span>
                    </div>
                    <div style="height:6px;background:#2d2d2f;border-radius:3px;overflow:hidden;">
                        <div style="height:100%;width:${pawnData.health}%;background:${healthColor};border-radius:3px;transition:width 0.5s;"></div>
                    </div>
                </div>
            `;

            // Навыки
            if (pawnData.skills.length > 0) {
                html += `<div style="margin-bottom:12px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                        <div style="font-size:13px;font-weight:600;color:#9147ff;">📊 Навыки</div>
                        <div style="display:flex;gap:4px;flex-shrink:0;">
                            <button data-open-modal="passion" title="Огоньки страсти" style="font-size:14px;padding:2px 6px;background:#2d2d2f;color:#9147ff;border:1px solid #9147ff;border-radius:4px;cursor:pointer;line-height:1;">🔥</button>
                            <button data-open-modal="neuro" title="Нейротренеры" style="font-size:14px;padding:2px 6px;background:#2d2d2f;color:#4ade80;border:1px solid #4ade80;border-radius:4px;cursor:pointer;line-height:1;">🧠</button>
                            <button data-open-modal="xenotype" title="Ксенотипы и гены" style="font-size:14px;padding:2px 6px;background:#2d2d2f;color:#38bdf8;border:1px solid #38bdf8;border-radius:4px;cursor:pointer;line-height:1;">🧬</button>
                        </div>
                    </div>`;
                const topSkills = [...pawnData.skills].sort((a,b) => b.level - a.level);
                topSkills.forEach(skill => {
                    const isDisabled = skill.is_disabled === true || skill.disabled === true;
                    const lvlColor = isDisabled ? '#4d4d4f'
                        : skill.level >= 15 ? '#fbbf24' : skill.level >= 10 ? '#4ade80'
                        : skill.level >= 5 ? '#60a5fa' : '#adadb8';
                    const passion = skill.passion ?? 0;
                    const passionIcon = !isDisabled
                        ? (passion === 2 ? ' 🔥' : passion === 1 ? ' ⭐' : '')
                        : '';
                    const skillName = skill.def_name || skill.name || '?';
                    const skillLabel = localizeSkill(skill);
                    // Недоступный навык показываем с пометкой "-" вместо полного скрытия
                    const disabledMark = isDisabled
                        ? ' <span style="font-size:9px;color:#f87171;background:#3a1a1a;border:1px solid #f87171;border-radius:2px;padding:0 3px;">—</span>'
                        : '';
                    html += `
                        <div style="display:flex;align-items:center;gap:8px;margin-bottom:5px;${isDisabled?'opacity:0.55;':''}">
                            <span style="font-size:12px;color:#adadb8;width:90px;flex-shrink:0;">${escapeHtml(skillLabel)}${passionIcon}${disabledMark}</span>
                            <div style="flex:1;height:4px;background:#2d2d2f;border-radius:2px;">
                                <div style="height:100%;width:${isDisabled?0:Math.min(100,(skill.level/20)*100)}%;background:${lvlColor};border-radius:2px;"></div>
                            </div>
                            <span style="font-size:12px;font-weight:bold;color:${lvlColor};width:20px;text-align:right;">${isDisabled?'—':skill.level}</span>
                        </div>
                    `;
                });
                html += `</div>`;
            }

            // Экипировка с тултипами оружия
            if (pawnData.equipment.length > 0) {
                html += `<div style="margin-bottom:12px;"><div style="font-size:13px;font-weight:600;color:#9147ff;margin-bottom:8px;">🎒 Экипировка</div>`;
                pawnData.equipment.forEach(item => {
                    const slotEmoji = { weapon: '⚔️', apparel: '👕', armour: '🛡️', head: '🪖', body: '👘' }[item.slot] || '🎒';
                    const hpColor = item.hp >= 80 ? '#4ade80' : item.hp >= 40 ? '#f59e0b' : '#f87171';
                    
                    // Сборка тултипа для оружия
                    let weaponTooltip = '';
                    if (item.slot === 'weapon') {
                        const traits = item.weapon_traits || [];
                        const psi    = item.psi_abilities || [];
                        const blade  = item.is_bladelink;
                        if (traits.length || psi.length || blade) {
                            let tip = '';
                            if (blade) tip += '🔗 <b>Привязанное оружие</b><br>';
                            traits.forEach(t => tip += `🔮 ${escapeHtml(t.label)} <i style="color:#666">${escapeHtml(t.description)}</i><br>`);
                            psi.forEach(a => tip += `🌀 ${escapeHtml(a.label)} <i style="color:#666">${escapeHtml(a.desc)}</i><br>`);
                            weaponTooltip = tip;
                        }
                    } else {
                        weaponTooltip = item.description || item.tooltip || '';
                    }

                    const tooltipId = 'eq-tip-' + Math.random().toString(36).slice(2, 7);
                    html += `
                        <div style="background:#3d3d3f;border-radius:6px;padding:7px 10px;margin-bottom:4px;position:relative;cursor:help;"
                             ${weaponTooltip ? `data-tooltip-id="${tooltipId}"` : ''}>
                            <div style="display:flex;justify-content:space-between;align-items:center;">
                                <span style="font-size:12px;">${slotEmoji} ${escapeHtml(item.label || item.name || '')}</span>
                                <span style="font-size:10px;color:${hpColor};">HP ${item.hp ?? 100}%</span>
                            </div>
                            ${weaponTooltip ? `
                            <div id="${tooltipId}" style="display:none;position:absolute;left:0;right:0;top:100%;z-index:999;
                                background:#1f1f23;border:1px solid #9147ff;border-radius:8px;padding:10px 12px;
                                font-size:11px;color:#adadb8;line-height:1.5;white-space:pre-wrap;margin-top:2px;
                                box-shadow:0 4px 20px rgba(0,0,0,0.6);max-height:200px;overflow-y:auto;">
                                ${weaponTooltip}
                            </div>` : ''}
                        </div>
                    `;
                });
                html += `</div>`;
            }
            

            // Состояния здоровья (раны, импланты)
            // Черты характера
            if (pawnData.traits && pawnData.traits.length > 0) {
                html += `<div style="margin-bottom:12px;"><div style="font-size:13px;font-weight:600;color:#9147ff;margin-bottom:8px;">🧬 Черты</div>`;
                pawnData.traits.forEach(t => {
                    html += `
                        <div style="background:#3d3d3f;border-radius:6px;padding:7px 10px;margin-bottom:4px;display:flex;justify-content:space-between;align-items:center;">
                            <span style="font-size:12px;">${parseRimColor(t.label)}</span>
                            <button data-remove-trait="${(t.def_name||'').replace(/\\/g, '\\\\').replace(/'/g, "\\'")}" data-degree="${t.degree || 0}" data-label="${escapeHtml(t.label.replace(/<[^>]+>/g,''))}"
                                style="font-size:10px;padding:2px 8px;background:#3a1a1a;color:#f87171;border:1px solid #f87171;border-radius:4px;cursor:pointer;">
                                🗑️ 300💎
                            </button>
                        </div>`;
                });
                html += `</div>`;
            }

            // Гены (Biotech) — как черты, но с пометкой ксено/неактив/подавлен
            if (pawnData.genes && pawnData.genes.length > 0) {
                html += `<div style="margin-bottom:12px;"><div style="font-size:13px;font-weight:600;color:#9147ff;margin-bottom:8px;">🔬 Гены</div>`;
                pawnData.genes.forEach(gene => {
                    const isActive     = gene.is_active !== false && gene.is_active !== 0;
                    const isOverridden = gene.is_overridden === true || gene.is_overridden === 1;
                    const isXeno = gene.xenogene === true || gene.xenogene === 1;
                    const lbl     = gene.label    || gene.def_name || '?';
                    const defName = gene.def_name || '';
                    const canRemove = true;
                    html += `<div style="background:#3d3d3f;border-radius:6px;padding:7px 10px;margin-bottom:4px;display:flex;justify-content:space-between;align-items:center;${isOverridden ? 'opacity:0.6;' : ''}">
                        <span style="font-size:12px;">
                            ${escapeHtml(lbl)}
                            ${isXeno
                                ? '<span style="font-size:9px;color:#9147ff;margin-left:4px;background:#2d2d2f;padding:1px 4px;border-radius:3px;">ксено</span>'
                                : '<span style="font-size:9px;color:#adadb8;margin-left:4px;">эндо</span>'}
                            ${isOverridden
                                ? '<span style="font-size:9px;color:#f59e0b;margin-left:4px;" title="Подавлен другим геном">подавлен</span>'
                                : (!isActive ? '<span style="font-size:9px;color:#f87171;margin-left:4px;">неакт.</span>' : '')}
                        </span>
                        ${canRemove
                            ? `<button data-remove-gene="${(defName||'').replace(/\\/g, '\\\\').replace(/'/g, "\\'")}" data-gene-label="${lbl.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}" data-overridden="${isOverridden}"
                                style="font-size:10px;padding:2px 8px;background:#3a1a1a;color:#f87171;border:1px solid #f87171;border-radius:4px;cursor:pointer;flex-shrink:0;"
                                title="${isOverridden ? 'Ген подавлен, но будет удалён' : 'Удалить ксеноген'}">🗑️ 3000💎</button>`
                            : ''}
                    </div>`;
                });
                html += `</div>`;
            }

            // ── Ксенотип ───────────────────────────────────────────────────────────────
            if (pawnData.xenotype && (pawnData.xenotype.name || pawnData.xenotype.xenogenes?.length > 0)) {
                const xt = pawnData.xenotype;
                const metColor = xt.metabolism < 0 ? '#f87171' : xt.metabolism > 0 ? '#4ade80' : '#adadb8';
                const metSign  = xt.metabolism > 0 ? '+' : '';
                const isCustom = xt.is_custom;
                const xenoCount = (xt.xenogenes || []).length;

                html += `<div style="margin-bottom:12px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                        <div style="font-size:13px;font-weight:600;color:#9147ff;">🧬 Ксенотип</div>
                        <button data-open-modal="xenotype" style="font-size:10px;padding:2px 8px;background:#2d2d2f;color:#9147ff;border:1px solid #9147ff;border-radius:4px;cursor:pointer;">🔄 Сменить</button>
                    </div>
                    <div style="background:#2d2d2f;border-radius:8px;padding:10px 12px;margin-bottom:6px;">
                        <div style="display:flex;justify-content:space-between;align-items:center;">
                            <div>
                                <span style="font-size:13px;font-weight:700;">${escapeHtml(xt.name)}</span>
                                ${isCustom ? '<span style="font-size:9px;color:#adadb8;margin-left:6px;background:#1f1f23;padding:1px 5px;border-radius:3px;">кастом</span>' : ''}
                            </div>
                            <div style="font-size:11px;color:${metColor};">
                                ⚡ ${metSign}${xt.metabolism ?? 0} мет.
                            </div>
                        </div>
                        <div style="font-size:10px;color:#adadb8;margin-top:3px;">${xenoCount} ксеноген${xenoCount === 1 ? '' : xenoCount < 5 ? 'а' : 'ов'}</div>
                    </div>`;

                // Список ксеногенов (свёрнутый — по клику)
                if (xenoCount > 0) {
                    const xenoId = 'xenogenes-list-' + (userLogin || 'p');
                    html += `<div id="${xenoId}" style="display:none;">`;
                    (xt.xenogenes || []).forEach(g => {
                        const isActive    = g.is_active !== false;
                        const isOverridden = g.is_overridden === true;
                        const icon = g.biostat_arc > 0 ? '👁' : g.biostat_met < -1 ? '⚠️' : '🔘';
                        html += `<div style="display:flex;justify-content:space-between;align-items:center;
                                    background:#3d3d3f;border-radius:5px;padding:5px 9px;margin-bottom:3px;
                                    ${isOverridden ? 'opacity:0.55;' : ''}">
                            <span style="font-size:11px;">${icon} ${escapeHtml(g.label)}
                                ${isOverridden ? '<span style="font-size:9px;color:#f59e0b;margin-left:3px;">подавлен</span>' : ''}
                                ${!isActive && !isOverridden ? '<span style="font-size:9px;color:#f87171;margin-left:3px;">неакт.</span>' : ''}
                            </span>
                            ${g.biostat_met !== 0 ? `<span style="font-size:9px;color:${g.biostat_met < 0 ? '#f87171' : '#4ade80'};">${g.biostat_met > 0 ? '+' : ''}${g.biostat_met}</span>` : ''}
                        </div>`;
                    });
                    html += `</div>
                    <button data-toggle-target="${xenoId}" data-toggle-closed-text="▼ Показать гены (${xenoCount})" data-toggle-open-text="▲ Скрыть гены"
                        style="width:100%;font-size:10px;padding:4px;background:none;border:1px solid #3d3d3f;border-radius:5px;color:#adadb8;cursor:pointer;margin-top:2px;">
                        ▼ Показать гены (${xenoCount})
                    </button>`;
                }

                html += `</div>`;
            }

            if (pawnData.hediffs.length > 0) {
                // === Расшифровка body_part → читаемое название + сторона ===
                const PART_NAMES = {
                    // Руки
                    'LeftArm':      ['Левая рука',    '🤲'],
                    'RightArm':     ['Правая рука',   '🤱'],
                    'LeftHand':     ['Левая кисть',   '🤲'],
                    'RightHand':    ['Правая кисть',  '🤱'],
                    'LeftShoulder': ['Левое плечо',   '🤲'],
                    'RightShoulder':['Правое плечо',  '🤱'],
                    'LeftElbow':    ['Левый локоть',  '🤲'],
                    'RightElbow':   ['Правый локоть', '🤱'],
                    // Ноги
                    'LeftLeg':      ['Левая нога',    '🦵'],
                    'RightLeg':     ['Правая нога',   '🦵'],
                    'LeftFoot':     ['Левая ступня',  '🦶'],
                    'RightFoot':    ['Правая ступня', '🦶'],
                    'LeftHip':      ['Левое бедро',   '🦵'],
                    'RightHip':     ['Правое бедро',  '🦵'],
                    'LeftKnee':     ['Левое колено',  '🦵'],
                    'RightKnee':    ['Правое колено', '🦵'],
                    // Голова
                    'LeftEye':      ['Левый глаз',    '👁️'],
                    'RightEye':     ['Правый глаз',   '👁️'],
                    'LeftEar':      ['Левое ухо',     '👂'],
                    'RightEar':     ['Правое ухо',    '👂'],
                    'Nose':         ['Нос',            '👃'],
                    'Jaw':          ['Челюсть',        '🦷'],
                    'Head':         ['Голова',         '🗨️'],
                    'Brain':        ['Мозг',           '🧠'],
                    // Тело
                    'LeftLung':     ['Левое лёгкое',  '🫁'],
                    'RightLung':    ['Правое лёгкое', '🫁'],
                    'LeftKidney':   ['Левая почка',   '🫘'],
                    'RightKidney':  ['Правая почка',  '🫘'],
                    'Heart':        ['Сердце',         '❤️'],
                    'Liver':        ['Печень',         '🫀'],
                    'Stomach':      ['Желудок',        '🫄'],
                    'Torso':        ['Торс',           '🫀'],
                    'Spine':        ['Позвоночник',    '🦴'],
                    'Neck':         ['Шея',            '🫙'],
                    'тело':         ['Тело',           '🧍'],
                };

                function partInfo(rawPart) {
                    const p = (rawPart || 'тело').trim();
                    if (PART_NAMES[p]) return PART_NAMES[p];
                    // Не нашли — выводим как есть, красиво
                    const side = p.startsWith('Left') ? '🤲 Лев. ' : p.startsWith('Right') ? '🤱 Прав. ' : '';
                    const name = p.replace(/^(Left|Right)/, '').replace(/([A-Z])/g, ' $1').trim();
                    return [side + name, '🔘'];
                }

                // === Разделяем импланты/протезы и раны/болезни ===
                const implantHediffs = [];
                const woundHediffs   = [];

                pawnData.hediffs.forEach(h => {
                    const lbl = (h.label || '').toLowerCase();
                    const isImplant = lbl.includes('имплант') || lbl.includes('протез')
                        || lbl.includes('биони') || lbl.includes('архо')
                        || lbl.includes('нано')  || lbl.includes('synth')
                        || h.severity <= 0.01;   // severity=0 — обычно пассивный эффект (имплант)
                    if (isImplant) implantHediffs.push(h);
                    else           woundHediffs.push(h);
                });

                // --- Блок имплантов ---
                if (implantHediffs.length > 0) {
                    html += `<div style="margin-bottom:12px;">
                        <div style="font-size:13px;font-weight:600;color:#4ade80;margin-bottom:8px;">🦾 Импланты и протезы</div>`;

                    implantHediffs.forEach(h => {
                        const [partName, partIcon] = partInfo(h.part);
                        // Сторона: из поля side (C#) или из названия части тела
                        // Сторона: используем is_left (bool/null) от сервера,
                        // fallback на part_def (английский defName, надёжно содержит Left/Right)
                        const side = h.is_left === true  ? 'left'
                            : h.is_left === false ? 'right'
                            : (h.part_def || '').startsWith('Left')  ? 'left'
                            : (h.part_def || '').startsWith('Right') ? 'right'
                            : '';
                        const sideTag = side === 'left'
                            ? `<span style="font-size:10px;background:#1a3a5a;color:#60a5fa;border-radius:4px;padding:1px 5px;margin-left:5px;">← лев</span>`
                            : side === 'right'
                            ? `<span style="font-size:10px;background:#3a1a5a;color:#c084fc;border-radius:4px;padding:1px 5px;margin-left:5px;">прав →</span>`
                            : '';
                        html += `
                        <div style="background:#1a2d1a;border:1px solid #2d4d2d;border-radius:8px;padding:8px 10px;margin-bottom:5px;display:flex;align-items:center;gap:10px;">
                            <div style="flex-shrink:0;background:#2d4d2d;border-radius:6px;padding:4px 7px;font-size:11px;color:#4ade80;font-weight:600;white-space:nowrap;">
                                ${partIcon} ${escapeHtml(partName)}
                            </div>
                            <div style="font-size:12px;color:#e0ffe0;font-weight:500;">${parseRimColor(h.label)}${sideTag}</div>
                        </div>`;
                    });
                    html += `</div>`;
                }

                // --- Блок ран/состояний ---
                if (woundHediffs.length > 0) {
                    html += `<div style="margin-bottom:12px;">
                        <div style="font-size:13px;font-weight:600;color:#9147ff;margin-bottom:8px;">🩺 Состояние здоровья</div>`;

                    woundHediffs.forEach(h => {
                        const [partName, partIcon] = partInfo(h.part);
                        const lbl = (h.label || '').toLowerCase();
                        let accentColor = '#4d4d4f';
                        let bgColor     = '#3d3d3f';
                        if      (lbl.includes('рана') || lbl.includes('кровот') || lbl.includes('перелом')) { accentColor = '#f87171'; bgColor = '#2d1a1a'; }
                        else if (lbl.includes('болезнь') || lbl.includes('инфекц') || lbl.includes('чума')) { accentColor = '#fbbf24'; bgColor = '#2d2514'; }
                        else if (lbl.includes('ожог'))  { accentColor = '#fb923c'; bgColor = '#2d1e10'; }
                        else if (h.severity > 0.5)      { accentColor = '#f87171'; bgColor = '#2d1a1a'; }

                        const sevPct = Math.round(Math.min(1, h.severity || 0) * 100);

                        html += `
                        <div style="background:${bgColor};border-left:3px solid ${accentColor};border-radius:6px;padding:8px 10px;margin-bottom:4px;">
                            <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
                                <div style="display:flex;align-items:center;gap:6px;min-width:0;">
                                    <span style="font-size:11px;background:rgba(255,255,255,0.07);border-radius:4px;padding:2px 6px;white-space:nowrap;flex-shrink:0;color:rgba(255,255,255,0.55);">
                                        ${partIcon} ${escapeHtml(partName)}
                                    </span>
                                    <span style="font-size:12px;color:#efeff1;">${parseRimColor(h.label)}</span>
                                </div>
                                ${sevPct > 0 ? `<span style="font-size:11px;color:${accentColor};font-weight:600;flex-shrink:0;">${sevPct}%</span>` : ''}
                            </div>
                        </div>`;
                    });
                    html += `</div>`;
                }
            }


            // (гены отображены выше)

            pawnContainer.innerHTML = html;
            pawnContainer.querySelectorAll('[data-remove-trait]').forEach(btn => {
                btn.addEventListener('click', () => {
                    removeMyTrait(btn.dataset.removeTrait, parseInt(btn.dataset.degree), btn.dataset.label);
                });
            });
            pawnContainer.querySelectorAll('[data-remove-gene]').forEach(btn => {
                btn.addEventListener('click', () => {
                    removeMyGene(btn.dataset.removeGene, btn.dataset.geneLabel, btn.dataset.overridden === 'true');
                });
            });

            // Кнопки действий
            if (createBtn) createBtn.style.display = 'none';
            if (pawnActions) pawnActions.style.display = 'flex';
            // Берём кнопки ПОСЛЕ innerHTML чтобы не работать с мёртвыми элементами
            const healBtn = document.getElementById('heal-pawn-btn');
            const resBtn  = document.getElementById('btn-resurrect');
            if (healBtn) healBtn.style.display = pawnData.alive ? 'flex' : 'none';
            if (resBtn)  resBtn.style.display  = !pawnData.alive ? 'flex' : 'none';
            // Восстанавливаем таймер КД лечения
            try {
                const cd = await fetch(`${API_URL}/api/rimworld/heal-cooldown/${encodeURIComponent(userLogin)}`, {
                    headers: {'X-Twitch-JWT': authToken || ''}
                });
                const cdData = await cd.json();
                if (cdData.cooldown_left > 0) startBtnCountdown('heal-pawn-btn', cdData.cooldown_left);
            } catch (e) {}

        } else {
            pawnContainer.innerHTML = `
                <div class="card-header"><h3>👤 Моя пешка</h3></div>
                <div class="loading" style="padding:20px;">У тебя пока нет пешки в RimWorld</div>
            `;
            if (createBtn) createBtn.style.display = 'block';
            if (pawnActions) pawnActions.style.display = 'none';
        }
    } catch (e) {
        console.error('🔽 Ошибка загрузки пешки:', e);
        const pawnContainer = document.getElementById('my-pawn-card');
        if (pawnContainer) {
            pawnContainer.innerHTML = `
                <div class="card-header"><h3>👤 Моя пешка</h3></div>
                <div class="loading" style="color:#f87171;">Ошибка загрузки — сервер недоступен</div>
            `;
        }
    }
}

// ===== ЛЕЧЕНИЕ ПЕШКИ =====
async function healMyPawn() {
    // Сначала проверяем КД на сервере
    try {
        const cd = await fetch(`${API_URL}/api/rimworld/heal-cooldown/${encodeURIComponent(userLogin)}`, {
            headers: {'X-Twitch-JWT': authToken || ''}
        });
        const cdData = await cd.json();
        if (cdData.cooldown_left > 0) {
            const mins = Math.floor(cdData.cooldown_left / 60);
            const secs = cdData.cooldown_left % 60;
            showNotification(`⏳ Лечение через ${mins}:${secs.toString().padStart(2,'0')}`, 'error');
            startBtnCountdown('heal-pawn-btn', cdData.cooldown_left);
            return;
        }
    } catch (e) { /* если эндпоинт недоступен — разрешаем попытку */ }

    const points = parseInt(document.getElementById('points')?.textContent || '0');
    if (points < 150) {
        showNotification('❌ Нужно 150💎 для лечения!', 'error');
        return;
    }

    showConfirm('💊 Лечение пешки', `Потратить 150💎 на лечение пешки?`, async () => {
        try {
            const r = await fetch(`${API_URL}/api/rimworld/heal-pawn`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
                body: JSON.stringify({ username: userLogin })
            });
            const data = await r.json();
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) {
                startBtnCountdown('heal-pawn-btn', 15 * 60);
                loadUserData();
                startPawnRefresh();
            } else if (data.cooldown_left) {
                startBtnCountdown('heal-pawn-btn', data.cooldown_left);
            }
        } catch (e) {
            showNotification('❌ Ошибка', 'error');
        }
    });
}

function startBtnCountdown(btnOrId, seconds) {
    const btn = (typeof btnOrId === 'string') ? document.getElementById(btnOrId) : btnOrId;
    if (!btn) return;
    if (btn._cdInterval) clearInterval(btn._cdInterval);
    const origText = btn._origText || btn.dataset.origText || btn.textContent;
    btn._origText = origText;
    btn.dataset.origText = origText;
    btn.disabled = true;
    let left = seconds;
    const update = () => {
        if (left >= 60) {
            const m = Math.floor(left / 60), s = left % 60;
            btn.textContent = `⏳ ${m}:${s.toString().padStart(2,'0')}`;
        } else {
            btn.textContent = `⏳ ${left}с`;
        }
    };
    update();
    btn._cdInterval = setInterval(() => {
        left--;
        if (left <= 0) {
            clearInterval(btn._cdInterval);
            btn._cdInterval = null;
            btn.disabled = false;
            btn.textContent = origText;
        } else {
            update();
        }
    }, 1000);
}

// ===== ВОСКРЕШЕНИЕ ПЕШКИ =====
async function resurrectMyPawn() {
    const points = parseInt(document.getElementById('points')?.textContent || '0');
    if (points < 500) {
        showNotification('❌ Нужно 500💎 для воскрешения!', 'error');
        return;
    }

    showConfirm('✨ Воскрешение', `Потратить 500💎 на воскрешение пешки?`, async () => {
        try {
            const r = await fetch(`${API_URL}/api/rimworld/resurrect-pawn`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
                body: JSON.stringify({ username: userLogin })
            });
            const data = await r.json();
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) { loadUserData(); startPawnRefresh(); }
        } catch (e) {
            showNotification('❌ Ошибка', 'error');
        }
    });
}

// ===== МАГАЗИН RIMWORLD =====
