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
 */
(function () {
    'use strict';

    // NOTE: prices mirror routes/shedcolony.py _ACTION_PRICES (backend is the source of truth;
    // it enforces the real price and ignores the client). Keep in sync on a price change.
    var SC = {
        spawn:   { type: 'colonist.spawn',            price: 1000 },
        job:     { type: 'colonist.assign_job',       price: 300 },
        home:    { type: 'colonist.assign_home',      price: 200 },
        xp:      { type: 'colonist.add_xp',           price: 400 },
        fulfill: { type: 'colonist.fulfill_request',  price: 100 },
        rename:  { type: 'colonist.rename',           price: 300 },
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
    };

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
        'colonist.rename':           '✏️ Заявка на переименование принята — применим через пару секунд.',
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
    };

    var _pollId = null;
    var _inflight = {};            // action_type → true while a buy is in flight (anti-double-click)
    var _state = { colonist: null, capacity: { jobs: [], free_beds: null } };
    var _lastSig = '';
    var _stylesInjected = false;

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

    function _num(v, dflt) {
        return (typeof v === 'number' && !isNaN(v)) ? v : dflt;
    }

    // MineColonies happiness is ~0–2 (1.0 = normal) → mood emoji.
    function _moodEmoji(h) {
        if (h == null) { return '🙂'; }
        if (h >= 1.3) { return '😄'; }
        if (h >= 1.0) { return '🙂'; }
        if (h >= 0.7) { return '😐'; }
        if (h >= 0.4) { return '😟'; }
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
            + '#shedcolony-content .sc-reqs ul{margin:4px 0 0;padding-left:18px;}';
        var s = document.createElement('style');
        s.id = 'sc-styles';
        s.textContent = css;
        document.head.appendChild(s);
    }

    // ── buy: POST /api/shedcolony/action (charge crustics + enqueue) ──────────
    function _buy(actionType, data) {
        if (_inflight[actionType]) { return Promise.resolve(null); }
        _inflight[actionType] = true;
        var clientActionId = 'sc_' + (typeof Date !== 'undefined' ? Date.now() : '')
            + '_' + Math.random().toString(36).slice(2, 8);
        var body = JSON.stringify({
            action_type: actionType,
            data: Object.assign({}, data || {}, { client_action_id: clientActionId }),
        });
        return fetch(API_URL + '/api/shedcolony/action', {
            method: 'POST', headers: _jwtHeaders(true), body: body,
        }).then(function (r) { return r.json(); }).then(function (result) {
            if (result && result.success) {
                showNotification(SC_SUCCESS_MSG[actionType] || result.message || 'Готово', 'success', 6000);
            } else {
                showNotification((result && result.message) || 'Не получилось', 'error', 4500);
            }
            return result;
        }).catch(function () {
            showNotification('Сеть недоступна — попробуй ещё раз', 'error', 4000);
            return null;
        }).then(function (res) {
            delete _inflight[actionType];
            return res;
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

        if (!c || !c.linked) {
            html += '<div class="sc-card">'
                + '<p class="sc-muted" style="margin-bottom:10px;">У тебя ещё нет колониста в этой колонии. '
                + 'Создай своего — он появится у стримера в игре.</p>'
                + '<button class="sc-btn" data-sc="spawn">Создать колониста — 1000 💎</button>'
                + '</div>';
        } else {
            var st = c.state || {};
            var job = (st.job != null) ? st.job : c.job;
            var who = escapeHtml(c.name || 'Мой колонист')
                + (st.child ? ' 👶' : '')
                + (st.female === true ? ' ♀' : (st.female === false ? ' ♂' : ''));

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

            // Characteristics — all skills.
            var sk = (st.skills && Object.keys(st.skills).length) ? st.skills : (c.skills || {});
            if (Object.keys(sk).length) {
                html += '<div class="sc-card"><div class="sc-section-title">Характеристики</div><div class="sc-skills">';
                SC_SKILLS.forEach(function (pair) {
                    var lvl = sk[pair[0]];
                    if (lvl == null) { return; }
                    html += '<div class="sc-skill"><span>' + escapeHtml(pair[1]) + '</span><b>' + lvl + '</b></div>';
                });
                html += '</div></div>';
            }

            // Care — own-colonist Phase 7 actions (cheap, deterministic, grief-safe).
            html += '<div class="sc-card"><div class="sc-section-title">Забота о колонисте</div>';
            html += '<input class="sc-input" id="sc-rename-input" maxlength="16" placeholder="Новое имя (1–16)">';
            html += '<button class="sc-btn" data-sc="rename">Переименовать — 300 💎</button>';
            html += '<div class="sc-care-row">'
                + '<button class="sc-btn sc-btn-sm" data-sc="feed">🍖 Покормить · 75</button>'
                + '<button class="sc-btn sc-btn-sm" data-sc="cure">💊 Вылечить · 100</button>'
                + '<button class="sc-btn sc-btn-sm" data-sc="heal">❤ Исцелить · 100</button>'
                + '<button class="sc-btn sc-btn-sm" data-sc="mourn">🕯 Снять траур · 50</button>'
                + '</div>';
            html += '<select class="sc-select" id="sc-give-select" style="margin-top:8px;">';
            SC_GIVE_ITEMS.forEach(function (pair) {
                html += '<option value="' + pair[0] + '">' + escapeHtml(pair[1]) + '</option>';
            });
            html += '</select><button class="sc-btn" data-sc="give_item">🎁 Выдать предмет — 200 💎</button>';
            html += '<div class="sc-care-row">'
                + '<button class="sc-btn sc-btn-sm" data-sc="set_gender">🔄 Сменить пол · 200</button>'
                + '<button class="sc-btn sc-btn-sm" data-sc="teleport">✨ Призвать · 150</button>'
                + '</div></div>';

            // Equipment — armour tiers (visible in-game, raid-survivable, prestige crustic sink).
            html += '<div class="sc-card"><div class="sc-section-title">Экипировка — броня</div>'
                + '<div class="sc-care-row">'
                + '<button class="sc-btn sc-btn-sm" data-sc="equip_leather">🟫 Кожа · 500</button>'
                + '<button class="sc-btn sc-btn-sm" data-sc="equip_iron">⬜ Железо · 1500</button>'
                + '<button class="sc-btn sc-btn-sm" data-sc="equip_diamond">💎 Алмаз · 3000</button>'
                + '</div></div>';

            // Job — gated by free job slots from capacity.
            var freeJobs = (cap.jobs || []).filter(function (j) { return j.free > 0; });
            html += '<div class="sc-card"><div class="sc-section-title">Назначить работу — 300 💎</div>';
            if (freeJobs.length) {
                html += '<select class="sc-select" id="sc-job-select">';
                freeJobs.forEach(function (j) {
                    html += '<option value="' + escapeHtml(j.job) + '">'
                        + escapeHtml(_jobLabel(j.job)) + ' (' + j.free + ' своб.)</option>';
                });
                html += '</select><button class="sc-btn" data-sc="job">Нанять — 300 💎</button>';
            } else {
                html += '<p class="sc-muted">Нет свободных рабочих мест — стример ещё не построил хаты или все заняты.</p>';
            }
            html += '</div>';

            // Home — gated by free beds.
            var beds = cap.free_beds;
            html += '<div class="sc-card"><div class="sc-section-title">Дать дом — 200 💎</div>';
            if (beds == null) {
                html += '<button class="sc-btn" data-sc="home">Дать дом — 200 💎</button>';
            } else if (beds > 0) {
                html += '<button class="sc-btn" data-sc="home">Дать дом (' + beds + ' своб. коек) — 200 💎</button>';
            } else {
                html += '<p class="sc-muted">Нет свободных коек — стример ещё не построил дома.</p>';
            }
            html += '</div>';

            // XP — pick a skill.
            html += '<div class="sc-card"><div class="sc-section-title">Прокачать скилл — 400 💎</div><select class="sc-select" id="sc-skill-select">';
            SC_SKILLS.forEach(function (pair) {
                html += '<option value="' + pair[0] + '">' + escapeHtml(pair[1]) + '</option>';
            });
            html += '</select><button class="sc-btn" data-sc="xp">Прокачать (+1000 XP) — 400 💎</button></div>';

            // Fulfill — show the colonist's actual open requests + gate the button.
            // Graceful: if the mod doesn't report requests yet (state.requests undefined), keep the
            // old always-on button; only claim "nothing needed" when we actually know the list.
            var hasReqInfo = st && Array.isArray(st.requests);
            var reqs = hasReqInfo ? st.requests : [];
            html += '<div class="sc-card"><div class="sc-section-title">Помочь колонисту</div>';
            if (hasReqInfo && reqs.length === 0) {
                html += '<p class="sc-muted">Колонисту сейчас ничего не нужно.</p>';
            } else {
                if (reqs.length) {
                    html += '<div class="sc-reqs">Сейчас просит:<ul>';
                    reqs.forEach(function (rq) { html += '<li>' + escapeHtml(rq) + '</li>'; });
                    html += '</ul></div>';
                }
                html += '<button class="sc-btn" data-sc="fulfill">Выполнить просьбу — 100 💎</button>';
            }
            html += '</div>';

            // Colony-level sinks (Phase 8) — support the streamer's whole colony.
            html += '<div class="sc-card"><div class="sc-section-title">Колония стримера</div>'
                + '<div class="sc-care-row">'
                + '<button class="sc-btn sc-btn-sm" data-sc="festival">🎉 Фестиваль · 3000</button>'
                + '<button class="sc-btn sc-btn-sm" data-sc="spawn_visitor">🚶 Гость · 2000</button>'
                + '<button class="sc-btn sc-btn-sm" data-sc="quest_unlock">📜 Квест · 2000</button>'
                + '<button class="sc-btn sc-btn-sm" data-sc="spy_boost">🕵 Шпионы · 1500</button>'
                + '</div>'
                + '<p class="sc-muted" style="margin-top:6px;">Шпионы работают только во время рейда; гость — если есть таверна.</p>'
                + '</div>';
        }

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
        var btns = root.querySelectorAll('[data-sc]');
        for (var i = 0; i < btns.length; i++) {
            (function (btn) {
                btn.addEventListener('click', function () { _onClick(btn); });
            })(btns[i]);
        }
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
        } else if (kind === 'rename') {
            var ri = document.getElementById('sc-rename-input');
            var nm = ri && ri.value ? ri.value.trim() : '';
            if (!nm) { showNotification('Введи имя (1–16 символов)', 'error', 3000); return; }
            data.new_name = nm;
        } else if (kind === 'give_item') {
            var gs = document.getElementById('sc-give-select');
            if (!gs || !gs.value) { showNotification('Выбери предмет', 'error', 3000); return; }
            data.item = gs.value;
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
            if (cap && cap.success) { _state.capacity = { jobs: cap.jobs || [], free_beds: cap.free_beds }; }
            _renderIfChanged();
        });
    }

    window._startShedcolonyPolling = function () {
        _lastSig = '';                 // force a fresh render when the tab is (re)opened
        _refresh();
        if (_pollId === null) { _pollId = safeInterval(_refresh, 5000); }
    };

    window._stopShedcolonyPolling = function () {
        if (_pollId !== null) { clearInterval(_pollId); _pollId = null; }
    };
})();
