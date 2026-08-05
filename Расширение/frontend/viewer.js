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
        else if (action === 'dice') openDiceModal();
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

    document.addEventListener('change', function(event) {
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        if (target.id === 'mkt-sel') onMktSelChange();
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

// CRITICAL FIX #5: Debouncing for activity tracking to reduce excessive network requests
function debounceActivityReport() {
    const now = Date.now();
    if (now - lastReportTime < ACTIVITY_CONFIG.watch_time_update_interval * 1000) return;
    
    // Send accumulated activity data
    sendActivityData();
    lastReportTime = now;
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

document.addEventListener('DOMContentLoaded', function() {
    dbg('DOM загружен');

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
    if (_authUiInitialized) {
        const usernameEl = document.getElementById('username');
        if (usernameEl) usernameEl.textContent = userLogin;
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
        });
        const d = await r.json();
        if (!d || !d.success) {
            // Sprint 5.31 #45c — больше не silent. Пусть видно в console.
            dbg('[perks] response not success', d);
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
                if (!userLogin && btn) { btn.textContent = '🔑 Войти'; btn.disabled = false; }
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
    el.innerHTML = `
        <div class="first-step${step.compact ? ' first-step-compact' : ''}">
            <h3>${escapeHtml(step.title)}</h3>
            ${step.text ? `<p>${escapeHtml(step.text)}</p>` : ''}
            <button type="button" id="first-step-go">
                ${escapeHtml(step.cta || 'Открыть')} →
            </button>
        </div>`;

    const btn = document.getElementById('first-step-go');
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
async function loadUserData() {
    if (!userLogin) return;
    
    try {
        const response = await fetch(`${API_URL}/api/viewer/stats/${userLogin}`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });

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
        { key: 'common',    emoji: '🎁', label: 'Обычный',     color: '#9ca3af' },
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
                <span style="font-size:11px;">Они выпадают рандомно за активность.</span>
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

// ===== ИНТЕГРАЦИЯ (Sprint 1.5, 2026-05-15) =====
// Switcher tab «🔌 Интеграция» по channel.active_module:
//   'rimworld'   → существующий pawn UI
//   'bannerlord' → bannerlord hero UI + покупка actions
//   null         → подсказка «Подключи модуль игры»
let _bannerlordPollId = null;
let _bannerlordBuffPollId = null;   // 4.6 — periodic GET /api/bannerlord/my-buffs (2.5s)
let _bannerlordBuffTickId = null;   // 4.6 — client-side decrement (1s) для smooth countdown
let _bannerlordBuffs = [];          // 4.6 — last-known buffs cache; entries { power_key, remaining_s }
let _bannerlordCooldowns = [];      // 4.8 — last-known cooldowns; entries { power_key, remaining_s }
let _bannerlordCurrentGearTier = 0; // M20 — last seen gear_tier (cached for shop render)
let _bannerlordTournamentPollId = null;  // Sprint 5.3 — poll /api/bannerlord/tournament (3s)
let _bannerlordTournament = null;        // last snapshot {queue, state, in_queue, my_prediction, config}
let _bannerlordBattlePollId = null;      // Sprint 5.5 — poll /api/bannerlord/battle-status (2s)
let _bannerlordBattle = null;            // last snapshot {in_battle, my_stats, participant_count}
let _bannerlordWasInBattle = false;      // detect new-battle transition для cooldown UI refresh
let _bannerlordLastRetinue = [];         // last retinue snapshot — repaint без re-fetch
let _bannerlordLastHero = null;          // last /my-hero snapshot — для progression modal
let _bnrOptimisticStance = null;         // 2026-06-10 — оптимистичная боевая стойка до эха мода

// Sprint 5.5: helper для проверки battle state (для banner / future use).
function bnrIsInBattle() { return !!(_bannerlordBattle && _bannerlordBattle.in_battle); }
function bnrCanUseActivePowers() {
    return !!(_bannerlordBattle && _bannerlordBattle.in_battle
              && _bannerlordBattle.my_stats && _bannerlordBattle.my_stats.alive);
}

// 2026-06-10 — тосты про отказ действия. Mod отказывает асинхронно (после ACK)
// → крустики возвращаются, но раньше зритель не видел ПОЧЕМУ «не сработало» и
// кликал снова. my-hero отдаёт recent_refunds[{action_id,type,reason,refunded}];
// тут локализуем reason и показываем тост (дедуп по action_id, чтобы 30s-окно
// бэка не плодило повторы между poll'ами).
const _bnrShownRefunds = new Set();
const BNR_REFUSE_REASON_RU = {
    in_mission:             'Нельзя во время боя или миссии',
    no_active_mission:      'Сначала вступи в бой',
    arena_or_tournament:    'Сила недоступна на арене и турнире',
    hero_not_spawned:       'Твой герой ещё не вышел на поле боя',
    hero_not_found_or_dead: 'Герой не найден или мёртв',
    hero_not_found:         'Герой не найден',
    not_enough_hero_gold:   'Не хватает динаров у героя',
    attribute_maxed:        'Атрибут уже на максимуме',
    all_attributes_maxed:   'Все атрибуты прокачаны до максимума',
    no_attributes_object:   'Нет данных по атрибутам героя',
    skill_focus_maxed:      'Фокус навыка уже на максимуме',
    all_skills_focus_maxed: 'Все фокусы прокачаны до максимума',
    no_skills_object:       'Нет данных по навыкам героя',
    is_prisoner:            'Твой герой в плену',
    already_clan_leader:    'Ты уже глава клана',
    not_clan_leader:        'Только для главы клана',
    clan_name_exists:       'Клан с таким именем уже существует',
    no_clan:                'Сначала нужно вступить или создать клан',
    in_player_clan:         'Недоступно в клане игрока',
    already_in_party:       'Отряд уже создан',
    clan_party_limit:       'Достигнут лимит отрядов клана',
    no_kingdom:             'Сначала нужно вступить в королевство',
    not_king:               'Только для короля',
    not_authorized:         'Недостаточно прав',
    not_at_war:             'Вы не в состоянии войны',
    self_target:            'Нельзя выбрать себя',
    target_not_found:       'Цель не найдена',
    town_not_found:         'Город не найден',
    no_campaign:            'Действие сейчас недоступно',
    no_inventory:           'Нет инвентаря',
    no_matching_item:       'Подходящий предмет не найден',
    // 2026-06-15 «Кузница» (перековка качества) — отказы ReforgeQualityHandler.
    already_best:           'Предмет уже наилучшего качества — крустики возвращены',
    slot_empty:             'В этом слоте ничего не надето',
    no_quality_group:       'У этого предмета нельзя улучшить качество',
    no_modifier:            'У этого предмета нет вариантов улучшения качества',
    unknown_slot:           'Неизвестный слот',
};
function _bnrRefuseReasonRu(reason) {
    if (!reason || reason === 'unspecified') return 'Сейчас недоступно';
    if (BNR_REFUSE_REASON_RU[reason]) return BNR_REFUSE_REASON_RU[reason];
    // prefixed диагностические: unknown_skill:X / bad_state:Y / exception:.. / crashed
    const base = reason.split(':')[0];
    if (BNR_REFUSE_REASON_RU[base]) return BNR_REFUSE_REASON_RU[base];
    if (base === 'unknown') return 'Неизвестный параметр действия';
    return 'Действие не удалось';
}
function _bnrNotifyRefunds(list) {
    if (!Array.isArray(list) || !list.length) return;
    if (_bnrShownRefunds.size > 1000) _bnrShownRefunds.clear();   // session safety cap
    for (const rf of list) {
        if (!rf || !rf.action_id || _bnrShownRefunds.has(rf.action_id)) continue;
        _bnrShownRefunds.add(rf.action_id);
        const msg = _bnrRefuseReasonRu(rf.reason)
            + (rf.refunded ? ' — крустики возвращены' : '');
        showNotification('❌ ' + msg, 'warning', 6000);
    }
}

// Sprint 5.5: persist open/closed state у <details> элементов (Топ скиллы /
// Экипировка / Свита) между ре-рендерами hero card. innerHTML replace
// иначе сбрасывает раскрытое состояние каждые 8s.
const _bannerlordDetailsOpen = new Set();
function _bnrDetailsAttr(key) {
    return _bannerlordDetailsOpen.has(key) ? 'open' : '';
}
function _bnrBindDetailsPersistence() {
    document.querySelectorAll('[data-bnr-details]').forEach(el => {
        const key = el.getAttribute('data-bnr-details');
        if (!key || el.dataset.bnrBound === '1') return;
        el.dataset.bnrBound = '1';
        el.addEventListener('toggle', () => {
            if (el.open) _bannerlordDetailsOpen.add(key);
            else _bannerlordDetailsOpen.delete(key);
        });
    });
}
// Sprint M21 — gear upgrade costs в Hero.Gold (in-game динары, не крустики).
// Mirror HERO_GOLD_TIER_COSTS на backend и в UpgradeGearHandler.cs.
// let (не const): thin-front гидрирует значениями с /api/bannerlord/config
// (см. _hydrateBnrConfig в viewer-bannerlord.js). Значения ниже — fallback.
let HERO_GOLD_TIER_COSTS = {
    1:    50_000,
    2:   100_000,
    3:   200_000,
    4:   400_000,
    5:   800_000,
    6: 1_500_000,
};
const _formatBigGold = n => n >= 1_000_000
    ? `${(n / 1_000_000).toFixed(2).replace(/\.?0+$/, '')}М💰`
    : n >= 1_000
        ? `${Math.round(n / 1_000)}К💰`
        : `${n}💰`;
const _formatBigPrice = n => n >= 1_000_000
    ? `${(n / 1_000_000).toFixed(2).replace(/\.?0+$/, '')}М💎`
    : n >= 1_000
        ? `${Math.round(n / 1_000)}К💎`
        : `${n}💎`;

// Sprint 4.7 — UI labels + hardcoded prices для active power buttons.
// Цены rebалансим в админку позже; сейчас просто работающий MVP.
const BNR_POWER_LABELS = {
    heal_burst:         { icon: '💊', label: 'Лечение',  desc: '+50 HP' },
    // 2026-07-24: описание врало. Механику переделали 2026-07-20 (мгновенный AoE
    // по радиусу → бафф «твои удары ломают щиты»), а текст остался старый —
    // зритель платил 200💎 за «мгновенно AoE» и не понимал, почему «ничего не было».
    shield_break_burst: { icon: '🛡️', label: 'Ломать щиты', desc: 'твои удары ломают щиты, 45с' },
    rage:               { icon: '🔥', label: 'Ярость',    desc: 'твой урон умножается, 45с' },
    // 2026-07-24: ключ retribution_toggle переиспользован под «Невидимость»
    // ассасина (docs/SPEC_ASSASSIN_INVIS.md) — отражения урона на нём больше нет.
    // ⚠️ Ярлык менять ВМЕСТЕ с описанием класса assassin (миграция m94 содержит
    // оговорку «кнопка пока подписана Стойкость») — иначе бэк и фронт разъедутся.
    retribution_toggle: { icon: '🌫', label: 'Невидимость', desc: 'враги теряют цель, 45с' },
    // Sprint 5.33 (BLT-parity FX) — character effects.
    // 2026-07-24: тоже врало — 2026-07-20 «яд случайному врагу в 15м» заменили на
    // бафф «попал → отравил», а текст остался про случайного.
    poison_dot:         { icon: '☠',  label: 'Яд',        desc: 'твои попадания травят, 45с' },
    disarm_burst:       { icon: '💥', label: 'Обезоружить', desc: 'Случ. враг роняет оружие' },
    berserker_charge:   { icon: '💨', label: 'Берсерк-рывок', desc: 'бежишь быстрее, 45с' },
    // 2026-05-29 (BLT-parity combat powers) — active варианты.
    lifesteal_burst:    { icon: '🩸', label: 'Вампиризм',   desc: 'часть урона лечит тебя, 45с' },
    ironskin_toggle:    { icon: '🛡', label: 'Железная кожа', desc: 'входящий урон меньше, 45с' },
    explosive_arrows:   { icon: '🧨', label: 'Взрывные стрелы', desc: 'попадания взрываются, 45с' },
    cleave:             { icon: '⚔️', label: 'Рассечение', desc: 'удар задевает соседей, 45с' },
};
// BNR_POWER_PRICES удалён 2026-06-14 — цена активок теперь приходит с бэка
// (POWER_PRICES в routes/bannerlord.py, в current_powers[].price). Тонкий фронт:
// не держим display-копию балансового числа, которое enforce'ит бэк.

function switchIntegrationModule(activeModule) {
    const normalized = ['bannerlord', 'rimworld', 'shedcolony'].includes(activeModule)
        ? activeModule : null;
    _activeIntegrationModule = normalized;

    const empty   = document.getElementById('integration-empty');
    const rim     = document.getElementById('rimworld-content');
    const bnr     = document.getElementById('bannerlord-content');
    const sc      = document.getElementById('shedcolony-content');
    if (!empty || !rim || !bnr) return;

    // 2026-08-05 — раньше название игры записывалось в .panel-title, то есть
    // затирало название расширения: переключил интеграцию — и «ShedLink» из
    // шапки пропал. Теперь игра живёт отдельной подписью под названием.
    const _moduleNameEl = document.getElementById('panel-module-name');
    if (_moduleNameEl) {
        _moduleNameEl.textContent = {
            bannerlord: '⚔️ Bannerlord',
            rimworld:   '🧬 RimWorld',
            shedcolony: '⛏️ Колония',
        }[activeModule] || '';
    }

    if (normalized === 'bannerlord') {
        empty.style.display = 'none';
        rim.style.display = 'none';
        bnr.style.display = '';
        if (sc) sc.style.display = 'none';
        _startBannerlordPolling();
        if (window._stopRimworldPolling) window._stopRimworldPolling();
        if (window._stopShedcolonyPolling) _stopShedcolonyPolling();
    } else if (normalized === 'rimworld') {
        empty.style.display = 'none';
        rim.style.display = '';
        bnr.style.display = 'none';
        if (sc) sc.style.display = 'none';
        _stopBannerlordPolling();
        if (window._startRimworldPolling) window._startRimworldPolling();
        if (window._stopShedcolonyPolling) _stopShedcolonyPolling();
    } else if (normalized === 'shedcolony') {
        empty.style.display = 'none';
        rim.style.display = 'none';
        bnr.style.display = 'none';
        if (sc) sc.style.display = '';
        _stopBannerlordPolling();
        if (window._stopRimworldPolling) window._stopRimworldPolling();
        if (window._startShedcolonyPolling) _startShedcolonyPolling();
    } else {
        empty.style.display = '';
        rim.style.display = 'none';
        bnr.style.display = 'none';
        if (sc) sc.style.display = 'none';
        _stopBannerlordPolling();
        if (window._stopRimworldPolling) window._stopRimworldPolling();
        if (window._stopShedcolonyPolling) _stopShedcolonyPolling();
    }
}

// ===== Daily rewards / Heirs / Family (брак, дети) =====
// Перенесено в viewer-bannerlord.js (ROADMAP 2.4, Bannerlord split чанк 6, 2026-06-13).
// daily(+claim)/heirs/family(+rename/respec/looks/propose-marriage).
// daily — из _startBannerlordPolling; heirs/family — из loadBannerlordHero (рантайм).

// 2026-06-07 — _openProposalsModal удалена: предложения брака теперь инлайн в
// секции семьи (принять/отклонить per-proposal, см. loadBannerlordFamily).

// ===== Vassals / Party orders / Diplomacy / Ransom (династия лидера клана) =====
// Перенесено в viewer-bannerlord.js (ROADMAP 2.4, Bannerlord split чанк 5, 2026-06-13).
// vassals(+create-inline)/party-orders(+inline)/_BNR_POLICIES+diplomacy(+make-peace)/ransom.
// Зовётся из loadBannerlordHero (рантайм, только у clan-leader).

// ───────────────────────────────────────────────────────────────────────────
// Sprint 5.33 (BLT-parity SHOP) — Workshops passive income panel.
// Viewer покупает workshop в town за 2500💎 (чистая 💎 — Hero.Gold капитал
// движком НЕ списывается). Мастерская реально создаётся в игре (передача
// владения через ChangeOwnerOfWorkshopAction) и генерит доход герою.

// Curated vanilla 1.3.x workshop types. Mod валидирует через
// MBObjectManager.GetObject<WorkshopType>(stringId).
// ───────────────────────────────────────────────────────────────────────────
// Sprint 5.33 CURRENCY-1 (2026-05-28) — emoji-clarified price display.
//
// Two currencies в Bannerlord:
//   💎     — krustiki (platform — viewer earns watching/chat, spent на actions)
//   💰     — dinars (Hero.Gold engine in-game gold — earned battles/trade)
//
// 2026-05-29 currency re-map: одно действие = одна валюта. Хелперы ниже
// принимают (crustic, dinars) и для нулевого компонента просто скрывают его
// (см. _bnrPriceHtml/_bnrAfford), так что одновалютные вызовы рендерятся чисто.
//
// Helpers:
//   _bnrPrice(c, d) → HTML span "💎 1000 + 💰 20K" (или одну если другая 0)
//   _bnrCanAfford(c, d) → bool — есть ли у viewer'а обе суммы
//   _bnrAfford(c, d) → {ok, missing: 'crustic'|'dinar'|'both'|null}
//
// _bannerlordLastHero.hero.gold = current Hero.Gold (cached).
// _cachedUserPoints (module) = current 💎 balance (updated on /api/me poll).
// ───────────────────────────────────────────────────────────────────────────

// Sprint 5.33 FLICKER-FIX (2026-05-28) — skip identical innerHTML rewrite.
// Раньше каждый 8s poll re-render'ил весь hero pane + sub-loaders, даже
// если данные не изменились. Browser discard'ил/recreate'ил DOM tree →
// visible flicker.
//
// FLICKER-FIX v2: module-scoped cache keyed by element ID. Раньше cache
// жил на DOM element (`el._lastSmartHtml`). Когда hero body innerHTML
// rewrite'ился (gold/HP change), все sub-slot DIVs (workshops, caravans,
// etc.) re-created → их per-element cache пропадал → cascading flicker.
// Теперь keyed cache survives parent re-render.
const _smartHtmlCache = {};
function _smartInnerHTML(el, html) {
    if (!el) return false;
    const key = el.id;
    // Same html string AND element has content → cache hit, no paint.
    // (Если parent re-rendered и el — fresh empty node, length=0 → paint.)
    if (key && _smartHtmlCache[key] === html && el.innerHTML.length > 0) {
        return false;
    }
    el.innerHTML = html;
    if (key) _smartHtmlCache[key] = html;
    return true;
}

function _bnrFmtN(n) {
    // Compact format: 12345 → "12.3K", 1234 → "1.2K", 999 → "999".
    if (n == null || isNaN(n)) return '0';
    n = Math.abs(Math.round(n));
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M';
    if (n >= 1_000)     return (n / 1_000).toFixed(1).replace(/\.0$/, '') + 'K';
    return String(n);
}

function _bnrPrice(crustic, dinars) {
    // Returns plain text "💎 1000 + 💰 20K". For inline button text.
    const parts = [];
    if (crustic && crustic > 0) parts.push(`💎 ${_bnrFmtN(crustic)}`);
    if (dinars && dinars > 0)   parts.push(`💰 ${_bnrFmtN(dinars)}`);
    return parts.length ? parts.join(' + ') : '💎 0';
}

function _bnrAfford(crustic, dinars) {
    const haveCrustic = (_cachedUserPoints || 0);
    const haveDinars  = (_bannerlordLastHero?.hero?.gold) || 0;
    const lackCrustic = crustic > haveCrustic;
    const lackDinars  = dinars  > haveDinars;
    return {
        ok:      !lackCrustic && !lackDinars,
        lackCrustic, lackDinars,
        haveCrustic, haveDinars,
        needCrustic: crustic || 0,
        needDinars:  dinars  || 0,
    };
}

function _bnrPriceHtml(crustic, dinars) {
    // Color-coded HTML: red на любой компонент которого не хватает.
    const a = _bnrAfford(crustic, dinars);
    const parts = [];
    if (crustic && crustic > 0) {
        const color = a.lackCrustic ? '#f87171' : '#a5f3fc';
        parts.push(`<span style="color:${color};">💎 ${_bnrFmtN(crustic)}</span>`);
    }
    if (dinars && dinars > 0) {
        const color = a.lackDinars ? '#f87171' : '#fbbf24';
        parts.push(`<span style="color:${color};">💰 ${_bnrFmtN(dinars)}</span>`);
    }
    return parts.length ? parts.join(' <span style="color:#6b7280;">+</span> ') : '💎 0';
}

function _bnrAffordTooltip(crustic, dinars) {
    const a = _bnrAfford(crustic, dinars);
    if (a.ok) return `Стоимость: ${_bnrPrice(crustic, dinars)} — хватает ✓`;
    const missing = [];
    if (a.lackCrustic) missing.push(`💎: нужно ${crustic.toLocaleString('ru-RU')}, есть ${a.haveCrustic.toLocaleString('ru-RU')}`);
    if (a.lackDinars)  missing.push(`💰 динаров: нужно ${dinars.toLocaleString('ru-RU')}, есть ${a.haveDinars.toLocaleString('ru-RU')}`);
    return 'Не хватает:\n  • ' + missing.join('\n  • ');
}

// Header strip — current balances. Renders into element by id.
function _bnrRenderBalances(targetId) {
    const el = document.getElementById(targetId);
    if (!el) return;
    const c = window.userPoints || 0;
    const d = (_bannerlordLastHero?.hero?.gold) || 0;
    el.innerHTML = `
        <span style="display:inline-flex;gap:8px;font-size:11px;
                     background:#0a1308;padding:3px 8px;border-radius:3px;
                     border:1px solid #1f2937;">
            <span title="Крустики — платформенная валюта (зарабатываются за просмотр/чат). 1💎 = 5💰 динаров" style="color:#a5f3fc;">
                💎 ${c.toLocaleString('ru-RU')}
            </span>
            <span style="color:#374151;">|</span>
            <span title="Динары — in-game Hero.Gold (зарабатывается боями/торговлей)"
                  style="color:#fbbf24;">
                💰 ${d.toLocaleString('ru-RU')} дин.
            </span>
        </span>`;
}

// ───────────────────────────────────────────────────────────────────────────
// Sprint 5.33 CATALOG-3 (2026-05-28) — live settlements catalog from mod.
//
// Mod пушит /v1/module/bannerlord/event:world.settlements_catalog со списком
// всех engine settlements. Backend кэширует per-channel. Endpoint:
//   GET /api/bannerlord/settlements?type=town
//
// Cached на frontend в _bnrSettlementsCache (refresh при первом fetch +
// при open модала). Filtered by type для каждого use case.
// ───────────────────────────────────────────────────────────────────────────

let _bnrSettlementsCache = null;   // { ts, by_type: {town: [...], castle: [...]}}
let _bnrSettlementsFetching = null; // promise если уже в полёте

async function _bnrFetchSettlements(force = false) {
    if (!force && _bnrSettlementsCache &&
        Date.now() - _bnrSettlementsCache.ts < 60_000) {
        return _bnrSettlementsCache.by_type;
    }
    if (_bnrSettlementsFetching) return _bnrSettlementsFetching;
    _bnrSettlementsFetching = (async () => {
        try {
            const r = await fetch(`${API_URL}/api/bannerlord/settlements`, {
                headers: { 'X-Twitch-JWT': authToken || '' },
            }).then(r => r.json()).catch(() => ({success: false}));
            const all = (r.success && Array.isArray(r.settlements))
                        ? r.settlements : [];
            const by_type = { town: [], castle: [], village: [], other: [] };
            for (const s of all) {
                const t = (s.type || 'other');
                if (!by_type[t]) by_type[t] = [];
                by_type[t].push(s);
            }
            // Sort each by name для предсказуемого UX
            for (const t of Object.keys(by_type)) {
                by_type[t].sort((a, b) =>
                    (a.name || '').localeCompare(b.name || '', 'ru'));
            }
            _bnrSettlementsCache = { ts: Date.now(), by_type };
            return by_type;
        } catch (e) {
            console.warn('[FE-CATALOG] fetch failed', e);
            return { town: [], castle: [], village: [], other: [] };
        } finally {
            _bnrSettlementsFetching = null;
        }
    })();
    return _bnrSettlementsFetching;
}

// Renders a <select> с группировкой по culture/faction.
function _bnrRenderSettlementSelect(settlements, opts) {
    opts = opts || {};
    const inputId = opts.id || 'bnr-settlement-select';
    if (!settlements || settlements.length === 0) {
        return `
            <div style="font-size:11px;color:#fb7185;padding:6px;background:#2a0a0a;
                        border-radius:3px;">
                ⚠ Мод не передал список settlements (game не запущена или
                устаревший mod). Перезагрузи save в игре.
            </div>
            <input type="hidden" id="${inputId}" value="">
            <input type="hidden" id="${inputId}-name" value="">`;
    }
    // Group by faction name
    const byFaction = {};
    for (const s of settlements) {
        const k = s.faction_n || s.faction || '— нейтральные —';
        if (!byFaction[k]) byFaction[k] = [];
        byFaction[k].push(s);
    }
    const factionNames = Object.keys(byFaction).sort((a, b) =>
        a.localeCompare(b, 'ru'));
    const optgroups = factionNames.map(fn => {
        const items = byFaction[fn].map(s => `
            <option value="${escapeHtml(s.id)}"
                    data-name="${escapeHtml(s.name)}">
                ${escapeHtml(s.name)}
            </option>`).join('');
        return `<optgroup label="${escapeHtml(fn)}">${items}</optgroup>`;
    }).join('');
    return `
        <select id="${inputId}"
                style="width:100%;padding:6px;font-size:12px;
                       background:#0a1308;color:#d9f99d;
                       border:1px solid #65a30d;box-sizing:border-box;">
            <option value="">— выбери из списка —</option>
            ${optgroups}
        </select>`;
}

// ===== Workshops (мастерские) =====
// Перенесено в viewer-bannerlord.js (ROADMAP 2.4, Bannerlord split чанк 3, 2026-06-13).
// _BNR_WORKSHOP_TYPES + loadBannerlordWorkshops + _renderBuyWorkshopInline. Зовётся из loadBannerlordHero (рантайм).

// ───────────────────────────────────────────────────────────────────────────
// ===== Fiefs / Caravans / Inheritance =====
// Перенесено в viewer-bannerlord.js (ROADMAP 2.4, Bannerlord split чанк 4, 2026-06-13).
// loadBannerlordFiefs/Caravans(+_renderBuyCaravanInline)/CaravanRescues/Inheritance.
// Зовётся из loadBannerlordHero (рантайм).

// Sprint 5.32 — inner tab switcher. 4 panes: combat / hero / inventory / dynasty.
// Состояние persisted в localStorage чтобы при reopen extension вернуться туда же.
function _setBnrInnerTab(tab) {
    const valid = ['combat', 'hero', 'inventory', 'dynasty'];
    if (!valid.includes(tab)) tab = 'combat';
    document.querySelectorAll('.bnr-tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.bnrTab === tab);
    });
    document.querySelectorAll('.bnr-tab-pane').forEach(pane => {
        pane.classList.toggle('active', pane.dataset.bnrPane === tab);
    });
    try { localStorage.setItem('bnr_active_tab', tab); } catch (e) {}
}

function _bindBnrInnerTabs() {
    document.querySelectorAll('.bnr-tab-btn').forEach(btn => {
        if (btn.dataset.bnrBound) return;  // idempotent
        btn.dataset.bnrBound = '1';
        btn.addEventListener('click', () => _setBnrInnerTab(btn.dataset.bnrTab));
    });
    // Restore tab из last session. Sprint 5.32 (revised): default = combat.
    let saved = 'combat';
    try { saved = localStorage.getItem('bnr_active_tab') || 'combat'; } catch (e) {}
    _setBnrInnerTab(saved);
}

function _startBannerlordPolling() {
    if (_bannerlordPollId) return;
    // Thin-front: подтянуть статические цены с бэка один раз при активации модуля.
    if (typeof _hydrateBnrConfig === 'function') _hydrateBnrConfig();
    _bindBnrInnerTabs();
    loadBannerlordHero();
    loadBannerlordShop();
    loadBannerlordStatus();
    loadBannerlordClasses();
    loadBannerlordBuffs();
    loadBannerlordTournament();
    loadBannerlordBattleStatus();
    // Sprint 5.32 #46 — daily reward status. Один раз на startup + после
    // каждого re-render hero pane (через chain inside renderBannerlordHero).
    loadBannerlordDaily();
    // Sprint 5.31 #45e (audit MED-10) — все 4 интервала обёрнуты в
    // safeInterval. Раньше использовали raw setInterval — на cleanupAllTimers()
    // (закрытие страницы / Twitch helper teardown) эти 4 ID не были
    // зарегистрированы в _globalIntervals и оставались висеть до natural GC.
    // AUDIT 2026-05-29 (fix #5): back off ВСЕ Bannerlord-поллеры когда панель
    // не видна (зритель свернул панель / переключил вкладку). Раньше ~16 req/8с
    // уходили на бэк даже для невидимой панели × N зрителей = доминирующая
    // нагрузка. document.hidden=true → skip; на re-show следующий tick подхватит.
    _bannerlordPollId = safeInterval(() => {
        if (document.hidden) return;
        loadBannerlordHero();
        loadBannerlordShop();
        loadBannerlordStatus();
        loadBannerlordClasses();
    }, 8000);
    // Buff HUD: faster poll (2.5s) для смены состояния, плюс client-side
    // decrement (1s) чтобы countdown был smooth между poll'ами.
    _bannerlordBuffPollId = safeInterval(() => { if (!document.hidden) loadBannerlordBuffs(); }, 2500);
    // Tournament: 3s poll — отображает queue / running state / bets
    _bannerlordTournamentPollId = safeInterval(() => { if (!document.hidden) loadBannerlordTournament(); }, 3000);
    // Battle status: 2s poll — banner "идёт бой" + my HP/kills/gold/xp
    _bannerlordBattlePollId = safeInterval(() => { if (!document.hidden) loadBannerlordBattleStatus(); }, 2000);
    // Sprint 5.29 audit fix #37: clock-based recompute вместо decrement.
    // Раньше client-side -1/sec drift'ил когда browser tab throttled (background
    // / mobile sleep). Теперь — каждый tick читает Date.now() и computes
    // remaining_s из expires_at_ms. No drift, выживает throttling и suspend.
    _bannerlordBuffTickId = safeInterval(() => {
        const now = Date.now();
        let buffsChanged = false, cdsChanged = false;
        for (const b of _bannerlordBuffs) {
            const newRem = b.expires_at_ms
                ? Math.max(0, (b.expires_at_ms - now) / 1000)
                : Math.max(0, (b.remaining_s || 0) - 1);
            if (Math.abs(newRem - (b.remaining_s || 0)) >= 0.5) {
                b.remaining_s = newRem;
                buffsChanged = true;
            } else if (newRem === 0 && b.remaining_s !== 0) {
                b.remaining_s = 0;
                buffsChanged = true;
            }
        }
        _bannerlordBuffs = _bannerlordBuffs.filter(b => b.remaining_s > 0);
        for (const c of _bannerlordCooldowns) {
            const newRem = c.expires_at_ms
                ? Math.max(0, (c.expires_at_ms - now) / 1000)
                : Math.max(0, (c.remaining_s || 0) - 1);
            if (Math.abs(newRem - (c.remaining_s || 0)) >= 0.5) {
                c.remaining_s = newRem;
                cdsChanged = true;
            } else if (newRem === 0 && c.remaining_s !== 0) {
                c.remaining_s = 0;
                cdsChanged = true;
            }
        }
        _bannerlordCooldowns = _bannerlordCooldowns.filter(c => c.remaining_s > 0);
        if (buffsChanged) _renderBannerlordBuffs();
        if (cdsChanged || buffsChanged) renderBannerlordActivePowers();
    }, 1000);
}

let _bannerlordClassesCache = null;
// ===== Classes / active powers / summon =====
// Перенесено в viewer-bannerlord.js (ROADMAP 2.4, Bannerlord split чанк 9, 2026-06-13).
// loadBannerlordClasses + class-picker + active-powers + summon-button.
// BNR_POWER_LABELS/PRICES + _bannerlordClassesCache ОСТАЮТСЯ в core (форвард). Callers рантайм.

// ===== Random-equip / retinue / currency converters =====
// Перенесено в viewer-bannerlord.js (ROADMAP 2.4, Bannerlord split чанк 12, 2026-06-13).
// renderBannerlordRandomEquipHtml/_renderEquipRow/retinue/currency converters.
// _formatBigGold/Price + _bannerlordClassesCache ОСТАЮТСЯ в core (форвард). Callers рантайм.

// ===== Sprint 5.8: Focus / Attribute investments (Hero.Gold cost) =====
// Перенесено в viewer-bannerlord.js (ROADMAP 2.4, Bannerlord split чанк 2, 2026-06-13).
// loadBannerlordProgression + консты BNR_SKILLS / BNR_SKILL_LABELS_RU / BNR_ATTRIBUTES /
// BNR_ATTR_* / BNR_FOCUS_TIER_COSTS / BNR_ATTRIBUTE_COST. Зовётся из _startBannerlordPolling.
// NB: BNR_SKILL_LABELS_RU используется hero-card НИЖЕ (кросс-файловая ссылка в рантайме,
// пока hero-card в core; переедет — связь станет внутрифайловой).

// Sprint 5.11: общий helper для открытия modal — clan / kingdom management.
// Содержит варианты create / join / leave в зависимости от текущего state.
// 2026-06-07 — модалка управления кланом УДАЛЕНА: всё инлайн во вкладке «Династия»
// (секция 🏰 Клан для лидера; locked-actions создать/вступить/покинуть для
// clanless/участника). Имя клана — через _renderCreateClanInline/_renderJoinInline.

// ===== Dynasty A: clan-upgrades/forge/achievements/gender/profile/family/clan+kingdom mgmt =====
// Перенесено в viewer-bannerlord.js (ROADMAP 2.4, Bannerlord split чанк 13, 2026-06-13).
// clan-upgrades/forge/achievements/gender/profile/family/dynasty-locked/clan-mgmt/kingdom-mgmt.
// _bnrConfirm/_bnrShowSimpleModal ОСТАЮТСЯ в core (форвард). Callers рантайм (hero-card).

// Common modal shell — для clan / kingdom management.
// Sprint 5.32 BUGFIX — `window.confirm()` тихо подавляется в sandboxed Twitch
// Extension iframe (без allow-modals в sandbox attr) и всегда возвращает false.
// Каждый `if (!confirm(...)) return;` блокировал hero.marry / divorce /
// set_gender / leave_clan / create_party / make_baby / heir respawn etc.
// Этот helper — drop-in замена: показывает HTML-overlay с Да/Нет,
// resolve'ит promise по клику. Используем await pattern в caller'ах.
// 2026-06-07 — подтверждения отключены по просьбе («кнопку нажал — сработало»):
// клик = сразу действие, без попапа да/нет. Пасс-тру всегда resolve(true) — все
// вызовы `if (!await _bnrConfirm(...)) return;` проходят насквозь. Аргументы
// (message/labels) игнорируются. Вернуть диалог для конкретного действия —
// восстановить overlay-реализацию из git-истории этого файла.
function _bnrConfirm(message, confirmLabel = 'Да', cancelLabel = 'Отмена') {
    return Promise.resolve(true);
}

// 2026-07-24 — ОТДЕЛЬНАЯ функция ТОЛЬКО для необратимых и очень дорогих действий.
// Решение «кнопку нажал — сработало» остаётся в силе для всего остального: обычные
// покупки как были, мгновенные. Но аудит показал край — «Нанять вассальный клан за
// 3 000 000💰» уходил по ОДНОМУ клику, а написанный текст подтверждения зритель
// никогда не видел (_bnrConfirm — пасс-тру). Промах мышью = минус три миллиона.
// Сюда подключены только: наём вассала, продажа мастерской/каравана, выброс предмета.
function _bnrConfirmDanger(message, confirmLabel = 'Да, я уверен') {
    return new Promise(resolve => {
        let answered = false;
        showConfirm('⚠️ Подтверди', message, () => { answered = true; resolve(true); });
        // showConfirm зовёт onYes только на «Да»; на «Нет»/закрытие модалка просто
        // исчезает — ловим это, чтобы промис не висел вечно.
        const modal = document.getElementById('confirm-dyn-modal');
        if (!modal) { resolve(true); return; }   // модалка не поднялась → не блокируем
        const obs = new MutationObserver(() => {
            if (!document.getElementById('confirm-dyn-modal')) {
                obs.disconnect();
                if (!answered) resolve(false);
            }
        });
        obs.observe(modal.parentNode || document.body, { childList: true });
    });
}

function _bnrShowSimpleModal({ title, body, bind }) {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);' +
        'display:flex;align-items:center;justify-content:center;z-index:9999;padding:10px;';
    overlay.innerHTML = `
        <div style="background:#18181b;border:1px solid #3d3d3f;border-radius:8px;
                    padding:18px;max-width:340px;width:100%;">
            <div style="display:flex;justify-content:space-between;align-items:center;
                        margin-bottom:12px;border-bottom:1px solid #3d3d3f;padding-bottom:8px;">
                <h3 style="margin:0;font-size:14px;color:#efeff1;">${title}</h3>
                <button class="small-btn bnr-modal-close-btn"
                        style="padding:4px 10px;font-size:11px;background:#3d3d3f;">✕</button>
            </div>
            ${body}
        </div>`;
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    overlay.querySelector('.bnr-modal-close-btn')?.addEventListener('click', close);
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
    if (typeof bind === 'function') bind(overlay);
}

// ===== Part B: create-kingdom/join/create-clan inline + bind-random-equip =====
// Перенесено в viewer-bannerlord.js (ROADMAP 2.4, Bannerlord split чанк 14, 2026-06-13).
// _renderCreateKingdomInline/_renderJoinInline/_renderCreateClanInline/_bindBannerlordRandomEquip.
// Зовутся из Part-A + shop (bannerlord.js). Callers рантайм.

// Sprint 4.6 — buff HUD: chip-list с current remaining time.
// ===== Buffs HUD (активные баффы/кулдауны) =====
// Перенесено в viewer-bannerlord.js (ROADMAP 2.4, Bannerlord split чанк 10, 2026-06-13).
// loadBannerlordBuffs + _renderBannerlordBuffs. BNR_POWER_LABELS + стейт остаются в core (форвард).

// ===== Status badge (онлайн/оффлайн Bannerlord) =====
// Перенесено в viewer-bannerlord.js (ROADMAP 2.4, Bannerlord split чанк 11, 2026-06-13).
// loadBannerlordStatus. Зовётся из _startBannerlordPolling (рантайм).

function _stopBannerlordPolling() {
    if (_bannerlordPollId) {
        clearInterval(_bannerlordPollId);
        _bannerlordPollId = null;
    }
    if (_bannerlordBuffPollId) {
        clearInterval(_bannerlordBuffPollId);
        _bannerlordBuffPollId = null;
    }
    if (_bannerlordBuffTickId) {
        clearInterval(_bannerlordBuffTickId);
        _bannerlordBuffTickId = null;
    }
    if (_bannerlordTournamentPollId) {
        clearInterval(_bannerlordTournamentPollId);
        _bannerlordTournamentPollId = null;
    }
    if (_bannerlordBattlePollId) {
        clearInterval(_bannerlordBattlePollId);
        _bannerlordBattlePollId = null;
    }
    _bannerlordBuffs = [];
    _bannerlordCooldowns = [];
    _bannerlordTournament = null;
    _bannerlordBattle = null;
    _bannerlordWasInBattle = false;
}

// ===== Battle status / detachment / stance / banner =====
// Перенесено в viewer-bannerlord.js (ROADMAP 2.4, Bannerlord split чанк 7, 2026-06-13).
// loadBannerlordBattleStatus + detachment-panel + stance + battle-banner.
// Зовётся из _startBannerlordPolling / loadBannerlordHero / loadBannerlordStatus (рантайм).

// ===== Sprint 5.3: Турнир зрителей (BLT-style) =====
// Перенесено в viewer-bannerlord.js (ROADMAP 2.4, Bannerlord split чанк 1, 2026-06-13).
// loadBannerlordTournament + _renderBannerlordTournament + _promptBannerlordPredict
// + TOURNAMENT_PRIZE_GOLD/ROUND_GOLD. Зовётся из _startBannerlordPolling +
// _bannerlordBuyAction (рантайм); viewer-bannerlord.js грузится после viewer.js.

// ===== Hero-card (loadBannerlordHero) =====
// Перенесено в viewer-bannerlord.js (ROADMAP 2.4, Bannerlord split чанк 15, 2026-06-13).
// Центральный рендер героя. Зовёт саб-рендеры (bannerlord.js). _bnrConfirm/_formatBigGold/
// _smartInnerHTML/диспетчер/стейт остаются в core (форвард). Callers рантайм.

// ===== Shop (магазин Bannerlord) =====
// Перенесено в viewer-bannerlord.js (ROADMAP 2.4, Bannerlord split чанк 8, 2026-06-13).
// loadBannerlordShop. Зовёт core currency/random-equip рендеры форвард; callers рантайм.

// Sprint 5.29 audit fix #35: in-flight guard per actionType. Раньше rapid
// double-click → 2 POSTs → 2 charges → 2 actions enqueued. Mod может оба
// выполнить или один отказать, но backend оба раза charged. Двойная оплата
// крустиков. Single-flight per actionType блокирует второй click пока первый
// не завершится. Если в полёте — silent return (toast уже видит первый).
const _bnrInflight = new Set();

// ===== КУЛДАУН НА КНОПКЕ (data-bnr-cd) =====
// 2026-05-29: вместо warning-тоста «способность на перезарядке» показываем
// тикающий отсчёт прямо на кнопке (как у кнопок способностей/призыва).
// Источник истины — _bannerlordCooldowns (poll /my-buffs обновляет, ключ =
// power_key, для action-level CD ключ = сам action_type). Кнопка помечается
// атрибутом data-bnr-cd="<action_type>". Глобальный 1s-тикер сканирует все
// такие кнопки и синхронизирует их состояние. Подход data-driven →
// переживает перерисовку панели (после re-render тикер заново применит CD).

// Сколько секунд осталось по cooldown-ключу (0 = не на CD). Берём абсолютный
// expires_at_ms чтобы не было drift'а при throttled-табе.
function _bnrCdRemaining(key) {
    if (!key) return 0;
    const c = _bannerlordCooldowns.find(x => x.power_key === key);
    if (!c) return 0;
    if (typeof c.expires_at_ms === 'number') {
        return Math.max(0, (c.expires_at_ms - Date.now()) / 1000);
    }
    return c.remaining_s || 0;
}

// Локально проставить/обновить CD (до следующего poll'а). Вызывается из
// dispatcher'а сразу после ответа backend'а — кнопка реагирует мгновенно.
function _bnrSetLocalCooldown(key, seconds) {
    if (!key || !(seconds > 0)) return;
    const expires_at_ms = Date.now() + seconds * 1000;
    const existing = _bannerlordCooldowns.find(c => c.power_key === key);
    if (existing) {
        existing.expires_at_ms = expires_at_ms;
        existing.remaining_s = seconds;
    } else {
        _bannerlordCooldowns.push({ power_key: key, remaining_s: seconds, expires_at_ms });
    }
    _bnrActionCdTick();   // применить немедленно, не ждать тика
}

function _bnrCdLabel(rem) {
    return rem >= 60
        ? `⏳ ${Math.floor(rem / 60)}:${(rem % 60).toString().padStart(2, '0')}`
        : `⏳ ${rem}с`;
}

// Глобальный тик: синхронизирует все [data-bnr-cd] кнопки с _bannerlordCooldowns.
function _bnrActionCdTick() {
    const btns = document.querySelectorAll('[data-bnr-cd]');
    if (!btns.length) return;
    btns.forEach(btn => {
        const key = btn.getAttribute('data-bnr-cd');
        const rem = Math.ceil(_bnrCdRemaining(key));
        if (rem > 0) {
            // Входим/обновляем CD-состояние. Сохраняем оригинальный HTML один раз.
            if (btn.dataset.bnrCdOrig === undefined) {
                btn.dataset.bnrCdOrig = btn.innerHTML;
                btn.dataset.bnrCdWasDisabled = btn.disabled ? '1' : '0';
            }
            btn.disabled = true;
            btn.classList.add('bnr-on-cd');
            const label = _bnrCdLabel(rem);
            if (btn.textContent !== label) btn.textContent = label;
        } else if (btn.dataset.bnrCdOrig !== undefined) {
            // CD истёк — восстанавливаем кнопку.
            btn.innerHTML = btn.dataset.bnrCdOrig;
            btn.disabled = btn.dataset.bnrCdWasDisabled === '1';
            btn.classList.remove('bnr-on-cd');
            delete btn.dataset.bnrCdOrig;
            delete btn.dataset.bnrCdWasDisabled;
        }
    });
}

// P1 #5 — единый affordance-гейт: дим + tooltip «Не хватает» на priced-кнопках
// с атрибутом data-bnr-cost="<крустики>,<динары>". Реюзает _bnrAfford /
// _bnrAffordTooltip. НАМЕРЕННО трогает только title+class (не .disabled и не
// innerHTML) — поэтому композится с cooldown-тиком и серверной валидацией:
// клик не ломается, сервер всё равно refuse'нёт неоплатное действие.
function _bnrAffordTick() {
    const btns = document.querySelectorAll('[data-bnr-cost]');
    if (!btns.length) return;
    btns.forEach(btn => {
        const m = (btn.getAttribute('data-bnr-cost') || '').split(',');
        const c = parseInt(m[0], 10) || 0;
        const d = parseInt(m[1], 10) || 0;
        if (!c && !d) return;
        const a = _bnrAfford(c, d);
        if (!a.ok) {
            if (btn.dataset.bnrAffOrig === undefined) btn.dataset.bnrAffOrig = btn.getAttribute('title') || '';
            btn.setAttribute('title', _bnrAffordTooltip(c, d));
            btn.classList.add('bnr-cant-afford');
        } else if (btn.dataset.bnrAffOrig !== undefined) {
            if (btn.dataset.bnrAffOrig) btn.setAttribute('title', btn.dataset.bnrAffOrig);
            else btn.removeAttribute('title');
            delete btn.dataset.bnrAffOrig;
            btn.classList.remove('bnr-cant-afford');
        }
    });
}

// Один глобальный тикер на страницу (cooldown + affordance).
if (!window._bnrCdTickerStarted) {
    window._bnrCdTickerStarted = true;
    if (!document.getElementById('bnr-afford-style')) {
        const st = document.createElement('style');
        st.id = 'bnr-afford-style';
        st.textContent = '.bnr-cant-afford{opacity:.5!important;filter:grayscale(.4);}';
        document.head.appendChild(st);
    }
    setInterval(() => { _bnrActionCdTick(); _bnrAffordTick(); }, 1000);
}

async function _bannerlordBuyAction(actionType, data) {
    if (!isAuthUser()) {
        showNotification('⚠️ Войдите через Twitch', 'warning');
        return;
    }
    if (_bnrInflight.has(actionType)) {
        console.warn('[BNR action] duplicate-click guarded', actionType);
        return;
    }
    _bnrInflight.add(actionType);
    // Sprint 5.32 (BLT-parity H1) — idempotency client_action_id. Backend
    // m46 UNIQUE partial index на (channel_id, module_id, client_action_id)
    // блокирует двойной charge крустиков при retry (network blip, proxy
    // replay, multi-click обходящий _bnrInflight). crypto.randomUUID
    // доступен на HTTPS (Twitch Extension всегда грузится через HTTPS),
    // fallback — Date.now() + Math.random для совместимости.
    const clientActionId = (window.crypto && window.crypto.randomUUID)
        ? window.crypto.randomUUID()
        : (Date.now().toString(36) + '-' + Math.random().toString(36).slice(2));
    const payload = { ...data, client_action_id: clientActionId };
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/action`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Twitch-JWT': authToken || '',
            },
            body: JSON.stringify({ action_type: actionType, data: payload }),
        });
        const result = await r.json();
        // Sprint 5.29 audit fix #36: backend message в console для audit trail.
        // Раньше backend rejections / silent issues — нечем диагностировать без
        // прикладного breakpoint в DevTools.
        dbg('[BNR action]', actionType,
                    result.success ? '✓' : '✗',
                    result.message || '(no message)',
                    result.perk ? `(perk=${result.perk} ×${result.perk_price_mult})` : '');
        // Sprint 5.30 #40: append perk-badge к toast если discount применён.
        // Sprint 5.33 TOS-COMPLIANCE: sub-based perks removed. Только
        // channel-role perks (broadcaster/moderator) дают discount.
        let toastMsg = result.message || (result.success ? 'OK' : 'Действие не выполнено');
        if (result.success && result.perk && result.perk_price_mult < 1.0) {
            const perkIcons = {
                broadcaster: '👑',
                moderator:   '🛡️',
            };
            const icon = perkIcons[result.perk] || '✨';
            toastMsg = `${toastMsg} (${icon} ×${result.perk_price_mult.toFixed(2)} price)`;
        }
        // Channel-role gate refusal (moderator/broadcaster administrative actions).
        // Subscription tiers are cosmetic-only and never enter this path.
        if (!result.success && result.required_role) {
            const roleLabel = {
                moderator:    '🛡 модераторов',
                broadcaster:  '👑 стримера',
            }[result.required_role] || result.required_role;
            toastMsg = `🔒 ${toastMsg}`;
            // Sprint 5.32 (LOG-4) — categorized prefix [FE-GATE] для grep'а.
            dbg('[FE-GATE]', actionType,
                         `required=${result.required_role} your=${result.your_role}`);
        }
        // Sprint 5.32 (LOG-4) — log на idempotent_replay (H1) чтобы видно
        // когда retry реально срабатывает (дебаг network blip / proxy issues).
        if (result.idempotent_replay) {
            dbg('[FE-IDEM] retry hit', actionType,
                         'action_id=' + result.action_id);
        }
        // 2026-05-29 — кулдаун на кнопке вместо warning-тоста.
        // На успехе с CD — запускаем отсчёт сразу (cooldown_applied_s).
        // На отказе по CD — синхронизируем remaining и НЕ показываем тост,
        // если для этого действия есть помеченная кнопка (она покажет отсчёт).
        const isCdReject = !result.success
            && typeof result.cooldown_remaining_s === 'number'
            && result.cooldown_remaining_s > 0;
        if (result.success
            && typeof result.cooldown_applied_s === 'number'
            && result.cooldown_applied_s > 0) {
            _bnrSetLocalCooldown(actionType, result.cooldown_applied_s);
        }
        if (isCdReject) {
            _bnrSetLocalCooldown(actionType, result.cooldown_remaining_s);
        }
        let _hasCdBtn = false;
        try {
            _hasCdBtn = !!document.querySelector(`[data-bnr-cd="${actionType}"]`);
        } catch (_) { _hasCdBtn = false; }

        // Sprint 5.32 UX — errors longer (6s) чтобы юзер успел прочесть
        // cooldown / refuse сообщения. Success short (3.5s default).
        if (!(isCdReject && _hasCdBtn)) {
            showNotification(toastMsg, result.success ? 'success' : 'error',
                             result.success ? 3500 : 6000);
        }
        if (result.success) {
            if (typeof loadUserData === 'function') loadUserData();
            // Sprint 5.3d: ускоряем UI feedback для bannerlord actions —
            // вместо ожидания 8s polling cycle, дёргаем reload через ~3.5s
            // (после mod poll + apply). Особенно важно для recruit_troops
            // и upgrade_gear — viewer видит результат почти сразу.
            const isBannerlord = actionType.startsWith('hero.')
                || actionType.startsWith('player.')
                || actionType.startsWith('power.')
                || actionType.startsWith('tournament.');
            if (isBannerlord && typeof loadBannerlordHero === 'function') {
                setTimeout(() => {
                    loadBannerlordHero();
                    if (typeof loadBannerlordTournament === 'function') {
                        loadBannerlordTournament();
                    }
                }, 3500);
            }
        }
        return result;
    } catch (e) {
        // Sprint 5.29 audit fix #36: real error в console чтобы можно было
        // диагностировать — раньше «Ошибка сети» без context.
        console.error('[BNR action] network/json error', actionType, e);
        showNotification(`Ошибка сети: ${e.message || e}`, 'error');
    } finally {
        _bnrInflight.delete(actionType);
    }
}

// Refresh button
document.addEventListener('click', (ev) => {
    if (ev.target && ev.target.id === 'refresh-hero-btn') {
        loadBannerlordHero();
        loadBannerlordShop();
    }
});

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
const TTS_COST    = 5000;
const TTS_MAX_LEN = 200;

function openTtsModal() {
    let modal = document.getElementById('tts-modal');
    if (modal) modal.remove();
    modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'tts-modal';
    const balance = parseInt(document.getElementById('points')?.textContent || '0');
    const canAfford = balance >= TTS_COST;
    modal.innerHTML = `
        <div class="modal-content" style="max-width:420px;">
            <h2>🎤 Озвучить сообщение</h2>
            <p style="margin-bottom:10px;color:#adadb8;font-size:12px;">
                Стример услышит твоё сообщение на стриме через TTS.
            </p>
            <textarea id="tts-input" maxlength="${TTS_MAX_LEN}"
                placeholder="Напиши что озвучить..."
                style="width:100%;min-height:90px;background:#2d2d2f;border:1px solid #3d3d3f;
                       border-radius:7px;padding:10px;color:#efeff1;font-size:13px;font-family:inherit;
                       resize:vertical;outline:none;box-sizing:border-box;"></textarea>
            <div style="display:flex;justify-content:space-between;align-items:center;
                        margin-top:8px;margin-bottom:14px;font-size:11px;color:#adadb8;">
                <span id="tts-char-count">0 / ${TTS_MAX_LEN}</span>
                <span style="color:${canAfford ? '#fbbf24' : '#f87171'};font-weight:700;">
                    ${TTS_COST}💎 · у тебя ${balance}💎
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
        count.textContent = `${input.value.length} / ${TTS_MAX_LEN}`;
    });
    submit.addEventListener('click', () => _submitTts(input.value));
    setTimeout(() => input.focus(), 50);
}

async function _submitTts(text) {
    const msg = (text || '').trim();
    if (!msg) return showNotification('Введи сообщение', 'error');
    if (msg.length > TTS_MAX_LEN) {
        return showNotification(`Макс ${TTS_MAX_LEN} символов`, 'error');
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
        const h = { headers: { 'X-Twitch-JWT': authToken || '' } };
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
        html += `<div style="font-size:11px;font-weight:700;color:#6b7280;margin:10px 0 6px;">🔒 ЗАБЛОКИРОВАНО (${locked.length})</div>`;
        html += locked.map(a => `
            <div style="display:flex;align-items:center;gap:10px;background:#1a1a1c;border:1px solid #2d2d2f;border-radius:8px;padding:8px 10px;margin-bottom:5px;opacity:0.55;">
                <div style="font-size:22px;flex-shrink:0;filter:grayscale(1);">${a.emoji}</div>
                <div style="flex:1;min-width:0;">
                    <div style="font-size:12px;font-weight:700;color:#6b7280;">${escapeHtml(a.name)}</div>
                    <div style="font-size:10px;color:#4d4d4f;margin-top:1px;">${escapeHtml(a.description)}</div>
                </div>
                <div style="font-size:11px;color:#6b7280;flex-shrink:0;">+${a.reward}💎</div>
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
        </div>
    `;
    (document.getElementById('overlay-panel') || document.body).appendChild(modal);
    modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });

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
