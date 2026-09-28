// Only presentation options for components already shipped in this Twitch ZIP.
// The backend cannot add markup, scripts, CSS rules or new action types here.
const BnrUiConfig = (() => {
    const sections = ['summon', 'active_powers', 'tournament', 'weapon_choice'];
    const defaults = {
        active_powers: 'Активки', tournament: '🏆 Турнир зрителей',
        weapon_choice: 'Оружейная способность',
        summon_ally: '📯 Призвать за стримера', summon_enemy: '⚔️ Призвать против стримера',
        discard: '🗑 Выкинуть вещь',
    };
    const palette = {
        1: {text:'#c0c3ca',border:'#5b5e66',background:'#2b2d31'},
        2: {text:'#89dba1',border:'#467457',background:'#203127'},
        3: {text:'#87c6fa',border:'#426c91',background:'#202d3a'},
        4: {text:'#c7a0f5',border:'#785398',background:'#30253b'},
        5: {text:'#f2b17f',border:'#966139',background:'#3b2b20'},
        6: {text:'#f5d174',border:'#aa8436',background:'#39311e'},
    };
    const validColor = value => typeof value === 'string' && /^#[0-9a-fA-F]{6}$/.test(value);
    let order = [...sections];
    let visible = Object.fromEntries(sections.map(id => [id,true]));
    let labels = {...defaults};
    let colors = Object.fromEntries(Object.entries(palette).map(([tier,value]) => [tier,{...value}]));

    function label(key, fallback='') { return labels[key] ?? fallback; }

    function applyTierPalette(host=document.getElementById('bnr-equipment-shop')) {
        if (!host) return;
        host.querySelectorAll('[data-tier]').forEach(node => {
            const tier=String(Number(node.dataset.tier));
            if (!Object.prototype.hasOwnProperty.call(colors,tier)) return;
            const item=colors[tier];
            node.style.setProperty('--tier-color',item.text);
            node.style.setProperty('--tier-border',item.border);
            node.style.setProperty('--tier-bg',item.background);
        });
    }

    function apply() {
        const pane=document.querySelector('.bnr-tab-pane[data-bnr-pane="combat"]');
        if (pane) {
            const nodes=Object.fromEntries(sections.map(id => [id,pane.querySelector(`[data-bnr-ui-section="${id}"]`)]));
            for (const id of order) if (nodes[id]) pane.appendChild(nodes[id]);
            for (const id of sections) if (nodes[id]) {
                nodes[id].hidden=!visible[id];
                nodes[id].style.display=visible[id]?'':'none';
            }
            const tournament=pane.querySelector('[data-bnr-ui-label="tournament"]');
            if (tournament) tournament.textContent=label('tournament');
        }
        applyTierPalette();
    }

    function update(raw) {
        order=[...sections];
        visible=Object.fromEntries(sections.map(id => [id,true]));
        labels={...defaults};
        colors=Object.fromEntries(Object.entries(palette).map(([tier,value]) => [tier,{...value}]));
        if (raw && typeof raw === 'object' && !Array.isArray(raw) && raw.version===1) {
            const proposed=raw.combat_order;
            if (Array.isArray(proposed) && proposed.length===sections.length &&
                proposed.every(id => typeof id==='string' && sections.includes(id)) &&
                new Set(proposed).size===sections.length) order=[...proposed];
            if (raw.combat_visible && typeof raw.combat_visible==='object') {
                for (const id of sections)
                    if (typeof raw.combat_visible[id]==='boolean') visible[id]=raw.combat_visible[id];
            }
            if (raw.labels && typeof raw.labels==='object') {
                for (const id of Object.keys(defaults)) {
                    const value=raw.labels[id];
                    if (typeof value==='string' && value.length>=1 && value.length<=64 && !/[\u0000-\u001f\u007f]/.test(value))
                        labels[id]=value;
                }
            }
            if (raw.tier_colors && typeof raw.tier_colors==='object') {
                for (const tier of Object.keys(palette)) {
                    const item=raw.tier_colors[tier];
                    if (!item || typeof item!=='object') continue;
                    for (const key of ['text','border','background'])
                        if (validColor(item[key])) colors[tier][key]=item[key];
                }
            }
        }
        apply();
        const active=document.getElementById('bnr-active-powers-slot');
        if (active?.innerHTML.trim() && typeof renderBannerlordActivePowers==='function') renderBannerlordActivePowers();
        const summon=document.getElementById('bnr-summon-slot');
        if (summon?.innerHTML.trim() && typeof renderBannerlordSummonButton==='function') renderBannerlordSummonButton();
        if (typeof BnrEquipmentShop !== 'undefined') BnrEquipmentShop.refreshPresentation();
    }

    return {update,label,applyTierPalette,apply};
})();
