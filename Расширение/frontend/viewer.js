// viewer.js - ФИНАЛЬНАЯ РАБОЧАЯ ВЕРСИЯ

// ===== ОТЛАДКА =====
// Установите в true для отладки в браузере, false в продакшне
const DEBUG = false;
const dbg = (...args) => { if (DEBUG) console.log(...args); };

// ===== ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК =====
window.addEventListener('unhandledrejection', function(event) {
    console.error('[viewer.js] Необработанная ошибка промиса:', event.reason);
    event.preventDefault();
});
window.addEventListener('error', function(event) {
    console.error('[viewer.js] Глобальная ошибка:', event.message, event.filename, event.lineno);
});

// Автоопределение API_URL: локальный сервер или продакшен
const API_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' 
    ? `${window.location.protocol}//${window.location.host}` 
    : 'https://shedoy23.ru';
let userId = 'testuser';
let userLogin = 'testuser';
let authToken = '';
let helixToken = '';
let clientId = '';

// ── Потеря опознания зрителя (07.09) ─────────────────────────────────────────
// Объявления живут ЗДЕСЬ, рядом с остальным состоянием авторизации, а не рядом
// со своими функциями ниже. Причина конкретная: Twitch вызывает onAuthorized
// сразу при регистрации, если токен уже есть, — то есть ПОКА файл ещё
// выполняется. Объявление `let` ниже этой точки означает временную мёртвую
// зону: присваивание падает с ReferenceError и убивает весь вход в панель.
// Именно так я сломал вход 07.09, перенеся сюда — починил.
let _authUserId = null;
let _authOpaqueId = null;
let _authLost = false;
let _authRecoverTried = 0;
// Единственный источник истины для module-specific загрузок и polling.
// До первого /api/viewer/stats модуль неизвестен, поэтому игровые endpoints
// не вызываем вообще.
let _activeIntegrationModule = null;

// ===== ГЛОБАЛЬНЫЙ МЕНЕДЖЕР ИНТЕРВАЛОВ =====
// Все таймеры и интервалы регистрируются здесь и очищаются при закрытии страницы
const _globalIntervals = new Set();
const _globalTimeouts = new Set();

// Обёртка для безопасных интервалов с автоматической очисткой
function safeInterval(callback, ms) {
    const id = setInterval(callback, ms);
    _globalIntervals.add(id);
    return id;
}

// Обёртка для безопасных таймаутов с автоматической очисткой
function safeTimeout(callback, ms) {
    const id = setTimeout(callback, ms);
    _globalTimeouts.add(id);
    return id;
}

// Очистка ВСЕХ таймеров и интервалов
function cleanupAllTimers() {
    _globalIntervals.forEach(id => clearInterval(id));
    _globalTimeouts.forEach(id => clearTimeout(id));
    _globalIntervals.clear();
    _globalTimeouts.clear();
}

// ===== ОТСЛЕЖИВАНИЕ АКТИВНОСТИ =====
let lastActivityTime = Date.now();
let totalTimeWatched = 0;
let lastReportTime = Date.now();
let sessionStartTime = Date.now();
let clickCount = 0;
let moveCount = 0;
let lastMoveTime = Date.now();
let uiUpdateInterval = null;     // защита от множественных setInterval
const _shownWinners = new Set();    // показанные победители (вместо localStorage)
let _cachedUserPoints = 0;          // кэш баланса для renderEvents до обновления DOM
let _cspHandlersBound = false;      // защита от повторного навешивания делегированных обработчиков
let _authUiInitialized = false;     // защита от повторной инициализации после onAuthorized

function setupCspSafeHandlers() {
    if (_cspHandlersBound) return;
    _cspHandlersBound = true;

    document.addEventListener('click', function(event) {
        // legacy-кнопки удалены 2026-05-10 (Phase 1.A compliance rework)
        const actionEl = event.target.closest('[data-action],[data-open-modal],[data-toggle-target],[data-close-self-modal],[data-accept-family],[data-reject-family],[data-close-modal],[data-cat],#create-pawn-btn,#heal-pawn-btn,#btn-resurrect,#stats-refresh-btn,#refresh-pawn-btn,#panel-hide-btn,#panel-hide-tab,#promo-activate-btn,#create-colonist-btn');
        if (!actionEl) return;

        if (actionEl.hasAttribute('data-close-modal')) {
            closeModal();
            return;
        }

        if (actionEl.hasAttribute('data-close-self-modal')) {
            actionEl.closest('.modal')?.remove();
            return;
        }

        if (actionEl.id === 'panel-hide-btn' || actionEl.id === 'panel-hide-tab') {
            hidePanel();
            return;
        }

        if (actionEl.id === 'promo-activate-btn') {
            usePromo();
            return;
        }

        if (actionEl.id === 'create-colonist-btn') {
            closeModal();
            return;
        }

        if (actionEl.dataset.cat) {
            filterShop(actionEl.dataset.cat);
            return;
        }

        // legacy-handlers удалены 2026-05-10 (Phase 1.A compliance rework)

        if (actionEl.id === 'create-pawn-btn') {
            showCreatePawnModal();
            return;
        }

        if (actionEl.id === 'heal-pawn-btn') {
            healMyPawn();
            return;
        }

        if (actionEl.id === 'btn-resurrect') {
            resurrectMyPawn();
            return;
        }

        // market-refresh-btn handler удалён 2026-05-10 (Phase 1.C)

        if (actionEl.id === 'stats-refresh-btn') {
            loadStats();
            return;
        }

        if (actionEl.id === 'refresh-pawn-btn') {
            loadMyPawn();
            return;
        }

        const openModal = actionEl.dataset.openModal;
        if (openModal) {
            if (openModal === 'passion') openPassionModal();
            else if (openModal === 'neuro') openNeuroModal();
            else if (openModal === 'xenotype') openXenotypeModal();
            return;
        }

        if (actionEl.dataset.acceptFamily) {
            const fromUser = decodeURIComponent(actionEl.dataset.acceptFamily);
            if (fromUser) acceptFamilyProposal(fromUser);
            return;
        }

        if (actionEl.dataset.rejectFamily) {
            const fromUser = decodeURIComponent(actionEl.dataset.rejectFamily);
            if (fromUser) rejectFamilyProposal(fromUser);
            return;
        }

        if (actionEl.dataset.toggleTarget) {
            const targetId = actionEl.dataset.toggleTarget;
            const targetEl = document.getElementById(targetId);
            if (!targetEl) return;
            const isOpen = targetEl.style.display === 'block';
            targetEl.style.display = isOpen ? 'none' : 'block';
            const closedText = actionEl.dataset.toggleClosedText;
            const openText = actionEl.dataset.toggleOpenText;
            if (closedText && openText) {
                actionEl.textContent = isOpen ? closedText : openText;
            }
            return;
        }

        const action = actionEl.dataset.action;
        if (!action) return;

        // legacy-actions удалены 2026-05-10 (Phase 1.A/1.C compliance rework)
        if (action === 'cases') openCasesModal();
        else if (action === 'tictactoe') openTicTacToeModal();
        // 2026-09-01: ветка кубиков УДАЛЕНА вместе с заморозкой механики —
        // dice.js больше не грузится ни одной оболочкой, и линтер no-undef
        // справедливо ловил обращение к несуществующей функции. Это тот же
        // класс, что месяцами держал мёртвым магазин RimWorld.
        else if (action === 'tug') openTugModal();
        else if (action === 'guilds') openGuildsModal();
        else if (action === 'voting') openVotingModal();
        else if (action === 'pets') openPetsModal();
        else if (action === 'duels') openDuels();
        // Sprint 5.19: квесты/промо переехали из inline-блоков в модалки
        else if (action === 'quests') openQuestsModal();
        else if (action === 'promo') openPromoModal();
        // Sprint 5.23: TTS «Озвучить сообщение»
        else if (action === 'tts') openTtsModal();
        else if (action === 'bug_report') openBugReport();
        // 'transfer' action удалён 2026-05-10 (Phase 1.D compliance rework — P2P transfer)
        else if (action === 'family') openFamily();
        else if (action === 'refresh-shop-catalog') loadShopCatalog();
        else if (action === 'close-modal') closeModal();
        // 'withdraw-family' action удалён 2026-05-10 (Phase 1.G compliance rework)
        else if (action === 'divorce-family') divorceFamily();
        else if (action === 'propose-family') proposeFamily();
        else if (action === 'create-duel') createDuel();
        // 'transfer-points' action удалён 2026-05-10 (Phase 1.D compliance rework)
        else if (action === 'toggle-next') {
            const host = actionEl.closest('div');
            const details = host ? host.nextElementSibling : null;
            if (!details) return;
            const isOpen = details.style.display === 'block';
            details.style.display = isOpen ? 'none' : 'block';
            actionEl.textContent = isOpen ? 'подробнее ▼' : 'подробнее ▲';
        }
    });


    document.addEventListener('input', function(event) {
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        if (target.id === 'xt-search') filterXenotypes(target.value || '');
        if (target.id === 'neuro-modal-search') _filterNeuroModal(target.value || '');
        if (target.id === 'shop-search') onShopSearch(target.value || '');
        if (target.id === 'events-search') onEventsSearch(target.value || '');
    });

    document.addEventListener('mouseover', function(event) {
        const host = event.target.closest('[data-tooltip-id]');
        if (!host || host.contains(event.relatedTarget)) return;
        const tip = document.getElementById(host.dataset.tooltipId);
        if (tip) tip.style.display = 'block';
    });

    document.addEventListener('mouseout', function(event) {
        const host = event.target.closest('[data-tooltip-id]');
        if (!host || host.contains(event.relatedTarget)) return;
        const tip = document.getElementById(host.dataset.tooltipId);
        if (tip) tip.style.display = 'none';
    });
}


// CRITICAL FIX #5: Debounce function for click/move counters
function createDebouncedReporter(thresholdMs = 5000, callback) {
    let timer = null;
    return (...args) => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => {
            callback(...args);
            timer = null;
        }, thresholdMs);
    };
}

const debouncedClickReport = createDebouncedReporter(2000, () => {
    clickCount++;
    lastActivityTime = Date.now();
});

const debouncedMoveReport = createDebouncedReporter(2000, () => {
    const now = Date.now();
    if (now - lastMoveTime > 2000) {
        moveCount++;
        lastMoveTime = now;
    }
    lastActivityTime = now;
});

// isAuthUser() helper — перенесён из удалённого legacy-модуля 2026-05-10
// (Phase 1.A compliance rework). Используется cases/dice/duels/family/
// guilds/pets/tictactoe/voting/xenotype.js для guard'а перед UI-действиями.
function isAuthUser() {
    return userLogin && userLogin !== 'testuser' && !/^U[a-zA-Z0-9]{8,}$/.test(userLogin);
}
window.isAuthUser = isAuthUser;

const ACTIVITY_CONFIG = {
    watch_time_update_interval: 60,
    chat_bonus_enabled: true,
    activity_bonus_enabled: true,
    bonus_per_click: 1,
    bonus_per_minute_active: 2
};

/** Версия сборки в шапку. Единственный источник — метка, которую ставит
 *  упаковщик (`scripts/pack-extension.py`, `stamp_version`). Своей копии
 *  номера во фронте нет намеренно: две копии разъедутся, и шапка начнёт
 *  врать про то, какая версия реально у зрителя. Незапакованный фронт
 *  (наш сервер, страница /dev) метки не имеет и честно пишет «dev». */
function showBuildVersion() {
    const el = document.getElementById('panel-version');
    if (!el) return;
    const meta = document.querySelector('meta[name="shedlink-version"]');
    const version = (meta && meta.getAttribute('content') || '').trim();
    el.textContent = version ? 'v' + version : 'dev';
    el.title = version
        ? 'Версия расширения ' + version
        : 'Незапакованная сборка (не с Twitch CDN)';
}

// ===== ЦЕНЫ ЯДРА — С СЕРВЕРА =====
// Голосование, гильдии и семья держали свои копии цен, пока у Bannerlord и
// RimWorld источник на бэке был с июля. Фронт замерзает на CDN Twitch до
// следующего ревью, поэтому цену, изменённую на сервере, интерфейс показал бы
// правильно только через недели. Зашитые числа остаются запасными.
let coreConfig = {};

function corePrice(key, fallback) {
    const raw = coreConfig[key];
    if (raw == null || raw === '') return fallback;
    const v = Number(raw);
    return Number.isFinite(v) ? v : fallback;
}

async function loadCoreConfig() {
    try {
        const r = await fetch(`${API_URL}/api/core/config`);
        if (!r.ok) return;
        coreConfig = await r.json() || {};
        // Подписи, которые лежат в разметке обеих оболочек, перерисовываем сами:
        // в HTML остаётся только запасное число.
        const ttsSub = document.getElementById('tts-price-sub');
        if (ttsSub) ttsSub.textContent = `${corePrice('tts_cost', 5000)}💎 на оверлей`;
    } catch (e) {
        // Остаёмся на запасных числах: панель без цен бесполезнее, чем со старыми.
    }
}

document.addEventListener('DOMContentLoaded', function() {
    dbg('DOM загружен');
    loadCoreConfig();

    showBuildVersion();
    setupTabs();
    setupCspSafeHandlers();
    setupActivityTracking();

    // Кнопка обновления на вкладке RimWorld
    const rimworldTab = document.getElementById('rimworld-tab');
    if (rimworldTab) {
        const refreshBtn = document.createElement('button');
        refreshBtn.className = 'extra-btn';
        refreshBtn.style.marginTop = '12px';
        refreshBtn.innerHTML = '<span>🔄</span> Обновить данные';
        refreshBtn.onclick = function() {
            loadMyPawn();
            showNotification('🔄 Данные обновлены', 'success');
        };
        rimworldTab.appendChild(refreshBtn);
    }
    
    // === DEV PREVIEW MODE ===
    // Открыто как ?dev_jwt=<TOKEN>&dev_user=<LOGIN> → инициализируем
    // auth state вручную без Twitch helper'a. JWT генерится через
    // /api/admin/dev/jwt (требует admin auth), подпись = legit
    // (TWITCH_EXTENSION_SECRET), backend принимает как обычный.
    const _devParams = new URLSearchParams(location.search);
    const _devJwt    = _devParams.get('dev_jwt');
    const _devUser   = _devParams.get('dev_user');
    if (_devJwt) {
        dbg('🛠️  DEV PREVIEW MODE active');
        authToken = _devJwt;
        userLogin = (_devUser || 'shedoy23').toLowerCase();
        try {
            const parts  = _devJwt.split('.');
            const pad    = 4 - parts[1].length % 4;
            const payload = JSON.parse(atob(parts[1] + '='.repeat(pad % 4)));
            userId       = String(payload.user_id || payload.channel_id || '0');
        } catch (e) {}
        updateUIAfterAuth();
        return;  // не идём в Twitch.ext path
    }

    if (window.Twitch && window.Twitch.ext) {
        dbg('✅ Twitch API доступен');

        window.Twitch.ext.onAuthorized(function(auth) {
            // auth получена
            userId = auth.userId;
            authToken = auth.token;
            helixToken = auth.helixToken;
            clientId = auth.clientId;

            // Phase C (2026-05-17): init PubSub realtime bus. Подписываемся на
            // broadcast + whisper-<opaqueId>. Idempotent — safe to call multiple
            // times (Twitch может re-fire onAuthorized при token refresh).
            if (window.RealtimeBus) {
                window.RealtimeBus.init(auth.userId);
            }

            // Декодируем токен — проверяем есть ли user_id
            let jwtUserId = null;
            try {
                const parts = auth.token.split('.');
                const pad = 4 - parts[1].length % 4;
                const payload = JSON.parse(atob(parts[1] + '='.repeat(pad % 4)));
                jwtUserId = payload.user_id || null;
                // JWT payload не логируем в продакшене
            } catch(e) {}

            // Запоминаем то, чем зритель опознаётся: если сервер перестанет его
            // узнавать (например, после перезапуска бэкенда), панель повторит
            // резолв сама, не заставляя зрителя перезагружать страницу.
            _authUserId = jwtUserId ? String(jwtUserId) : null;
            _authOpaqueId = auth.userId || null;

            if (jwtUserId) {
                // Есть числовой user_id — резолвим логин через сервер
                getUsernameFromTwitchId(String(jwtUserId), auth.token, auth.userId).then(login => {
                    if (!login || /^U[a-zA-Z0-9]{8,}$/.test(login)) {
                        console.warn('⚠️ Не удалось получить логин — запрашиваем разрешение');
                        showLoginPrompt();
                    } else {
                        userLogin = login;
                        updateUIAfterAuth();
                    }
                });
            } else {
                // Нет user_id — запрашиваем разрешение через Twitch
                console.warn('⚠️ user_id недоступен — запрашиваем разрешение');
                showLoginPrompt();
            }
        });

        // После того как пользователь дал разрешение — onAuthorized сработает снова автоматически
        window.Twitch.ext.onContext(function(ctx) {});
        
        // Слушаем события чата
        try {
            window.Twitch.ext.chat.onMessage((channel, user, message, msgId) => {
                fetch(`${API_URL}/api/viewer/chat-message`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
                    body: JSON.stringify({
                        username: userLogin,
                        message_length: message ? message.length : 0,
                        message_text: message || ''
                    })
                }).catch(e => dbg('chat error:', e));
            });
        } catch (e) {
            dbg('Чат API недоступен');
        }
        
    } else {
        dbg('🧪 Тестовый режим');
        userLogin = 'testuser';
        document.getElementById('username').textContent = userLogin + ' (тест)';
        loadUserData();
    }
});

// ===== ОБНОВЛЕНИЕ UI ПОСЛЕ АВТОРИЗАЦИИ =====
function updateUIAfterAuth() {
    const loginPrompt = document.getElementById('login-prompt');
    if (loginPrompt) loginPrompt.remove();
    _authLost = false;
    if (_authUiInitialized) {
        const usernameEl = document.getElementById('username');
        if (usernameEl) usernameEl.textContent = userLogin;
        loadUserData();
        loadUserPerksBadge();
        return;
    }
    _authUiInitialized = true;

    fetchOnlineUsers();
    if (!window._intervalOnlineUsers) {
        window._intervalOnlineUsers = safeInterval(fetchOnlineUsers, 30000);
    }
    // UI update
    
    const usernameEl = document.getElementById('username');
    if (usernameEl) usernameEl.textContent = userLogin;
    
    // Сообщаем серверу об онлайне
    fetch(`${API_URL}/api/viewer/online`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
        body: JSON.stringify({ username: userLogin, channel_id: clientId || 'unknown' })
    }).catch(e => dbg('online error:', e));
    
    // Загружаем данные
    loadUserData();
    // Sprint 5.31 #45b: подгрузить role+sub-tier badges под ником.
    loadUserPerksBadge();
    // M103: причины отказов, накопившиеся пока панель была закрыта.
    pollNotices();
    if (!window._intervalNotices) {
        window._intervalNotices = safeInterval(pollNotices, 20000);
    }
    if (!window._intervalUserPerks) {
        // Refresh каждые 5 мин (Helix sub cache TTL).
        window._intervalUserPerks = safeInterval(loadUserPerksBadge, 5 * 60 * 1000);
    }
    
    // Запускаем периодическое обновление (только один раз)
    if (!uiUpdateInterval) {
        uiUpdateInterval = safeInterval(() => {
            loadUserData();
            // Обновляем стату только если вкладка активна
            const statsTab = document.getElementById('stats-tab');
            if (statsTab && statsTab.classList.contains('active')) loadStats();
        }, 60000);
    }

    _startAttendanceTracking();
}


// Sprint 5.31 #45b — обновить бейдж роли + tier'ов под ником зрителя.
// Endpoint /api/viewer/perks returns role and Twitch subscription tier.
// Role: broadcaster → '👑 Стример', moderator → '🛡 Модер', else 'Зритель'.
// Twitch sub → TS1/TS2/TS3 cosmetic badge.
// Sprint 5.33 TOS-COMPLIANCE — tier badges = COSMETIC ONLY. Подписки больше
// НЕ дают discount или reward bonus. Только moderator/broadcaster имеют perks.
async function loadUserPerksBadge() {
    try {
        const r = await fetch(`${API_URL}/api/viewer/perks`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
            cache: 'no-store',
        });
        const d = await r.json();
        if (!d || !d.success) {
            // Sprint 5.31 #45c — больше не silent. Пусть видно в console.
            // 07.09: раньше выход был просто `return`, но при неудачном опознании
            // бейдж оставался с разметочным значением «Зритель» — и стример на
            // своём канале читал это как «меня разжаловали». Пустой бейдж честнее
            // неверного: роль неизвестна, значит не утверждаем ничего.
            dbg('[perks] response not success', d);
            const roleElUnknown = document.getElementById('user-role-badge');
            if (roleElUnknown) roleElUnknown.textContent = '';
            return;
        }
        dbg('[perks] resolved', d);
        const roleEl = document.getElementById('user-role-badge');
        if (roleEl) {
            if (d.role === 'broadcaster') {
                roleEl.textContent = '👑 Стример';
                roleEl.style.color = '#fbbf24';
            } else if (d.role === 'moderator') {
                roleEl.textContent = '🛡 Модер';
                roleEl.style.color = '#34d399';
            } else {
                roleEl.textContent = 'Зритель';
                roleEl.style.color = '';
            }
        }
        const tierEl = document.getElementById('user-tier-badges');
        if (tierEl) {
            const badges = [];
            const ts = parseInt(d.twitch_sub_tier || 0, 10);
            const badgeStyle = (bg, brd, fg, title) =>
                `display:inline-block;padding:2px 7px;border-radius:4px;`
              + `font-size:10px;font-weight:700;line-height:1.3;`
              + `background:${bg};border:1px solid ${brd};color:${fg};`
              + `letter-spacing:0.3px;` + (title ? `cursor:help;` : '');
            // Sprint 5.33 TOS-COMPLIANCE — sub tier badges remain как cosmetic
            // ONLY. Подписки больше не дают gameplay benefits (Twitch ToS).
            // Badge — это just "thanks for supporting"-style visual.
            if (ts >= 1 && ts <= 3) {
                badges.push(
                    `<span title="Twitch Sub Tier ${ts}"
                           style="${badgeStyle('#1f1145','#7e22ce','#c084fc',true)}">
                        TS${ts}
                    </span>`);
            }
            tierEl.innerHTML = badges.join('');
        }
    } catch (e) {
        // Sprint 5.31 #45c — было silent. Теперь в console чтобы багрепорт
        // от пользователя «нет тиерного бейджа» можно было дебажить.
        console.warn('[perks] loadUserPerksBadge failed:', e);
    }
}


// ===== ЗАПРОС IDENTITY У ЗРИТЕЛЯ =====
// ── Потеря опознания зрителя (07.09) ─────────────────────────────────────────
// Сервер держит связку «токен → логин» и может перестать узнавать зрителя —
// например, сразу после перезапуска бэкенда. Панель при этом обязана сказать
// «не знаю», а не показать нули: нарисованный ноль зритель читает как «у меня
// украли крустики», а ревьюер Twitch — как «расширение не работает».

function handleAuthLost() {
    // Значения, которых мы НЕ знаем, показываем прочерком, а не нулём.
    const pointsEl = document.getElementById('points');
    if (pointsEl) pointsEl.textContent = '—';
    const incomeEl = document.getElementById('income');
    if (incomeEl) incomeEl.textContent = '—';

    if (_authLost) return;   // не шуметь на каждом опросе, он раз в минуту
    _authLost = true;

    // Сначала пробуем восстановиться молча: повторяем тот же резолв, который
    // делается при загрузке панели. После перезапуска бэкенда этого достаточно,
    // и зритель вообще ничего не заметит.
    if (_authUserId && authToken && _authRecoverTried < 3) {
        _authRecoverTried++;
        getUsernameFromTwitchId(_authUserId, authToken, _authOpaqueId).then(login => {
            if (login && !/^U[a-zA-Z0-9]{8,}$/.test(login)) {
                userLogin = login;
                _authLost = false;
                updateUIAfterAuth();
            } else {
                showNotification('⚠️ Не удалось подтвердить вход — нажми «Войти»', 'warning');
                showLoginPrompt();
            }
        }).catch(() => {
            showNotification('⚠️ Не удалось подтвердить вход — нажми «Войти»', 'warning');
            showLoginPrompt();
        });
        return;
    }

    showNotification('⚠️ Не удалось подтвердить вход — нажми «Войти»', 'warning');
    showLoginPrompt();
}

function showLoginPrompt() {
    const usernameEl = document.getElementById('username');
    if (usernameEl) usernameEl.textContent = 'Не авторизован';

    // Убираем старый промпт если есть
    const old = document.getElementById('login-prompt');
    if (old) old.remove();

    const prompt = document.createElement('div');
    prompt.id = 'login-prompt';
    prompt.style.cssText = 'padding:20px;text-align:center;';
    prompt.innerHTML = `
        <p style="color:#adadb8;font-size:13px;margin-bottom:12px;">
            Для участия нужно войти через Twitch
        </p>
        <button id="login-prompt-btn"
            style="background:#9147ff;color:white;border:none;padding:10px 24px;border-radius:8px;cursor:pointer;font-size:14px;font-weight:700;">
            🔑 Войти
        </button>
    `;

    const panel = document.getElementById('overlay-panel') || document.body;
    panel.insertBefore(prompt, panel.firstChild);

    document.getElementById('login-prompt-btn').addEventListener('click', function() {
        const btn = document.getElementById('login-prompt-btn');
        if (window.Twitch && window.Twitch.ext && window.Twitch.ext.actions && window.Twitch.ext.actions.requestIdShare) {
            if (btn) { btn.textContent = '⏳ Ожидаем...'; btn.disabled = true; }
            window.Twitch.ext.actions.requestIdShare();
            // После подтверждения Twitch сам вызовет onAuthorized заново с реальным user_id
            setTimeout(function() {
                if (document.getElementById('login-prompt-btn') === btn && btn) {
                    btn.textContent = '🔑 Войти'; btn.disabled = false;
                }
            }, 8000);
        } else {
            console.warn('[login] Twitch.ext.actions.requestIdShare недоступен', window.Twitch?.ext?.actions);
            showNotification('⚠️ Авторизация через Twitch недоступна — обнови страницу', 'warning');
        }
    });
}

// ===== БЕЗОПАСНОСТЬ =====
// CRITICAL FIX #3: Use textContent instead of innerHTML for dynamic content
// This is simpler, faster and doesn't require external libraries

// ===== ЧЕРТЫ / ГЕНЫ МАРАКЕРА =====
// Перенесено в viewer-rimworld.js (ROADMAP 2.4, split чанк 3, 2026-06-13).
// Функции: removeMyTrait, startPawnRefresh (+_pawnRefreshTimer), buyTrait,
// buyGene, removeMyGene. Вызываются из shop.js/pawn.js на рантайм-кликах.




function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// ===== RIMWORLD RICH TEXT → HTML =====
// parseRimColor перенесён в viewer-rimworld.js (ROADMAP 2.4, split чанк 4, 2026-06-13).
// Зовётся из pawn.js при рендере (рантайм).
const _cmdCooldowns = {};
const _cdTimers = {}; // активные таймеры обратного отсчёта на кнопках

function checkCooldown(cmdName, ms = 5000, btnEl = null) {
    const now = Date.now();
    if (_cmdCooldowns[cmdName] && now - _cmdCooldowns[cmdName] < ms) {
        const left = Math.ceil((ms - (now - _cmdCooldowns[cmdName])) / 1000);
        showNotification(`⏱ Подожди ${left} сек...`, 'warning');
        return false;
    }
    _cmdCooldowns[cmdName] = now;
    if (btnEl) startBtnCountdown(btnEl, Math.ceil(ms / 1000));
    return true;
}


// startBtnCountdown — объявлена ниже, рядом с healMyPawn


// ===== СПИСОК ОНЛАЙН ПОЛЬЗОВАТЕЛЕЙ =====
let _onlineUsers = [];

async function fetchOnlineUsers() {
    try {
        const r = await fetch(`${API_URL}/api/viewer/online-list`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        const d = await r.json();
        _onlineUsers = (d.users || []).filter(u => u !== userLogin);
    } catch(e) { console.error('[fetchOnlineUsers]', e); }
}

function buildUserSelect(elementId, placeholder = 'Выбери игрока') {
    const el = document.getElementById(elementId);
    if (!el) return;
    const current = el.value;
    el.innerHTML = `<option value="">${placeholder}</option>` +
        _onlineUsers.map(u => `<option value="${escapeHtml(u)}" ${u === current ? 'selected' : ''}>${escapeHtml(u)}</option>`).join('');
}

// ===== ПОЛУЧЕНИЕ USERNAME ПО TWITCH ID =====
async function getUsernameFromTwitchId(twitchId, token, rawOpaqueId = null) {
    // resolve twitchId
    const useToken = token || authToken;
    const cleanId = String(twitchId || '').replace(/^U/, '');
    const opaqueId = rawOpaqueId || twitchId;

    try {
        // Шлём JWT токен + opaque_id на сервер
        const r = await fetch(`${API_URL}/api/user/resolve-twitch-token`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: useToken,
                opaque_id: opaqueId,
                user_id: /^\d+$/.test(cleanId) ? cleanId : null
            })
        });
        const data = await r.json();
        // token resolved

        if (data.login) {
            // логин получен
            showNotification(`👋 Добро пожаловать, ${data.login}!`, 'success');
            return data.login;
        }

        console.warn('⚠️ Не удалось получить логин, требуется разрешение');
        return null;

    } catch (e) {
        console.error('🔽 Ошибка получения логина:', e);
        return null;
    }
}

// Здесь до 2026-07-29 жила requestUserPermissions() — модалка «разреши
// доступ», которую никто не вызывал. Внутри она звала
// Twitch.ext.actions.requestFullAccess(), а такого метода в Extension
// Helper не существует (есть followChannel, minimize, onFollow,
// requestIdShare) — то есть оживить её значило получить TypeError.
// Живой путь входа ниже написан правильно: проверяет наличие метода и
// зовёт requestIdShare. Мёртвый код убран из ZIP, который читает ревьюер.

// ===== НАСТРОЙКА ВКЛАДОК =====
/**
 * Подписи под кнопками главной вкладки — приходят с бэкенда картой «id → текст».
 *
 * ЗАЧЕМ. «Свободен» и «Не состоишь» стояли в разметке намертво и не менялись
 * никогда: женатый зритель всё равно читал «Свободен». Данные для этих подписей
 * существуют давно, их просто никто не подставлял.
 *
 * Список подписей здесь НЕ хранится специально: добавить новую можно будет с
 * бэкенда, а фронт до следующего ревью Twitch заморожен на CDN.
 */
function applyCardSubtitles(subtitles) {
    if (!subtitles) return;
    Object.keys(subtitles).forEach(id => {
        const el = document.getElementById(id);
        if (el && typeof subtitles[id] === 'string') el.textContent = subtitles[id];
    });
}

/**
 * Приглашение к первому шагу для зрителя без персонажа.
 *
 * ЗАЧЕМ (разбор воронки по боевой базе, 2026-08-05). Из 86 зрителей персонажа
 * завели 18. Среди заведших нет ни одного, кто попробовал пару раз и ушёл:
 * минимум шесть действий, у большинства — десятки, многие возвращались днями.
 * И первое действие у всех одно и то же — создать персонажа. Значит теряем
 * людей не на «непонятном интерфейсе», а ровно на одном шаге, который ничем
 * не выделен среди дюжины равных кнопок.
 *
 * ТОНКИЙ ФРОНТ. Заголовок, текст и надпись на кнопке приходят с бэкенда и
 * рисуются как есть — здесь нет ни списка модулей, ни switch по ним. Появится
 * новая игра — карточка заработает без правки фронта, а она бы ждала ревью
 * Twitch неделями. Здесь только вёрстка и один переход.
 *
 * Кнопка НЕ создаёт персонажа сама, а переводит на вкладку интеграции, где
 * уже живёт выбор культуры и вся проверка условий. Второй путь к тому же
 * действию — как раз то, на чём проект уже обжигался.
 */
function renderFirstStep(step) {
    const el = document.getElementById('first-step-card');
    if (!el) return;
    if (!step || !step.title) { el.innerHTML = ''; return; }

    // Два состояния одного места: приглашение новичку и короткий переход
    // «Твой герой · имя» тому, у кого персонаж уже есть. Что именно показать,
    // решает бэкенд — здесь только вёрстка, без знания о конкретных играх.
    // `enabled: false` присылается, когда нажимать бессмысленно (игра у
    // стримера не запущена): купленное действие простояло бы в очереди полчаса
    // и вернулось возвратом — для новичка это «нажал, ничего не произошло».
    const disabled = step.enabled === false;
    el.innerHTML = `
        <div class="first-step${step.compact ? ' first-step-compact' : ''}">
            <h3>${escapeHtml(step.title)}</h3>
            ${step.text ? `<p>${escapeHtml(step.text)}</p>` : ''}
            <button type="button" id="first-step-go"${disabled ? ' disabled' : ''}>
                ${escapeHtml(step.cta || 'Открыть')}${disabled ? '' : ' →'}
            </button>
        </div>`;

    const btn = disabled ? null : document.getElementById('first-step-go');
    if (btn) {
        btn.addEventListener('click', () => {
            // data-tab="rimworld" — историческое имя вкладки «🔌 Интеграция»
            // (осталось с тех пор, когда игра была одна). Переименование
            // тронет оба шелла и весь switchTab — отдельной правкой.
            const tab = document.querySelector('.tab[data-tab="rimworld"]');
            if (tab) switchTab(tab);
        });
    }
}

function setupTabs() {
    const tabs = document.querySelectorAll('.tab');
    if (!tabs.length) return;
    
    tabs.forEach(tab => {
        // Используем touchstart для мгновенной реакции на мобильных
        tab.addEventListener('touchstart', function(e) {
            // Предотвращаем задержку 300ms на мобильных
            e.preventDefault();
            switchTab(this);
        }, { passive: false });
        
        tab.addEventListener('click', function() {
            switchTab(this);
        });
    });
}

function switchTab(tab) {
    // Мгновенное переключение без задержек
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    
    tab.classList.add('active');
    const tabId = tab.dataset.tab;
    const content = document.getElementById(`${tabId}-tab`);
    if (content) content.classList.add('active');

    // Загружаем данные при переходе на вкладку RimWorld
    if (tabId === 'rimworld') {
        loadMyPawn();
        // Шоп грузим только если ещё не загружен
        if (!shopAllItems || shopAllItems.length === 0) loadShopCatalog();
    }

    if (tabId === 'stats') {
        loadStats();
    }
}

// ===== НАСТРОЙКА ОТСЛЕЖИВАНИЯ АКТИВНОСТИ =====
function setupActivityTracking() {
    sessionStartTime = Date.now();
    lastReportTime = Date.now();
    clickCount = 0;
    moveCount = 0;
    
    document.addEventListener('click', () => {
        clickCount++;
        lastActivityTime = Date.now();
    });
    
    document.addEventListener('mousemove', () => {
        const now = Date.now();
        if (now - lastMoveTime > 2000) {
            moveCount++;
            lastMoveTime = now;
        }
        lastActivityTime = now;
    });
    
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            reportActivity(true);
        } else {
            sessionStartTime = Date.now();
            lastReportTime = Date.now();
        }
    });
    
    startActivityReporting();
    
    window.addEventListener('beforeunload', () => {
        reportActivity(true);
        cleanupAllTimers();
    });
}

// ===== ОТПРАВКА АКТИВНОСТИ =====
function reportActivity(isFinal = false) {
    const now = Date.now();
    const watchTime = Math.floor((now - lastReportTime) / 1000);
    
    if (watchTime < 5 && !isFinal) return;
    
    if (userLogin && userLogin !== 'testuser' && !userLogin.includes('U')) {
        const activityData = {
            username: userLogin,
            watch_time: watchTime,
            total_time: Math.floor((now - sessionStartTime) / 1000),
            active_clicks: clickCount,
            active_moves: moveCount
        };
        
        fetch(`${API_URL}/api/viewer/activity`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify(activityData)
        })
        .then(response => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
        })
        .then(data => {
            if (data.status === 'ok') {
                clickCount = 0;
                moveCount = 0;
                lastReportTime = now;
            }
        })
        .catch(e => console.warn('[activity]', e.message));
    }
}

// ===== ЖИЗНЕННЫЙ ЦИКЛ ОТПРАВКИ СТАТИСТИКИ =====
function startActivityReporting() {
    // Отправляем накопленное время каждые 60 секунд
    safeInterval(() => {
        reportActivity(false);
    }, 60000);
}

// CRITICAL FIX #6: ARIA live regions for screen reader accessibility
function showNotification(message, type = 'info', duration = 3500) {
    // Убираем старое уведомление
    document.querySelectorAll('.notification').forEach(n => n.remove());
    
    const notif = document.createElement('div');
    notif.className = `notification ${type}`;
    // CRITICAL FIX #6: Add aria-live for screen reader announcements
    notif.setAttribute('aria-live', type === 'error' ? 'assertive' : 'polite');
    notif.setAttribute('role', 'alert');
    
    const iconMap = { success:'✅', error:'❌', warning:'⚠️', info:'ℹ️' };
    const icon = iconMap[type] || 'ℹ️';
    notif.innerHTML = `<span class="notif-icon">${icon}</span> ${escapeHtml(message)}`;
    
    // Рендерим внутри панели если она есть, иначе в body
    const panel = document.getElementById('overlay-panel') || document.body;
    panel.appendChild(notif);
    
    setTimeout(() => notif.remove(), duration);
}

// ===== ПОЧТОВЫЙ ЯЩИК ЗРИТЕЛЯ (M103, 2026-07-29) =====
// Зачем: отказ мода возвращал крустики МОЛЧА. Зритель видел, что баланс
// вернулся, и не мог отличить «я сделал не то» от «у них сломалось» — отсюда
// повторные нажатия платных действий (баги #16/#17).
//
// Текст причины приходит с бэкенда ГОТОВЫМ. Словаря кодов здесь нет и быть не
// должно: фронт замерзает на CDN до следующего ревью Twitch, а коды отказа
// появляются с каждым новым действием мода — держи словарь тут, и новый код
// показывался бы зрителю сырым неделями.
let _noticesBusy = false;
const NOTICES_PER_TICK = 3;      // больше трёх подряд — это уже спам
const NOTICE_TOAST_MS = 7000;

async function pollNotices() {
    if (!userLogin || _noticesBusy || document.hidden) return;
    _noticesBusy = true;
    try {
        const resp = await fetch(`${API_URL}/api/notices`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        if (!resp.ok) return;
        const data = await resp.json();
        const items = ((data && data.notices) || []).slice(0, NOTICES_PER_TICK);
        if (!items.length) return;

        let refunded = 0;
        items.forEach((n, i) => {
            const amount = Number(n.amount || 0);
            if (amount > 0) refunded += amount;
            const tail = amount > 0 ? ` Крустики вернулись: +${amount}💎` : '';
            // showNotification убирает предыдущий тост — разводим по времени,
            // иначе из трёх причин зритель увидит только последнюю.
            safeTimeout(() => showNotification(String(n.text || '') + tail,
                                               'warning', NOTICE_TOAST_MS),
                        i * (NOTICE_TOAST_MS + 500));
        });

        // Баланс уже другой — показать его сразу, а не через минутный цикл.
        if (refunded > 0) loadUserData();

        // Подтверждаем показ сразу, а не после последнего тоста: иначе
        // следующий опрос (через 20с) принесёт те же уведомления и покажет их
        // повторно. Цена решения честная — если зритель закроет панель в
        // ближайшие секунды, поздний тост он не увидит, хотя тот уже помечен
        // показанным. Сетевой сбой при этом уведомление НЕ съедает: без
        // успешного ack оно вернётся в следующий опрос.
        await fetch(`${API_URL}/api/notices/ack`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Twitch-JWT': authToken || '',
            },
            body: JSON.stringify({ ids: items.map(n => n.id) }),
        });
    } catch (e) {
        dbg('notices error:', e);
    } finally {
        _noticesBusy = false;
    }
}

// ===== ЗАГРУЗКА ДАННЫХ ПОЛЬЗОВАТЕЛЯ (исправленная) =====
// Поколение запроса состояния. `loadUserData()` зовут из тридцати мест —
// интервал, каждая покупка, восстановление входа, — поэтому два запроса
// регулярно летят одновременно, а сеть не обязана вернуть их по порядку.
// Без этого счётчика панель закрашивал ТОТ, ЧЕЙ ОТВЕТ ПРИШЁЛ ПОСЛЕДНИМ, и
// зритель видел одно из двух: баланс, отправленный ДО покупки («деньги не
// списались» → жмёт ещё раз), либо `unauthorized`, отправленный ДО
// восстановления входа, — он стирал баланс в «—» и показывал карточку входа
// поверх рабочей панели. Держит `scripts/test-frontend-state-race.mjs`.
let _stateSeq = 0;

async function loadUserData() {
    if (!userLogin) return;
    const seq = ++_stateSeq;

    try {
        const response = await fetch(`${API_URL}/api/viewer/stats/${userLogin}`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
            // Safari must not reuse an unauthorized/empty response from an
            // earlier token or backend restart. This also bypasses entries
            // cached before the server started sending Cache-Control: no-store.
            cache: 'no-store',
        });

        // Пока летел этот запрос, ушёл более свежий — его ответ и есть правда.
        // Молча выходим: рисовать устаревшее состояние хуже, чем не рисовать.
        if (seq !== _stateSeq) return;

        // 🔧 ИСПРАВЛЕНИЕ: Проверяем код ответа сервера
        if (!response.ok) {
            // Если сервер вернул 4xx или 5xx, читаем текст ошибки
            const errText = await response.text();
            console.error(`❌ ОШИБКА СЕРВЕРА [${response.status}]:`, errText);
            showNotification('Ошибка загрузки данных с сервера', 'error');
            return;
        }

        // Если всё хорошо (200 OK), парсим JSON
        const data = await response.json();

        // Разбор тела — тоже await, и за это время мог уйти новый запрос.
        // Проверяем ВТОРОЙ раз, иначе устаревший `unauthorized` дошёл бы до
        // handleAuthLost() и погасил панель уже после восстановления входа.
        if (seq !== _stateSeq) return;

        // ВАЖНО: 200 OK — ещё не «всё хорошо». Когда сервер не смог опознать
        // зрителя, он отвечает ИМЕННО 200 с {"status":"unauthorized"} и без
        // поля points. Раньше этот ответ проваливался вниз, и `data.points || 0`
        // рисовал НОЛЬ: баланс, доход, квесты и кейсы обнулялись, а бейдж падал
        // в «Зритель». То есть «у тебя ноль» и «я не знаю, кто ты» выглядели
        // одинаково — один пиксель на два разных смысла.
        // Случай не теоретический: 07.09 так выглядела панель владельца, у
        // которого в базе лежало 11 058 327💎. Ловится это только здесь: HTTP-код
        // честный, ошибок в консоли нет.
        if (data.status === 'unauthorized' || !('points' in data)) {
            console.warn('[stats] сервер не опознал зрителя:', data.status);
            handleAuthLost();
            return;
        }
        _authLost = false;

        const pointsEl = document.getElementById('points');
        if (pointsEl) pointsEl.textContent = data.points || 0;
        _cachedUserPoints = data.points || 0;
        
        const income = data.income_per_min || 0;
        const incomeEl = document.getElementById('income');
        if (incomeEl) incomeEl.textContent = `+${income}`;
        
        renderInventoryCases(data.unopened_cases || {});
        renderQuests(data.quests || []);
        switchIntegrationModule(data.active_module || null);
        renderFirstStep(data.first_step || null);
        applyCardSubtitles(data.card_subtitles || null);
        loadUserLevel();
        
        // Перерисовываем магазин и ивенты с актуальным балансом (кнопки enabled/disabled)
        if (shopAllItems && shopAllItems.length > 0) applyShopFilters();
        if (_activeIntegrationModule === 'rimworld'
            && rimworldEvents && rimworldEvents.length > 0) renderEvents();
        
        // Обновляем счётчик дуэлей
        fetch(`${API_URL}/api/duel/list`, { headers: { 'X-Twitch-JWT': authToken || '' } })
            .then(r => r.json())
            .then(d => {
                const el = document.getElementById('duel-count');
                if (el) el.textContent = (d.duels || []).length + ' активных';
            }).catch(() => {});
        
    } catch (e) {
        console.error('Ошибка loadUserData:', e);
        // #60: явный сигнал зрителю вместо бесконечного «Загрузка…»
        try { showNotification('⚠️ Сервер недоступен — обновите через пару секунд', 'error', 5000); } catch (_) {}
    }
}

// ===== СИСТЕМА УРОВНЕЙ =====
async function loadUserLevel() {
    if (!userLogin) return;
    try {
        const r = await fetch(`${API_URL}/api/user/level/${userLogin}`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        const d = await r.json();
        renderLevelBar(d);
    } catch(e) { console.error('[level]', e); }
}

function renderLevelBar(data) {
    const container = document.getElementById('level-bar-container');
    if (!container) return;
    
    const { level, exp, exp_needed, title, bonus_pct } = data;
    const pct = Math.min(100, Math.round((exp / exp_needed) * 100));
    
    container.innerHTML = `
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
            <div style="background:linear-gradient(135deg,#9147ff,#b47cff);border-radius:10px;padding:4px 10px;font-size:13px;font-weight:700;color:#fff;white-space:nowrap;">
                LVL ${level}
            </div>
            <div style="font-size:11px;color:#adadb8;">${escapeHtml(title)}${bonus_pct > 0 ? ` (+${Number(bonus_pct) || 0}% доход)` : ''}</div>
        </div>
        <div style="height:6px;background:#2d2d2f;border-radius:3px;overflow:hidden;margin-bottom:4px;">
            <div style="height:100%;width:${pct}%;background:linear-gradient(90deg,#9147ff,#b47cff);border-radius:3px;transition:width 0.5s;"></div>
        </div>
        <div style="font-size:10px;color:#666;text-align:right;">${exp} / ${exp_needed} EXP (${pct}%)</div>
    `;
}

// ===== ИНВЕНТАРЬ =====
// MARKET_MIN_PRICES удалён 2026-06-14 (audit) — маркет вырезан Phase 1.C (m8), орфан.


// Русские названия навыков RimWorld (SKILL_LABELS_RU) + localizeSkill —
// перенесено в viewer-rimworld.js (ROADMAP 2.4, split чанк 4, 2026-06-13).
// Зовётся из pawn.js/xenotype.js (рантайм).

// CRAFT_RECIPES + craftItem удалены 2026-05-10 (Phase 1.B compliance rework —
// Twitch Extension Guidelines §6.2.4 + §5.3).

let _cachedInventory = [];

// renderInventory → renderInventoryCases (Phase 8.C, 2026-05-13):
// «Инвентарь» теперь показывает закрытые кейсы per tier, не старые items.
// Items были utility (passive income) — §5.3 ban. Кейсы — fixed-reward
// активити (§6.2.4 compliant, see migrations/m9_cases.py).
//
// Sprint 5.19 (2026-05-20): inventory-list div убран из bot-tab (кейсы теперь
// открываются модалкой через openCasesModal в cases.js). Функция оставлена
// чтобы обновлять badge `inventory-count` в секции «🎁 Награды» из loadUserData.
// Если inventory-list где-то всё ещё есть — рендерим (backward-compat).
function renderInventoryCases(unopenedCounts) {
    const tiers = [
        { key: 'legendary', emoji: '👑', label: 'Легендарный', color: '#fbbf24' },
        { key: 'epic',      emoji: '💠', label: 'Эпический',   color: '#a855f7' },
        { key: 'rare',      emoji: '💎', label: 'Редкий',      color: '#3b82f6' },
        { key: 'common',    emoji: '🎁', label: 'Обычный',     color: 'var(--muted)' },
    ];

    const total = tiers.reduce((s, t) => s + (unopenedCounts[t.key] || 0), 0);
    const countEl = document.getElementById('inventory-count');
    if (countEl) countEl.textContent = total > 0 ? `${total} закрытых` : 'Нет закрытых';

    const container = document.getElementById('inventory-list');
    if (!container) return;  // Sprint 5.19: норма — div больше не в main view

    if (total === 0) {
        container.innerHTML = `
            <div style="font-size:12px;color:#adadb8;text-align:center;padding:14px 8px;">
                Нет закрытых кейсов.<br>
                <span style="font-size:11px;">Они выпадают за активность на стриме.</span>
            </div>`;
        return;
    }

    let html = '';
    tiers.forEach(t => {
        const n = unopenedCounts[t.key] || 0;
        if (n === 0) return;
        html += `
            <div class="inventory-item" data-action="cases" style="cursor:pointer;border:1px solid ${t.color}33;">
                <span class="item-icon" style="font-size:22px;">${t.emoji}</span>
                <div class="item-info">
                    <div class="item-name">${t.label} кейс</div>
                    <div class="item-rarity" style="font-size:11px;color:${t.color};">
                        Кликни чтобы открыть
                    </div>
                </div>
                <div class="item-actions">
                    <div class="item-quantity">×${n}</div>
                </div>
            </div>`;
    });
    container.innerHTML = html;
}

// ===== Bannerlord =====
// 2026-08-20 (шаг 3 плана «ядро + игровые модули»): весь Bannerlord-код
// уехал в viewer-bannerlord.js. Раньше 800+ строк одной игры жили в общем
// файле, и правка Bannerlord означала правку файла всех игр. В ядре остался
// только переключатель — он не знает имён игр.

// 2026-08-19 (шаг 2 плана «ядро + игровые модули»): цепочка if/else на три
// игры заменена реестром (viewer-registry.js). Ядро больше не знает ни имён
// игр, ни id их блоков, ни имён их функций опроса — игра объявляет это сама.
// Инвариант «активна не более одной, остальные остановлены» теперь записан
// один раз в реестре, а не повторяется в каждой ветке.
function switchIntegrationModule(activeModule) {
    _activeIntegrationModule = ShedLink.switchGame(activeModule);
}

// Sprint 5.19 (2026-05-20): quests-list div переехал из bot-tab в модалку
// (openQuestsModal). Кешируем quests чтобы при открытии модалки сразу
// показать актуальные данные без повторного fetch.
let _cachedQuests = [];

function renderQuests(quests) {
    _cachedQuests = quests || [];

    const completed = _cachedQuests.filter(q => q.completed).length;
    const countEl = document.getElementById('quest-count');
    if (countEl) {
        countEl.textContent = _cachedQuests.length === 0
            ? 'Нет квестов'
            : `${completed}/${_cachedQuests.length}`;
    }

    // Рендерим только если div quests-list виден (т.е. модалка открыта)
    const container = document.getElementById('quests-list');
    if (!container) return;

    if (!quests || quests.length === 0) {
        container.innerHTML = '<div class="loading">Нет активных квестов</div>';
        return;
    }

    let html = '';
    quests.forEach(quest => {
        const progress = (quest.current / quest.target) * 100;
        html += `
            <div class="quest-item">
                <div class="quest-header">
                    <span>${escapeHtml(quest.emoji || '')} ${escapeHtml(quest.name || '')}</span>
                    <span>${Number(quest.current)||0}/${Number(quest.target)||0}</span>
                </div>
                <div class="quest-progress">
                    <div class="quest-progress-fill" style="width: ${Math.min(100, progress)}%"></div>
                </div>
                <div class="quest-reward">Награда: +${Number(quest.reward)||0}💎</div>
            </div>
        `;
    });
    container.innerHTML = html;
}

// ===== МОДАЛКИ КВЕСТОВ И ПРОМО (Sprint 5.19, 2026-05-20) =====
// Раньше квесты + промо жили inline на «Бот» вкладке. Теперь — три
// компактные кнопки в секции «🎁 Награды» открывают модалки.

function openQuestsModal() {
    let modal = document.getElementById('quests-modal');
    if (modal) modal.remove();
    modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'quests-modal';

    const completed = _cachedQuests.filter(q => q.completed).length;
    const totalCount = _cachedQuests.length;
    const subtitle = totalCount === 0
        ? 'Сегодня квестов нет'
        : `Выполнено ${completed}/${totalCount}`;

    modal.innerHTML = `
        <div class="modal-content" style="max-width:480px;max-height:85vh;overflow-y:auto;">
            <h2 style="display:flex;align-items:center;justify-content:space-between;">
                <span>📜 Квесты</span>
                <span style="font-size:13px;color:#adadb8;font-weight:500;">${subtitle}</span>
            </h2>
            <div id="quests-list" class="quests-list" style="margin-bottom:12px;">
                <div class="loading">Загрузка...</div>
            </div>
            <button class="modal-btn cancel" data-action="close-modal" style="width:100%;">
                Закрыть
            </button>
        </div>
    `;
    (document.getElementById('overlay-panel') || document.body).appendChild(modal);
    // Сразу рендерим из кеша (loadUserData уже вызвал renderQuests до открытия)
    renderQuests(_cachedQuests);
}

function openPromoModal() {
    let modal = document.getElementById('promo-modal');
    if (modal) modal.remove();
    modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'promo-modal';
    modal.innerHTML = `
        <div class="modal-content" style="max-width:380px;">
            <h2>💌 Промокод</h2>
            <p style="margin-bottom:14px;color:#adadb8;font-size:12px;">
                Введи активный промокод и получи бонус.
            </p>
            <input type="text" id="promo-input" class="modal-input"
                placeholder="Промокод..."
                style="text-transform:uppercase;letter-spacing:1.5px;text-align:center;margin-bottom:10px;">
            <div style="display:flex;gap:8px;">
                <button id="promo-activate-btn" class="modal-btn" style="flex:1;">
                    ✅ Активировать
                </button>
                <button class="modal-btn cancel" data-action="close-modal" style="flex:1;">
                    Отмена
                </button>
            </div>
        </div>
    `;
    (document.getElementById('overlay-panel') || document.body).appendChild(modal);
    // Автофокус на input для удобства мобильного ввода
    setTimeout(() => document.getElementById('promo-input')?.focus(), 50);
}

// ===== TTS «Озвучить сообщение» (Sprint 5.23, 2026-05-21) =====
// Зритель платит 5000💎 за озвучку текста до 200 символов через
// Web Speech API на overlay'е стрима. Cooldown 30s между сообщениями.
function openTtsModal() {
    let modal = document.getElementById('tts-modal');
    if (modal) modal.remove();
    modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'tts-modal';
    const balance = parseInt(document.getElementById('points')?.textContent || '0');
    const ttsCost = corePrice('tts_cost', 5000);
    const ttsMaxLen = corePrice('tts_max_len', 200);
    const canAfford = balance >= ttsCost;
    modal.innerHTML = `
        <div class="modal-content" style="max-width:420px;">
            <h2>🎤 Озвучить сообщение</h2>
            <p style="margin-bottom:10px;color:#adadb8;font-size:12px;">
                Стример услышит твоё сообщение на стриме через TTS.
            </p>
            <textarea id="tts-input" maxlength="${ttsMaxLen}"
                placeholder="Напиши что озвучить..."
                style="width:100%;min-height:90px;background:#2d2d2f;border:1px solid #3d3d3f;
                       border-radius:7px;padding:10px;color:#efeff1;font-size:13px;font-family:inherit;
                       resize:vertical;outline:none;box-sizing:border-box;"></textarea>
            <div style="display:flex;justify-content:space-between;align-items:center;
                        margin-top:8px;margin-bottom:14px;font-size:11px;color:#adadb8;">
                <span id="tts-char-count">0 / ${ttsMaxLen}</span>
                <span style="color:${canAfford ? '#fbbf24' : '#f87171'};font-weight:700;">
                    ${ttsCost}💎 · у тебя ${balance}💎
                </span>
            </div>
            <div style="display:flex;gap:8px;">
                <button id="tts-submit-btn" class="modal-btn" style="flex:1;"
                        ${canAfford ? '' : 'disabled'}>
                    🎤 Озвучить
                </button>
                <button class="modal-btn cancel" data-action="close-modal" style="flex:1;">
                    Отмена
                </button>
            </div>
        </div>
    `;
    (document.getElementById('overlay-panel') || document.body).appendChild(modal);
    const input  = document.getElementById('tts-input');
    const count  = document.getElementById('tts-char-count');
    const submit = document.getElementById('tts-submit-btn');
    input.addEventListener('input', () => {
        count.textContent = `${input.value.length} / ${ttsMaxLen}`;
    });
    submit.addEventListener('click', () => _submitTts(input.value));
    setTimeout(() => input.focus(), 50);
}

async function _submitTts(text) {
    const msg = (text || '').trim();
    if (!msg) return showNotification('Введи сообщение', 'error');
    const ttsMaxLen = corePrice('tts_max_len', 200);
    if (msg.length > ttsMaxLen) {
        return showNotification(`Макс ${ttsMaxLen} символов`, 'error');
    }
    const btn = document.getElementById('tts-submit-btn');
    if (btn) btn.disabled = true;
    try {
        const r = await fetch(`${API_URL}/api/tts/submit`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
            body: JSON.stringify({ message: msg }),
        });
        const d = await r.json();
        showNotification(d.message, d.success ? 'success' : 'error', 4000);
        if (d.success) {
            const modal = document.getElementById('tts-modal');
            if (modal) modal.remove();
            loadUserData();
        } else if (btn) {
            btn.disabled = false;
        }
    } catch (e) {
        showNotification('Ошибка сети', 'error');
        if (btn) btn.disabled = false;
    }
}

// ===== КОЛОНИСТЫ =====
function showConfirm(title, message, onYes) {
    const existing = document.getElementById('confirm-dyn-modal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'confirm-dyn-modal';
    modal.innerHTML = `
        <div class="modal-content" style="max-width:320px;">
            <h2>${title}</h2>
            <p style="margin-bottom:20px;color:#adadb8;text-align:center;">${message}</p>
            <div style="display:flex;gap:10px;">
                <button class="modal-btn" id="confirm-dyn-yes" style="flex:1;">✅ Да</button>
                <button class="modal-btn cancel" id="confirm-dyn-no" style="flex:1;">❌ Нет</button>
            </div>
        </div>
    `;
    (document.getElementById("overlay-panel") || document.body).appendChild(modal);
    document.getElementById('confirm-dyn-yes').onclick = () => { modal.remove(); onYes(); };
    document.getElementById('confirm-dyn-no').onclick = () => modal.remove();
}

// ===== СОЗДАНИЕ ПЕШКИ =====
// Перенесено в viewer-rimworld.js (ROADMAP 2.4, split чанк 4, 2026-06-13).
// showCreatePawnModal + createPawn. Зовётся из create-pawn-btn (рантайм).
async function loadStats() {
    if (!userLogin) return;
    try {
        const h = { headers: { 'X-Twitch-JWT': authToken || '' }, cache: 'no-store' };
        const [statsResp, achResp, streakResp] = await Promise.all([
            fetch(`${API_URL}/api/viewer/stats/${userLogin}`,        h),
            fetch(`${API_URL}/api/viewer/achievements/${userLogin}`, h),
            fetch(`${API_URL}/api/viewer/streak/${userLogin}`,       h),
        ]);
        const statsData  = await statsResp.json();
        const achData    = await achResp.json();
        const streakData = await streakResp.json();
        const stats = statsData.stats || {};

        const wtToday = document.getElementById('watch-time-today');
        if (wtToday) wtToday.textContent = Math.round((stats.watch_time_today || 0) / 60) + ' мин';
        const wtTotal = document.getElementById('watch-time-total');
        if (wtTotal) wtTotal.textContent = Math.round((stats.watch_time_total || 0) / 60) + ' мин';
        const chatToday = document.getElementById('chat-today');
        if (chatToday) chatToday.textContent = stats.chat_messages_today || 0;
        const chatTotal = document.getElementById('chat-total');
        if (chatTotal) chatTotal.textContent = stats.chat_messages_total || 0;
        const chatLen = document.getElementById('chat-length');
        if (chatLen) chatLen.textContent = stats.chat_length_today || 0;

        renderStreak(streakData);
        renderAchievements(achData.achievements || []);
    } catch (e) {
        console.error('Ошибка загрузки статистики:', e);
    }
}

function renderStreak(streakData) {
    const container = document.getElementById('streak-block');
    if (!container) return;
    const cur = streakData.current_streak || 0;
    const max = streakData.max_streak    || 0;
    const reward = (cur + 1) * 1000;
    const pct = Math.min(100, (cur / 10) * 100);
    const fires = cur > 0 ? '🔥'.repeat(Math.min(cur, 10)) : '—';
    container.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <span style="font-weight:700;font-size:13px;">🔥 Стрик стримов</span>
            <span style="font-size:11px;color:#adadb8;">Рекорд: <b style="color:#fbbf24;">${max}</b></span>
        </div>
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
            <div style="flex:1;background:#2d2d2f;border-radius:6px;height:8px;overflow:hidden;">
                <div style="width:${pct}%;height:100%;background:linear-gradient(90deg,#f97316,#fbbf24);border-radius:6px;transition:width 0.4s;"></div>
            </div>
            <span style="font-size:13px;font-weight:800;color:#fbbf24;min-width:20px;text-align:right;">${cur}</span>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:11px;color:#adadb8;">
            <span>${fires}</span>
            <span>Следующий бонус: <b style="color:#4ade80;">+${reward}💎</b></span>
        </div>`;
}

function renderAchievements(achievements) {
    const container = document.getElementById('achievements-list');
    if (!container) return;
    if (!achievements.length) {
        container.innerHTML = '<div class="loading">Нет достижений</div>';
        return;
    }
    const unlocked = achievements.filter(a => a.unlocked);
    const locked   = achievements.filter(a => !a.unlocked);
    let html = '';
    if (unlocked.length) {
        html += `<div style="font-size:11px;font-weight:700;color:#4ade80;margin-bottom:6px;">✅ ПОЛУЧЕНО (${unlocked.length})</div>`;
        html += unlocked.map(a => `
            <div style="display:flex;align-items:center;gap:10px;background:#1a2d1a;border:1px solid #2d4d2d;border-radius:8px;padding:8px 10px;margin-bottom:5px;">
                <div style="font-size:22px;flex-shrink:0;">${a.emoji}</div>
                <div style="flex:1;min-width:0;">
                    <div style="font-size:12px;font-weight:700;color:#e0ffe0;">${escapeHtml(a.name)}</div>
                    <div style="font-size:10px;color:#adadb8;margin-top:1px;">${escapeHtml(a.description)}</div>
                </div>
                <div style="font-size:11px;font-weight:700;color:#4ade80;flex-shrink:0;">+${a.reward}💎</div>
            </div>`).join('');
    }
    if (locked.length) {
        html += `<div style="font-size:11px;font-weight:700;color:var(--dim);margin:10px 0 6px;">🔒 ЗАБЛОКИРОВАНО (${locked.length})</div>`;
        html += locked.map(a => `
            <div style="display:flex;align-items:center;gap:10px;background:#1a1a1c;border:1px solid #2d2d2f;border-radius:8px;padding:8px 10px;margin-bottom:5px;opacity:0.55;">
                <div style="font-size:22px;flex-shrink:0;filter:grayscale(1);">${a.emoji}</div>
                <div style="flex:1;min-width:0;">
                    <div style="font-size:12px;font-weight:700;color:var(--dim);">${escapeHtml(a.name)}</div>
                    <div style="font-size:10px;color:#4d4d4f;margin-top:1px;">${escapeHtml(a.description)}</div>
                </div>
                <div style="font-size:11px;color:var(--dim);flex-shrink:0;">+${a.reward}💎</div>
            </div>`).join('');
    }
    container.innerHTML = html;
}

// ===== ПРИСУТСТВИЕ НА СТРИМЕ =====
let _attendanceMinutes = 0;
let _attendanceInterval = null;

function _startAttendanceTracking() {
    if (_attendanceInterval) return;
    safeInterval(() => { if (userLogin && userLogin !== 'testuser') _attendanceMinutes++; }, 60000);
    _attendanceInterval = safeInterval(async () => {
        if (!userLogin || userLogin === 'testuser' || _attendanceMinutes < 1) return;
        try {
            const r = await fetch(`${API_URL}/api/viewer/attendance`, {
                method: 'POST',
                headers: {'Content-Type':'application/json', 'X-Twitch-JWT': authToken || ''},
                body: JSON.stringify({ username: userLogin, minutes: _attendanceMinutes })
            });
            const data = await r.json();
            if (data.rewarded) {
                showNotification(`🔥 Стрик ${data.current_streak} стримов подряд! +${data.reward}💎`, 'success');
                loadUserData();
                const streakBlock = document.getElementById('streak-block');
                if (streakBlock) loadStats();
            }
        } catch(e) {}
    }, 5 * 60 * 1000);
}


// ===== ПРОМОКОД =====
/** Возвращает true если пользователь авторизован (не testuser и не opaque ID) */
async function usePromo() {
    const code = document.getElementById('promo-input')?.value?.trim().toUpperCase();
    if (!code) { showNotification('❌ Введи промокод', 'error'); return; }
    if (!checkCooldown('promo', 3000)) return;

    try {
        const r = await fetch(`${API_URL}/api/promo/use`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
            body: JSON.stringify({ code })
        });
        const d = await r.json();
        showNotification(d.message, d.success ? 'success' : 'error', 5000);
        if (d.success) {
            // 2026-06-06 FIX — промо это просто очки: обновляем баланс и ВСЁ.
            // Убраны openPassionModal()+startPawnRefresh() — это RimWorld-флоу
            // пешки («огоньки страсти»), попавший сюда copy-paste'ом и всплывавший
            // после активации промо в Bannerlord.
            loadUserData();
        }
    } catch(e) { showNotification('❌ Ошибка', 'error'); }
}


// ===== СЕМЬЯ (ЕДИНЫЙ МОДУЛЬ) =====
function closeModal() {
    // Закрываем статичные модалы
    document.querySelectorAll('.modal').forEach(m => m.classList.remove('active'));
    // Удаляем динамические модалы добавленные через appendChild
    ['duels-modal', 'family-modal', 'create-pawn-confirm-modal', 'permission-modal', 'marriage-modal', 'passion-modal', 'xenotype-modal', 'neuro-modal'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.remove();
    });
}

// Функция для ручного обновления и отладки
window.debugPawn = function() {
    dbg('🔧 Ручное обновление пешки...');
    loadMyPawn();
}



// ===== RIMWORLD ИВЕНТЫ (магазин событий) =====
// Перенесено в viewer-rimworld.js (ROADMAP 2.4, split чанк 2, 2026-06-13).
// Функции: loadRimworldEvents, onEventsSearch, renderEvents, buyEvent
// + EVENT_COOLDOWN_MS + event-tick interval. Поведение не изменилось.

// ===== RIMWORLD ONLINE STATUS + IDENTITY-запрос =====
// Перенесено в viewer-rimworld.js (ROADMAP 2.4, split чанк 1, 2026-06-13).
// Функции: checkRimworldStatus, updateRimworldStatusUI, showLoginBanner,
// requestTwitchIdentity + status-poll interval. Поведение не изменилось.

// ===== ФУНКЦИИ ПАНЕЛИ (перенесены из extension.html для CSP) =====
function togglePanel() {
    const panel = document.getElementById('overlay-panel');
    const btn = document.getElementById('overlay-toggle');
    const isOpen = panel.classList.toggle('open');
    const panelWidth = Math.min(420, window.innerWidth);
    if (btn) {
        btn.style.right = isOpen ? panelWidth + 'px' : '0';
        const icon = btn.querySelector('span');
        if (icon) icon.textContent = isOpen ? '✕' : '🌌';
    }
}

function hidePanel() {
    const panel = document.getElementById('overlay-panel');
    panel.style.transition = 'right 0.3s cubic-bezier(0.4, 0, 0.2, 1)';
    panel.style.right = '-' + panel.offsetWidth + 'px';
    // Язычок скрытия уезжает вместе с панелью (багрепорт #20).
    const hideTab = document.getElementById('panel-hide-tab');
    if (hideTab) hideTab.style.display = 'none';
    let restoreBtn = document.getElementById('panel-restore-tab');
    if (!restoreBtn) {
        restoreBtn = document.createElement('button');
        restoreBtn.id = 'panel-restore-tab';
        restoreBtn.innerHTML = '🌌';
        restoreBtn.title = 'Открыть ShedLink';   // было «RimLink» — старое имя проекта
        restoreBtn.onclick = restorePanel;
        document.body.appendChild(restoreBtn);
    }
    restoreBtn.style.display = 'flex';
}

function restorePanel() {
    const panel = document.getElementById('overlay-panel');
    panel.style.right = '0';
    const restoreBtn = document.getElementById('panel-restore-tab');
    if (restoreBtn) restoreBtn.style.display = 'none';
    const hideTab = document.getElementById('panel-hide-tab');
    if (hideTab) hideTab.style.display = 'flex';
}

// ===== БАГРЕПОРТ (бывш. реклама — убрана для §9.3, переделана в багрепорт) =====
function openBugReport() {
    const old = document.getElementById('bug-modal');
    if (old) old.remove();

    const modal = document.createElement('div');
    modal.id = 'bug-modal';
    modal.className = 'modal active';
    modal.innerHTML = `
        <div class="modal-content" style="max-width:400px;">
            <h2>🐛 Сообщить о баге</h2>
            <p style="margin-bottom:10px;color:#adadb8;font-size:13px;">
                Опиши, что сломалось — отправится напрямую стримеру.
            </p>
            <textarea id="bug-text" maxlength="500" rows="4" placeholder="Что пошло не так?"
                style="width:100%;box-sizing:border-box;background:#1f1f23;border:1px solid #3d3d3f;border-radius:10px;color:#efeff1;padding:10px;font-size:13px;resize:vertical;"></textarea>
            <div id="bug-status" style="font-size:12px;margin:8px 0;min-height:14px;"></div>
            <button id="bug-send" style="width:100%;background:#12b886;border:none;color:#fff;padding:12px;border-radius:10px;font-weight:700;font-size:14px;cursor:pointer;">Отправить</button>
            <button id="bug-close" type="button" style="width:100%;margin-top:8px;background:#3d3d3f;border:none;color:#efeff1;padding:10px;border-radius:10px;font-weight:600;font-size:13px;cursor:pointer;">Отмена</button>
        </div>
    `;
    (document.getElementById('overlay-panel') || document.body).appendChild(modal);
    modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
    modal.querySelector('#bug-close').addEventListener('click', () => modal.remove());

    const status = modal.querySelector('#bug-status');
    modal.querySelector('#bug-send').addEventListener('click', async () => {
        const text = (modal.querySelector('#bug-text').value || '').trim();
        if (text.length < 5) { status.textContent = 'Опиши подробнее (мин. 5 символов)'; status.style.color = '#fbbf24'; return; }
        status.textContent = 'Отправка…'; status.style.color = '#adadb8';
        try {
            const r = await fetch(`${API_URL}/api/bug-report`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
                body: JSON.stringify({ message: text }),
            });
            const data = await r.json();
            if (data.success) {
                status.textContent = data.message || 'Отправлено!'; status.style.color = '#34d399';
                setTimeout(() => modal.remove(), 1500);
            } else {
                status.textContent = data.message || 'Не получилось'; status.style.color = '#f87171';
            }
        } catch (e) {
            status.textContent = 'Сеть недоступна — попробуй ещё раз'; status.style.color = '#f87171';
        }
    });
}

// ===== IFRAME DETECTION (перенесено из extension.html) =====
if (window.self !== window.top) {
    document.addEventListener('DOMContentLoaded', () => {
        const btn = document.getElementById('overlay-toggle');
        if (btn) btn.style.display = 'none';
        const panel = document.getElementById('overlay-panel');
        if (panel) { panel.classList.add('open'); panel.style.right = '0'; }
    });
}

window.addEventListener('message', (e) => {
    const ALLOWED_ORIGINS = [
        'https://www.twitch.tv',
        'https://supervisor.ext-twitch.tv',
        window.location.origin,
    ];
    if (!ALLOWED_ORIGINS.includes(e.origin)) return;

    if (e.data?.type === 'HIDE_TOGGLE') {
        const btn = document.getElementById('overlay-toggle');
        if (btn) btn.style.display = 'none';
    }
    if (e.data?.type === 'SET_TEST_USER' && DEBUG) {
        userLogin = e.data.username;
        loadUserData();
        loadMyPawn();
    }
});
