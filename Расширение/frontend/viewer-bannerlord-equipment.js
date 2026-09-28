// Deterministic Bannerlord equipment catalog. Prices and availability are server data.
const BnrEquipmentShop = (() => {
    const slotNames = {weapon0:'Оружие 1',weapon1:'Оружие 2',weapon2:'Оружие 3',weapon3:'Оружие 4',
        head:'Шлем',body:'Доспех',leg:'Обувь',gloves:'Перчатки',cape:'Плечи',horse:'Конь',horseharness:'Броня коня'};
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
    let purchaseSlots = {};
    let activeOwnedSlot = 'weapon0';
    const pageSize = 20;
    const text = value => escapeHtml(String(value ?? ''));
    const number = value => Number(value || 0).toLocaleString('ru-RU');
    const tierName = value => ['—','I','II','III','IV','V','VI'][Number(value)] || text(value);
    const uiLabel=(key,fallback)=>typeof BnrUiConfig==='undefined'?fallback:BnrUiConfig.label(key,fallback);
    const root = () => document.getElementById('bnr-equipment-shop');
    function purchaseOption(item) {
        const options = item.purchase_options || [];
        return options.find(option => option.slot === purchaseSlots[item.item_id])
            || options.find(option => option.can_buy) || options[0];
    }
    const paymentText = amount => Number(amount) < 0 ? `Получишь ${number(-amount)} 💰` : `К оплате ${number(amount)} 💰`;

    function stats(item) {
        const rawWeight = item.weight ?? item.stats?.weight;
        const gameWeight = Number(rawWeight);
        const weight = rawWeight != null && Number.isFinite(gameWeight) && gameWeight >= 0
            ? `Вес ${gameWeight.toLocaleString('ru-RU',{maximumFractionDigits:2})} кг` : null;
        const other = Object.entries(item.stats || {}).filter(([key,value]) => key !== 'weight' && statNames[key]
            && Number.isFinite(Number(value)) && Number(value) > 0)
            .map(([key,value]) => `${statNames[key]} ${text(value)}`);
        return [weight,...other].filter(Boolean).slice(0,6).join(' · ');
    }

    function numericStats(item) {
        const values = {...(item?.stats || {})};
        if (item?.weight != null) values.weight = item.weight;
        return Object.fromEntries(Object.entries(values).filter(([key,value]) => statNames[key]
            && Number.isFinite(Number(value))));
    }

    function comparedStats(item, equipped) {
        const current = numericStats(equipped);
        return Object.entries(numericStats(item)).filter(([,value]) => Number(value) > 0).slice(0,8).map(([key,value]) => {
            const amount = Number(value);
            const baseline = Number(current[key] || 0);
            const delta = amount - baseline;
            const usefulDelta = key === 'weight' ? -delta : delta;
            const comparison = !equipped || Math.abs(delta) < 0.001 ? ''
                : ` <span class="bnr-eq-delta ${usefulDelta > 0 ? 'better' : 'worse'}">${delta > 0 ? '+' : ''}${delta.toLocaleString('ru-RU',{maximumFractionDigits:2})}</span>`;
            return `<span>${statNames[key]} ${amount.toLocaleString('ru-RU',{maximumFractionDigits:2})}${comparison}</span>`;
        }).join('');
    }

    function itemHtml(item, owned) {
        const id = text(owned ? item.owned_id : item.item_id);
        const tierValue = Number(item.tier);
        const tierKey = Number.isInteger(tierValue) && tierValue >= 1 && tierValue <= 6 ? tierValue : 1;
        const actionBlocked = busy || !snapshot.can_manage || snapshot.pending;
        const blocked = actionBlocked || item.unavailable;
        let controls;
        if (!owned) {
            if (item.purchase_mode === 'equip') {
                const option = purchaseOption(item);
                controls = `<div class="bnr-eq-filters"><select aria-label="Куда надеть ${text(item.name)}" data-bnr-eq-purchase-slot="${id}" ${actionBlocked ? 'disabled' : ''}>
                    ${(item.purchase_options || []).map(o => `<option value="${text(o.slot)}" ${o.slot === option?.slot ? 'selected' : ''}>${text(slotNames[o.slot] || o.slot)} · ${o.replace_owned_id ? `заменить ${text(o.replaced_name)}` : 'пусто'}</option>`).join('')}</select></div>
                    <div class="bnr-eq-meta">Цена ${number(item.price_gold)} 💰${option?.replace_owned_id ? ` · Продажа старой вещи ${number(option.trade_in_gold)} 💰` : ''}</div>
                    <button type="button" class="bnr-eq-action" data-bnr-eq-buy="${id}" ${blocked || !option?.can_buy ? 'disabled' : ''}>Купить и надеть · ${paymentText(option?.net_price_gold)}</button>
                    ${option?.reason ? `<div class="bnr-eq-reason">${text(option.message || option.reason)}</div>` : ''}`;
            } else {
                const disabled = blocked || !item.can_buy;
                controls = `<button type="button" class="bnr-eq-action" data-bnr-eq-buy="${id}" ${disabled ? 'disabled' : ''}>
                Купить · ${number(item.price_gold)} 💰</button>
                ${!item.can_buy && item.reason ? `<div class="bnr-eq-reason">${text(item.message || item.reason)}</div>` : ''}`;
            }
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

    function ownedSlotHtml(slot) {
        const equipped = (snapshot.inventory || []).find(item => item.slot === slot);
        return `<button type="button" class="bnr-eq-slot ${activeOwnedSlot === slot ? 'active' : ''}"
            data-bnr-owned-slot="${text(slot)}" aria-pressed="${activeOwnedSlot === slot}">
            <span>${text(slotNames[slot])}</span><strong>${text(equipped?.name || 'Пусто')}</strong></button>`;
    }

    function renderOwned() {
        const host = root();
        const result = host?.querySelector('[data-bnr-eq-results]');
        if (!host || !result || !snapshot) return;
        if (!snapshot.ready) {
            result.innerHTML = '<div class="bnr-eq-empty">Данных о вещах героя пока нет.</div>';
            host.querySelector('[data-bnr-eq-count]').textContent = 'Нет данных';
            return;
        }
        const inventory = snapshot.inventory || [];
        const party = snapshot.party_inventory;
        const partyAvailable = party?.available === true;
        const equipped = inventory.find(item => item.slot === activeOwnedSlot);
        const query = search.trim().toLocaleLowerCase('ru-RU');
        const available = inventory.filter(item => !item.slot && (item.source !== 'party' || partyAvailable) && (item.slots || []).includes(activeOwnedSlot)
            && (!query || String(item.name || item.item_id || '').toLocaleLowerCase('ru-RU').includes(query)));
        const blocked = busy || !snapshot.can_manage || snapshot.pending || !partyAvailable;
        const current = equipped ? `<article class="bnr-eq-current" data-tier="${Number(equipped.tier) || 1}">
            <div><span>Сейчас надето</span><strong>${text(equipped.name || equipped.item_id)}</strong></div>
            <div class="bnr-eq-stats">${stats(equipped)}</div>
            <div class="bnr-eq-current-actions"><button type="button" class="bnr-eq-action secondary" data-bnr-eq-unequip="${text(activeOwnedSlot)}" ${blocked ? 'disabled' : ''}>Снять</button>
            <button type="button" class="bnr-eq-action discard" data-bnr-eq-discard="${text(equipped.owned_id)}" ${blocked ? 'disabled' : ''}>${text(uiLabel('discard','🗑 Выкинуть'))}</button></div></article>`
            : '<div class="bnr-eq-current empty">Слот свободен</div>';
        const candidateHtml = item => `<article class="bnr-eq-candidate" data-tier="${Number(item.tier) || 1}">
                <div class="bnr-eq-item-top"><strong>${text(item.name || item.item_id)}${item.source === 'party' && Number(item.count) > 1 ? ` ×${number(item.count)}` : ''}</strong><span class="bnr-eq-tier">${tierName(item.tier)}</span></div>
                <div class="bnr-eq-source">${item.source === 'party' ? 'Инвентарь отряда (багаж)' : 'Старое хранилище мода — не багаж отряда'}</div>
                <div class="bnr-eq-compare">${comparedStats(item,equipped)}</div>
                <button type="button" class="bnr-eq-action secondary" data-bnr-eq-equip="${text(item.owned_id)}" ${blocked || item.unavailable ? 'disabled' : ''}>Надеть в «${text(slotNames[activeOwnedSlot])}»</button>
                <button type="button" class="bnr-eq-action discard" data-bnr-eq-discard="${text(item.owned_id)}" ${blocked ? 'disabled' : ''}>${text(uiLabel('discard',item.source === 'party' ? '🗑 Выкинуть одну' : '🗑 Выкинуть вещь'))}</button>
                ${item.unavailable ? '<div class="bnr-eq-reason">Предмет недоступен в текущей сборке игры.</div>' : ''}</article>`;
        const baggage = available.filter(item => item.source === 'party');
        const legacy = available.filter(item => item.source !== 'party');
        result.innerHTML = `<h4>Надето на герое</h4><div class="bnr-eq-slots">${Object.keys(slotNames).map(ownedSlotHtml).join('')}</div>${current}
            <h4>Багаж отряда${partyAvailable && party.party_name ? ` · ${text(party.party_name)}` : ''}</h4>
            ${!partyAvailable ? `<div class="bnr-eq-notice">${text(party?.message || 'Доступ к багажу ещё не подтверждён игрой.')}</div>` : ''}
            <div class="bnr-eq-slot-title"><strong>${text(slotNames[activeOwnedSlot])}</strong>${partyAvailable ? `<span>${baggage.reduce((sum,item) => sum + Number(item.count || 1),0)} доступно</span>` : ''}</div>
            <div class="bnr-eq-candidates">${baggage.map(candidateHtml).join('')
                || (partyAvailable ? `<div class="bnr-eq-empty">Для слота «${text(slotNames[activeOwnedSlot])}» подходящих вещей нет.</div>` : '')}</div>
            ${legacy.length ? `<h4>Старое хранилище мода</h4><div class="bnr-eq-candidates">${legacy.map(candidateHtml).join('')}</div>` : ''}`;
        host.querySelector('[data-bnr-eq-count]').textContent = `${inventory.length} вещей`;
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
                <button type="button" data-bnr-eq-view="owned" aria-pressed="${view === 'owned'}">Инвентарь${snapshot.ready ? '' : ' · нет данных'}</button></div>
            <p class="bnr-eq-help">${view === 'shop' ? (snapshot.party_inventory?.available ? 'Покупка за динары героя. Вещь попадёт в инвентарь его отряда.' : 'Без багажа можно купить вещь сразу на героя. При замене старая вещь продаётся за указанную сумму. Покупка с надеванием доступна вне боя и сцен.') : 'Надетое снаряжение героя и доступные вещи для замены из общего багажа его отряда. Еда и торговые товары здесь не показаны.'}</p>
            ${snapshot.pending || busy ? '<div class="bnr-eq-notice" role="status">Заявка отправлена — ждём результат из игры.</div>' : ''}
            ${snapshot.reason ? `<div class="bnr-eq-notice" role="status">${text(snapshot.message || snapshot.reason)}</div>` : ''}
            <div class="bnr-eq-filters"><input type="search" data-bnr-eq-search aria-label="Найти вещь" placeholder="Найти вещь…" value="${text(search)}">
                ${view === 'owned' ? '' : `
                <div><select data-bnr-eq-category aria-label="Категория"><option value="">Все категории</option>
                    ${availableCategories.map(c => `<option value="${text(c)}" ${category === c ? 'selected' : ''}>${text(categories[c] || c)}</option>`).join('')}</select>
                <select data-bnr-eq-tier aria-label="Тир"><option value="">Все тиры</option>${(snapshot.tiers || []).map(t => `<option value="${t.tier}" ${tier === String(t.tier) ? 'selected' : ''}>Тир ${tierName(t.tier)}</option>`).join('')}</select></div>`}</div>
            <div class="bnr-eq-results" data-bnr-eq-results></div><div class="bnr-eq-pages" data-bnr-eq-pages></div>`;
        host.oninput = event => {
            if (!event.target.matches('[data-bnr-eq-search]')) return;
            search = event.target.value; page = 0; view === 'owned' ? renderOwned() : renderResults();
        };
        host.onchange = event => {
            if (event.target.matches('[data-bnr-eq-category]')) {category=event.target.value;page=0;renderResults();}
            if (event.target.matches('[data-bnr-eq-tier]')) {tier=event.target.value;page=0;renderResults();}
            if (event.target.matches('[data-bnr-eq-slot]')) selectedSlots[event.target.dataset.bnrEqSlot]=event.target.value;
            if (event.target.matches('[data-bnr-eq-purchase-slot]')) {purchaseSlots[event.target.dataset.bnrEqPurchaseSlot]=event.target.value;renderResults();}
        };
        host.onclick = async event => {
            const button = event.target.closest('button');
            if (!button || !host.contains(button) || button.disabled) return;
            if (button.dataset.bnrEqView) {view=button.dataset.bnrEqView;page=0;render();return;}
            if (button.dataset.bnrOwnedSlot) {activeOwnedSlot=button.dataset.bnrOwnedSlot;search='';render();return;}
            if (button.dataset.bnrEqPage) {page+=Number(button.dataset.bnrEqPage);renderResults();return;}
            if (busy || !snapshot.can_manage || snapshot.pending) return;
            let action, payload;
            if (button.dataset.bnrEqBuy) {
                const item = (snapshot.items || []).find(i => i.item_id === button.dataset.bnrEqBuy);
                if (!item?.can_buy) return;
                action='hero.buy_equipment';payload={item_id:item.item_id};
                if (item.purchase_mode === 'equip') {
                    const option = purchaseOption(item);
                    if (!option?.can_buy) return;
                    payload={...payload,equip_now:true,slot:option.slot,replace_owned_id:option.replace_owned_id,
                        replace_item_id:option.replace_item_id,replace_modifier_id:option.replace_modifier_id,
                        expected_price_gold:item.price_gold,expected_trade_in_gold:option.trade_in_gold};
                    const confirmationGeneration = generation;
                    const confirmed = await _bnrConfirmDanger(`Купить и надеть «${text(item.name || item.item_id)}» в «${text(slotNames[option.slot] || option.slot)}»?${option.replace_owned_id ? ` «${text(option.replaced_name)}» будет продан за ${number(option.trade_in_gold)} 💰 и исчезнет из снаряжения.` : ''} ${paymentText(option.net_price_gold)}.`);
                    if (!confirmed || confirmationGeneration !== generation || busy || !snapshot?.can_manage || snapshot.pending) return;
                }
            } else if (button.dataset.bnrEqEquip) {
                const item = (snapshot.inventory || []).find(i => i.owned_id === button.dataset.bnrEqEquip);
                if (!item || item.slot) return;
                const slot = view === 'owned' ? activeOwnedSlot : selectedSlots[item.owned_id] || (item.slots || [])[0];
                if (!(item.slots || []).includes(slot)) return;
                action='hero.equip_owned';payload={owned_id:item.owned_id,slot};
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
        view === 'owned' ? renderOwned() : renderResults();
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
        requestNumber++;generation++;fetching=false;snapshot=null;busy=false;selectedSlots={};purchaseSlots={};
        view='shop';search='';category='';tier='';page=0;activeOwnedSlot='weapon0';
        const host=root();if(host) host.innerHTML='';
    }
    function refreshPresentation() { if(snapshot) render(); }
    return {load,reset,refreshPresentation};
})();

function loadBannerlordEquipmentShop() {return BnrEquipmentShop.load();}
