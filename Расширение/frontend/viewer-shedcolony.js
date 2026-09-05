/* viewer-shedcolony.js — per-game viewer UI for the ShedColony module (Minecraft / MineColonies).
 *
 * Plain <script>, loaded after viewer.js, using its globals: API_URL, authToken, safeInterval,
 * showNotification, escapeHtml, _cachedUserPoints. Renders into #shedcolony-content. viewer.js'
 * switchIntegrationModule() calls window._startShedcolonyPolling / _stopShedcolonyPolling.
 *
 * Mirrors the proven bannerlord buy pattern: POST /api/shedcolony/action with X-Twitch-JWT.
 * Every action is PAID + DEFERRED (enqueued → the mod polls + executes in-game a moment later),
 * so each success shows an action-specific "заявка принята, выполнится в игре" toast — the viewer
 * must not re-click thinking nothing happened (bugs #16/#17 lesson).
 *
 * IA (Фаза 0, 2026-07-03): 3 вкладки (👤 Колонист / ⚔️ Экипировка / 🏛 Колония) + аккордеон
 * внутри — паттерн BLink. Активная вкладка (_activeTab) и открытые группы (_openGroups)
 * ПЕРСИСТЯТ между перерисовками (иначе тик HP каждые 5с сбрасывал бы выбор). Действия не менялись.
 */
(function () {
    'use strict';

    // Цены ниже — ЗАПАСНЫЕ. Настоящие приезжают с бэка (/api/shedcolony/config →
    // action_prices, тот же словарь _ACTION_PRICES, по которому он списывает) и
    // перетирают эту таблицу при открытии вкладки. Держать копии было нельзя:
    // расширение замерзает на CDN Twitch до следующего ревью, а цену меняют на
    // сервере за минуты — до 2026-09-05 тут лежало 28 чисел, которые молча
    // разъехались бы с первым же ребалансом.
    var SC = {
        spawn:   { type: 'colonist.spawn',            price: 1000 },
        job:     { type: 'colonist.assign_job',       price: 300 },
        home:    { type: 'colonist.assign_home',      price: 200 },
        xp:      { type: 'colonist.add_xp',           price: 400 },
        fulfill: { type: 'colonist.fulfill_request',  price: 100 },
        feed:    { type: 'colonist.feed',             price: 75 },
        cure:    { type: 'colonist.cure_disease',     price: 100 },
        heal:    { type: 'colonist.heal',             price: 100 },
        mourn:   { type: 'colonist.clear_mourn',      price: 50 },
        give_item:  { type: 'colonist.give_item',     price: 200 },
        set_gender: { type: 'colonist.set_gender',    price: 200 },
        teleport:   { type: 'colonist.teleport',      price: 150 },
        equip_leather: { type: 'colonist.equip_leather', price: 500 },
        equip_iron:    { type: 'colonist.equip_iron',    price: 1500 },
        equip_diamond: { type: 'colonist.equip_diamond', price: 3000 },
        festival:      { type: 'colony.festival',       price: 3000 },
        spawn_visitor: { type: 'colony.spawn_visitor',  price: 2000 },
        quest_unlock:  { type: 'colony.quest_unlock',   price: 2000 },
        spy_boost:     { type: 'colony.spy_boost',      price: 1500 },
        happiness:     { type: 'colonist.happiness_boost', price: 400 },
        supply:        { type: 'colony.supply',           price: 1000 },
        // Phase A — развитие колонии + склад (цены-копии; истина на бэке _ACTION_PRICES)
        min_stock:      { type: 'colony.set_minimum_stock', price: 75000 },
        clear_backlog:  { type: 'colony.clear_backlog',     price: 50000 },
        start_research: { type: 'colony.start_research',     price: 75000 },
        finish_research:{ type: 'colony.finish_research',    price: 37500 },
        // Phase C — гир-кластер (свой колонист)
        equip_netherite:  { type: 'colonist.equip_netherite',   price: 4000 },
        equip_weapon:     { type: 'colonist.equip_weapon',      price: 2500 },
        give_shield:      { type: 'colonist.give_shield',       price: 1000 },
        give_tools:       { type: 'colonist.give_tools',        price: 2500 },
        set_guard_task:   { type: 'colonist.set_guard_task',    price: 500 },
        set_guard_retreat:{ type: 'colonist.set_guard_retreat', price: 300 },
        // Phase D — дёшево-вовлекающее
        auto_work:        { type: 'colonist.auto_work',         price: 1000 },
        // Phase B — флагман
        upgrade_building: { type: 'colony.upgrade_building',    price: 50000 },
    };

    // colonist.auto_work — job → what its automation does (only these 4 jobs have it; button hidden otherwise).
    var SC_AUTO_LABELS = {
        farmer: 'Авто-удобрение поля', lumberjack: 'Авто-пересадка деревьев',
        shepherd: 'Авто-стрижка овец', composter: 'Авто-компост (земля)',
    };

    // set_minimum_stock item picker — MUST stay a subset of _MIN_STOCK_WHITELIST in routes/shedcolony.py.
    var SC_MIN_STOCK_ITEMS = [
        ['minecraft:bread', 'Хлеб'], ['minecraft:oak_planks', 'Доски'], ['minecraft:oak_log', 'Брёвна'],
        ['minecraft:cobblestone', 'Булыжник'], ['minecraft:stone', 'Камень'], ['minecraft:coal', 'Уголь'],
        ['minecraft:charcoal', 'Древ. уголь'], ['minecraft:torch', 'Факелы'], ['minecraft:stick', 'Палки'],
        ['minecraft:wheat', 'Пшеница'], ['minecraft:carrot', 'Морковь'], ['minecraft:potato', 'Картофель'],
        ['minecraft:apple', 'Яблоки'],
    ];
    // set_minimum_stock quantity picker — in STACKS (1..16; mirrors _MIN_STOCK_QTY_MAX + mod clamp).
    var SC_MIN_STOCK_QTYS = [1, 2, 4, 8, 16];

    // RU labels for the common building types (backlog + upgrade pickers; fallback = raw registry path).
    // NB: cook = Ресторан (столовая, где едят), kitchen = Кухня (готовит) — это РАЗНЫЕ здания.
    var SC_BUILDING_LABELS = {
        builder: 'Строитель', baker: 'Пекарня', cook: 'Ресторан', kitchen: 'Кухня', farmer: 'Ферма',
        residence: 'Жилой дом', fisherman: 'Рыбак', lumberjack: 'Лесопилка', miner: 'Шахта',
        guardtower: 'Башня стражи', barrackstower: 'Башня казарм',
        barracks: 'Казармы', warehouse: 'Склад', townhall: 'Ратуша', deliveryman: 'Курьерская',
        smeltery: 'Плавильня', blacksmith: 'Кузница', stonemason: 'Каменотёс', sawmill: 'Лесопилка',
        farm: 'Ферма', chickenherder: 'Птичник', cowboy: 'Скотник', shepherd: 'Пастух',
        swineherder: 'Свинарник', composter: 'Компост', florist: 'Цветовод', university: 'Университет',
        library: 'Библиотека', hospital: 'Госпиталь', tavern: 'Таверна', mysticalsite: 'Алтарь',
        school: 'Школа', archery: 'Стрельбище', combatacademy: 'Академия боя', graveyard: 'Кладбище',
        plantation: 'Плантация', dyer: 'Красильня', fletcher: 'Мастер стрел', glassblower: 'Стеклодув',
        enchanter: 'Чародейская', apiary: 'Пасека', mechanic: 'Механик', concretemixer: 'Бетонщик',
        crusher: 'Дробилка', sifter: 'Просеиватель', alchemist: 'Алхимик', netherworker: 'Незер-бригада',
    };

    // colony.supply dropdown — MUST stay a subset of _SUPPLY_WHITELIST in routes/shedcolony.py.
    var SC_SUPPLY_ITEMS = [
        ['minecraft:oak_log', 'Брёвна'], ['minecraft:oak_planks', 'Доски'],
        ['minecraft:cobblestone', 'Булыжник'], ['minecraft:stone', 'Камень'],
        ['minecraft:dirt', 'Земля'], ['minecraft:sand', 'Песок'], ['minecraft:gravel', 'Гравий'],
        ['minecraft:torch', 'Факелы'], ['minecraft:bread', 'Хлеб'], ['minecraft:wheat', 'Пшеница'],
        ['minecraft:carrot', 'Морковь'], ['minecraft:potato', 'Картофель'],
    ];

    // give_item dropdown — MUST stay a subset of _GIVE_ITEM_WHITELIST in routes/shedcolony.py.
    var SC_GIVE_ITEMS = [
        ['minecraft:bread', 'Хлеб'], ['minecraft:cooked_beef', 'Стейк'],
        ['minecraft:cooked_chicken', 'Жареная курица'], ['minecraft:cooked_porkchop', 'Свинина'],
        ['minecraft:apple', 'Яблоко'], ['minecraft:golden_carrot', 'Золотая морковь'],
        ['minecraft:golden_apple', 'Золотое яблоко'], ['minecraft:cake', 'Торт'],
        ['minecraft:pumpkin_pie', 'Тыквенный пирог'], ['minecraft:cookie', 'Печенье'],
    ];

    // Action-specific deferred-success toasts (paid + async → "это заявка, исход в игре").
    var SC_SUCCESS_MSG = {
        'colonist.spawn':            '✨ Заявка принята! Твой колонист появится в колонии через пару секунд.',
        'colonist.assign_job':       '🔨 Заявка на работу принята — назначим в игре через пару секунд.',
        'colonist.assign_home':      '🏠 Заявка на дом принята — поселим через пару секунд.',
        'colonist.add_xp':           '📈 Заявка на прокачку принята — скилл вырастет через пару секунд.',
        'colonist.fulfill_request':  '📦 Заявка принята — просьбу колониста выполним через пару секунд.',
        'colonist.feed':             '🍖 Заявка принята — колониста покормят через пару секунд.',
        'colonist.cure_disease':     '💊 Заявка принята — вылечим через пару секунд.',
        'colonist.heal':             '❤ Заявка принята — восстановим здоровье через пару секунд.',
        'colonist.clear_mourn':      '🕯 Заявка принята — снимем траур через пару секунд.',
        'colonist.give_item':        '🎁 Заявка принята — предмет передадим колонисту через пару секунд.',
        'colonist.set_gender':       '🔄 Заявка принята — сменим пол через пару секунд.',
        'colonist.teleport':         '✨ Заявка принята — призовём в центр колонии через пару секунд.',
        'colony.festival':           '🎉 Заявка принята — фестиваль поднимет настроение колонии через пару секунд.',
        'colony.spawn_visitor':      '🚶 Заявка принята — гость появится в таверне через пару секунд.',
        'colony.quest_unlock':       '📜 Заявка принята — новый квест откроется в колонии через пару секунд.',
        'colony.spy_boost':          '🕵 Заявка принята — шпионы включатся (работает только во время рейда).',
        'colonist.equip_leather':    '🛡 Заявка принята — наденем кожаную броню через пару секунд.',
        'colonist.equip_iron':       '🛡 Заявка принята — наденем железную броню через пару секунд.',
        'colonist.equip_diamond':    '💎 Заявка принята — наденем алмазную броню через пару секунд.',
        'colonist.happiness_boost':  '😊 Заявка принята — поднимем настроение колонисту через пару секунд.',
        'colony.supply':             '📦 Заявка принята — ресурсы появятся на складе колонии через пару секунд.',
        'colony.set_minimum_stock':  '📦 Заявка принята — неснижаемый запас закрепим на складе через пару секунд.',
        'colony.clear_backlog':      '🚚 Заявка принята — очередь заказов здания разгребём через пару секунд.',
        'colony.start_research':     '🔬 Заявка принята — исследование профинансировано, университет им займётся.',
        'colony.finish_research':    '🔬 Заявка принята — исследование завершится мгновенно (эффект применится).',
        'colonist.equip_netherite':  '🖤 Заявка принята — наденем незеритовую броню через пару секунд.',
        'colonist.equip_weapon':     '⚔ Заявка принята — вооружим гвардейца (лучшим по уровню башни) через пару секунд.',
        'colonist.give_shield':      '🛡 Заявка принята — выдадим щит через пару секунд.',
        'colonist.give_tools':       '⛏ Заявка принята — выдадим набор инструментов через пару секунд.',
        'colonist.set_guard_task':   '🛡 Заявка принята — сменим боевую задачу гвардейца через пару секунд.',
        'colonist.set_guard_retreat':'🛡 Заявка принята — настроим отступление через пару секунд.',
        'colonist.auto_work':        '⚙ Заявка принята — включим авто-режим на работе через пару секунд.',
        'colony.upgrade_building':   '🏗 Заявка принята — строитель начнёт улучшение здания (не мгновенно, повторно жать не нужно).',
    };

    // 11 MineColonies skills (value = enum name the mod expects; label = RU).
    var SC_SKILLS = [
        ['Athletics', 'Атлетика'], ['Dexterity', 'Ловкость'], ['Strength', 'Сила'],
        ['Agility', 'Проворство'], ['Stamina', 'Выносливость'], ['Mana', 'Мана'],
        ['Adaptability', 'Адаптивность'], ['Focus', 'Фокус'], ['Creativity', 'Креативность'],
        ['Knowledge', 'Знания'], ['Intelligence', 'Интеллект'],
    ];

    // RU labels for the common job keys (fallback = the raw key).
    var SC_JOB_LABELS = {
        builder: 'Строитель', cook: 'Повар', knight: 'Рыцарь', farmer: 'Фермер',
        fisherman: 'Рыбак', lumberjack: 'Лесоруб', miner: 'Шахтёр', guard: 'Стражник',
        baker: 'Пекарь', smelter: 'Плавильщик', blacksmith: 'Кузнец', deliveryman: 'Курьер',
        forester: 'Лесник', shepherd: 'Пастух', cowboy: 'Скотовод', swineherd: 'Свинопас',
        chickenherd: 'Птичник', composter: 'Компостёр', florist: 'Флорист', healer: 'Лекарь',
        teacher: 'Учитель', archer: 'Лучник', enchanter: 'Чародей', alchemist: 'Алхимик',
        // добавлено 2026-07-13 (баг #30 «роли на инглише») — недостающие профессии MineColonies
        ranger: 'Лучник', druid: 'Друид', dyer: 'Красильщик', fletcher: 'Лучных дел мастер',
        mechanic: 'Механик', planter: 'Плантатор', sawmill: 'Пилорама', stonemason: 'Каменщик',
        concretemixer: 'Бетонщик', glassblower: 'Стеклодув', netherworker: 'Незер-рабочий',
        undertaker: 'Гробовщик', quarrier: 'Карьерщик', beekeeper: 'Пчеловод', sifter: 'Просеиватель',
        crusher: 'Дробильщик', student: 'Ученик', pupil: 'Ученик', researcher: 'Исследователь',
        swineherder: 'Свинопас', chickenherder: 'Птичник', rabbitherder: 'Кроликовод',
        cowboyherder: 'Скотовод', stonesmeltery: 'Обжигальщик', cookassistant: 'Помощник повара',
    };

    var _pollId = null;
    var _state = { colonist: null, capacity: { jobs: [], free_beds: null }, targets: null, stale: false };
    var _lastSig = '';
    var _stylesInjected = false;
    var _activeTab = 'me';                                     // persisted across re-renders
    var _openGroups = { 'g-care': true, 'g-gear': true, 'g-events': true };  // open accordion ids (first per pane)
    var _selVals = {};                                         // last-picked <select> value by id (survives re-render)

    function _jwtHeaders(withBody) {
        var h = { 'X-Twitch-JWT': (typeof authToken !== 'undefined' ? authToken : '') || '' };
        if (withBody) { h['Content-Type'] = 'application/json'; }
        return h;
    }

    function _jobLabel(key) {
        if (!key) { return key; }
        var base = key.indexOf(':') >= 0 ? key.split(':').pop() : key;
        return SC_JOB_LABELS[base] || base;
    }

    // Building registry path (e.g. "minecolonies:builder" or "builder") → RU label (fallback = path).
    function _buildingLabel(type) {
        if (!type) { return type; }
        var base = type.indexOf(':') >= 0 ? type.split(':').pop() : type;
        return SC_BUILDING_LABELS[base] || base;
    }

    function _num(v, dflt) {
        return (typeof v === 'number' && !isNaN(v)) ? v : dflt;
    }

    // MineColonies happiness is ~0–2 (1.0 = normal) → mood emoji.
    // MineColonies happiness is a 0–10 scale (10 = max). The old thresholds assumed 0–2, so every
    // real value (7–10) fell into 😄 and the emoji never changed — bug #28 «настроение не меняется».
    function _moodEmoji(h) {
        if (h == null) { return '🙂'; }
        if (h >= 8) { return '😄'; }
        if (h >= 6) { return '🙂'; }
        if (h >= 4) { return '😐'; }
        if (h >= 2) { return '😟'; }
        return '😣';
    }

    function _bar(emoji, label, val, max, color) {
        var pct = max > 0 ? Math.max(0, Math.min(100, Math.round(val / max * 100))) : 0;
        return '<div class="sc-stat"><div class="sc-stat-top"><span>' + emoji + ' ' + escapeHtml(label)
            + '</span><span>' + Math.round(val) + ' / ' + Math.round(max) + '</span></div>'
            + '<div class="sc-bar"><div class="sc-bar-fill" style="width:' + pct + '%;background:' + color + ';"></div></div></div>';
    }

    function _statusFlags(st) {
        var f = [];
        if (st.sick) { f.push('🤒 болеет'); }
        if (st.hurt) { f.push('🩹 ранен'); }
        if (st.asleep) { f.push('😴 спит'); }
        if (st.paused) { f.push('⏸ на паузе'); }
        if (st.idle) { f.push('💤 простаивает'); }
        return f;
    }

    // Accordion group wrapper — persists open/closed via _openGroups.
    function _grp(id, title, body) {
        var open = _openGroups[id] ? ' open' : '';
        return '<details class="sc-acc" data-grp="' + id + '"' + open + '>'
            + '<summary class="sc-acc-h">' + title + '</summary>'
            + '<div class="sc-acc-body">' + body + '</div></details>';
    }

    // Show the active pane + highlight its tab (called after every render; also on tab click).
    function _applyTab() {
        var root = document.getElementById('shedcolony-content');
        if (!root) { return; }
        var panes = root.querySelectorAll('.sc-pane');
        for (var i = 0; i < panes.length; i++) {
            panes[i].style.display = (panes[i].getAttribute('data-pane') === _activeTab) ? 'block' : 'none';
        }
        var tabs = root.querySelectorAll('.sc-tab');
        for (var j = 0; j < tabs.length; j++) {
            if (tabs[j].getAttribute('data-tab') === _activeTab) { tabs[j].classList.add('on'); }
            else { tabs[j].classList.remove('on'); }
        }
    }

    function _injectStyles() {
        if (_stylesInjected) { return; }
        _stylesInjected = true;
        var css = ''
            + '#shedcolony-content .sc-header{font-size:15px;font-weight:700;margin:6px 0 10px;}'
            + '#shedcolony-content .sc-balance{font-size:12px;opacity:.8;margin-bottom:10px;}'
            + '#shedcolony-content .sc-card{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.10);'
            + 'border-radius:10px;padding:12px;margin-bottom:10px;}'
            + '#shedcolony-content .sc-colonist-name{font-size:15px;font-weight:700;margin-bottom:4px;}'
            + '#shedcolony-content .sc-colonist-job,#shedcolony-content .sc-colonist-status{font-size:12px;opacity:.85;}'
            + '#shedcolony-content .sc-section-title{font-size:13px;font-weight:600;margin-bottom:8px;}'
            + '#shedcolony-content .sc-muted{font-size:12px;opacity:.65;margin:0;}'
            + '#shedcolony-content .sc-select{width:100%;padding:7px;margin-bottom:8px;border-radius:8px;'
            + 'background:rgba(0,0,0,.25);color:inherit;border:1px solid rgba(255,255,255,.15);}'
            + '#shedcolony-content .sc-btn{width:100%;padding:9px 12px;border:none;border-radius:8px;cursor:pointer;'
            + 'font-weight:600;font-size:13px;background:linear-gradient(135deg,#5b8c3a,#3f6b27);color:#fff;}'
            + '#shedcolony-content .sc-btn:hover{filter:brightness(1.1);}'
            + '#shedcolony-content .sc-btn:disabled{opacity:.45;cursor:not-allowed;filter:none;}'
            + '#shedcolony-content .sc-mood{font-size:13px;margin:6px 0 2px;}'
            + '#shedcolony-content .sc-flags{font-size:12px;opacity:.85;margin:4px 0;}'
            + '#shedcolony-content .sc-stat{margin-top:8px;}'
            + '#shedcolony-content .sc-stat-top{display:flex;justify-content:space-between;font-size:11px;opacity:.8;margin-bottom:3px;}'
            + '#shedcolony-content .sc-bar{height:8px;border-radius:5px;background:rgba(0,0,0,.30);overflow:hidden;}'
            + '#shedcolony-content .sc-bar-fill{height:100%;border-radius:5px;transition:width .3s;}'
            + '#shedcolony-content .sc-skills{display:grid;grid-template-columns:1fr 1fr;gap:4px 12px;}'
            + '#shedcolony-content .sc-skill{display:flex;justify-content:space-between;font-size:12px;'
            + 'padding:2px 0;border-bottom:1px solid rgba(255,255,255,.06);}'
            + '#shedcolony-content .sc-skill b{font-weight:700;}'
            + '#shedcolony-content .sc-input{width:100%;padding:7px;margin-bottom:8px;border-radius:8px;box-sizing:border-box;'
            + 'background:rgba(0,0,0,.25);color:inherit;border:1px solid rgba(255,255,255,.15);}'
            + '#shedcolony-content .sc-care-row{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px;}'
            + '#shedcolony-content .sc-btn-sm{width:auto;padding:7px 8px;font-size:12px;}'
            + '#shedcolony-content .sc-reqs{font-size:12px;opacity:.9;margin-bottom:8px;}'
            + '#shedcolony-content .sc-reqs ul{margin:4px 0 0;padding-left:18px;}'
            + '#shedcolony-content .sc-btn-req{margin-bottom:6px;text-align:left;}'
            + '#shedcolony-content .sc-req-blocked{font-size:12px;opacity:.55;margin:4px 0;}'
            + '#shedcolony-content .sc-tabs{display:flex;gap:4px;margin:2px 0 10px;}'
            + '#shedcolony-content .sc-tab{flex:1;padding:8px 4px;font-size:12px;font-weight:600;cursor:pointer;color:inherit;'
            + 'background:rgba(255,255,255,.04);border:none;border-bottom:2px solid transparent;opacity:.55;border-radius:6px 6px 0 0;}'
            + '#shedcolony-content .sc-tab.on{opacity:1;border-bottom-color:#7bbf4a;background:rgba(123,191,74,.10);}'
            + '#shedcolony-content .sc-pane{display:none;}'
            + '#shedcolony-content .sc-acc{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);'
            + 'border-radius:10px;margin-bottom:8px;overflow:hidden;}'
            + '#shedcolony-content .sc-acc-h{font-size:13px;font-weight:600;padding:10px 12px;cursor:pointer;list-style:none;}'
            + '#shedcolony-content .sc-acc-h::-webkit-details-marker{display:none;}'
            + '#shedcolony-content .sc-acc[open] .sc-acc-h{border-bottom:1px solid rgba(255,255,255,.08);}'
            + '#shedcolony-content .sc-acc-body{padding:10px 12px 12px;}'
            + '#shedcolony-content .sc-offline{background:rgba(224,85,107,.15);border:1px solid rgba(224,85,107,.4);'
            + 'border-radius:8px;padding:8px 10px;font-size:12px;margin-bottom:10px;}';
        var s = document.createElement('style');
        s.id = 'sc-styles';
        s.textContent = css;
        document.head.appendChild(s);
    }

    // ── buy: общий платный путь ядра (ShedLink.buyAction, viewer-actions.js) ──
    // 2026-08-19: раньше здесь была своя копия. Она не перечитывала баланс после
    // успеха, поэтому панель показывала непотраченные крустики до минуты и
    // дольше — зритель жал покупку второй раз. Переезд на общий путь чинит это
    // и заодно даёт кулдаун/role-gate, если бэк начнёт их присылать.
    // Отложенный характер действий (заявка исполнится в игре) по-прежнему
    // объясняется своим текстом тоста — SC_SUCCESS_MSG (баги #16/#17).
    function _buy(actionType, data) {
        return ShedLink.buyAction('shedcolony', actionType, data, {
            successMessage:      SC_SUCCESS_MSG[actionType],
            failMessage:         'Не получилось',
            successToastMs:      6000,
            errorToastMs:        4500,
            networkErrorMessage: 'Сеть недоступна — попробуй ещё раз',
            networkToastMs:      4000,
        });
    }

    // ── render ────────────────────────────────────────────────────────────────
    function _render() {
        var root = document.getElementById('shedcolony-content');
        if (!root) { return; }
        _injectStyles();
        var c = _state.colonist;
        var cap = _state.capacity || { jobs: [], free_beds: null };
        var bal = (typeof _cachedUserPoints !== 'undefined' && _cachedUserPoints != null) ? _cachedUserPoints : null;

        var html = '<div class="sc-header">🏰 Колония стримера</div>';
        if (bal != null) { html += '<div class="sc-balance">Баланс: ' + bal + ' 💎</div>'; }
        if (_state.stale) {
            html += '<div class="sc-offline">⚠ Сервер Minecraft сейчас офлайн — покупки временно недоступны, загляни позже.</div>';
        }

        if (!c || !c.linked) {
            html += '<div class="sc-card">'
                + '<p class="sc-muted" style="margin-bottom:10px;">У тебя ещё нет колониста в этой колонии. '
                + 'Создай своего — он появится у стримера в игре.</p>'
                + '<button class="sc-btn" data-sc="spawn">Создать колониста — ' + SC.spawn.price + ' 💎</button>'
                + '</div>';
            root.innerHTML = html;
            _bind(root);
            return;
        }

        var st = c.state || {};
        var job = (st.job != null) ? st.job : c.job;
        var who = escapeHtml(c.name || 'Мой колонист')
            + (st.child ? ' 👶' : '')
            + (st.female === true ? ' ♀' : (st.female === false ? ' ♂' : ''));

        // ── colonist card (always visible above the tabs) ──
        html += '<div class="sc-card">';
        html += '<div class="sc-colonist-name">👤 ' + who + '</div>';
        html += '<div class="sc-colonist-job">Работа: ' + escapeHtml(job ? _jobLabel(job) : 'без работы')
            + ' · Дом: ' + (st.has_home ? 'есть' : 'нет') + '</div>';
        if (st.happiness != null) {
            html += '<div class="sc-mood">' + _moodEmoji(st.happiness)
                + ' Настроение: ' + Number(st.happiness).toFixed(2) + '</div>';
        }
        var flags = _statusFlags(st);
        if (flags.length) { html += '<div class="sc-flags">' + flags.map(escapeHtml).join(' · ') + '</div>'; }
        if (st.hp != null || c.hp != null) {
            html += _bar('❤️', 'Здоровье', _num(st.hp, _num(c.hp, 0)), _num(st.max_hp, 20), '#e0556b');
        }
        if (st.saturation != null) {
            html += _bar('🍖', 'Сытость', st.saturation, 60, '#d8923a');
        }
        html += '</div>';

        // ── gating data ──
        var sk = (st.skills && Object.keys(st.skills).length) ? st.skills : (c.skills || {});
        var freeJobs = (cap.jobs || []).filter(function (j) { return j.free > 0; });
        var beds = cap.free_beds;
        var hasReqInfo = st && Array.isArray(st.requests);
        var reqs = hasReqInfo ? st.requests : [];
        // Phase A picker targets (from the colony.targets snapshot the mod pushes)
        var tg = _state.targets || {};
        var researchAvail = (tg.researches || []).filter(function (r) { return r.state === 'available'; });
        var researchProg = (tg.researches || []).filter(function (r) { return r.state === 'in_progress'; });
        var backlogBuildings = tg.buildings || [];
        var warehouseOk = !!(tg.min_stock && tg.min_stock.warehouse);
        var canBuild = !!tg.can_build;                                   // Phase B: streamer online?
        var upgradeBuildings = (tg.upgradable || []).filter(function (b) { return !b.in_progress; });
        // Phase C gear gating (advisory — mod is authoritative). job key drives guard/worker gates.
        var jobBase = (job || '').indexOf(':') >= 0 ? (job || '').split(':').pop() : (job || '');
        var isGuard = ['knight', 'ranger', 'archer', 'druid'].indexOf(jobBase) >= 0;
        var hasJob = !!jobBase;
        var autoLabel = SC_AUTO_LABELS[jobBase];   // Phase D: only farmer/lumberjack/shepherd/composter

        // ── tab bar ──
        html += '<div class="sc-tabs">'
            + '<button class="sc-tab" data-tab="me">👤 Колонист</button>'
            + '<button class="sc-tab" data-tab="gear">⚔️ Экипировка</button>'
            + '<button class="sc-tab" data-tab="colony">🏛 Колония</button>'
            + '</div>';

        // ══════════ PANE: Колонист ══════════
        html += '<div class="sc-pane" data-pane="me">';

        // ❤️ Забота — кнопки серятся, когда действию нечего менять (бэк на таких путях рефандит;
        // серая кнопка честнее, чем «купил → вернули»). Данные уже в state: saturation/sick/hp.
        var satFull = (st.saturation != null && st.saturation >= 60);
        var notSick = (st.sick === false);
        var hpFull = (st.hp != null && st.hp >= _num(st.max_hp, 20));
        var careBody = '<div class="sc-care-row">'
            + '<button class="sc-btn sc-btn-sm" data-sc="feed"' + (satFull ? ' disabled title="Колонист уже сыт"' : '') + '>🍖 Покормить · 75</button>'
            + '<button class="sc-btn sc-btn-sm" data-sc="cure"' + (notSick ? ' disabled title="Колонист здоров"' : '') + '>💊 Вылечить · 100</button>'
            + '<button class="sc-btn sc-btn-sm" data-sc="heal"' + (hpFull ? ' disabled title="Здоровье уже полное"' : '') + '>❤ Исцелить · 100</button>'
            + '<button class="sc-btn sc-btn-sm" data-sc="mourn">🕯 Снять траур · 50</button>'
            + '</div>'
            + '<button class="sc-btn" style="margin-top:8px;" data-sc="happiness">😊 Поднять настроение · 400</button>';
        html += _grp('g-care', '❤️ Забота', careBody);

        // 📈 Прокачка и роль (скилл + работа + дом)
        var progBody = '<div class="sc-section-title">Прокачать скилл — ' + SC.xp.price + ' 💎</div>'
            + '<select class="sc-select" id="sc-skill-select">';
        SC_SKILLS.forEach(function (pair) { progBody += '<option value="' + pair[0] + '">' + escapeHtml(pair[1]) + '</option>'; });
        progBody += '</select><button class="sc-btn" data-sc="xp">Прокачать (+1000 XP) — ' + SC.xp.price + ' 💎</button>';
        progBody += '<div class="sc-section-title" style="margin-top:14px;">Назначить работу — ' + SC.job.price + ' 💎</div>';
        if (freeJobs.length) {
            progBody += '<select class="sc-select" id="sc-job-select">';
            freeJobs.forEach(function (j) {
                progBody += '<option value="' + escapeHtml(j.job) + '">'
                    + escapeHtml(_jobLabel(j.job)) + ' (' + j.free + ' своб.)</option>';
            });
            progBody += '</select><button class="sc-btn" data-sc="job">Нанять — ' + SC.job.price + ' 💎</button>';
        } else {
            progBody += '<p class="sc-muted">Нет свободных рабочих мест — стример ещё не построил хаты или все заняты.</p>';
        }
        progBody += '<div class="sc-section-title" style="margin-top:14px;">Дать дом — ' + SC.home.price + ' 💎</div>';
        if (beds == null) {
            progBody += '<button class="sc-btn" data-sc="home">Дать дом — ' + SC.home.price + ' 💎</button>';
        } else if (beds > 0) {
            progBody += '<button class="sc-btn" data-sc="home">Дать дом (' + beds + ' своб. коек) — ' + SC.home.price + ' 💎</button>';
        } else {
            progBody += '<p class="sc-muted">Нет свободных коек — стример ещё не построил дома.</p>';
        }
        html += _grp('g-progress', '📈 Прокачка и роль', progBody);

        // ⚙️ Авто-режим работы (Phase D — только farmer/lumberjack/shepherd/composter)
        if (autoLabel) {
            var autoBody = '<button class="sc-btn" data-sc="auto_work">⚙ ' + escapeHtml(autoLabel) + ' — ' + SC.auto_work.price + ' 💎</button>'
                + '<p class="sc-muted" style="margin-top:6px;">Включает авто-режим на рабочем месте колониста. Только включает — настройки стримера не трогает.</p>';
            html += _grp('g-auto', '⚙️ Авто-режим работы', autoBody);
        }

        // 🎁 Просьбы колониста
        var reqBody = '';
        if (hasReqInfo && reqs.length === 0) {
            reqBody += '<p class="sc-muted">Колонисту сейчас ничего не нужно.</p>';
        } else if (!hasReqInfo) {
            reqBody += '<button class="sc-btn" data-sc="fulfill">Выполнить просьбу — ' + SC.fulfill.price + ' 💎</button>';
        } else {
            reqBody += '<div class="sc-reqs">Сейчас просит:</div>';
            var anyDeliverable = false;
            reqs.forEach(function (rq) {
                var isObj = rq && typeof rq === 'object';
                var text = isObj ? rq.text : rq;
                var rid = isObj ? (rq.id || '') : '';
                var canDeliver = isObj ? (rq.deliverable !== false) : true;
                if (canDeliver) {
                    anyDeliverable = true;
                    reqBody += '<button class="sc-btn sc-btn-req" data-sc="fulfill" data-req-id="'
                        + escapeHtml(rid) + '">Выполнить: ' + escapeHtml(text) + ' — ' + SC.fulfill.price + ' 💎</button>';
                } else {
                    reqBody += '<div class="sc-req-blocked">• ' + escapeHtml(text) + ' — выполнит сама колония</div>';
                }
            });
            if (!anyDeliverable) { reqBody += '<p class="sc-muted">Эти просьбы нельзя закрыть предметом.</p>'; }
        }
        html += _grp('g-requests', '🎁 Просьбы колониста', reqBody);

        // 🎭 Кастомизация
        var custBody = '<select class="sc-select" id="sc-give-select">';
        SC_GIVE_ITEMS.forEach(function (pair) { custBody += '<option value="' + pair[0] + '">' + escapeHtml(pair[1]) + '</option>'; });
        custBody += '</select><button class="sc-btn" data-sc="give_item">🎁 Выдать предмет — ' + SC.give_item.price + ' 💎</button>'
            + '<div class="sc-care-row">'
            + '<button class="sc-btn sc-btn-sm" data-sc="set_gender">🔄 Сменить пол · 200</button>'
            + '<button class="sc-btn sc-btn-sm" data-sc="teleport">✨ Призвать · 150</button>'
            + '</div>';
        html += _grp('g-custom', '🎭 Кастомизация', custBody);

        // 📊 Характеристики
        var skillsBody = '';
        if (Object.keys(sk).length) {
            skillsBody += '<div class="sc-skills">';
            SC_SKILLS.forEach(function (pair) {
                var lvl = sk[pair[0]];
                if (lvl == null) { return; }
                skillsBody += '<div class="sc-skill"><span>' + escapeHtml(pair[1]) + '</span><b>' + lvl + '</b></div>';
            });
            skillsBody += '</div>';
        } else {
            skillsBody = '<p class="sc-muted">Пока нет данных о навыках.</p>';
        }
        html += _grp('g-skills', '📊 Характеристики', skillsBody);

        html += '</div>';  // /pane me

        // ══════════ PANE: Экипировка ══════════
        html += '<div class="sc-pane" data-pane="gear">';
        // 🛡 Броня (любой колонист — force-slot, всегда работает)
        var gearBody = '<div class="sc-care-row">'
            + '<button class="sc-btn sc-btn-sm" data-sc="equip_leather">🟫 Кожа · 500</button>'
            + '<button class="sc-btn sc-btn-sm" data-sc="equip_iron">⬜ Железо · 1500</button>'
            + '<button class="sc-btn sc-btn-sm" data-sc="equip_diamond">💎 Алмаз · 3000</button>'
            + '<button class="sc-btn sc-btn-sm" data-sc="equip_netherite">🖤 Незерит · 4000</button>'
            + '</div>';
        html += _grp('g-gear', '🛡 Броня', gearBody);

        // ⛏ Инструменты рабочего (нужна работа; тир по уровню хаты)
        var toolBody;
        if (hasJob) {
            toolBody = '<button class="sc-btn" data-sc="give_tools">⛏ Набор инструментов — ' + SC.give_tools.price + ' 💎</button>'
                + '<p class="sc-muted" style="margin-top:6px;">Кирка/топор/лопата/мотыга — рабочий возьмёт подходящий. Тир — лучший, что тянет его хата.</p>';
        } else {
            toolBody = '<p class="sc-muted">Сначала дай колонисту работу — без неё инструменты не нужны.</p>';
        }
        html += _grp('g-tools', '⛏ Инструменты', toolBody);

        // 💂 Гвардеец (только гвардейцам — оружие/щит/задача/отступление)
        var guardBody;
        if (isGuard) {
            guardBody = '<div class="sc-care-row">'
                + '<button class="sc-btn sc-btn-sm" data-sc="equip_weapon">⚔ Оружие · 2500</button>'
                + '<button class="sc-btn sc-btn-sm" data-sc="give_shield">🛡 Щит · 1000</button>'
                + '</div>'
                + '<p class="sc-muted" style="margin-top:6px;">Оружие — лучший меч+лук по уровню башни (боец возьмёт своё).</p>'
                + '<div class="sc-section-title" style="margin-top:12px;">Боевая задача — ' + SC.set_guard_task.price + ' 💎</div>'
                + '<select class="sc-select" id="sc-guardtask-select">'
                + '<option value="guard">Охрана (стоять у башни)</option>'
                + '<option value="patrol">Патруль</option>'
                + '</select><button class="sc-btn" data-sc="set_guard_task">Задать задачу — ' + SC.set_guard_task.price + ' 💎</button>'
                + '<div class="sc-section-title" style="margin-top:12px;">Отступление на низком HP — ' + SC.set_guard_retreat.price + ' 💎</div>'
                + '<select class="sc-select" id="sc-retreat-select">'
                + '<option value="on">Отступать (беречь бойца)</option>'
                + '<option value="off">Не отступать (стоять насмерть)</option>'
                + '</select><button class="sc-btn" data-sc="set_guard_retreat">Настроить — ' + SC.set_guard_retreat.price + ' 💎</button>';
        } else {
            guardBody = '<p class="sc-muted">Только для гвардейцев (рыцарь / лучник / друид). Назначь колониста в гвардейскую башню — тогда откроются оружие, щит и боевые настройки.</p>';
        }
        html += _grp('g-guard', '💂 Гвардеец', guardBody);
        html += '</div>';  // /pane gear

        // ══════════ PANE: Колония ══════════
        html += '<div class="sc-pane" data-pane="colony">';
        var eventsBody = '<div class="sc-care-row">'
            + '<button class="sc-btn sc-btn-sm" data-sc="festival">🎉 Фестиваль · 3000</button>'
            + '<button class="sc-btn sc-btn-sm" data-sc="spawn_visitor">🚶 Гость · 2000</button>'
            + '<button class="sc-btn sc-btn-sm" data-sc="quest_unlock">📜 Квест · 2000</button>'
            + '<button class="sc-btn sc-btn-sm" data-sc="spy_boost">🕵 Шпионы · 1500</button>'
            + '</div>'
            + '<p class="sc-muted" style="margin-top:8px;">Шпионы работают только во время рейда; гость — если есть таверна.</p>';
        html += _grp('g-events', '🎉 События колонии', eventsBody);

        // 🔬 Развитие (research — single-slot; picker discloses what's available/running)
        var researchBody = '<div class="sc-section-title">Профинансировать исследование — ' + SC.start_research.price + ' 💎</div>';
        if (researchAvail.length) {
            researchBody += '<select class="sc-select" id="sc-research-start-select">';
            researchAvail.forEach(function (r) {
                researchBody += '<option value="' + escapeHtml(r.branch + '|' + r.id) + '">'
                    + escapeHtml(r.name || r.id) + '</option>';
            });
            researchBody += '</select><button class="sc-btn" data-sc="start_research">Профинансировать — ' + SC.start_research.price + ' 💎</button>';
        } else {
            researchBody += '<p class="sc-muted">Нет доступных исследований — нужен построенный университет (или всё в ветке уже изучено).</p>';
        }
        researchBody += '<div class="sc-section-title" style="margin-top:14px;">Завершить мгновенно — ' + SC.finish_research.price + ' 💎</div>';
        if (researchProg.length) {
            researchBody += '<select class="sc-select" id="sc-research-finish-select">';
            researchProg.forEach(function (r) {
                researchBody += '<option value="' + escapeHtml(r.branch + '|' + r.id) + '">'
                    + escapeHtml(r.name || r.id) + '</option>';
            });
            researchBody += '</select><button class="sc-btn" data-sc="finish_research">Завершить сейчас — ' + SC.finish_research.price + ' 💎</button>';
        } else {
            researchBody += '<p class="sc-muted">Сейчас нет идущих исследований, которые можно ускорить.</p>';
        }
        html += _grp('g-research', '🔬 Развитие', researchBody);

        // 📦 Склад — снабжение (стак) + неснижаемый запас + разгрести очередь заказов
        var supplyBody = '<div class="sc-section-title">Снабдить колонию (стак) — ' + SC.supply.price + ' 💎</div>'
            + '<select class="sc-select" id="sc-supply-select">';
        SC_SUPPLY_ITEMS.forEach(function (pair) { supplyBody += '<option value="' + pair[0] + '">' + escapeHtml(pair[1]) + '</option>'; });
        supplyBody += '</select><button class="sc-btn" data-sc="supply">📦 Снабдить — ' + SC.supply.price + ' 💎</button>'
            + '<p class="sc-muted" style="margin-top:6px;">Только базовые материалы — помогаешь колонии строиться.</p>';
        supplyBody += '<div class="sc-section-title" style="margin-top:14px;">Неснижаемый запас — ' + SC.min_stock.price + ' 💎</div>';
        if (warehouseOk) {
            supplyBody += '<select class="sc-select" id="sc-minstock-item-select">';
            SC_MIN_STOCK_ITEMS.forEach(function (pair) { supplyBody += '<option value="' + pair[0] + '">' + escapeHtml(pair[1]) + '</option>'; });
            supplyBody += '</select><select class="sc-select" id="sc-minstock-qty-select">';
            SC_MIN_STOCK_QTYS.forEach(function (q) { supplyBody += '<option value="' + q + '">' + q + ' стак.</option>'; });
            supplyBody += '</select><button class="sc-btn" data-sc="min_stock">📌 Закрепить запас — ' + SC.min_stock.price + ' 💎</button>'
                + '<p class="sc-muted" style="margin-top:6px;">Склад будет держать выбранное количество этого предмета не ниже порога.</p>';
        } else {
            supplyBody += '<p class="sc-muted">Нужен построенный склад в колонии.</p>';
        }
        supplyBody += '<div class="sc-section-title" style="margin-top:14px;">Разгрести очередь заказов — ' + SC.clear_backlog.price + ' 💎</div>';
        if (backlogBuildings.length) {
            supplyBody += '<select class="sc-select" id="sc-backlog-select">';
            backlogBuildings.forEach(function (b) {
                supplyBody += '<option value="' + escapeHtml(b.pos) + '">'
                    + escapeHtml(_buildingLabel(b.type) + ' (' + b.backlog + ' в очереди)') + '</option>';
            });
            supplyBody += '</select><button class="sc-btn" data-sc="clear_backlog">🚚 Разгрести — ' + SC.clear_backlog.price + ' 💎</button>'
                + '<p class="sc-muted" style="margin-top:6px;">Выдаст зданию материалы, которые оно ждёт — ускоряет стройку/работу, ничего не отменяет.</p>';
        } else {
            supplyBody += '<p class="sc-muted">Ни у одного здания сейчас нет очереди заказов.</p>';
        }
        html += _grp('g-supply', '📦 Склад', supplyBody);

        // 🏗 Стройка (Phase B — флагман: апгрейд здания; гейт по онлайну стримера + наличию цели)
        var buildBody;
        if (!canBuild) {
            buildBody = '<p class="sc-muted">Стример сейчас офлайн — строитель не начнёт улучшение. Загляни, когда он в игре.</p>';
        } else if (upgradeBuildings.length) {
            buildBody = '<select class="sc-select" id="sc-upgrade-select">';
            upgradeBuildings.forEach(function (b) {
                buildBody += '<option value="' + escapeHtml(b.pos) + '">'
                    + escapeHtml(_buildingLabel(b.type) + ' — ур. ' + b.level + '→' + (b.level + 1)) + '</option>';
            });
            buildBody += '</select><button class="sc-btn" data-sc="upgrade_building">🏗 Улучшить здание — ' + SC.upgrade_building.price + ' 💎</button>'
                + '<p class="sc-muted" style="margin-top:6px;">Строитель построит следующий уровень на реальных ресурсах — не мгновенно. Главный способ вложиться в колонию стримера.</p>';
        } else {
            buildBody = '<p class="sc-muted">Сейчас нечего улучшать — все здания на максимуме или уже строятся.</p>';
        }
        html += _grp('g-build', '🏗 Стройка', buildBody);
        html += '</div>';  // /pane colony

        root.innerHTML = html;
        _bind(root);
    }

    function _renderIfChanged() {
        var sig;
        try { sig = JSON.stringify(_state); } catch (e) { sig = ''; }
        if (sig && sig === _lastSig) { return; }
        _lastSig = sig;
        _render();
    }

    function _bind(root) {
        // action buttons (all greyed while the game server is offline — buys would queue forever)
        var btns = root.querySelectorAll('[data-sc]');
        for (var i = 0; i < btns.length; i++) {
            (function (btn) {
                if (_state.stale) { btn.disabled = true; }
                btn.addEventListener('click', function () { _onClick(btn); });
            })(btns[i]);
        }
        // tab switching — pure DOM (no re-render) so the choice survives between polls
        var tabs = root.querySelectorAll('.sc-tab');
        for (var t = 0; t < tabs.length; t++) {
            (function (tab) {
                tab.addEventListener('click', function () {
                    _activeTab = tab.getAttribute('data-tab');
                    _applyTab();
                });
            })(tabs[t]);
        }
        // accordion open/closed tracking → persists across re-renders via _openGroups
        var accs = root.querySelectorAll('.sc-acc');
        for (var a = 0; a < accs.length; a++) {
            (function (acc) {
                acc.addEventListener('toggle', function () {
                    var id = acc.getAttribute('data-grp');
                    if (!id) { return; }
                    if (acc.open) { _openGroups[id] = true; } else { delete _openGroups[id]; }
                });
            })(accs[a]);
        }
        // Persist dropdown choices across the 5s re-render (bug #31: viewer picks Strength, an HP/
        // saturation tick re-renders, the skill select snaps back to the first option = Athletics,
        // and «Прокачать» levels the wrong skill). Restore each select's last value, then track changes.
        var sels = root.querySelectorAll('select');
        for (var s = 0; s < sels.length; s++) {
            (function (sel) {
                if (sel.id && _selVals[sel.id] != null) {
                    sel.value = _selVals[sel.id];   // no-op if that option no longer exists → stays default
                }
                sel.addEventListener('change', function () {
                    if (sel.id) { _selVals[sel.id] = sel.value; }
                });
            })(sels[s]);
        }
        _applyTab();
    }

    function _onClick(btn) {
        var kind = btn.getAttribute('data-sc');
        var cfg = SC[kind];
        if (!cfg) { return; }
        var data = {};
        if (kind === 'job') {
            var js = document.getElementById('sc-job-select');
            if (!js || !js.value) { showNotification('Выбери работу', 'error', 3000); return; }
            data.job = js.value;
        } else if (kind === 'xp') {
            var ss = document.getElementById('sc-skill-select');
            data.skill = ss && ss.value ? ss.value : 'Strength';
        } else if (kind === 'give_item') {
            var gs = document.getElementById('sc-give-select');
            if (!gs || !gs.value) { showNotification('Выбери предмет', 'error', 3000); return; }
            data.item = gs.value;
        } else if (kind === 'supply') {
            var ds = document.getElementById('sc-supply-select');
            if (!ds || !ds.value) { showNotification('Выбери ресурс', 'error', 3000); return; }
            data.item = ds.value;
        } else if (kind === 'fulfill') {
            // Per-request buttons carry the chosen request token; legacy button has none (mod closes top).
            var rid = btn.getAttribute('data-req-id');
            if (rid) { data.request_id = rid; }
        } else if (kind === 'min_stock') {
            var mi = document.getElementById('sc-minstock-item-select');
            var mq = document.getElementById('sc-minstock-qty-select');
            if (!mi || !mi.value) { showNotification('Выбери предмет', 'error', 3000); return; }
            data.item = mi.value;
            data.qty = (mq && mq.value) ? parseInt(mq.value, 10) : 1;
        } else if (kind === 'clear_backlog') {
            var bl = document.getElementById('sc-backlog-select');
            if (!bl || !bl.value) { showNotification('Выбери здание', 'error', 3000); return; }
            data.building = bl.value;
        } else if (kind === 'upgrade_building') {
            var ub = document.getElementById('sc-upgrade-select');
            if (!ub || !ub.value) { showNotification('Выбери здание', 'error', 3000); return; }
            data.building = ub.value;
        } else if (kind === 'start_research' || kind === 'finish_research') {
            var rs = document.getElementById(kind === 'start_research'
                ? 'sc-research-start-select' : 'sc-research-finish-select');
            if (!rs || !rs.value) { showNotification('Выбери исследование', 'error', 3000); return; }
            var parts = rs.value.split('|');
            data.branch = parts[0];
            data.research = parts.slice(1).join('|');   // id itself may contain '/', never '|'
        } else if (kind === 'set_guard_task') {
            var gt = document.getElementById('sc-guardtask-select');
            data.task = (gt && gt.value) ? gt.value : 'guard';
        } else if (kind === 'set_guard_retreat') {
            var rt = document.getElementById('sc-retreat-select');
            data.retreat = !(rt && rt.value === 'off');   // default on
        }
        btn.disabled = true;
        _buy(cfg.type, data).then(function (res) {
            btn.disabled = false;
            if (res && res.success) { _refresh(); }   // re-pull state right after a successful buy
        });
    }

    // ── poll: my-colonist + capacity ───────────────────────────────────────────
    function _refresh() {
        if (typeof API_URL === 'undefined') { return; }
        var mcP = fetch(API_URL + '/api/shedcolony/my-colonist', { headers: _jwtHeaders(false) })
            .then(function (r) { return r.json(); }).catch(function () { return null; });
        var capP = fetch(API_URL + '/api/shedcolony/capacity', { headers: _jwtHeaders(false) })
            .then(function (r) { return r.json(); }).catch(function () { return null; });
        return Promise.all([mcP, capP]).then(function (res) {
            var mc = res[0], cap = res[1];
            if (mc && mc.success) { _state.colonist = mc; }
            if (cap && cap.success) {
                _state.capacity = { jobs: cap.jobs || [], free_beds: cap.free_beds };
                _state.targets = cap.targets || null;
                _state.stale = !!cap.stale;   // сервер мода молчит >60с → покупки в вечную очередь
            }
            _renderIfChanged();
        });
    }

    // Цены с бэка перетирают запасные в SC. Ошибку глотаем: со старыми ценами
    // панель работает, без панели — нет.
    async function _hydratePrices() {
        try {
            var r = await fetch(API_URL + '/api/shedcolony/config');
            if (!r.ok) return;
            var cfg = await r.json();
            var prices = (cfg && cfg.action_prices) || {};
            Object.keys(SC).forEach(function (k) {
                var v = Number(prices[SC[k].type]);
                if (isFinite(v)) SC[k].price = v;
            });
        } catch (e) { /* остаёмся на запасных */ }
    }

    window._startShedcolonyPolling = function () {
        _lastSig = '';                 // force a fresh render when the tab is (re)opened
        _hydratePrices().then(function () { _lastSig = ''; _refresh(); });
        _refresh();
        if (_pollId === null) { _pollId = safeInterval(_refresh, 5000); }
    };

    window._stopShedcolonyPolling = function () {
        if (_pollId !== null) { clearInterval(_pollId); _pollId = null; }
    };

    // 2026-08-19: игра объявляет себя ядру сама (viewer-registry.js).
    ShedLink.registerGame('shedcolony', {
        rootId: 'shedcolony-content',
        title:  '⛏️ Колония',
        start:  function () { window._startShedcolonyPolling(); },
        stop:   function () { window._stopShedcolonyPolling(); },
    });
})();
