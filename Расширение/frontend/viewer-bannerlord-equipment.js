// Deterministic Bannerlord equipment catalog. Prices and availability are server data.
const BnrEquipmentShop = (() => {
    const slotNames = {weapon0:'Оружие 1',weapon1:'Оружие 2',weapon2:'Оружие 3',weapon3:'Оружие 4',
        head:'Голова',body:'Тело',leg:'Ноги',gloves:'Руки',cape:'Плечи',horse:'Лошадь',horseharness:'Сбруя'};
    const categories = {one_handed:'Одноручное',two_handed:'Двуручное',polearm:'Древковое',
        bow:'Луки',crossbow:'Арбалеты',thrown:'Метательное',shield:'Щиты',arrows:'Стрелы',bolts:'Болты',
        head:'Шлемы',body:'Доспехи',leg:'Обувь',gloves:'Перчатки',cape:'Наплечники',
        horse:'Лошади',horseharness:'Сбруя'};
    const statNames = {weight:'Вес',head:'Голова',body:'Тело',leg:'Ноги',arm:'Руки',
        swing_dmg:'Урон руб.',thrust_dmg:'Урон кол.',swing_spd:'Скорость руб.',thrust_spd:'Скорость кол.',
        length:'Длина',missile_spd:'Скорость снаряда',accuracy:'Точность',stack:'Боезапас',
        speed:'Скорость',maneuver:'Манёвренность',charge:'Урон натиска',hp:'Прочность',armor:'Защита',dmg:'Урон'};
    let snapshot = null;
    let view = 'shop';
    let search = '';
    let category = '';
    let tier = '';
    let page = 0;
    let busy = false;
    let requestNumber = 0;
    let generation = 0;
    let fetching = false;
    let selectedSlots = {};
    const pageSize = 20;
    const text = value => escapeHtml(String(value ?? ''));
    const number = value => Number(value || 0).toLocaleString('ru-RU');
    const tierName = value => ['—','I','II','III','IV','V','VI'][Number(value)] || text(value);
    const uiLabel=(key,fallback)=>typeof BnrUiConfig==='undefined'?fallback:BnrUiConfig.label(key,fallback);
    const root = () => document.getElementById('bnr-equipment-shop');

    function stats(item) {
        return Object.entries(item.stats || {}).filter(([key,value]) => statNames[key] && Number.isFinite(Number(value)) && Number(value) > 0)
            .slice(0,6).map(([key,value]) => `${statNames[key]} ${text(value)}`).join(' · ');
    }

    function itemHtml(item, owned) {
        const id = text(owned ? item.owned_id : item.item_id);
        const tierValue = Number(item.tier);
        const tierKey = Number.isInteger(tierValue) && tierValue >= 1 && tierValue <= 6 ? tierValue : 1;
        const actionBlocked = busy || !snapshot.can_manage || snapshot.pending;
        const blocked = actionBlocked || item.unavailable;
        let controls;
        if (!owned) {
            const disabled = blocked || !item.can_buy;
            controls = `<button type="button" class="bnr-eq-action" data-bnr-eq-buy="${id}" ${disabled ? 'disabled' : ''}>
                Купить · ${number(item.price_gold)} 💰</button>
                ${!item.can_buy && item.reason ? `<div class="bnr-eq-reason">${text(item.message || item.reason)}</div>` : ''}`;
        } else if (item.slot) {
            controls = `<div class="bnr-eq-equipped">Надето: ${text(slotNames[item.slot] || item.slot)}</div>
                <button type="button" class="bnr-eq-action secondary" data-bnr-eq-unequip="${text(item.slot)}" ${blocked ? 'disabled' : ''}>Снять в инвентарь</button>`;
        } else {
            const slots = (item.slots || []).filter(s => slotNames[s]);
            const chosen = slots.includes(selectedSlots[item.owned_id]) ? selectedSlots[item.owned_id] : slots[0];
            controls = `<div class="bnr-eq-equip-controls">
                <select aria-label="Куда надеть ${text(item.name)}" data-bnr-eq-slot="${id}" ${blocked ? 'disabled' : ''}>
                    ${slots.map(s => `<option value="${text(s)}" ${s === chosen ? 'selected' : ''}>${slotNames[s]}</option>`).join('')}
                </select><button type="button" class="bnr-eq-action secondary" data-bnr-eq-equip="${id}" ${blocked || !slots.length ? 'disabled' : ''}>Надеть</button></div>`;
        }
        if (owned) controls += `<button type="button" class="bnr-eq-action discard" data-bnr-eq-discard="${id}" ${actionBlocked ? 'disabled' : ''}>${text(uiLabel('discard','🗑 Выкинуть вещь'))}</button>`;
        return `<article class="bnr-eq-item" data-tier="${tierKey}"><div class="bnr-eq-item-top"><strong>${text(item.name || item.item_id)}</strong>
            <span class="bnr-eq-tier">${tierName(item.tier)}</span></div>
            <div class="bnr-eq-meta">${text(categories[item.category] || item.category || '')}${!owned ? ` · ур. ${number(item.required_level)}` : ''}</div>
            ${stats(item) ? `<div class="bnr-eq-stats">${stats(item)}</div>` : ''}${controls}
            ${owned && item.unavailable ? '<div class="bnr-eq-reason">Предмет или его качество недоступны в текущей сборке игры.</div>' : ''}</article>`;
    }

    function renderResults() {
        const host = root();
        if (!host || !snapshot) return;
        const owned = view === 'owned';
        const items = (owned ? snapshot.inventory : snapshot.items) || [];
        const query = search.trim().toLocaleLowerCase('ru-RU');
        const filtered = items.filter(item => (!category || item.category === category)
            && (!tier || String(item.tier) === tier)
            && (!query || String(item.name || item.item_id || '').toLocaleLowerCase('ru-RU').includes(query)));
        const pages = Math.max(1,Math.ceil(filtered.length/pageSize));
        page = Math.min(page,pages-1);
        const result = host.querySelector('[data-bnr-eq-results]');
        result.innerHTML = filtered.slice(page*pageSize,(page+1)*pageSize).map(item => itemHtml(item,owned)).join('')
            || `<div class="bnr-eq-empty">${search || category || tier ? 'Ничего не найдено. Измени фильтры.' : owned
                ? 'Здесь будут купленные и снятые вещи.' : 'Каталог появится, когда мод передаст вещи из игры.'}</div>`;
        host.querySelector('[data-bnr-eq-count]').textContent = `${filtered.length} вещей`;
        host.querySelector('[data-bnr-eq-pages]').innerHTML = pages > 1
            ? `<button type="button" data-bnr-eq-page="-1" ${page === 0 ? 'disabled' : ''}>Назад</button><span>${page+1} / ${pages}</span><button type="button" data-bnr-eq-page="1" ${page+1 === pages ? 'disabled' : ''}>Далее</button>` : '';
        if (typeof BnrUiConfig !== 'undefined') BnrUiConfig.applyTierPalette(host);
    }

    function render() {
        const host = root();
        if (!host || !snapshot) return;
        // Do not replace a focused filter during a background refresh.
        const focus = host.contains(document.activeElement) ? document.activeElement : null;
        const selection = focus?.matches('[data-bnr-eq-search]') ? [focus.selectionStart,focus.selectionEnd] : null;
        const items = (view === 'owned' ? snapshot.inventory : snapshot.items) || [];
        const availableCategories = [...new Set(items.map(i => i.category).filter(Boolean))];
        if (category && !availableCategories.includes(category)) category = '';
        host.innerHTML = `<div class="card-header"><h3>🎒 Снаряжение</h3><span class="card-badge" data-bnr-eq-count></span></div>
            <div class="bnr-eq-summary"><span>Герой · ур. ${number(snapshot.hero_level)}</span><strong>${number(snapshot.gold)} 💰</strong></div>
            <div class="bnr-eq-unlocks">${(snapshot.tiers || []).map(t => `<span data-tier="${Number(t.tier)}" class="${Number(snapshot.hero_level) >= t.required_level ? 'unlocked' : ''}">${tierName(t.tier)} · ур. ${number(t.required_level)}</span>`).join('')}</div>
            <div class="bnr-eq-tabs" role="group" aria-label="Снаряжение">
                <button type="button" data-bnr-eq-view="shop" aria-pressed="${view === 'shop'}">Магазин</button>
                <button type="button" data-bnr-eq-view="owned" aria-pressed="${view === 'owned'}">Мои вещи · ${(snapshot.inventory || []).length}</button></div>
            <p class="bnr-eq-help">${view === 'shop' ? 'Покупка за динары героя. Вещь попадёт в твой инвентарь.' : 'Надевай вещи между боями. Заменённую вещь можно надеть снова или выкинуть навсегда.'}</p>
            ${snapshot.pending || busy ? '<div class="bnr-eq-notice" role="status">Заявка отправлена — ждём результат из игры.</div>' : ''}
            ${snapshot.reason ? `<div class="bnr-eq-notice" role="status">${text(snapshot.message || snapshot.reason)}</div>` : ''}
            <div class="bnr-eq-filters"><input type="search" data-bnr-eq-search aria-label="Найти вещь" placeholder="Найти вещь…" value="${text(search)}">
                <div><select data-bnr-eq-category aria-label="Категория"><option value="">Все категории</option>
                    ${availableCategories.map(c => `<option value="${text(c)}" ${category === c ? 'selected' : ''}>${text(categories[c] || c)}</option>`).join('')}</select>
                <select data-bnr-eq-tier aria-label="Тир"><option value="">Все тиры</option>${(snapshot.tiers || []).map(t => `<option value="${t.tier}" ${tier === String(t.tier) ? 'selected' : ''}>Тир ${tierName(t.tier)}</option>`).join('')}</select></div></div>
            <div class="bnr-eq-results" data-bnr-eq-results></div><div class="bnr-eq-pages" data-bnr-eq-pages></div>`;
        host.oninput = event => {
            if (!event.target.matches('[data-bnr-eq-search]')) return;
            search = event.target.value; page = 0; renderResults();
        };
        host.onchange = event => {
            if (event.target.matches('[data-bnr-eq-category]')) {category=event.target.value;page=0;renderResults();}
            if (event.target.matches('[data-bnr-eq-tier]')) {tier=event.target.value;page=0;renderResults();}
            if (event.target.matches('[data-bnr-eq-slot]')) selectedSlots[event.target.dataset.bnrEqSlot]=event.target.value;
        };
        host.onclick = async event => {
            const button = event.target.closest('button');
            if (!button || !host.contains(button) || button.disabled) return;
            if (button.dataset.bnrEqView) {view=button.dataset.bnrEqView;page=0;render();return;}
            if (button.dataset.bnrEqPage) {page+=Number(button.dataset.bnrEqPage);renderResults();return;}
            if (busy || !snapshot.can_manage || snapshot.pending) return;
            let action, payload;
            if (button.dataset.bnrEqBuy) {
                const item = (snapshot.items || []).find(i => i.item_id === button.dataset.bnrEqBuy);
                if (!item?.can_buy) return;
                action='hero.buy_equipment';payload={item_id:item.item_id};
            } else if (button.dataset.bnrEqEquip) {
                const item = (snapshot.inventory || []).find(i => i.owned_id === button.dataset.bnrEqEquip);
                if (!item || item.slot) return;
                action='hero.equip_owned';payload={owned_id:item.owned_id,slot:selectedSlots[item.owned_id] || (item.slots || [])[0]};
            } else if (button.dataset.bnrEqUnequip) {
                action='hero.unequip_owned';payload={slot:button.dataset.bnrEqUnequip};
            } else if (button.dataset.bnrEqDiscard) {
                const item = (snapshot.inventory || []).find(i => i.owned_id === button.dataset.bnrEqDiscard);
                if (!item || !await _bnrConfirmDanger(`Выкинуть «${text(item.name || item.item_id)}»? Предмет исчезнет навсегда${item.slot ? ' и будет снят с героя' : ''}. Динары не вернутся.`, 'Да, выкинуть')) return;
                action='hero.discard_owned';payload={owned_id:item.owned_id};
            } else return;
            const actionGeneration=generation;
            busy=true;render();
            try {
                const result=await ShedLink.buyAction('bannerlord',action,payload,{
                    successMessage:'Заявка отправлена в игру. Инвентарь обновится после выполнения.'});
                if (actionGeneration === generation && result?.success && snapshot) snapshot.pending=true;
            } finally {if (actionGeneration === generation) {busy=false;render();}}
        };
        renderResults();
        if (selection) {
            const input=host.querySelector('[data-bnr-eq-search]');input.focus();input.setSelectionRange(...selection);
        }
        const legacy=document.getElementById('bnr-legacy-equipment');
        if (legacy) legacy.hidden=!!snapshot.ready;
    }

    async function load() {
        const host=root();
        if (!host || fetching) return;
        const token=++requestNumber;
        fetching=true;
        try {
            const response=await fetch(`${API_URL}/api/bannerlord/equipment-shop`,{headers:{'X-Twitch-JWT':authToken || ''}});
            if (!response.ok) throw new Error('equipment_shop_unavailable');
            const data=await response.json();
            if (token !== requestNumber) return;
            if (!data.success) throw new Error(data.message || 'Не удалось загрузить снаряжение');
            snapshot=data;render();
        } catch (error) {
            if (token !== requestNumber) return;
            snapshot=null;
            host.innerHTML='<div class="card-header"><h3>🎒 Снаряжение</h3></div><div class="bnr-eq-empty">Не удалось загрузить магазин. Обнови данные.</div>';
            const legacy=document.getElementById('bnr-legacy-equipment');if (legacy) legacy.hidden=false;
        } finally {if (token === requestNumber) fetching=false;}
    }

    function reset() {
        requestNumber++;generation++;fetching=false;snapshot=null;busy=false;selectedSlots={};
        view='shop';search='';category='';tier='';page=0;
        const host=root();if(host) host.innerHTML='';
    }
    function refreshPresentation() { if(snapshot) render(); }
    return {load,reset,refreshPresentation};
})();

function loadBannerlordEquipmentShop() {return BnrEquipmentShop.load();}
