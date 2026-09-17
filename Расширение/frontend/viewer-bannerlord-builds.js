// New-campaign builds: all choices, effects and prices come from the game/server.
const BnrBuilds = (() => {
    let state=null, known=false, busy=false, loading=false, request=0, generation=0, serverCooldownUntil=0;
    const text=value=>escapeHtml(String(value ?? ''));
    const skills={OneHanded:'Одноручное',TwoHanded:'Двуручное',Polearm:'Древковое',Bow:'Лук',Crossbow:'Арбалет',Throwing:'Метательное',Riding:'Верховая езда',Athletics:'Атлетика'};
    const isNew=()=>known || state?.build?.version===1;
    const manage=()=>!!state?.can_manage && !state?.pending && !state?.build?.in_battle && !busy;
    const cooldown=key=>Math.max(0,..._bannerlordCooldowns.filter(c=>c.power_key===key).map(c=>Number(c.remaining_s)||0));
    const weaponCooldown=()=>Math.max(cooldown('weapon_power'),Math.ceil(Math.max(serverCooldownUntil,Number(state?.build?.weapon_power_cooldown_until)||0)-Date.now()/1000),0);
    const notice=()=> state?.pending || busy ? 'Заявка отправлена — ждём подтверждения из игры.' : state?.message || state?.reason || '';
    const messageHtml=()=>notice()?`<div class="bnr-eq-notice" role="status">${text(notice())}</div>`:'';
    function strength(power) {
        const value=Number(power.value);
        if(!Number.isFinite(value)) return '';
        switch(power.power_key) {
        case 'rage': return `Урон +${Math.round((value-1)*100)}%`;
        case 'cleave': return `${Math.round(value*100)}% урона удара соседним врагам`;
        case 'shield_break_burst': return `${value}% шанс разбить щит при попадании`;
        case 'explosive_arrows': return `До ${value} урона соседним врагам`;
        case 'poison_dot': return `${value} урона в секунду от яда`;
        case 'ironskin_toggle': return `Входящий урон −${value}% со щитом в руке`;
        default: return '';
        }
    }

    function draw(slot,html) {
        if(slot._buildHtml!==html || !slot.innerHTML) {slot.innerHTML=html;slot._buildHtml=html;}
        slot.onclick=click;
    }

    function renderHero(slot=document.getElementById('hero-class-picker-slot')) {
        if(!slot || !isNew()) return false;
        if(!state?.ready || !state?.build) {
            draw(slot,'<div class="bnr-eq-empty">Сборка героя пока недоступна. Обнови данные после подключения игры.</div>');
            return true;
        }
        const build=state.build;
        const disabled=!manage();
        let html=`<div class="bnr-build-heading">Специализация</div><p class="bnr-eq-help">Один пассивный бонус. Оружие и броню выбираешь свободно в «Инвентаре».</p>${messageHtml()}
            <div class="bnr-build-choices">${(build.specializations || []).map(spec=>`<button type="button" class="bnr-build-choice"
                data-bnr-build-spec="${text(spec.id)}" aria-pressed="${build.specialization===spec.id}" ${disabled || build.specialization===spec.id?'disabled':''}>
                <strong>${text(spec.label)}</strong><span>${text(spec.description)}</span></button>`).join('')}</div>`;
        if(!build.starter_claimed) {
            html+=`<div class="bnr-build-heading">Стартовый комплект</div><p class="bnr-eq-help">Один бесплатный набор на героя. Полученные вещи можно заменить через магазин.</p>
                <div class="bnr-build-choices">${(build.starter_kits || []).map(kit=>`<article class="bnr-eq-item">
                    <div class="bnr-eq-item-top"><strong>${text(kit.label)}</strong></div>
                    <div class="bnr-eq-stats">${(kit.items || []).map(item=>text(item.name || item.item_id)).join(' · ')}</div>
                    <button type="button" class="bnr-eq-action secondary" data-bnr-build-starter="${text(kit.id)}" ${disabled || !kit.available?'disabled':''}>Получить бесплатно</button>
                    ${!kit.available && kit.reason?`<div class="bnr-eq-reason">${text(kit.reason)}</div>`:''}</article>`).join('')}</div>`;
        } else html+='<p class="bnr-eq-help">✓ Стартовый набор получен. Все вещи — во вкладке «Инвентарь».</p>';
        draw(slot,html);return true;
    }

    function activateHtml(power,isWeapon) {
        const cd=isWeapon?weaponCooldown():cooldown(power.power_key);
        const active=_bannerlordBuffs.some(b=>b.power_key===power.power_key);
        const balance=typeof _cachedUserPoints==='number'?_cachedUserPoints:Infinity;
        const validPrice=typeof power.price==='number' && power.price>=0;
        const allowed=!!state.ready && !state.pending && !busy && bnrCanUseActivePowers()
            && (!isWeapon || power.available) && cd===0 && !active && validPrice && balance>=power.price;
        const suffix=cd>0?` · ${Math.ceil(cd)} с`:active?' · действует':'';
        return `<button type="button" class="bnr-eq-action" data-bnr-build-activate="${text(power.power_key)}" ${allowed?'':'disabled'}
            title="${text(power.description)}">${text(power.label || power.power_key)} · ${validPrice?power.price.toLocaleString('ru-RU'):'—'} 💎${suffix}</button>`;
    }

    function renderCombat(slot=document.getElementById('bnr-active-powers-slot')) {
        if(!slot || !isNew()) return false;
        const choiceSlot=document.getElementById('bnr-build-choice-slot');
        if(!state?.ready || !state?.build) {
            draw(slot,'<div class="bnr-eq-empty">Ждём актуальные способности героя из игры.</div>');
            if(choiceSlot) draw(choiceSlot,'');
            return true;
        }
        const build=state.build;
        const options=build.power_options || [];
        const current=options.find(p=>p.weapon_type===build.selected_weapon_type && p.power_key===build.selected_power);
        let choicesHtml=`<div class="bnr-build-heading">Оружейная способность</div>
            <p class="bnr-eq-help">Выбери одну способность перед боем. Доступность зависит от надетого оружия, сила — от навыка. Смена выбора не сбрасывает перезарядку.</p>
            ${messageHtml()}<div class="bnr-build-choices">${options.map(power=>`<button type="button" class="bnr-build-choice"
                data-bnr-build-select="${text(power.weapon_type)}" aria-pressed="${build.selected_weapon_type===power.weapon_type}"
                ${!manage() || !power.available || build.selected_weapon_type===power.weapon_type?'disabled':''}>
                <strong>${text(power.label)}</strong><span>${text(power.description)}</span>
                <span>${text(strength(power))}</span>
                <span>Ранг ${text(power.rank)} · ${text(skills[power.skill] || power.skill)} ${text(power.skill_level)}</span>
                ${Number(power.skill_level)<150?`<span>Следующее усиление: навык ${Number(power.skill_level)<50?50:150}</span>`:''}
                ${!power.available && power.reason?`<span class="bnr-eq-reason">${text(power.reason)}</span>`:''}</button>`).join('')}</div>`;
        let activeHtml='<div class="bnr-build-heading">Активки</div>';
        activeHtml+=current?activateHtml(current,true):'<p class="bnr-eq-help">Надень оружие и выбери способность ниже.</p>';
        if(current && !current.available && current.reason) activeHtml+=`<p class="bnr-eq-reason">${text(current.reason)}</p>`;
        activeHtml+=(build.common_powers || []).map(p=>activateHtml(p,false)).join('');
        if(!bnrCanUseActivePowers()) activeHtml+='<p class="bnr-eq-help">Активация доступна, когда твой герой находится на поле боя.</p>';
        draw(slot,activeHtml);
        if(choiceSlot) draw(choiceSlot,choicesHtml);
        return true;
    }

    function render() {renderHero();renderCombat();}

    async function click(event) {
        const button=event.target.closest('button');
        if(!button || button.disabled || busy || !state?.ready) return;
        let type,payload;
        if(button.dataset.bnrBuildSpec) {
            if(!manage()) return;
            type='hero.set_specialization';payload={specialization:button.dataset.bnrBuildSpec};
        } else if(button.dataset.bnrBuildStarter) {
            if(!manage() || state.build.starter_claimed) return;
            type='hero.claim_starter';payload={starter_kit:button.dataset.bnrBuildStarter};
        } else if(button.dataset.bnrBuildSelect) {
            if(!manage()) return;
            type='hero.select_weapon_power';payload={weapon_type:button.dataset.bnrBuildSelect};
        } else if(button.dataset.bnrBuildActivate) {
            type='power.activate';payload={power_key:button.dataset.bnrBuildActivate};
        } else return;
        const epoch=generation;
        busy=true;render();
        try {
            const result=await _bannerlordBuyAction(type,payload);
            if(epoch===generation && state && result?.success) state.pending=true;
        } finally {if(epoch===generation) {busy=false;render();}}
    }

    async function load() {
        if(loading) return;
        loading=true;const id=++request;
        try {
            const response=await fetch(`${API_URL}/api/bannerlord/build`,{headers:{'X-Twitch-JWT':authToken || ''}});
            if(!response.ok) throw Error('build_unavailable');
            const data=await response.json();
            if(id!==request) return;
            if(!data.success) throw Error('build_unavailable');
            state=data;
            known=!!data.enabled || data.build?.version===1;
            serverCooldownUntil=Date.now()/1000+Math.max(0,Number(data.cooldown_remaining_s)||0);
            render();
        } catch(error) {
            if(id!==request) return;
            state=null;render();
        } finally {if(id===request) loading=false;}
    }

    function reset() {
        request++;generation++;state=null;known=false;busy=false;loading=false;serverCooldownUntil=0;
    }
    function detachment() {
        if(!isNew()) return null;
        return {mounted:!!state?.ready && !!state.build.is_mounted,
            ranged:!!state?.ready && (state.build.power_options || []).some(p=>['bow','crossbow'].includes(p.weapon_type) && p.available)};
    }
    return {load,reset,renderHero,renderCombat,detachment};
})();

function loadBannerlordBuild() {return BnrBuilds.load();}
