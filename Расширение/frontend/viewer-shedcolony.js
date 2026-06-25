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

    var SC = {
        spawn:   { type: 'colonist.spawn',            price: 1000 },
        job:     { type: 'colonist.assign_job',       price: 300 },
        home:    { type: 'colonist.assign_home',      price: 200 },
        xp:      { type: 'colonist.add_xp',           price: 150 },
        fulfill: { type: 'colonist.fulfill_request',  price: 100 },
    };

    // Action-specific deferred-success toasts (paid + async → "это заявка, исход в игре").
    var SC_SUCCESS_MSG = {
        'colonist.spawn':            '✨ Заявка принята! Твой колонист появится в колонии через пару секунд.',
        'colonist.assign_job':       '🔨 Заявка на работу принята — назначим в игре через пару секунд.',
        'colonist.assign_home':      '🏠 Заявка на дом принята — поселим через пару секунд.',
        'colonist.add_xp':           '📈 Заявка на прокачку принята — скилл вырастет через пару секунд.',
        'colonist.fulfill_request':  '📦 Заявка принята — просьбу колониста выполним через пару секунд.',
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
            + '#shedcolony-content .sc-btn:disabled{opacity:.45;cursor:not-allowed;filter:none;}';
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
            html += '<div class="sc-card">'
                + '<div class="sc-colonist-name">👤 ' + escapeHtml(c.name || 'Мой колонист') + '</div>'
                + '<div class="sc-colonist-job">Работа: ' + escapeHtml(c.job ? _jobLabel(c.job) : 'без работы') + '</div>'
                + (c.status ? '<div class="sc-colonist-status">Статус: ' + escapeHtml(String(c.status)) + '</div>' : '')
                + '</div>';

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
            html += '<div class="sc-card"><div class="sc-section-title">Прокачать скилл — 150 💎</div><select class="sc-select" id="sc-skill-select">';
            SC_SKILLS.forEach(function (pair) {
                html += '<option value="' + pair[0] + '">' + escapeHtml(pair[1]) + '</option>';
            });
            html += '</select><button class="sc-btn" data-sc="xp">Прокачать — 150 💎</button></div>';

            // Fulfill an open request.
            html += '<div class="sc-card"><div class="sc-section-title">Помочь колонисту</div>'
                + '<button class="sc-btn" data-sc="fulfill">Выполнить его просьбу — 100 💎</button></div>';
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
        if (_pollId === null) { _pollId = safeInterval(_refresh, 8000); }
    };

    window._stopShedcolonyPolling = function () {
        if (_pollId !== null) { clearInterval(_pollId); _pollId = null; }
    };
})();
