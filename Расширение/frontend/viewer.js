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
let permissionsRequested = false; // вместо localStorage
let uiUpdateInterval = null;     // защита от множественных setInterval
let _rulectionTimerInterval = null; // таймер обратного отсчёта рулекциона
const _shownWinners = new Set();    // показанные победители (вместо localStorage)
let _cachedUserPoints = 0;          // кэш баланса для renderEvents до обновления DOM
let _cspHandlersBound = false;      // защита от повторного навешивания делегированных обработчиков
let _authUiInitialized = false;     // защита от повторной инициализации после onAuthorized
let _lastRulectionErrorTs = 0;      // антиспам ошибок рулекциона

function setupCspSafeHandlers() {
    if (_cspHandlersBound) return;
    _cspHandlersBound = true;

    document.addEventListener('click', function(event) {
        // casino-bet-btn / slots-spin-btn / data-bet / data-slots-bet удалены 2026-05-10 (Phase 1.A)
        const actionEl = event.target.closest('[data-action],[data-open-modal],[data-toggle-target],[data-close-self-modal],[data-accept-family],[data-close-modal],[data-cat],#create-pawn-btn,#heal-pawn-btn,#btn-resurrect,#market-refresh-btn,#stats-refresh-btn,#refresh-pawn-btn,#panel-hide-btn,#rulection-contribute-btn,#rulection-bid-btn,#promo-activate-btn,#create-colonist-btn');
        if (!actionEl) return;

        if (actionEl.hasAttribute('data-close-modal')) {
            closeModal();
            return;
        }

        if (actionEl.hasAttribute('data-close-self-modal')) {
            actionEl.closest('.modal')?.remove();
            return;
        }

        if (actionEl.id === 'panel-hide-btn') {
            hidePanel();
            return;
        }

        if (actionEl.id === 'rulection-contribute-btn') {
            contributeToPool();
            return;
        }

        if (actionEl.id === 'rulection-bid-btn') {
            placeBidEvent();
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

        // casino/slots handlers удалены 2026-05-10 (Phase 1.A compliance rework)

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

        // 'mkt-list-item' action удалён 2026-05-10 (Phase 1.C compliance rework)
        // 'casino' / 'slots' actions удалены 2026-05-10 (Phase 1.A compliance rework)
        if (action === 'cases') openCasesModal();
        else if (action === 'tictactoe') openTicTacToeModal();
        else if (action === 'dice') openDiceModal();
        else if (action === 'guilds') openGuildsModal();
        else if (action === 'voting') openVotingModal();
        else if (action === 'pets') openPetsModal();
        else if (action === 'duels') openDuels();
        else if (action === 'advertisement') openAdvertisement();
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

// isAuthUser() helper — перенесён из casino.js при его удалении 2026-05-10
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

document.addEventListener('DOMContentLoaded', function() {
    dbg('DOM загружен');
    
    setupTabs();
    setupCspSafeHandlers();
    setupActivityTracking();
    // setupBetInputListener() удалён 2026-05-13 — был в casino.js (Phase 1.A),
    // вызов забыли убрать. Bet-input UI не существует.

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
        loadColonists();
        loadMyPawn();
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
    loadColonists();
    loadMyPawn();
    loadShopCatalog();
    loadRimworldEvents();
    checkRimworldStatus();
    loadRulection(); // загружаем рулекцион сразу при входе
    
    // Запускаем периодическое обновление (только один раз)
    if (!uiUpdateInterval) {
        uiUpdateInterval = safeInterval(() => {
            loadUserData();
            loadColonists();
            // Обновляем стату только если вкладка активна
            const statsTab = document.getElementById('stats-tab');
            if (statsTab && statsTab.classList.contains('active')) loadStats();
        }, 60000);
    }

    // Глобальный polling рулекциона — работает на любой вкладке
    // Интервал: 8 сек в режиме копилки, 4 сек во время активного ивента
    _startRulectionPolling();
    _startAttendanceTracking();
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

// ===== ЧЕРТЫ МАРАКЕРА =====
async function removeMyTrait(traitDef, degree, label) {
    showConfirm('🗑️ Удалить черту', `Удалить черту <b>${escapeHtml(label)}</b> за <b style="color:#f87171;">300💎</b>?`, async () => {
        try {
            const r = await fetch(`${API_URL}/api/rimworld/remove-trait`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
                body: JSON.stringify({ username: userLogin, trait_def: traitDef, degree })
            });
            const d = await r.json();
            showNotification(d.message, d.success ? 'success' : 'error');
            if (d.success) {
                loadUserData();
                setTimeout(() => openPassionModal(), 2000);
                startPawnRefresh();
            }
        } catch(e) { showNotification('❌ Ошибка', 'error'); }
    });
}

let _pawnRefreshTimer = null;

function startPawnRefresh(durationMs = 15000, intervalMs = 3000) {
    if (_pawnRefreshTimer) clearInterval(_pawnRefreshTimer);
    let elapsed = 0;
    _pawnRefreshTimer = setInterval(() => {
        elapsed += intervalMs;
        if (elapsed >= durationMs) {
            clearInterval(_pawnRefreshTimer);
            _pawnRefreshTimer = null;
            return;
        }
        loadMyPawn();
    }, intervalMs);
}

async function buyTrait(traitDef, degree, label, price) {
    if (!checkCooldown('buyTrait', 3000)) return;
    const displayPrice = price || 500;
    showConfirm('✨ Купить черту', `Добавить черту <b>${escapeHtml(label)}</b> за <b style="color:#9147ff;">${displayPrice}💎</b>?`, async () => {
        try {
            const r = await fetch(`${API_URL}/api/rimworld/buy-trait`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
                body: JSON.stringify({ username: userLogin, trait_def: traitDef, degree })
            });
            const d = await r.json();
            showNotification(d.message, d.success ? 'success' : 'error');
            if (d.success) { loadUserData(); startPawnRefresh(); loadShopCatalog(); }
        } catch(e) { showNotification('❌ Ошибка', 'error'); }
    });
}

async function buyGene(geneDef, geneLabel, price) {
    if (!checkCooldown('buyGene', 3000)) return;
    const displayPrice = price || 5000;
    showConfirm('🧬 Купить ген', `Установить ген <b>${escapeHtml(geneLabel)}</b> за <b style="color:#9147ff;">${displayPrice}💎</b>?`, async () => {
        try {
            const r = await fetch(`${API_URL}/api/rimworld/buy-gene`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
                body: JSON.stringify({ username: userLogin, def_name: geneDef })
            });
            const d = await r.json();
            showNotification(d.message, d.success ? 'success' : 'error');
            if (d.success) { loadUserData(); startPawnRefresh(); loadShopCatalog(); }
        } catch(e) { showNotification('❌ Ошибка', 'error'); }
    });
}

async function removeMyGene(geneDef, geneLabel, isOverridden) {
    const overriddenNote = isOverridden
        ? '<br><span style="color:#f59e0b;font-size:11px;">⚠️ Ген сейчас подавлен другим геном, но будет удалён из генома.</span>'
        : '';
    showConfirm('🗑️ Удалить ген',
        `Удалить ген <b>${escapeHtml(geneLabel)}</b> за <b style="color:#f87171;">3000💎</b>?${overriddenNote}`,
        async () => {
            try {
                const r = await fetch(`${API_URL}/api/rimworld/remove-gene`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ username: userLogin, def_name: geneDef, label: geneLabel })
                });
                const d = await r.json();
                showNotification(d.message, d.success ? 'success' : 'error');
            if (d.success) { loadUserData(); startPawnRefresh(); }
            } catch(e) { showNotification('❌ Ошибка', 'error'); }
        }
    );
}




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
// Конвертирует RimWorld теги <color=#hex>текст</color> в HTML <span style="color:...">
// Остальные теги (<b>, <i>, <size=N>) тоже поддерживаются
function parseRimColor(str) {
    if (!str) return '';
    // 1. Сначала экранируем ВСЁ для безопасности
    let safe = escapeHtml(String(str));
    // 2. Восстанавливаем только разрешённые теги (теперь они экранированы: &lt; и &gt;)
    safe = safe.replace(/&lt;color=(#[0-9a-fA-F]{3,8}|[a-zA-Z]{1,20})&gt;/g,
        (_, c) => `<span style="color:${c.replace(/[^a-zA-Z0-9#]/g, '')}">`);
    safe = safe.replace(/&lt;\/color&gt;/g, '</span>');
    safe = safe.replace(/&lt;b&gt;/g, '<b>').replace(/&lt;\/b&gt;/g, '</b>');
    safe = safe.replace(/&lt;i&gt;/g, '<i>').replace(/&lt;\/i&gt;/g, '</i>');
    safe = safe.replace(/&lt;size=\d+&gt;/g, '').replace(/&lt;\/size&gt;/g, '');
    return safe;
}
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
        const r = await fetch(`${API_URL}/api/viewer/online-list`);
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

// ===== ЗАПРОС РАЗРЕШЕНИЯ У ПОЛЬЗОВАТЕЛЯ =====
function requestUserPermissions() {
    dbg('🔐 Запрос разрешения у пользователя');
    
    // Проверяем, не показывали ли уже
    if (permissionsRequested) {
        dbg('⏰ Разрешения уже запрашивались');
        return;
    }
    
    // Создаём модальное окно
    const modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'permission-modal';
    modal.innerHTML = `
        <div class="modal-content" style="max-width: 400px;">
            <h2>🔐 Требуется доступ</h2>
            <p style="margin-bottom: 20px; color: #adadb8;">
                Для загрузки твоего инвентаря, квестов и создания пешки, 
                пожалуйста, разреши доступ к данным профиля.
            </p>
            <p style="margin-bottom: 20px; color: #4ade80; font-size: 14px;">
                ✅ Твои очки и предметы сохранятся!
            </p>
            <button class="modal-btn" id="permission-approve" style="margin-bottom: 10px;">
                ✅ Разрешить доступ
            </button>
            <button class="modal-btn cancel" id="permission-deny">
                ⏸ Продолжить без доступа
            </button>
        </div>
    `;
    (document.getElementById("overlay-panel") || document.body).appendChild(modal);
    
    permissionsRequested = true;
    
    document.getElementById('permission-approve').onclick = () => {
        modal.remove();
        showNotification('🔄 Запрашиваем разрешения...', 'info');
        
        // Запрашиваем разрешения
        if (window.Twitch && window.Twitch.ext) {
            window.Twitch.ext.actions.requestIdShare();
            window.Twitch.ext.actions.requestFullAccess();
            
            // Даём время на получение данных и пробуем снова
            setTimeout(() => {
                getUsernameFromTwitchId(userId).then(login => {
                    userLogin = login;
                    updateUIAfterAuth();
                });
            }, 2000);
        }
    };
    
    document.getElementById('permission-deny').onclick = () => {
        modal.remove();
        userLogin = userId;
        updateUIAfterAuth();
        showNotification('⚠️ Работа в ограниченном режиме', 'warning', 5000);
    };
}

// ===== НАСТРОЙКА ВКЛАДОК =====
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
        // Немедленный refresh при переходе на вкладку (глобальный poll уже работает)
        loadRulection();
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
        _stopRulectionPolling();
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
        loadUserLevel();
        
        // Перерисовываем магазин и ивенты с актуальным балансом (кнопки enabled/disabled)
        if (shopAllItems && shopAllItems.length > 0) applyShopFilters();
        if (rimworldEvents && rimworldEvents.length > 0) renderEvents();
        
        // Обновляем счётчик дуэлей
        fetch(`${API_URL}/api/duel/list`, { headers: { 'X-Twitch-JWT': authToken || '' } })
            .then(r => r.json())
            .then(d => {
                const el = document.getElementById('duel-count');
                if (el) el.textContent = (d.duels || []).length + ' активных';
            }).catch(() => {});
        
    } catch (e) {
        console.error('Ошибка loadUserData:', e);
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
            <div style="font-size:11px;color:#adadb8;">${title}${bonus_pct > 0 ? ` (+${bonus_pct}% доход)` : ''}</div>
        </div>
        <div style="height:6px;background:#2d2d2f;border-radius:3px;overflow:hidden;margin-bottom:4px;">
            <div style="height:100%;width:${pct}%;background:linear-gradient(90deg,#9147ff,#b47cff);border-radius:3px;transition:width 0.5s;"></div>
        </div>
        <div style="font-size:10px;color:#666;text-align:right;">${exp} / ${exp_needed} EXP (${pct}%)</div>
    `;
}

// ===== ИНВЕНТАРЬ =====
const MARKET_MIN_PRICES = { "деревяшка": 10, "камень": 60, "амулет": 320, "корона": 2000 };


// Русские названия навыков RimWorld (def_name → локализация)
const SKILL_LABELS_RU = {
    "Shooting":     "Стрельба",
    "Melee":        "Ближний бой",
    "Construction": "Строительство",
    "Mining":       "Добыча",
    "Cooking":      "Готовка",
    "Plants":       "Растениеводство",
    "Animals":      "Животноводство",
    "Crafting":     "Ремесло",
    "Artistic":     "Искусство",
    "Medicine":     "Медицина",
    "Social":       "Социальность",
    "Intellectual": "Интеллект",
};

/** Возвращает русское название навыка */
function localizeSkill(skill) {
    const def = skill.def_name || skill.name || "";
    return SKILL_LABELS_RU[def] || skill.label || skill.name || def || "?";
}

// CRAFT_RECIPES + craftItem удалены 2026-05-10 (Phase 1.B compliance rework —
// 3/3 gambling: §6.2.4 + §5.3 Twitch Extension Guidelines).

let _cachedInventory = [];

// renderInventory → renderInventoryCases (Phase 8.C, 2026-05-13):
// «Инвентарь» теперь показывает закрытые кейсы per tier, не старые items.
// Items были utility (passive income) — §5.3 ban. Кейсы — fixed-reward
// активити (§6.2.4 compliant, see migrations/m9_cases.py).
//
// ВАЖНО: name collision — в cases.js есть СВОЯ renderCases() для модалки.
// viewer.js грузится ПОСЛЕ cases.js → его function declarations перебивают
// глобальный scope. Поэтому здесь имя `renderInventoryCases`.
function renderInventoryCases(unopenedCounts) {
    const container = document.getElementById('inventory-list');
    if (!container) return;

    const tiers = [
        { key: 'legendary', emoji: '👑', label: 'Легендарный', color: '#fbbf24' },
        { key: 'epic',      emoji: '💠', label: 'Эпический',   color: '#a855f7' },
        { key: 'rare',      emoji: '💎', label: 'Редкий',      color: '#3b82f6' },
        { key: 'common',    emoji: '🎁', label: 'Обычный',     color: '#9ca3af' },
    ];

    const total = tiers.reduce((s, t) => s + (unopenedCounts[t.key] || 0), 0);
    const countEl = document.getElementById('inventory-count');
    if (countEl) countEl.textContent = total;

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

// Sprint M20 — gear upgrade prices (mirror TIER_COSTS на backend) для UI label.
// Server-side enforced — frontend price = display only.
const GEAR_TIER_COSTS = {
    1:    50_000,
    2:   100_000,
    3:   200_000,
    4:   400_000,
    5:   800_000,
    6: 1_500_000,
};
const _formatBigPrice = n => n >= 1_000_000
    ? `${(n / 1_000_000).toFixed(2).replace(/\.?0+$/, '')}М⦷`
    : n >= 1_000
        ? `${Math.round(n / 1_000)}К⦷`
        : `${n}⦷`;

// Sprint 4.7 — UI labels + hardcoded prices для active power buttons.
// Цены rebалансим в админку позже; сейчас просто работающий MVP.
const BNR_POWER_LABELS = {
    heal_burst:         { icon: '💊', label: 'Лечение',  desc: '+50 HP' },
    shield_break_burst: { icon: '🛡️', label: 'Разбить щит', desc: 'AoE, мгновенно' },
    rage:               { icon: '🔥', label: 'Ярость',    desc: 'damage ×, 30с' },
    retribution_toggle: { icon: '↩',  label: 'Возмездие', desc: '+reflect %, 60с' },
};
const BNR_POWER_PRICES = {
    heal_burst:         100,
    shield_break_burst: 200,
    rage:               300,
    retribution_toggle: 300,
};

function switchIntegrationModule(activeModule) {
    const empty   = document.getElementById('integration-empty');
    const rim     = document.getElementById('rimworld-content');
    const bnr     = document.getElementById('bannerlord-content');
    if (!empty || !rim || !bnr) return;

    if (activeModule === 'bannerlord') {
        empty.style.display = 'none';
        rim.style.display = 'none';
        bnr.style.display = '';
        _startBannerlordPolling();
    } else if (activeModule === 'rimworld') {
        empty.style.display = 'none';
        rim.style.display = '';
        bnr.style.display = 'none';
        _stopBannerlordPolling();
    } else {
        empty.style.display = '';
        rim.style.display = 'none';
        bnr.style.display = 'none';
        _stopBannerlordPolling();
    }
}

function _startBannerlordPolling() {
    if (_bannerlordPollId) return;
    loadBannerlordHero();
    loadBannerlordShop();
    loadBannerlordStatus();
    loadBannerlordClasses();
    loadBannerlordBuffs();
    _bannerlordPollId = setInterval(() => {
        loadBannerlordHero();
        loadBannerlordShop();
        loadBannerlordStatus();
        loadBannerlordClasses();
    }, 8000);
    // Buff HUD: faster poll (2.5s) для смены состояния, плюс client-side
    // decrement (1s) чтобы countdown был smooth между poll'ами.
    _bannerlordBuffPollId = setInterval(loadBannerlordBuffs, 2500);
    _bannerlordBuffTickId = setInterval(() => {
        let buffsChanged = false, cdsChanged = false;
        for (const b of _bannerlordBuffs) {
            if (b.remaining_s > 0) {
                b.remaining_s = Math.max(0, b.remaining_s - 1);
                buffsChanged = true;
            }
        }
        _bannerlordBuffs = _bannerlordBuffs.filter(b => b.remaining_s > 0);
        for (const c of _bannerlordCooldowns) {
            if (c.remaining_s > 0) {
                c.remaining_s = Math.max(0, c.remaining_s - 1);
                cdsChanged = true;
            }
        }
        _bannerlordCooldowns = _bannerlordCooldowns.filter(c => c.remaining_s > 0);
        if (buffsChanged) _renderBannerlordBuffs();
        if (cdsChanged || buffsChanged) renderBannerlordActivePowers();
    }, 1000);
}

let _bannerlordClassesCache = null;
async function loadBannerlordClasses() {
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/classes`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        const data = await r.json();
        if (data.success) _bannerlordClassesCache = data;
        // Re-render hero body если он уже отображён — picker появится
        renderBannerlordClassPicker();
    } catch (e) { /* silent */ }
}

function renderBannerlordClassPicker() {
    const slot = document.getElementById('hero-class-picker-slot');
    if (!slot || !_bannerlordClassesCache) return;
    const { classes, current } = _bannerlordClassesCache;
    const currentKey = current?.class_key;
    const currentName = currentKey
        ? (classes.find(c => c.class_key === currentKey)?.name || currentKey)
        : null;

    const optsHtml = classes.map(c => {
        const isCurrent = c.class_key === currentKey;
        return `
            <button class="small-btn"
                    data-bnr-class="${escapeHtml(c.class_key)}"
                    style="background:${isCurrent ? '#9147ff' : '#2d2d2f'};
                           color:#efeff1;padding:6px 10px;margin:2px;font-size:11px;
                           border:1px solid ${isCurrent ? '#fbbf24' : '#3d3d3f'};">
                ${escapeHtml(c.name)}
            </button>`;
    }).join('');

    slot.innerHTML = `
        <div style="font-size:11px;color:#adadb8;margin-top:8px;margin-bottom:4px;">
            ${currentName ? '🎖️ Текущий класс: <b style="color:#fbbf24;">' + escapeHtml(currentName) + '</b>'
                          : '⚠️ Класс не выбран'}
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:2px;margin-bottom:6px;">${optsHtml}</div>
    `;

    slot.querySelectorAll('[data-bnr-class]').forEach(btn => {
        btn.addEventListener('click', () => {
            const classKey = btn.dataset.bnrClass;
            _bannerlordBuyAction('hero.set_class', { price: 0, class_key: classKey });
        });
    });

    // Sprint 4.7: render active power buttons под picker'ом (для current class).
    renderBannerlordActivePowers();
}

// Sprint 4.7 — active power buttons (heal_burst + class-specific actives).
function renderBannerlordActivePowers() {
    const slot = document.getElementById('bnr-active-powers-slot');
    if (!slot) return;
    if (!_bannerlordClassesCache) { slot.innerHTML = ''; return; }
    const powers = _bannerlordClassesCache.current_powers || [];
    if (!powers.length) { slot.innerHTML = ''; return; }

    // Disabled state: если active buff с тем же power_key бежит (4.6) ИЛИ
    // cooldown ещё не истёк (4.8) — нельзя активировать. UX-only check,
    // backend всё равно отклонит /action на 4.8 cooldown server-side.
    const activeKeys = new Set(_bannerlordBuffs.map(b => b.power_key));
    const cdMap = {};
    for (const c of _bannerlordCooldowns) cdMap[c.power_key] = c.remaining_s;

    const btnsHtml = powers.map(p => {
        const meta = BNR_POWER_LABELS[p.power_key];
        if (!meta) return '';
        const price = BNR_POWER_PRICES[p.power_key] ?? 0;
        const isActive = activeKeys.has(p.power_key);
        const cdRem = cdMap[p.power_key] || 0;
        const onCooldown = cdRem > 0;
        const disabled = (isActive || onCooldown) ? 'disabled' : '';
        const bgColor = (isActive || onCooldown) ? '#3d3d3f' : '#2d2d2f';
        const suffix = onCooldown
            ? ` <span style="color:#9ca3af;">${Math.ceil(cdRem)}с</span>`
            : ` <span style="color:#fbbf24;">${price}💎</span>`;
        return `
            <button class="small-btn"
                    data-bnr-power="${escapeHtml(p.power_key)}"
                    data-bnr-price="${price}"
                    ${disabled}
                    title="${escapeHtml(meta.desc)}"
                    style="background:${bgColor};color:#efeff1;padding:6px 8px;
                           margin:2px;font-size:11px;border:1px solid #3d3d3f;
                           ${(isActive || onCooldown) ? 'opacity:0.5;cursor:not-allowed;' : ''}">
                ${meta.icon} ${escapeHtml(meta.label)}${suffix}
            </button>`;
    }).join('');

    slot.innerHTML = `
        <div style="font-size:11px;color:#adadb8;margin-top:8px;margin-bottom:4px;">
            ⚡ Способности
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:2px;margin-bottom:6px;">
            ${btnsHtml}
        </div>`;

    slot.querySelectorAll('[data-bnr-power]').forEach(btn => {
        btn.addEventListener('click', () => {
            const powerKey = btn.dataset.bnrPower;
            const price = parseInt(btn.dataset.bnrPrice, 10) || 0;
            _bannerlordBuyAction('power.activate', { price, power_key: powerKey });
        });
    });

    // Sprint 5.0: summon button (player.spawn) — отдельно, не active power.
    renderBannerlordSummonButton();
    // Sprint 5.1c random-equip перемещён в shop card (loadBannerlordShop рендерит).
}

// Sprint 5.0 — кнопки призыва (player.spawn).
// Cooldown ключ на backend'е = "player.spawn" (общий на обе стороны).
// Цены server-side enforced (SPAWN_PRICES в routes/bannerlord.py).
function renderBannerlordSummonButton() {
    const slot = document.getElementById('bnr-summon-slot');
    if (!slot) return;
    const ALLY_PRICE = 500;
    const ENEMY_PRICE = 1000;   // 2× тролл-tax
    const cdRem = (_bannerlordCooldowns.find(c => c.power_key === 'player.spawn') || {}).remaining_s || 0;
    const onCooldown = cdRem > 0;
    const cdLabel = onCooldown
        ? `<span style="color:#9ca3af;">${Math.ceil(cdRem)}с</span>`
        : '';

    slot.innerHTML = `
        <div style="display:flex;flex-direction:column;gap:4px;margin-top:6px;">
            <button class="modal-btn" id="bnr-summon-ally-btn"
                    ${onCooldown ? 'disabled' : ''}
                    title="Призвать героя в бой на сторону стримера"
                    style="width:100%;padding:7px;font-size:12px;
                           ${onCooldown ? 'opacity:0.5;cursor:not-allowed;' : ''}">
                📯 Призвать за стримера
                ${onCooldown ? cdLabel : `<span style="color:#fbbf24;">${ALLY_PRICE}💎</span>`}
            </button>
            <button class="modal-btn" id="bnr-summon-enemy-btn"
                    ${onCooldown ? 'disabled' : ''}
                    title="Призвать героя ПРОТИВ стримера (на сторону противника)"
                    style="width:100%;padding:7px;font-size:12px;background:#7c1d1d;
                           ${onCooldown ? 'opacity:0.5;cursor:not-allowed;' : ''}">
                ⚔️ Призвать против стримера
                ${onCooldown ? cdLabel : `<span style="color:#fbbf24;">${ENEMY_PRICE}💎</span>`}
            </button>
        </div>`;

    if (!onCooldown) {
        document.getElementById('bnr-summon-ally-btn')?.addEventListener('click', () => {
            _bannerlordBuyAction('player.spawn', { price: ALLY_PRICE, side: 'player' });
        });
        document.getElementById('bnr-summon-enemy-btn')?.addEventListener('click', () => {
            _bannerlordBuyAction('player.spawn', { price: ENEMY_PRICE, side: 'enemy' });
        });
    }
}

// Sprint 5.1c — 3 кнопки random-equip, размещены в shop card "Действия в игре".
// Рендерятся как HTML-блок (renderBannerlordRandomEquipHtml) который
// loadBannerlordShop добавляет перед catalog items.
//   weapon (1M⦷), armor (500K⦷), horse (1.25M⦷ — только mounted classes)
// Цены проверяются server-side (frontend price = display only).
function renderBannerlordRandomEquipHtml() {
    const currentKey = _bannerlordClassesCache?.current?.class_key || '';
    const MOUNTED = new Set(['cavalry', 'camel_cavalry', 'horse_archer', 'camel_archer', 'knight']);
    const isMounted = MOUNTED.has(currentKey);

    const horseDisabled = !isMounted ? 'disabled' : '';
    const horseStyle = !isMounted ? 'opacity:0.5;cursor:not-allowed;' : '';
    const horseTitle = !isMounted
        ? 'Только для конных классов (cavalry / horse_archer / camel_* / knight)'
        : 'Случайный скакун из high-tier пула';

    return `
        <div style="padding:6px 10px 10px 10px;">
            <div style="font-size:11px;color:#adadb8;margin-bottom:4px;">
                🎁 Случайный товар
            </div>
            <div style="display:flex;flex-direction:column;gap:4px;">
                <button class="extra-btn" id="bnr-random-weapon"
                        title="Случайное оружие из high-tier пула"
                        style="font-size:12px;padding:6px;">
                    🗡 Купить оружие <span style="color:#fbbf24;">1М⦷</span>
                </button>
                <button class="extra-btn" id="bnr-random-armor"
                        title="Случайная броня (любой slot) из high-tier пула"
                        style="font-size:12px;padding:6px;">
                    🛡 Купить броню <span style="color:#fbbf24;">500К⦷</span>
                </button>
                <button class="extra-btn" id="bnr-random-horse"
                        ${horseDisabled}
                        title="${horseTitle}"
                        style="font-size:12px;padding:6px;${horseStyle}">
                    🐎 Купить коня <span style="color:#fbbf24;">1.25М⦷</span>
                </button>
            </div>
        </div>`;
}

// Sprint M20 — gear upgrade button (hero.upgrade_gear).
// Tier-based progression: 0→1→…→6. Server-side resolve target_tier и price.
function renderBannerlordGearUpgradeHtml() {
    const currentTier = _bannerlordCurrentGearTier || 0;
    const hasClass = !!_bannerlordClassesCache?.current?.class_key;

    if (currentTier >= 6) {
        return `
            <div style="padding:6px 10px;border-top:1px solid #3d3d3f;margin-top:4px;">
                <div style="font-size:11px;color:#adadb8;margin-bottom:4px;">
                    🛡 Снаряжение
                </div>
                <div style="font-size:11px;color:#fbbf24;text-align:center;padding:4px;">
                    T6 ★ — максимум достигнут
                </div>
            </div>`;
    }

    const targetTier = currentTier + 1;
    const price = GEAR_TIER_COSTS[targetTier] || 0;
    const noClass = !hasClass;
    const title = noClass
        ? 'Сначала выбери класс — он определяет slot template'
        : `Прокачать снаряжение: T${currentTier} → T${targetTier}. Замена всех слотов на random items нужного tier.`;

    return `
        <div style="padding:6px 10px;border-top:1px solid #3d3d3f;margin-top:4px;">
            <div style="font-size:11px;color:#adadb8;margin-bottom:4px;">
                🛡 Снаряжение (текущий: ${currentTier === 0 ? 'базовое' : 'T' + currentTier})
            </div>
            <button class="extra-btn" id="bnr-upgrade-gear-btn"
                    ${noClass ? 'disabled' : ''}
                    title="${escapeHtml(title)}"
                    style="width:100%;font-size:12px;padding:6px;
                           ${noClass ? 'opacity:0.5;cursor:not-allowed;' : ''}">
                ⚒ Улучшить до T${targetTier}
                <span style="color:#fbbf24;">${_formatBigPrice(price)}</span>
            </button>
        </div>`;
}

function _bindBannerlordGearUpgrade() {
    const btn = document.getElementById('bnr-upgrade-gear-btn');
    if (!btn || btn.disabled) return;
    btn.addEventListener('click', () => {
        // Server resolves target_tier и price; frontend только триггер.
        _bannerlordBuyAction('hero.upgrade_gear', {});
    });
}

function _bindBannerlordRandomEquip() {
    const MOUNTED = new Set(['cavalry', 'camel_cavalry', 'horse_archer', 'camel_archer', 'knight']);
    const currentKey = _bannerlordClassesCache?.current?.class_key || '';
    const isMounted = MOUNTED.has(currentKey);

    document.getElementById('bnr-random-weapon')?.addEventListener('click', () => {
        _bannerlordBuyAction('player.equip_item', { random_category: 'weapon' });
    });
    document.getElementById('bnr-random-armor')?.addEventListener('click', () => {
        _bannerlordBuyAction('player.equip_item', { random_category: 'armor' });
    });
    const horseBtn = document.getElementById('bnr-random-horse');
    if (horseBtn && isMounted) {
        horseBtn.addEventListener('click', () => {
            _bannerlordBuyAction('player.equip_item', { random_category: 'horse' });
        });
    }
}

// Sprint 4.6 — buff HUD: chip-list с current remaining time.
async function loadBannerlordBuffs() {
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/my-buffs`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        const data = await r.json();
        if (data.success) {
            _bannerlordBuffs = data.buffs || [];
            _bannerlordCooldowns = data.cooldowns || [];   // Sprint 4.8
            _renderBannerlordBuffs();
            renderBannerlordActivePowers();
        }
    } catch (e) { /* silent — HUD не критичен */ }
}

function _renderBannerlordBuffs() {
    const slot = document.getElementById('bnr-buff-hud');
    if (!slot) return;
    if (!_bannerlordBuffs.length) { slot.innerHTML = ''; return; }

    const chips = _bannerlordBuffs.map(b => {
        const meta = BNR_POWER_LABELS[b.power_key];
        const icon = meta?.icon || '✨';
        const label = meta?.label || b.power_key;
        const sec = Math.ceil(b.remaining_s);
        return `<span style="display:inline-block;background:#9147ff;color:#efeff1;
                              padding:2px 8px;border-radius:10px;font-size:11px;
                              font-weight:700;margin:0 2px;">
            ${icon} ${escapeHtml(label)} ${sec}с
        </span>`;
    }).join('');

    slot.innerHTML = `<div style="padding:4px 0 6px 0;">${chips}</div>`;
}

async function loadBannerlordStatus() {
    const badge = document.getElementById('bannerlord-status-badge');
    if (!badge) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/status`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        const data = await r.json();
        if (data.online) {
            badge.style.color = '#34d399';
            badge.textContent = '🟢 Онлайн';
        } else {
            badge.style.color = '#f87171';
            badge.textContent = '🔴 Оффлайн';
        }
    } catch (e) {
        // silent — badge остаётся прежним
    }
}

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
    _bannerlordBuffs = [];
    _bannerlordCooldowns = [];
}

async function loadBannerlordHero() {
    const body = document.getElementById('hero-body');
    if (!body) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/my-hero`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        const data = await r.json();
        if (!data.success) {
            body.innerHTML = `<div style="color:#f87171;padding:10px;">${escapeHtml(data.message || 'Ошибка')}</div>`;
            return;
        }
        if (!data.has_hero) {
            body.innerHTML = `
                <div style="text-align:center;padding:16px;color:#adadb8;font-size:13px;">
                    <div style="font-size:36px;margin-bottom:8px;">⚔️</div>
                    У тебя ещё нет героя в Bannerlord.<br>
                    <span style="font-size:11px;">
                        Создай нового странника — он появится в случайном городе
                        с нулевыми навыками. Имя героя в игре = твой ник.
                    </span>
                    <div style="margin-top:14px;">
                        <button class="modal-btn"
                                id="bnr-adopt-btn"
                                data-bnr-buy="hero.create"
                                data-bnr-price="0"
                                style="width:auto;padding:8px 18px;">
                            ⚔️ Стать героем
                        </button>
                    </div>
                </div>`;
            // bind через event delegation которое уже есть для других bnr-buy
            const btn = document.getElementById('bnr-adopt-btn');
            if (btn) {
                btn.addEventListener('click', () => _bannerlordBuyAction('hero.create', { price: 0 }));
            }
            return;
        }
        const h = data.hero;
        const aliveBadge = h.is_alive
            ? `<span style="color:#34d399;">●&nbsp;жив</span>`
            : `<span style="color:#f87171;">💀&nbsp;мёртв</span>`;
        const prisonerBadge = h.is_prisoner
            ? ` <span style="color:#fbbf24;">⛓ в плену</span>` : '';

        // Top-5 skills
        const topSkills = (data.skills || []).slice(0, 5).map(s =>
            `<div style="display:flex;justify-content:space-between;font-size:11px;padding:1px 0;">
                <span>${escapeHtml(s.skill_key)}</span>
                <span style="color:#fbbf24;">${s.level}</span>
            </div>`
        ).join('') || '<div style="font-size:11px;color:#adadb8;">Нет данных по скиллам</div>';

        // Equipment
        const eqEntries = Object.entries(data.equipment || {});
        const eqHtml = eqEntries.length
            ? eqEntries.map(([slot, it]) =>
                `<div style="font-size:11px;padding:1px 0;">
                    <span style="color:#adadb8;">${slot}:</span>
                    ${escapeHtml(it.item_name || it.item_id || '—')}
                </div>`).join('')
            : '<div style="font-size:11px;color:#adadb8;">Нет экипировки</div>';

        // Sprint M19: level / clan / kingdom badges
        const clanLabel = h.clan_name ? escapeHtml(h.clan_name) : '<span style="color:#9ca3af;">не вступил</span>';
        const kingdomLabel = h.kingdom_name ? escapeHtml(h.kingdom_name) : '<span style="color:#9ca3af;">не вступил</span>';
        // Sprint M20: gear tier indicator (cached для shop UI)
        const gearTier = h.gear_tier || 0;
        _bannerlordCurrentGearTier = gearTier;
        const gearTierLabel = gearTier === 0
            ? '<span style="color:#9ca3af;">базовое</span>'
            : `<span style="color:#fbbf24;">T${gearTier} ★</span>`;

        body.innerHTML = `
            <div style="padding:8px;">
                <div style="font-weight:700;font-size:15px;margin-bottom:2px;">
                    ${escapeHtml(h.display_name || '—')}
                </div>
                <div style="font-size:11px;color:#adadb8;margin-bottom:8px;">
                    ${aliveBadge}${prisonerBadge}
                    ${h.culture ? ' · ' + escapeHtml(h.culture) : ''}
                    ${h.location ? ' · 📍 ' + escapeHtml(h.location) : ''}
                </div>
                <div style="display:grid;grid-template-columns:auto 1fr;gap:4px 10px;font-size:12px;margin-bottom:8px;">
                    <span style="color:#adadb8;">💰 Динары:</span>
                    <span style="color:#fbbf24;font-weight:700;">${(h.gold || 0).toLocaleString('ru-RU')}</span>
                    <span style="color:#adadb8;">⭐ Уровень:</span>
                    <span style="color:#efeff1;font-weight:700;">${h.level || 1}</span>
                    <span style="color:#adadb8;">🛡 Снаряжение:</span>
                    <span style="color:#efeff1;font-weight:700;">${gearTierLabel}</span>
                    <span style="color:#adadb8;">🏰 Клан:</span>
                    <span style="color:#efeff1;">${clanLabel}</span>
                    <span style="color:#adadb8;">👑 Королевство:</span>
                    <span style="color:#efeff1;">${kingdomLabel}</span>
                </div>
                <div id="bnr-buff-hud"></div>
                <div id="hero-class-picker-slot"></div>
                <div id="bnr-active-powers-slot"></div>
                <div id="bnr-summon-slot"></div>
                <details style="margin-bottom:6px;">
                    <summary style="font-size:11px;color:#adadb8;cursor:pointer;">Топ скиллы</summary>
                    <div style="margin-top:4px;">${topSkills}</div>
                </details>
                <details>
                    <summary style="font-size:11px;color:#adadb8;cursor:pointer;">Экипировка</summary>
                    <div style="margin-top:4px;">${eqHtml}</div>
                </details>
            </div>`;
        renderBannerlordClassPicker();
    } catch (e) {
        body.innerHTML = `<div style="color:#f87171;padding:10px;">Ошибка сети</div>`;
    }
}

async function loadBannerlordShop() {
    const list = document.getElementById('bannerlord-shop-list');
    const cnt  = document.getElementById('bannerlord-shop-count');
    if (!list) return;
    // Sprint M19+M20: random-equip + gear-upgrade всегда сверху.
    const randomEquipBlock = renderBannerlordRandomEquipHtml();
    const gearUpgradeBlock = renderBannerlordGearUpgradeHtml();
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/shop`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        const data = await r.json();
        if (!data.success) {
            list.innerHTML = randomEquipBlock + gearUpgradeBlock +
                `<div class="loading">${escapeHtml(data.message || 'Ошибка')}</div>`;
            _bindBannerlordRandomEquip();
            _bindBannerlordGearUpgrade();
            return;
        }
        const items = data.items || [];
        if (cnt) cnt.textContent = items.length + 4;  // +3 random-equip + 1 gear-upgrade
        if (items.length === 0) {
            list.innerHTML = randomEquipBlock + gearUpgradeBlock + `
                <div style="text-align:center;padding:14px;font-size:11px;color:#adadb8;border-top:1px solid #3d3d3f;margin-top:6px;">
                    Каталог пуст. Мод пришлёт shop-данные когда стример запустит игру.
                </div>`;
            _bindBannerlordRandomEquip();
            _bindBannerlordGearUpgrade();
            return;
        }
        // Каждый item — {catalog_type, entry_id, name?, price?, action_type?, ...}
        const catalogHtml = items.map(it => {
            const name = escapeHtml(it.name || it.entry_id || '?');
            const price = parseInt(it.price || 0, 10);
            const actionType = it.action_type || it.entry_id;
            const canBuy = actionType && _cachedUserPoints >= price;
            return `
                <div class="shop-item">
                    <div class="shop-item-info">
                        <div class="shop-item-name">${name}</div>
                        <div class="shop-item-cat" style="font-size:11px;color:#adadb8;">
                            ${escapeHtml(it.catalog_type || '')}${it.description ? ' · ' + escapeHtml(it.description) : ''}
                        </div>
                    </div>
                    <button class="shop-buy-btn"
                            data-bnr-buy="${escapeHtml(actionType || '')}"
                            data-bnr-price="${price}"
                            ${canBuy ? '' : 'disabled style="opacity:.5;cursor:not-allowed;"'}>
                        ${price.toLocaleString('ru-RU')}💎
                    </button>
                </div>`;
        }).join('');
        list.innerHTML = randomEquipBlock + gearUpgradeBlock + catalogHtml;
        _bindBannerlordRandomEquip();
        _bindBannerlordGearUpgrade();
        // Bind buy handlers для catalog items
        list.querySelectorAll('[data-bnr-buy]').forEach(btn => {
            btn.addEventListener('click', () => {
                const actionType = btn.dataset.bnrBuy;
                const price = parseInt(btn.dataset.bnrPrice || '0', 10);
                _bannerlordBuyAction(actionType, { price });
            });
        });
    } catch (e) {
        list.innerHTML = randomEquipBlock + gearUpgradeBlock +
            `<div class="loading" style="color:#f87171;">Ошибка сети</div>`;
        _bindBannerlordRandomEquip();
        _bindBannerlordGearUpgrade();
    }
}

async function _bannerlordBuyAction(actionType, data) {
    if (!isAuthUser()) {
        showNotification('⚠️ Войдите через Twitch', 'warning');
        return;
    }
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/action`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Twitch-JWT': authToken || '',
            },
            body: JSON.stringify({ action_type: actionType, data }),
        });
        const result = await r.json();
        showNotification(result.message, result.success ? 'success' : 'error');
        if (result.success) {
            if (typeof loadUserData === 'function') loadUserData();
        }
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    }
}

// Refresh button
document.addEventListener('click', (ev) => {
    if (ev.target && ev.target.id === 'refresh-hero-btn') {
        loadBannerlordHero();
        loadBannerlordShop();
    }
});

// ===== РЫНОК =====
function renderQuests(quests) {
    const container = document.getElementById('quests-list');
    if (!container) return;
    
    const completed = quests.filter(q => q.completed).length;
    const countEl = document.getElementById('quest-count');
    if (countEl) countEl.textContent = `${completed}/${quests.length}`;
    
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
function showCreatePawnModal() {
    const balance = parseInt(document.getElementById('points')?.textContent || '0');
    if (balance < 200) {
        showNotification('❌ Нужно 200💎 для создания пешки!', 'error');
        return;
    }
    showConfirm('✨ Создание пешки', `Создать пешку за <b style="color:#9147ff;">200💎</b>?<br><span style="color:#4ade80;">Ник: ${escapeHtml(userLogin)}</span>`, () => createPawn(userLogin));
}

async function createPawn(name) {
    try {
        const response = await fetch(`${API_URL}/api/rimworld/create-pawn`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: userLogin, pawn_name: name })
        });
        const data = await response.json();
        showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) {
                loadUserData();
                showNotification('⏳ Пешка создаётся, данные обновятся через 10 сек...', 'info', 5000);
                startPawnRefresh(25000, 5000);
            }
    } catch (e) {
        showNotification('❌ Ошибка при создании пешки', 'error');
    }
}
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


// ===== КАЗИНО =====
/** Возвращает true если пользователь авторизован (не testuser и не opaque ID) */
async function usePromo() {
    const code = document.getElementById('promo-input')?.value?.trim().toUpperCase();
    if (!code) { showNotification('❌ Введи промокод', 'error'); return; }
    if (!checkCooldown('promo', 3000)) return;

    try {
        const r = await fetch(`${API_URL}/api/promo/use`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ username: userLogin, code })
        });
        const d = await r.json();
        showNotification(d.message, d.success ? 'success' : 'error', 5000);
            if (d.success) {
                loadUserData();
                setTimeout(() => openPassionModal(), 2000);
                startPawnRefresh();
            }
    } catch(e) { showNotification('❌ Ошибка', 'error'); }
}


// ===== СЕМЬЯ (ЕДИНЫЙ МОДУЛЬ) =====
function closeModal() {
    // Закрываем статичные модалы
    document.querySelectorAll('.modal').forEach(m => m.classList.remove('active'));
    // Удаляем динамические модалы добавленные через appendChild
    ['duels-modal', 'transfer-modal', 'family-modal', 'create-pawn-confirm-modal', 'permission-modal', 'marriage-modal', 'passion-modal', 'xenotype-modal', 'neuro-modal'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.remove();
    });
}

// Функция для ручного обновления и отладки
window.debugPawn = function() {
    dbg('🔧 Ручное обновление пешки...');
    loadMyPawn();
}



// ╔══════════════════════════════════════════════════════════╗
// ║                    СЛОТ-МАШИНА                           ║
// ╚══════════════════════════════════════════════════════════╝

// Добавь поле weight (вес вероятности). Чем больше число, тем чаще падает.
let rimworldEvents = [];
let eventsSearchQuery = '';

async function loadRimworldEvents() {
    try {
        const r = await fetch(`${API_URL}/api/rimworld/events`);
        const data = await r.json();
        rimworldEvents = data.events || [];
        renderEvents();
    } catch(e) {
        const el = document.getElementById('events-list');
        if (el) el.innerHTML = '<div class="loading">Ивенты недоступны</div>';
    }
}

function onEventsSearch(val) {
    eventsSearchQuery = val.trim();
    renderEvents();
}

function renderEvents() {
    const container = document.getElementById('events-list');
    if (!container) return;
    const userPoints = parseInt((document.getElementById('points')?.textContent || '0').replace(/[^0-9]/g, '')) || 0;

    if (!rimworldEvents.length) {
        container.innerHTML = '<div class="loading">Список ивентов пуст</div>';
        return;
    }

    // Фильтрация по поиску
    let filtered = rimworldEvents;
    if (eventsSearchQuery) {
        const q = eventsSearchQuery.toLowerCase();
        filtered = rimworldEvents.filter(ev => 
            (ev.name || '').toLowerCase().includes(q) ||
            (ev.id || '').toString().toLowerCase().includes(q) ||
            (ev.category || '').toLowerCase().includes(q)
        );
    }

    if (!filtered.length) {
        container.innerHTML = '<div class="loading">Ничего не найдено</div>';
        return;
    }

    const now = Date.now();
    container.innerHTML = filtered.map(ev => {
        const canAfford = userPoints >= ev.cost;
        const cdKey = 'event_all';
        const cdSince = _cmdCooldowns[cdKey] || 0;
        const cdLeft = cdSince ? Math.max(0, Math.ceil((EVENT_COOLDOWN_MS - (now - cdSince)) / 1000)) : 0;
        const onCd = cdLeft > 0;
        const mins = Math.floor(cdLeft / 60);
        const secs = cdLeft % 60;
        const cdLabel = mins > 0 ? `⏱ ${mins}м ${secs}с` : `⏱ ${secs}с`;
        return `
            <div class="shop-item">
                <div class="shop-item-icon" style="font-size:22px;">${escapeHtml(ev.name.split(' ')[0])}</div>
                <div class="shop-item-info">
                    <div class="shop-item-name">${escapeHtml(ev.name.replace(/^\S+\s*/, ''))}</div>
                </div>
                <div class="shop-item-buy">
                    <div class="shop-item-price">${ev.cost}💎</div>
                    <button class="buy-btn" data-event-id="${escapeHtml(String(ev.id))}" ${(!canAfford || onCd) ? 'disabled' : ''}>
                        ${onCd ? cdLabel : canAfford ? 'Купить' : 'Мало 💎'}
                    </button>
                </div>
            </div>
        `;
    }).join('');

    // Event delegation для кнопок ивентов
    container.querySelectorAll('[data-event-id]').forEach(btn => {
        btn.addEventListener('click', () => buyEvent(btn.dataset.eventId));
    });
}

const EVENT_COOLDOWN_MS = 5 * 60 * 1000; // 5 минут на каждый ивент

// Тикаем каждую секунду — обновляем кнопки ивентов если есть активный КД
window._eventTickInterval = safeInterval(() => {
    const cdSince = _cmdCooldowns['event_all'] || 0;
    const hasEventCd = cdSince && Date.now() - cdSince < EVENT_COOLDOWN_MS;
    if (hasEventCd) {
        renderEvents();
    } else if (cdSince) {
        // КД только что истёк — рендерим ещё раз чтобы разблокировать кнопки, затем сбрасываем
        delete _cmdCooldowns['event_all'];
        renderEvents();
    }
}, 1000);

async function buyEvent(eventId) {
    if (!userLogin) return;
    // ev.id с сервера — число, eventId из data-атрибута — строка; приводим оба к строке
    const ev = rimworldEvents.find(e => String(e.id) === String(eventId));
    if (!ev) return;
    // Берём баланс из кэша если DOM ещё не обновился (например после перезагрузки страницы)
    const domPoints = parseInt(document.getElementById('points')?.textContent || '0');
    const userPoints = domPoints > 0 ? domPoints : (_cachedUserPoints || 0);
    if (userPoints < ev.cost) { showNotification('❌ Недостаточно 💎', 'error'); return; }

    // КД 5 минут per-event, таймер показывается на кнопке
    const evBtn = document.querySelector(`[data-event-id="${eventId}"]`);
    if (!checkCooldown('event_all', EVENT_COOLDOWN_MS, evBtn)) return;

    showConfirm(`${escapeHtml(ev.name)}`, `Потратить ${Number(ev.cost)||0}💎?`, async () => {
        try {
            const r = await fetch(`${API_URL}/api/rimworld/trigger-event`, {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({ username: userLogin, event_id: eventId })
            });
            const data = await r.json();
            if (data.success) {
                showNotification(`✅ ${data.message}`, 'success');
                loadUserData();
                setTimeout(renderEvents, 1000);
            } else {
                // Если сервер отклонил — сбрасываем КД чтобы можно было попробовать снова
                delete _cmdCooldowns['event_all'];
                showNotification(`❌ ${data.message}`, 'error');
            }
        } catch(e) {
            delete _cmdCooldowns['event_all'];
            showNotification('❌ Ошибка соединения', 'error');
        }
    });
}

// ===== RIMWORLD ONLINE STATUS =====
let rimworldOnline = false;

async function checkRimworldStatus() {
    try {
        const r = await fetch(`${API_URL}/api/rimworld/status`);
        const data = await r.json();
        rimworldOnline = data.online;
        updateRimworldStatusUI();
    } catch(e) {
        rimworldOnline = false;
        updateRimworldStatusUI();
    }
}

function updateRimworldStatusUI() {
    const badge = document.getElementById('rimworld-status-badge');
    if (badge) {
        badge.textContent = rimworldOnline ? '🟢 Онлайн' : '🔴 Оффлайн';
        badge.style.color = rimworldOnline ? '#4ade80' : '#f87171';
    }
    // Скрываем магазин и ивенты если игра не запущена
    const shopCard = document.getElementById('shop-card');
    const eventsCard = document.getElementById('events-card');
    if (shopCard) shopCard.style.opacity = rimworldOnline ? '1' : '0.4';
    if (eventsCard) eventsCard.style.opacity = rimworldOnline ? '1' : '0.4';
}

// Проверяем статус каждые 30 секунд
window._intervalRimStatus = window._rimworldStatusInterval = safeInterval(checkRimworldStatus, 30000);

// ===== ЗАПРОС РАЗРЕШЕНИЯ НА IDENTITY =====
function showLoginBanner() {
    const banner = document.createElement('div');
    banner.id = 'login-banner';
    banner.style.cssText = 'background:#18181b;border:1px solid #9147ff;border-radius:12px;padding:16px;margin:12px;text-align:center;';
    banner.innerHTML = `
        <div style="font-size:20px;margin-bottom:8px;">👋</div>
        <div style="font-size:14px;font-weight:600;margin-bottom:6px;">Войди на Twitch</div>
        <div style="color:#adadb8;font-size:12px;margin-bottom:14px;">
            Чтобы создать пешку и участвовать в игре, разреши доступ к профилю
        </div>
        <button id="request-identity-btn" style="background:#9147ff;color:#fff;border:none;border-radius:8px;padding:10px 20px;cursor:pointer;font-size:14px;width:100%;">
            ✅ Разрешить доступ
        </button>
    `;
    const firstCard = document.querySelector('.card');
    if (firstCard) firstCard.parentNode.insertBefore(banner, firstCard);
    else document.body.prepend(banner);
    const identityBtn = banner.querySelector('#request-identity-btn');
    if (identityBtn) {
        identityBtn.addEventListener('click', requestTwitchIdentity);
    }
}

function requestTwitchIdentity() {
    if (window.Twitch && window.Twitch.ext && window.Twitch.ext.actions) {
        window.Twitch.ext.actions.requestIdShare();
        showNotification('🔄 Ожидаем разрешения...', 'info');
        // Twitch перезапустит onAuthorized с user_id после согласия
    }
}

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
    let restoreBtn = document.getElementById('panel-restore-tab');
    if (!restoreBtn) {
        restoreBtn = document.createElement('button');
        restoreBtn.id = 'panel-restore-tab';
        restoreBtn.innerHTML = '🌌';
        restoreBtn.title = 'Открыть RimLink';
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
}

// ===== РЕКЛАМА =====
function openAdvertisement() {
    const old = document.getElementById('ad-modal');
    if (old) old.remove();

    const modal = document.createElement('div');
    modal.id = 'ad-modal';
    modal.className = 'modal active';
    modal.innerHTML = `
        <div class="modal-content" style="max-width:400px;">
            <h2>📢 Реклама</h2>
            <p style="margin-bottom:16px;color:#adadb8;font-size:13px;text-align:center;">
                Ваша реклама может быть здесь!
            </p>
            <a href="https://t.me/ttvshedoy23"
               target="_blank"
               rel="noopener noreferrer"
               style="display:block;background:#0088cc;color:white;padding:14px 20px;border-radius:12px;text-decoration:none;font-weight:700;margin-bottom:12px;text-align:center;">
                ✈ Перейти в Telegram
            </a>
            <p style="text-align:center;font-size:11px;color:#666;margin-top:8px;">
                Или откройте чат напрямую:
            </p>
            <a href="https://t.me/+x6Di_VyeFMxhZWE6"
               target="_blank"
               rel="noopener noreferrer"
               style="display:block;background:#2d2d2f;border:1px solid #3d3d3f;color:#adadb8;padding:10px 16px;border-radius:10px;text-decoration:none;font-size:12px;margin-top:4px;">
                💬 Открыть чат
            </a>
        </div>
    `;
    (document.getElementById('overlay-panel') || document.body).appendChild(modal);
    modal.addEventListener('click', e => {
        if (e.target === modal) modal.remove();
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
