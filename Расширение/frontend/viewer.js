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
        const actionEl = event.target.closest('[data-action],[data-open-modal],[data-toggle-target],[data-close-self-modal],[data-accept-family],[data-reject-family],[data-close-modal],[data-cat],#create-pawn-btn,#heal-pawn-btn,#btn-resurrect,#market-refresh-btn,#stats-refresh-btn,#refresh-pawn-btn,#panel-hide-btn,#rulection-contribute-btn,#rulection-bid-btn,#promo-activate-btn,#create-colonist-btn');
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
        // Sprint 5.19: квесты/промо переехали из inline-блоков в модалки
        else if (action === 'quests') openQuestsModal();
        else if (action === 'promo') openPromoModal();
        // Sprint 5.23: TTS «Озвучить сообщение»
        else if (action === 'tts') openTtsModal();
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
let _bannerlordTournament = null;        // last snapshot {queue, state, in_queue, my_bet, config}
let _bannerlordBattlePollId = null;      // Sprint 5.5 — poll /api/bannerlord/battle-status (2s)
let _bannerlordBattle = null;            // last snapshot {in_battle, my_stats, participant_count}
let _bannerlordWasInBattle = false;      // detect new-battle transition для cooldown UI refresh
let _bannerlordLastRetinue = [];         // last retinue snapshot — repaint без re-fetch
let _bannerlordLastHero = null;          // last /my-hero snapshot — для progression modal

// Sprint 5.5: helper для проверки battle state (для banner / future use).
function bnrIsInBattle() { return !!(_bannerlordBattle && _bannerlordBattle.in_battle); }

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
const HERO_GOLD_TIER_COSTS = {
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
    loadBannerlordTournament();
    loadBannerlordBattleStatus();
    _bannerlordPollId = setInterval(() => {
        loadBannerlordHero();
        loadBannerlordShop();
        loadBannerlordStatus();
        loadBannerlordClasses();
    }, 8000);
    // Buff HUD: faster poll (2.5s) для смены состояния, плюс client-side
    // decrement (1s) чтобы countdown был smooth между poll'ами.
    _bannerlordBuffPollId = setInterval(loadBannerlordBuffs, 2500);
    // Tournament: 3s poll — отображает queue / running state / bets
    _bannerlordTournamentPollId = setInterval(loadBannerlordTournament, 3000);
    // Battle status: 2s poll — banner "идёт бой" + my HP/kills/gold/xp
    _bannerlordBattlePollId = setInterval(loadBannerlordBattleStatus, 2000);
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
    const currentKey = current?.class_key || '';

    // Sprint 5.3b — compact dropdown вместо grid кнопок (UX feedback).
    const optionsHtml = classes.map(c => {
        const selected = c.class_key === currentKey ? 'selected' : '';
        return `<option value="${escapeHtml(c.class_key)}" ${selected}>${escapeHtml(c.name)}</option>`;
    }).join('');

    const placeholderOpt = currentKey
        ? ''
        : '<option value="" disabled selected>— выбери класс —</option>';

    slot.innerHTML = `
        <div style="display:flex;align-items:center;gap:6px;margin-top:8px;margin-bottom:6px;">
            <span style="font-size:11px;color:#adadb8;white-space:nowrap;">🎖️ Класс:</span>
            <select id="bnr-class-select"
                    style="flex:1;background:#2d2d2f;color:#efeff1;border:1px solid #3d3d3f;
                           padding:5px 8px;font-size:12px;border-radius:4px;cursor:pointer;
                           ${currentKey ? '' : 'border-color:#fbbf24;'}">
                ${placeholderOpt}
                ${optionsHtml}
            </select>
        </div>
    `;

    const sel = document.getElementById('bnr-class-select');
    if (sel) {
        sel.addEventListener('change', () => {
            const classKey = sel.value;
            if (!classKey || classKey === currentKey) return;
            _bannerlordBuyAction('hero.set_class', { price: 0, class_key: classKey });
        });
    }

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
    const ALLY_PRICE = 100;    // 5.4: 500→100
    const ENEMY_PRICE = 200;   // 5.4: 1000→200 (2× тролл-tax)
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

// Sprint M23: random-equip перенесён на Hero.Gold (in-game динары).
// Mod-side enforced (hero.Gold check + deduct). Backend price=0 в крустиках.
// Fairness через игровую экономику — viewer сначала копит динары
// (give_gold или внутри игры), потом тратит на random box.
function renderBannerlordRandomEquipHtml() {
    const currentKey = _bannerlordClassesCache?.current?.class_key || '';
    const MOUNTED = new Set(['cavalry', 'camel_cavalry', 'horse_archer', 'camel_archer', 'knight']);
    const isMounted = MOUNTED.has(currentKey);

    const horseDisabled = !isMounted ? 'disabled' : '';
    const horseStyle = !isMounted ? 'opacity:0.5;cursor:not-allowed;' : '';
    const horseTitle = !isMounted
        ? 'Только для конных классов (cavalry / horse_archer / camel_* / knight). 80K динаров у героя в игре.'
        : 'Случайный скакун из high-tier пула. Списываются 80K динаров у героя в игре.';

    return `
        <div style="padding:6px 10px 10px 10px;">
            <div style="font-size:11px;color:#adadb8;margin-bottom:4px;">
                🎁 Случайный товар — оплата in-game динарами героя
            </div>
            <div style="display:flex;flex-direction:column;gap:4px;">
                <button class="extra-btn" id="bnr-random-weapon"
                        title="Случайное оружие из high-tier пула. Списываются 50K динаров у героя в игре."
                        style="font-size:12px;padding:6px;">
                    🗡 Купить оружие <span style="color:#fbbf24;">50К💰</span>
                </button>
                <button class="extra-btn" id="bnr-random-armor"
                        title="Случайная броня (любой slot) из high-tier пула. Списываются 25K динаров у героя в игре."
                        style="font-size:12px;padding:6px;">
                    🛡 Купить броню <span style="color:#fbbf24;">25К💰</span>
                </button>
                <button class="extra-btn" id="bnr-random-horse"
                        ${horseDisabled}
                        title="${horseTitle}"
                        style="font-size:12px;padding:6px;${horseStyle}">
                    🐎 Купить коня <span style="color:#fbbf24;">80К💰</span>
                </button>
            </div>
        </div>`;
}

// Sprint M21 — рендер одного слота экипировки с stats badges.
// it = {item_id, item_name, tier (0-5), item_value, weight, stats (dict)}
function _renderEquipRow(slot, it, slotIcons) {
    if (!it || !it.item_id) {
        return `<div style="font-size:11px;padding:1px 0;color:#6b7280;">
            ${slotIcons[slot] || '·'} ${slot}: <em>пусто</em>
        </div>`;
    }
    const name = escapeHtml(it.item_name || it.item_id || '—');
    const tierBadge = (it.tier != null && it.tier >= 0)
        ? `<span style="color:#fbbf24;font-weight:700;margin-left:4px;">T${it.tier + 1}★</span>`
        : '';
    const stats = it.stats || {};
    const isWeapon = ['weapon0','weapon1','weapon2','weapon3'].includes(slot);
    const isArmor = ['head','body','leg','gloves','cape','horseharness'].includes(slot);
    const isHorse = slot === 'horse';

    let statsHtml = '';
    if (isWeapon) {
        const chunks = [];
        if (stats.swing_dmg)   chunks.push(`<span style="color:#f87171;">⚔ ${stats.swing_dmg}${stats.swing_type ? '/' + stats.swing_type[0].toUpperCase() : ''}</span>`);
        if (stats.thrust_dmg)  chunks.push(`<span style="color:#fb923c;">▶ ${stats.thrust_dmg}${stats.thrust_type ? '/' + stats.thrust_type[0].toUpperCase() : ''}</span>`);
        if (stats.swing_spd)   chunks.push(`<span style="color:#60a5fa;">⏱ ${stats.swing_spd}</span>`);
        if (stats.length)      chunks.push(`<span style="color:#9ca3af;">📏 ${stats.length}</span>`);
        if (stats.accuracy)    chunks.push(`<span style="color:#a78bfa;">🎯 ${stats.accuracy}</span>`);
        if (stats.missile_spd) chunks.push(`<span style="color:#34d399;">💨 ${stats.missile_spd}</span>`);
        // shield-specific (hp + body)
        if (stats.hp)          chunks.push(`<span style="color:#fbbf24;">🛡 hp ${stats.hp}</span>`);
        // ammo
        if (stats.stack)       chunks.push(`<span style="color:#94a3b8;">×${stats.stack}</span>`);
        statsHtml = chunks.join(' ');
    } else if (isArmor) {
        const a = stats || {};
        const chunks = [];
        if (a.head) chunks.push(`<span style="color:#a78bfa;">🪖${a.head}</span>`);
        if (a.body) chunks.push(`<span style="color:#fbbf24;">👕${a.body}</span>`);
        if (a.leg)  chunks.push(`<span style="color:#34d399;">👢${a.leg}</span>`);
        if (a.arm)  chunks.push(`<span style="color:#60a5fa;">💪${a.arm}</span>`);
        statsHtml = chunks.join(' ');
    } else if (isHorse) {
        const chunks = [];
        if (stats.speed)    chunks.push(`<span style="color:#60a5fa;">💨 ${stats.speed}</span>`);
        if (stats.charge)   chunks.push(`<span style="color:#f87171;">⚡ ${stats.charge}</span>`);
        if (stats.maneuver) chunks.push(`<span style="color:#34d399;">🔄 ${stats.maneuver}</span>`);
        if (stats.hp)       chunks.push(`<span style="color:#fbbf24;">❤ ${stats.hp}</span>`);
        statsHtml = chunks.join(' ');
    }

    return `<div style="font-size:11px;padding:2px 0;border-bottom:1px solid #2d2d2f;">
        <div style="display:flex;justify-content:space-between;">
            <span><span style="color:#adadb8;">${slotIcons[slot] || '·'}</span> ${name}${tierBadge}</span>
        </div>
        ${statsHtml ? `<div style="font-size:10px;color:#9ca3af;padding-left:14px;margin-top:1px;">${statsHtml}</div>` : ''}
    </div>`;
}

// Sprint M23/5.14 — render свита (retinue) под Экипировкой в hero card.
// retinue = [{slot_index, troop_id, troop_name, tier, is_elite}]
const RECRUIT_PRICE_BASIC = 100;   // крустиков basic
const RECRUIT_PRICE_ELITE = 300;   // крустиков elite (3×)
function _renderRetinue(retinue) {
    const slot = document.getElementById('bnr-retinue-slot');
    if (!slot) return;
    const MAX_SLOTS = 5;
    const list = retinue || [];

    const rows = list.length === 0
        ? '<div style="font-size:11px;color:#9ca3af;padding:2px 0;">пусто</div>'
        : list.map(t => {
            const eliteBadge = t.is_elite
                ? '<span style="color:#fbbf24;font-size:9px;margin-right:4px;" title="Elite troop (EliteBasicTroop chain)">★</span>'
                : '';
            return `
                <div style="display:flex;justify-content:space-between;font-size:11px;padding:1px 0;">
                    <span>${eliteBadge}${escapeHtml(t.troop_name || t.troop_id)}</span>
                    <span style="color:#fbbf24;">T${(t.tier || 0) + 1}★</span>
                </div>`;
        }).join('');

    const isMaxed = list.length >= MAX_SLOTS;
    // separate maxed checks для basic / elite
    const basicSlots = list.filter(t => !t.is_elite);
    const eliteSlots = list.filter(t => t.is_elite);
    const basicAllMax = basicSlots.length > 0 && basicSlots.every(t => (t.tier || 0) >= 5);
    const eliteAllMax = eliteSlots.length > 0 && eliteSlots.every(t => (t.tier || 0) >= 5);

    const basicLabel = !isMaxed
        ? `➕ Нанять воина (${RECRUIT_PRICE_BASIC}💎)`
        : (basicAllMax
            ? '✓ Basic maxed'
            : `⬆ Прокачать basic (${RECRUIT_PRICE_BASIC}💎)`);
    const eliteLabel = !isMaxed
        ? `★ Нанять элитного (${RECRUIT_PRICE_ELITE}💎)`
        : (eliteAllMax
            ? '✓ Elite maxed'
            : `⬆ Прокачать elite (${RECRUIT_PRICE_ELITE}💎)`);

    const basicDisabled = isMaxed && (basicSlots.length === 0 || basicAllMax);
    const eliteDisabled = isMaxed && (eliteSlots.length === 0 || eliteAllMax);

    slot.innerHTML = `
        <details data-bnr-details="retinue" ${_bnrDetailsAttr('retinue')}>
            <summary style="font-size:11px;color:#adadb8;cursor:pointer;">
                Свита (${list.length}/${MAX_SLOTS})
                ${eliteSlots.length > 0
                    ? `<span style="color:#fbbf24;font-size:10px;">★${eliteSlots.length}</span>`
                    : ''}
            </summary>
            <div style="margin-top:4px;">
                ${rows}
                <div style="display:flex;gap:4px;margin-top:6px;">
                    <button class="extra-btn" id="bnr-recruit-basic-btn"
                            ${basicDisabled ? 'disabled' : ''}
                            title="Basic troop (battanian_recruit / khuzait_nomad / etc). Списать 100💎 крустиков + 5K-80K динаров у героя."
                            style="flex:1;font-size:11px;padding:6px;
                                   ${basicDisabled ? 'opacity:0.5;cursor:not-allowed;' : ''}">
                        ${basicLabel}
                    </button>
                    <button class="extra-btn" id="bnr-recruit-elite-btn"
                            ${eliteDisabled ? 'disabled' : ''}
                            title="Elite troop (battanian_oathsworn / vlandian_squire / etc) — другая ветка прокачки до champion/hero. 3× стоимость."
                            style="flex:1;font-size:11px;padding:6px;background:#5c2d12;color:#fbbf24;
                                   ${eliteDisabled ? 'opacity:0.5;cursor:not-allowed;' : ''}">
                        ${eliteLabel}
                    </button>
                </div>
            </div>
        </details>`;

    document.getElementById('bnr-recruit-basic-btn')?.addEventListener('click', () => {
        if (basicDisabled) return;
        _bannerlordBuyAction('hero.recruit_troops', { is_elite: false });
    });
    document.getElementById('bnr-recruit-elite-btn')?.addEventListener('click', () => {
        if (eliteDisabled) return;
        _bannerlordBuyAction('hero.recruit_troops', { is_elite: true });
    });
}

// Sprint M21 → 5.10: gear upgrade button перенесена inline в hero card
// (рядом с "🛡 Снаряжение: T2 ★ [⚒ T3 (100K💰)]"). Раньше был отдельный
// shop-блок renderBannerlordGearUpgradeHtml + _bindBannerlordGearUpgrade —
// удалены в 5.18 cleanup. См. inline binding в loadBannerlordHero.

// Sprint M21 — конверт крустики → in-game динары (1:5) и крустики → skill XP.
// Цены server-side enforced (GIVE_GOLD_PRESETS / ADD_SKILL_XP_PRESETS).
const GIVE_GOLD_OPTIONS = [
    { crusticov: 1_000,  dinars:   5_000 },
    { crusticov: 5_000,  dinars:  25_000 },
    { crusticov: 20_000, dinars: 100_000 },
];
const ADD_SKILL_OPTIONS = [
    { crusticov:   500, xp:  50 },
    { crusticov: 1_000, xp: 100 },
    { crusticov: 5_000, xp: 500 },
];

function renderBannerlordCurrencyHtml() {
    const goldRows = GIVE_GOLD_OPTIONS.map(o => `
        <button class="extra-btn" data-bnr-givegold="${o.crusticov}"
                title="Дать +${o.dinars.toLocaleString('ru-RU')} динаров герою в игре"
                style="font-size:11px;padding:5px;">
            💰 +${_formatBigGold(o.dinars)}
            <span style="color:#fbbf24;">${_formatBigPrice(o.crusticov)}</span>
        </button>`).join('');

    const xpRows = ADD_SKILL_OPTIONS.map(o => `
        <button class="extra-btn" data-bnr-skillxp="${o.crusticov}"
                title="+${o.xp} XP в случайный skill"
                style="font-size:11px;padding:5px;">
            📚 +${o.xp} XP (рандом)
            <span style="color:#fbbf24;">${_formatBigPrice(o.crusticov)}</span>
        </button>`).join('');

    return `
        <div style="padding:6px 10px;border-top:1px solid #3d3d3f;margin-top:4px;">
            <div style="font-size:11px;color:#adadb8;margin-bottom:4px;">
                💰 Динары (1000💎 → 5000 динаров)
            </div>
            <div style="display:flex;flex-direction:column;gap:3px;">${goldRows}</div>
        </div>
        <div style="padding:6px 10px;border-top:1px solid #3d3d3f;margin-top:4px;">
            <div style="font-size:11px;color:#adadb8;margin-bottom:4px;">
                📚 Опыт в скилл (random)
            </div>
            <div style="display:flex;flex-direction:column;gap:3px;">${xpRows}</div>
        </div>`;
}

function _bindBannerlordCurrency() {
    document.querySelectorAll('[data-bnr-givegold]').forEach(btn => {
        btn.addEventListener('click', () => {
            const crusticov = parseInt(btn.dataset.bnrGivegold, 10) || 0;
            // Backend resolves amount; price = crusticov для charge.
            _bannerlordBuyAction('player.give_item', { price: crusticov, item_type: 'gold' });
        });
    });
    document.querySelectorAll('[data-bnr-skillxp]').forEach(btn => {
        btn.addEventListener('click', () => {
            const crusticov = parseInt(btn.dataset.bnrSkillxp, 10) || 0;
            // skill_key пуст → mod выбирает random.
            _bannerlordBuyAction('hero.add_skill', { price: crusticov });
        });
    });
}

// ===== Sprint 5.8: Focus / Attribute investments (Hero.Gold cost) =====
const BNR_SKILLS = [
    'OneHanded', 'TwoHanded', 'Polearm', 'Bow', 'Crossbow', 'Throwing',
    'Athletics', 'Riding', 'Smithing', 'Scouting', 'Tactics', 'Roguery',
    'Charm', 'Leadership', 'Trade', 'Steward', 'Medicine', 'Engineering',
];
const BNR_SKILL_LABELS_RU = {
    OneHanded: 'Одноручное', TwoHanded: 'Двуручное', Polearm: 'Древковое',
    Bow: 'Лук', Crossbow: 'Арбалет', Throwing: 'Метательное',
    Athletics: 'Атлетика', Riding: 'Верховая езда', Smithing: 'Кузнечное',
    Scouting: 'Разведка', Tactics: 'Тактика', Roguery: 'Бесчестие',
    Charm: 'Обаяние', Leadership: 'Лидерство', Trade: 'Торговля',
    Steward: 'Управление', Medicine: 'Медицина', Engineering: 'Инженерия',
};
const BNR_ATTRIBUTES = ['Vigor', 'Control', 'Endurance', 'Cunning', 'Social', 'Intelligence'];
const BNR_ATTR_LABELS_RU = {
    Vigor: 'Vigor (сила)', Control: 'Control (точность)',
    Endurance: 'Endurance (выносл.)', Cunning: 'Cunning (хитрость)',
    Social: 'Social (соц.)', Intelligence: 'Intelligence (интелл.)',
};
// Sprint 5.17: vanilla Bannerlord skill→attribute mapping. Атрибут даёт
// +1 cap к skill за каждое очко (max 30 cap при attr=10).
const BNR_ATTR_TO_SKILLS = {
    Vigor:        ['OneHanded', 'TwoHanded', 'Polearm'],
    Control:      ['Bow', 'Crossbow', 'Throwing'],
    Endurance:    ['Riding', 'Athletics', 'Smithing'],
    Cunning:      ['Scouting', 'Tactics', 'Roguery'],
    Social:       ['Charm', 'Leadership', 'Trade'],
    Intelligence: ['Steward', 'Medicine', 'Engineering'],
};
const BNR_ATTR_ICONS = {
    Vigor: '💪', Control: '🎯', Endurance: '⛰️',
    Cunning: '🦊', Social: '💬', Intelligence: '📚',
};
const BNR_FOCUS_TIER_COSTS = [30000, 40000, 50000, 60000, 75000];
const BNR_ATTRIBUTE_COST = 50000;

// Sprint 5.8 → 5.8c: ранее был renderBannerlordProgressionHtml (dropdown в shop)
// + _bindBannerlordProgression. Удалено в 5.8c — invest-кнопки перенесены
// внутрь progression modal (per-row + buttons). См. _openBannerlordProgressionModal.

// Sprint 5.8: Progression modal — отображает все скиллы (level + focus stars)
// + 6 атрибутов. Открывается по кнопке "🎯 Прогрессия" в hero card.
function _openBannerlordProgressionModal() {
    const data = _bannerlordLastHero;
    if (!data || !data.has_hero) {
        showNotification('⚠️ Сначала создай героя', 'warning');
        return;
    }
    const skills = data.skills || [];
    const attrs = data.attributes || {};

    // Build skill lookup
    const skillsByKey = {};
    for (const s of skills) skillsByKey[s.skill_key] = s;

    // Helper: render одну skill row
    function _renderSkillRow(key) {
        const s = skillsByKey[key] || { skill_key: key, level: 0, focus: 0 };
        const focus = s.focus || 0;
        const focusStars = '★'.repeat(focus) + '☆'.repeat(5 - focus);
        const label = BNR_SKILL_LABELS_RU[key] || key;
        const lvlColor = s.level >= 100 ? '#fbbf24' : (s.level >= 50 ? '#34d399' : '#efeff1');
        const maxed = focus >= 5;
        const nextCost = maxed ? 0 : BNR_FOCUS_TIER_COSTS[focus];
        const btnTitle = maxed
            ? 'F5 максимум'
            : `+1 focus в ${label} → F${focus + 1}. Списать ${nextCost.toLocaleString('ru-RU')}💰 динаров.`;
        return `
            <div style="display:flex;justify-content:space-between;align-items:center;
                        padding:3px 6px 3px 14px;font-size:11px;gap:8px;
                        border-bottom:1px solid rgba(255,255,255,0.05);">
                <span style="color:#efeff1;flex:1;">└ ${escapeHtml(label)}</span>
                <span style="color:#fbbf24;font-family:monospace;letter-spacing:1px;">${focusStars}</span>
                <span style="color:${lvlColor};min-width:30px;text-align:right;
                             font-family:monospace;font-weight:700;">${s.level || 0}</span>
                <button class="small-btn bnr-prog-focus-btn"
                        data-skill="${escapeHtml(key)}"
                        ${maxed ? 'disabled' : ''}
                        title="${escapeHtml(btnTitle)}"
                        style="padding:2px 8px;font-size:11px;background:#3d3d3f;
                               color:#fbbf24;font-weight:700;
                               ${maxed ? 'opacity:0.3;cursor:not-allowed;' : ''}">
                    🎯+
                </button>
            </div>`;
    }

    // Render: attribute header + nested skills (Sprint 5.17 group-by-attribute)
    const groupedRows = BNR_ATTRIBUTES.map(attrKey => {
        const val = attrs[attrKey] || 0;
        const filled = '●'.repeat(val) + '○'.repeat(10 - val);
        const attrLabel = BNR_ATTR_LABELS_RU[attrKey] || attrKey;
        const attrIcon = BNR_ATTR_ICONS[attrKey] || '·';
        const valColor = val >= 8 ? '#fbbf24' : (val >= 5 ? '#34d399' : '#efeff1');
        const maxed = val >= 10;
        const btnTitle = maxed
            ? '10/10 максимум'
            : `+1 в ${attrLabel} → ${val + 1}/10. Списать ${BNR_ATTRIBUTE_COST.toLocaleString('ru-RU')}💰 динаров.`;

        const childSkills = (BNR_ATTR_TO_SKILLS[attrKey] || []).map(_renderSkillRow).join('');

        return `
            <div style="background:rgba(147,197,253,0.06);border-top:1px solid rgba(147,197,253,0.15);
                        padding:5px 6px;display:flex;justify-content:space-between;
                        align-items:center;font-size:11px;gap:8px;font-weight:700;">
                <span style="color:#93c5fd;flex:1;">${attrIcon} ${escapeHtml(attrLabel)}</span>
                <span style="color:#93c5fd;font-family:monospace;letter-spacing:1px;font-weight:400;">${filled}</span>
                <span style="color:${valColor};min-width:36px;text-align:right;
                             font-family:monospace;">${val}/10</span>
                <button class="small-btn bnr-prog-attr-btn"
                        data-attr="${escapeHtml(attrKey)}"
                        ${maxed ? 'disabled' : ''}
                        title="${escapeHtml(btnTitle)}"
                        style="padding:2px 8px;font-size:11px;background:#3d3d3f;
                               color:#93c5fd;font-weight:700;
                               ${maxed ? 'opacity:0.3;cursor:not-allowed;' : ''}">
                    💪+
                </button>
            </div>
            ${childSkills}`;
    }).join('');

    const overlay = document.createElement('div');
    overlay.id = 'bnr-progression-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);' +
        'display:flex;align-items:center;justify-content:center;z-index:9999;padding:10px;';
    overlay.innerHTML = `
        <div style="background:#18181b;border:1px solid #3d3d3f;border-radius:8px;
                    padding:14px;max-width:380px;width:100%;max-height:90vh;overflow-y:auto;">
            <div style="display:flex;justify-content:space-between;align-items:center;
                        margin-bottom:10px;border-bottom:1px solid #3d3d3f;padding-bottom:6px;">
                <h3 style="margin:0;font-size:14px;color:#efeff1;">🎯 Прогрессия</h3>
                <button id="bnr-prog-close" class="small-btn"
                        style="padding:4px 10px;font-size:11px;background:#3d3d3f;">✕</button>
            </div>

            <div style="font-size:11px;color:#adadb8;margin-bottom:6px;line-height:1.4;">
                💪 Атрибут (50K💰) повышает cap трёх связанных скиллов.<br>
                🎯 Фокус (30-75K💰) ускоряет прокачку конкретного скилла.
            </div>
            <div>${groupedRows}</div>

            <div style="margin-top:10px;font-size:10px;color:#9ca3af;text-align:center;">
                Каждый атрибут даёт +1 cap к 3 скиллам своей категории.
                Без фокуса можно прокачать до 25-30 уровня.
            </div>
        </div>`;
    document.body.appendChild(overlay);

    document.getElementById('bnr-prog-close')?.addEventListener('click', () => overlay.remove());
    overlay.addEventListener('click', e => {
        if (e.target === overlay) overlay.remove();
    });

    // Per-row "+" buttons — invest в конкретный skill / attribute
    overlay.querySelectorAll('.bnr-prog-focus-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const skill_key = btn.getAttribute('data-skill');
            _bannerlordBuyAction('hero.add_focus', { skill_key, amount: 1 });
            // Re-open модал через ~3.5s чтобы показать новый focus state.
            // Закрываем сейчас, чтобы UX был чище.
            overlay.remove();
            setTimeout(() => {
                if (typeof loadBannerlordHero === 'function') loadBannerlordHero();
                setTimeout(_openBannerlordProgressionModal, 600);
            }, 3500);
        });
    });
    overlay.querySelectorAll('.bnr-prog-attr-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const attribute_key = btn.getAttribute('data-attr');
            _bannerlordBuyAction('hero.add_attribute', { attribute_key, amount: 1 });
            overlay.remove();
            setTimeout(() => {
                if (typeof loadBannerlordHero === 'function') loadBannerlordHero();
                setTimeout(_openBannerlordProgressionModal, 600);
            }, 3500);
        });
    });
}

// Sprint 5.11: общий helper для открытия modal — clan / kingdom management.
// Содержит варианты create / join / leave в зависимости от текущего state.
function _openBannerlordClanModal() {
    const h = _bannerlordLastHero?.hero || {};
    const hasClan = !!h.clan_name;
    const info = h.clan_info || null;

    // Info block (если есть clan)
    const infoBlock = hasClan && info ? `
        <div style="background:rgba(251,191,36,0.05);border:1px solid #3d3d3f;
                    border-radius:6px;padding:8px 10px;margin-bottom:10px;">
            <div style="font-size:13px;color:#fbbf24;font-weight:700;margin-bottom:6px;
                        text-align:center;">
                ${escapeHtml(info.name || h.clan_name)}
            </div>
            <div style="display:grid;grid-template-columns:auto 1fr;gap:4px 10px;font-size:11px;">
                <span style="color:#adadb8;">👑 Лидер:</span>
                <span style="color:#efeff1;">
                    ${escapeHtml(info.leader_name || '?')}
                    ${info.is_leader ? '<b style="color:#fbbf24;">(это ты!)</b>' : ''}
                </span>
                <span style="color:#adadb8;">⭐ Tier:</span>
                <span style="color:#efeff1;">${info.tier || 0}</span>
                <span style="color:#adadb8;">🏆 Renown:</span>
                <span style="color:#efeff1;">${(info.renown || 0).toLocaleString('ru-RU')}</span>
                <span style="color:#adadb8;">👥 Героев:</span>
                <span style="color:#efeff1;">${info.members_count || 0}</span>
                <span style="color:#adadb8;">⚔ Отрядов:</span>
                <span style="color:#efeff1;">${info.parties_count || 0}</span>
                <span style="color:#adadb8;">🏰 Поселений:</span>
                <span style="color:#efeff1;">${info.fiefs_count || 0}</span>
                ${info.kingdom_name ? `
                <span style="color:#adadb8;">👑 Королевство:</span>
                <span style="color:#efeff1;">${escapeHtml(info.kingdom_name)}</span>` : ''}
            </div>
        </div>` : '';

    const isLeader = !!info?.is_leader;
    const hasParties = (info?.parties_count || 0) > 0;
    const partyBtn = isLeader && !hasParties
        ? `<button class="extra-btn" id="bnr-clan-modal-create-party"
                   title="Создать MobileParty на карте — hero роумит как AI lord. Списать 200,000💰 динаров, добавит retinue в roster + стартовый food/horses."
                   style="width:100%;font-size:12px;padding:8px;
                          background:#1e3a5f;color:#93c5fd;font-weight:700;">
                ⚔ Создать отряд (party) (200K💰)
           </button>`
        : isLeader && hasParties
            ? `<div style="font-size:11px;color:#34d399;text-align:center;padding:6px;">
                ✅ У клана уже есть ${info.parties_count} отряд(ов)
               </div>`
            : `<button class="extra-btn" disabled
                       title="Только clan-leader может создать party"
                       style="width:100%;font-size:12px;padding:8px;opacity:0.5;cursor:not-allowed;">
                ⚔ Создать отряд <span style="color:#9ca3af;font-size:10px;">(только для лидеров)</span>
               </button>`;

    // Sprint 5.26b: кнопка «Апгрейды клана» (BLT-style buffs)
    const upgradesBtn = hasClan ? `
        <button class="extra-btn" id="bnr-clan-modal-upgrades"
                title="Долгосрочные баффы клана: +renown/день, +party size, +retinue size, и т.д."
                style="width:100%;font-size:12px;padding:8px;margin-bottom:6px;
                       background:#1f1a30;color:#c084fc;font-weight:700;
                       border:1px solid #5b21b6;">
            🏆 Апгрейды клана
        </button>` : '';

    const actions = hasClan ? `
        ${infoBlock}
        ${upgradesBtn}
        ${isLeader
            ? `<div style="font-size:11px;color:#fbbf24;margin-bottom:6px;text-align:center;">
                ⚠️ Ты лидер — нельзя просто покинуть. Сначала передай лидерство (TBD).
               </div>`
            : `<button class="extra-btn" id="bnr-clan-modal-leave"
                       title="Покинуть клан — бесплатно. Hero станет wanderer'ом."
                       style="width:100%;font-size:12px;padding:8px;margin-bottom:6px;
                              background:#7f1d1d;color:#fca5a5;">
                    🚪 Покинуть клан
               </button>`}
        ${partyBtn}` : `
        <div style="font-size:11px;color:#adadb8;margin-bottom:8px;">
            У тебя пока нет клана. Можно создать собственный или вступить в существующий.
        </div>
        <button class="extra-btn" id="bnr-clan-modal-create"
                title="Создать собственный клан под лидерством героя. Списать 1,000,000💰 динаров."
                style="width:100%;font-size:12px;padding:8px;margin-bottom:6px;
                       background:#7c2d12;color:#fbbf24;font-weight:700;">
            🏰 Создать свой клан (1M💰)
        </button>
        <button class="extra-btn" id="bnr-clan-modal-join"
                title="Вступить в существующий клан (50K💰). Введёшь имя клана."
                style="width:100%;font-size:12px;padding:8px;background:#1e3a5f;color:#93c5fd;">
            🤝 Вступить в клан (50K💰)
        </button>`;

    _bnrShowSimpleModal({
        title: '🏰 Управление кланом',
        body: actions,
        bind: overlay => {
            overlay.querySelector('#bnr-clan-modal-create')?.addEventListener('click', () => {
                overlay.remove();
                _openBannerlordCreateClanDialog();
            });
            overlay.querySelector('#bnr-clan-modal-join')?.addEventListener('click', () => {
                overlay.remove();
                _openBannerlordJoinDialog('clan');
            });
            overlay.querySelector('#bnr-clan-modal-leave')?.addEventListener('click', () => {
                if (!confirm('Ты уверен что хочешь покинуть клан? Hero станет wanderer\'ом.')) return;
                _bannerlordBuyAction('hero.leave_clan', {});
                overlay.remove();
            });
            overlay.querySelector('#bnr-clan-modal-create-party')?.addEventListener('click', () => {
                if (!confirm('Создать MobileParty? Hero появится на карте как AI lord. Списать 200K💰 динаров + добавит retinue в roster.')) return;
                _bannerlordBuyAction('hero.create_party', {});
                overlay.remove();
            });
            // Sprint 5.26b: clan upgrades
            overlay.querySelector('#bnr-clan-modal-upgrades')?.addEventListener('click', () => {
                overlay.remove();
                _openBannerlordClanUpgradesModal();
            });
        },
    });
}

// Sprint 5.26b: Clan upgrades modal (BLT-style buffs)
async function _openBannerlordClanUpgradesModal() {
    // Fetch list
    let data;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/clan-upgrades`, {
            headers: {'X-Twitch-JWT': authToken || ''},
        });
        data = await r.json();
    } catch (e) {
        showNotification('Ошибка загрузки апгрейдов', 'error');
        return;
    }
    if (!data.success) {
        showNotification(data.message || 'Не удалось загрузить', 'error');
        return;
    }
    const upgrades = data.upgrades || [];
    const heroGold = data.hero_gold || 0;

    // Группируем по tier
    const byTier = {};
    upgrades.forEach(u => {
        if (!byTier[u.tier]) byTier[u.tier] = [];
        byTier[u.tier].push(u);
    });
    const tiers = Object.keys(byTier).map(Number).sort((a, b) => a - b);

    const _effectsToStr = (effects) => {
        const labels = {
            renown_daily:       '🏆 +%v славы/день',
            influence_daily:    '👑 +%v влияния/день',
            party_size_bonus:   '⚔️ +%v к отряду',
            retinue_size_bonus: '🛡️ +%v к свите',
            party_speed_bonus:  '🐎 +%v скорости отряда',
            party_amount_bonus: '🪖 +%v к лимиту отрядов',
            max_vassals_bonus:  '🏰 +%v вассалов',
            army_speed_bonus:   '⚡ +%v скорости армии',
        };
        return Object.entries(effects || {})
            .map(([k, v]) => (labels[k] || `${k}: ${v}`).replace('%v', v))
            .join(' · ');
    };

    const tierHtml = tiers.map(tier => {
        const items = byTier[tier].map(u => {
            const canAfford = heroGold >= u.gold_cost;
            const ownedBadge = u.owned
                ? `<span style="color:#34d399;font-weight:700;font-size:11px;">✓ ВЛАДЕЕШЬ</span>`
                : u.locked
                    ? `<span style="color:#6b7280;font-size:11px;">🔒 Нужен предыдущий</span>`
                    : canAfford
                        ? `<button class="small-btn" data-bnr-upg-buy="${u.upgrade_id}"
                                  style="background:#5b21b6;color:#fbbf24;font-weight:700;">
                              Купить ${u.gold_cost.toLocaleString('ru-RU')}💰
                           </button>`
                        : `<span style="color:#f87171;font-size:11px;">
                              Нужно ${u.gold_cost.toLocaleString('ru-RU')}💰
                           </span>`;
            return `
                <div style="background:${u.owned ? 'rgba(52,211,153,0.05)' : '#1a1a1c'};
                            border:1px solid ${u.owned ? 'rgba(52,211,153,0.3)' : '#3a3a3e'};
                            border-radius:6px;padding:8px 10px;margin-bottom:5px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;
                                gap:8px;margin-bottom:3px;">
                        <span style="font-size:13px;font-weight:700;color:${u.owned ? '#34d399' : '#efeff1'};">
                            ${escapeHtml(u.name)}
                        </span>
                        ${ownedBadge}
                    </div>
                    <div style="font-size:11px;color:#adadb8;margin-bottom:3px;">
                        ${escapeHtml(u.description || '')}
                    </div>
                    <div style="font-size:10px;color:#c084fc;">
                        ${_effectsToStr(u.effects)}
                    </div>
                </div>`;
        }).join('');
        return `
            <div style="margin-bottom:12px;">
                <div style="font-size:11px;color:#9147ff;font-weight:700;letter-spacing:1px;
                            padding-bottom:4px;border-bottom:1px solid #3a3a3e;margin-bottom:6px;">
                    TIER ${tier}
                </div>
                ${items}
            </div>`;
    }).join('');

    _bnrShowSimpleModal({
        title: `🏆 Апгрейды клана · 💰 ${heroGold.toLocaleString('ru-RU')}`,
        body: tierHtml || '<div style="color:#adadb8;text-align:center;">Каталог пуст.</div>',
        bind: overlay => {
            overlay.querySelectorAll('[data-bnr-upg-buy]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const upgId = btn.dataset.bnrUpgBuy;
                    btn.disabled = true;
                    btn.textContent = '⏳ Покупаем...';
                    try {
                        const r = await fetch(`${API_URL}/api/bannerlord/clan-upgrades/buy`, {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json',
                                      'X-Twitch-JWT': authToken || ''},
                            body: JSON.stringify({upgrade_id: upgId}),
                        });
                        const d = await r.json();
                        showNotification(d.message, d.success ? 'success' : 'error', 4000);
                        if (d.success) {
                            // Refresh modal
                            overlay.remove();
                            _openBannerlordClanUpgradesModal();
                            if (typeof loadBannerlordHero === 'function') loadBannerlordHero();
                        } else {
                            btn.disabled = false;
                            btn.textContent = `Купить ${heroGold}💰`;
                        }
                    } catch (e) {
                        showNotification('Ошибка сети', 'error');
                        btn.disabled = false;
                    }
                });
            });
        },
    });
}

// Sprint 5.27a: profile modal — gender swap (+ marriage/family tree в 5.27b/c).
function _openBannerlordProfileModal() {
    const h = _bannerlordLastHero?.hero || {};
    const isFemale = !!h.is_female;
    const heroGold = h.gold || 0;
    const GENDER_COST = 50000;
    const canAfford = heroGold >= GENDER_COST;
    const currentLabel = h.is_female === true ? '♀ Женский'
                       : h.is_female === false ? '♂ Мужской'
                       : '— (не известно)';

    const body = `
        <div style="background:#1a1a1c;border:1px solid #3a3a3e;border-radius:6px;
                    padding:10px;margin-bottom:10px;">
            <div style="font-size:12px;color:#adadb8;margin-bottom:4px;">
                Текущий пол: <b style="color:#efeff1;">${currentLabel}</b>
            </div>
            <div style="font-size:11px;color:#adadb8;margin-bottom:8px;">
                Стоимость: <b style="color:#fbbf24;">${GENDER_COST.toLocaleString('ru-RU')}💰</b>
                · у тебя ${heroGold.toLocaleString('ru-RU')}💰
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                <button class="extra-btn" data-gender-set="male"
                        ${canAfford ? '' : 'disabled'}
                        style="font-size:12px;padding:8px;
                               background:${canAfford ? '#1e3a5f' : '#2d2d2f'};
                               color:${canAfford ? '#93c5fd' : '#6b7280'};
                               ${canAfford ? '' : 'cursor:not-allowed;'}">
                    ♂ Мужской
                </button>
                <button class="extra-btn" data-gender-set="female"
                        ${canAfford ? '' : 'disabled'}
                        style="font-size:12px;padding:8px;
                               background:${canAfford ? '#5b21b6' : '#2d2d2f'};
                               color:${canAfford ? '#f472b6' : '#6b7280'};
                               ${canAfford ? '' : 'cursor:not-allowed;'}">
                    ♀ Женский
                </button>
            </div>
            <div style="font-size:10px;color:#6b7280;margin-top:8px;text-align:center;">
                Если есть супруг(а) — engine автоматом перевернёт их пол
                чтоб брак остался валиден.
            </div>
        </div>
        <div style="background:#1a1a1c;border:1px solid #3a3a3e;border-radius:6px;
                    padding:10px;margin-bottom:8px;color:#6b7280;font-size:11px;
                    text-align:center;">
            🚧 Брак с NPC и family tree — в следующих обновлениях (5.27b/c)
        </div>
    `;

    _bnrShowSimpleModal({
        title: '🧬 Профиль и семья',
        body,
        bind: overlay => {
            overlay.querySelectorAll('[data-gender-set]').forEach(btn => {
                btn.addEventListener('click', () => {
                    const newGender = btn.dataset.genderSet;
                    if (!confirm(`Сменить пол на ${newGender === 'female' ? 'женский ♀' : 'мужской ♂'}? Спишет 50K💰.`)) return;
                    _bannerlordBuyAction('hero.set_gender', {gender: newGender});
                    overlay.remove();
                });
            });
        },
    });
}

function _openBannerlordKingdomModal() {
    const h = _bannerlordLastHero?.hero || {};
    const hasClan = !!h.clan_name;
    const hasKingdom = !!h.kingdom_name;
    const info = h.kingdom_info || null;

    let body;
    if (hasKingdom) {
        const infoBlock = info ? `
            <div style="background:rgba(147,197,253,0.05);border:1px solid #3d3d3f;
                        border-radius:6px;padding:8px 10px;margin-bottom:10px;">
                <div style="font-size:13px;color:#93c5fd;font-weight:700;margin-bottom:6px;
                            text-align:center;">
                    ${escapeHtml(info.name || h.kingdom_name)}
                </div>
                <div style="display:grid;grid-template-columns:auto 1fr;gap:4px 10px;font-size:11px;">
                    <span style="color:#adadb8;">👑 Правитель:</span>
                    <span style="color:#efeff1;">
                        ${escapeHtml(info.ruler_name || '?')}
                        ${info.is_ruler ? '<b style="color:#fbbf24;">(это ты!)</b>' : ''}
                    </span>
                    <span style="color:#adadb8;">🏰 Кланов:</span>
                    <span style="color:#efeff1;">${info.clans_count || 0}</span>
                    <span style="color:#adadb8;">🌆 Поселений:</span>
                    <span style="color:#efeff1;">${info.fiefs_count || 0}</span>
                    <span style="color:#adadb8;">⚔ Война с:</span>
                    <span style="color:${(info.at_war_count || 0) > 0 ? '#f87171' : '#efeff1'};">
                        ${info.at_war_count || 0} королевств
                    </span>
                </div>
            </div>` : `
            <div style="font-size:12px;color:#efeff1;margin-bottom:6px;">
                Текущее королевство: <b style="color:#fbbf24;">${escapeHtml(h.kingdom_name)}</b>
            </div>`;
        body = `
            ${infoBlock}
            <button class="extra-btn" id="bnr-kingdom-modal-leave"
                    title="Вывести clan из королевства — бесплатно."
                    style="width:100%;font-size:12px;padding:8px;
                           background:#7f1d1d;color:#fca5a5;">
                🚪 Покинуть королевство
            </button>`;
    } else if (!hasClan) {
        body = `
            <div style="font-size:11px;color:#fbbf24;margin-bottom:8px;">
                ⚠️ Сначала создай или вступи в клан — королевства создаются только клан-лидерами.
            </div>
            <button class="extra-btn" id="bnr-kingdom-goto-clan"
                    style="width:100%;font-size:12px;padding:8px;background:#3d3d3f;color:#fbbf24;">
                🏰 Открыть управление кланом
            </button>`;
    } else {
        body = `
            <div style="font-size:11px;color:#adadb8;margin-bottom:8px;">
                Твой клан '${escapeHtml(h.clan_name)}' независим. Можно создать собственное королевство или вступить в существующее.
            </div>
            <button class="extra-btn" id="bnr-kingdom-modal-create"
                    title="Создать собственное королевство (5,000,000💰 динаров). Clan становится правящим кланом."
                    style="width:100%;font-size:12px;padding:8px;margin-bottom:6px;
                           background:#7c2d12;color:#fbbf24;font-weight:700;">
                👑 Создать королевство (5M💰)
            </button>
            <button class="extra-btn" id="bnr-kingdom-modal-join"
                    title="Вступить в существующее королевство (100K💰)."
                    style="width:100%;font-size:12px;padding:8px;background:#1e3a5f;color:#93c5fd;">
                🤝 Вступить в королевство (100K💰)
            </button>`;
    }

    _bnrShowSimpleModal({
        title: '👑 Управление королевством',
        body: body,
        bind: overlay => {
            overlay.querySelector('#bnr-kingdom-goto-clan')?.addEventListener('click', () => {
                overlay.remove();
                _openBannerlordClanModal();
            });
            overlay.querySelector('#bnr-kingdom-modal-create')?.addEventListener('click', () => {
                overlay.remove();
                _openBannerlordCreateKingdomDialog();
            });
            overlay.querySelector('#bnr-kingdom-modal-join')?.addEventListener('click', () => {
                overlay.remove();
                _openBannerlordJoinDialog('kingdom');
            });
            overlay.querySelector('#bnr-kingdom-modal-leave')?.addEventListener('click', () => {
                if (!confirm('Ты уверен что хочешь покинуть королевство? Clan станет независимым.')) return;
                _bannerlordBuyAction('hero.leave_kingdom', {});
                overlay.remove();
            });
        },
    });
}

// Common modal shell — для clan / kingdom management.
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

// Sprint 5.12: dialog для ввода имени королевства + confirm "Создать".
function _openBannerlordCreateKingdomDialog() {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);' +
        'display:flex;align-items:center;justify-content:center;z-index:9999;padding:10px;';
    overlay.innerHTML = `
        <div style="background:#18181b;border:1px solid #3d3d3f;border-radius:8px;
                    padding:18px;max-width:340px;width:100%;">
            <h3 style="margin:0 0 10px 0;font-size:14px;color:#efeff1;">
                👑 Создать королевство
            </h3>
            <div style="font-size:11px;color:#adadb8;margin-bottom:10px;line-height:1.4;">
                Твой клан станет правящим в новом королевстве. Списывается
                <b style="color:#fbbf24;">5,000,000💰 динаров</b> + бонус: 2K влияния и
                2M kingdom wallet. Имя получит префикс <code>[BLink]</code>.
            </div>
            <input id="bnr-kingdom-name-input" type="text" maxlength="32"
                   placeholder="например: Великое Княжество"
                   style="width:100%;background:#2d2d2f;color:#efeff1;
                          border:1px solid #3d3d3f;border-radius:4px;
                          padding:6px 8px;font-size:12px;margin-bottom:12px;
                          box-sizing:border-box;">
            <div style="display:flex;gap:6px;">
                <button id="bnr-k-cancel" class="extra-btn"
                        style="flex:1;font-size:11px;padding:7px;background:#3d3d3f;">
                    Отмена
                </button>
                <button id="bnr-k-confirm" class="extra-btn"
                        style="flex:2;font-size:12px;padding:7px;background:#7c2d12;
                               color:#fbbf24;font-weight:700;">
                    👑 Создать (5M💰)
                </button>
            </div>
        </div>`;
    document.body.appendChild(overlay);
    const input = document.getElementById('bnr-kingdom-name-input');
    input?.focus();
    const close = () => overlay.remove();
    const confirm = () => {
        const kingdom_name = (input?.value || '').trim();
        _bannerlordBuyAction('hero.create_kingdom', { kingdom_name });
        close();
    };
    document.getElementById('bnr-k-cancel')?.addEventListener('click', close);
    document.getElementById('bnr-k-confirm')?.addEventListener('click', confirm);
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
    input?.addEventListener('keydown', e => {
        if (e.key === 'Enter') confirm();
        if (e.key === 'Escape') close();
    });
}

// Sprint 5.12: единый dialog для join — type 'clan' или 'kingdom'.
function _openBannerlordJoinDialog(type) {
    const isClan = type === 'clan';
    const config = isClan
        ? { icon: '🤝', title: 'Вступить в клан', cost: '50K💰',
            actionType: 'hero.join_clan', field: 'clan_name',
            placeholder: 'например: Vlandian Royal Clan',
            hint: 'Введи (часть) имя существующего клана. Mod fuzzy-matches.' }
        : { icon: '🤝', title: 'Вступить в королевство', cost: '100K💰',
            actionType: 'hero.join_kingdom', field: 'kingdom_name',
            placeholder: 'например: Vlandia',
            hint: 'Введи (часть) имя королевства. Твой clan присоединится как вассал.' };

    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);' +
        'display:flex;align-items:center;justify-content:center;z-index:9999;padding:10px;';
    overlay.innerHTML = `
        <div style="background:#18181b;border:1px solid #3d3d3f;border-radius:8px;
                    padding:18px;max-width:340px;width:100%;">
            <h3 style="margin:0 0 10px 0;font-size:14px;color:#efeff1;">
                ${config.icon} ${config.title}
            </h3>
            <div style="font-size:11px;color:#adadb8;margin-bottom:10px;line-height:1.4;">
                ${config.hint} Списать <b style="color:#fbbf24;">${config.cost} динаров</b>.
            </div>
            <input id="bnr-join-name-input" type="text" maxlength="64"
                   placeholder="${config.placeholder}"
                   style="width:100%;background:#2d2d2f;color:#efeff1;
                          border:1px solid #3d3d3f;border-radius:4px;
                          padding:6px 8px;font-size:12px;margin-bottom:12px;
                          box-sizing:border-box;">
            <div style="display:flex;gap:6px;">
                <button id="bnr-j-cancel" class="extra-btn"
                        style="flex:1;font-size:11px;padding:7px;background:#3d3d3f;">
                    Отмена
                </button>
                <button id="bnr-j-confirm" class="extra-btn"
                        style="flex:2;font-size:12px;padding:7px;background:#1e3a5f;
                               color:#93c5fd;font-weight:700;">
                    ${config.icon} Вступить (${config.cost})
                </button>
            </div>
        </div>`;
    document.body.appendChild(overlay);
    const input = document.getElementById('bnr-join-name-input');
    input?.focus();
    const close = () => overlay.remove();
    const confirm = () => {
        const name = (input?.value || '').trim();
        if (!name) return;
        _bannerlordBuyAction(config.actionType, { [config.field]: name });
        close();
    };
    document.getElementById('bnr-j-cancel')?.addEventListener('click', close);
    document.getElementById('bnr-j-confirm')?.addEventListener('click', confirm);
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
    input?.addEventListener('keydown', e => {
        if (e.key === 'Enter') confirm();
        if (e.key === 'Escape') close();
    });
}

// Sprint 5.9: dialog для ввода имени клана + confirm "Создать".
function _openBannerlordCreateClanDialog() {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);' +
        'display:flex;align-items:center;justify-content:center;z-index:9999;padding:10px;';
    overlay.innerHTML = `
        <div style="background:#18181b;border:1px solid #3d3d3f;border-radius:8px;
                    padding:18px;max-width:340px;width:100%;">
            <h3 style="margin:0 0 10px 0;font-size:14px;color:#efeff1;">
                🏰 Создать собственный клан
            </h3>
            <div style="font-size:11px;color:#adadb8;margin-bottom:10px;line-height:1.4;">
                Твой герой станет лидером нового клана и сможет создать отряд
                (party) на карте. Списывается <b style="color:#fbbf24;">1,000,000💰
                динаров</b> у героя в игре. Имя получит префикс <code>[BLink]</code>.
            </div>
            <div style="font-size:11px;color:#adadb8;margin-bottom:4px;">
                Имя клана (опционально, до 32 символов):
            </div>
            <input id="bnr-clan-name-input" type="text" maxlength="32"
                   placeholder="например: Воины Заката"
                   style="width:100%;background:#2d2d2f;color:#efeff1;
                          border:1px solid #3d3d3f;border-radius:4px;
                          padding:6px 8px;font-size:12px;margin-bottom:12px;
                          box-sizing:border-box;">
            <div style="display:flex;gap:6px;">
                <button id="bnr-clan-cancel" class="extra-btn"
                        style="flex:1;font-size:11px;padding:7px;background:#3d3d3f;">
                    Отмена
                </button>
                <button id="bnr-clan-confirm" class="extra-btn"
                        style="flex:2;font-size:12px;padding:7px;background:#7c2d12;
                               color:#fbbf24;font-weight:700;">
                    🏰 Создать (1M💰)
                </button>
            </div>
        </div>`;
    document.body.appendChild(overlay);

    const input = document.getElementById('bnr-clan-name-input');
    if (input) input.focus();

    const close = () => overlay.remove();
    const confirm = () => {
        const clan_name = (input?.value || '').trim();
        _bannerlordBuyAction('hero.create_clan', { clan_name });
        close();
    };

    document.getElementById('bnr-clan-cancel')?.addEventListener('click', close);
    document.getElementById('bnr-clan-confirm')?.addEventListener('click', confirm);
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
    input?.addEventListener('keydown', e => {
        if (e.key === 'Enter') confirm();
        if (e.key === 'Escape') close();
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

// ===== Sprint 5.5: Battle status indicator (banner only) =====
async function loadBannerlordBattleStatus() {
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/battle-status`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        const data = await r.json();
        if (!data.success) return;
        _bannerlordBattle = data;
        // На transition (старт боя) дёргаем buffs reload — backend сбрасывает
        // cooldowns у participants, frontend должен подхватить.
        if (!!data.in_battle && !_bannerlordWasInBattle) {
            if (typeof loadBannerlordBuffs === 'function') loadBannerlordBuffs();
        }
        _bannerlordWasInBattle = !!data.in_battle;
        _renderBannerlordBattleBanner(data);
    } catch (e) { /* silent */ }
}

function _renderBannerlordBattleBanner(data) {
    const slot = document.getElementById('bnr-battle-banner-slot');
    if (!slot) return;
    if (!data.in_battle) {
        slot.innerHTML = '';
        return;
    }

    const my = data.my_stats;
    const participantCount = data.participant_count || 0;
    const cnt = `${participantCount} участ.`;

    if (!my) {
        // Viewer не участвует в текущем бою — просто индикатор
        slot.innerHTML = `
            <div style="background:linear-gradient(135deg,#7c2d12,#dc2626);
                        border-radius:6px;padding:6px 10px;margin-bottom:6px;
                        font-size:11px;color:#fff;text-align:center;
                        animation:bnr-battle-pulse 2s ease-in-out infinite;">
                ⚔️ В игре идёт бой — ${cnt}
            </div>`;
        return;
    }

    // Viewer участвует — показываем его stats
    const hp = Math.max(0, my.hp || 0);
    const hpMax = Math.max(1, my.hp_max || 100);
    const pct = Math.max(0, Math.min(100, (hp / hpMax) * 100));
    const alive = my.alive && hp > 0;
    const stateLabels = {
        active: '⚔️ В бою',
        routed: '🏃 Бежит',
        unconscious: '💤 Без сознания',
        killed: '💀 Погиб',
    };
    const stateLabel = stateLabels[my.state] || (alive ? '⚔️ В бою' : '💀 Погиб');
    const stateColor = alive ? '#fbbf24' : '#f87171';

    slot.innerHTML = `
        <div style="background:linear-gradient(135deg,#1e293b,#7c2d12);
                    border:1px solid #dc2626;border-radius:8px;
                    padding:8px 10px;margin-bottom:8px;
                    box-shadow:0 0 12px rgba(220,38,38,0.4);">
            <div style="display:flex;justify-content:space-between;
                        align-items:center;margin-bottom:6px;">
                <span style="font-size:12px;color:${stateColor};font-weight:700;">
                    ${stateLabel}
                </span>
                <span style="font-size:10px;color:#9ca3af;">${cnt}</span>
            </div>
            <div style="background:rgba(0,0,0,0.4);border-radius:4px;
                        height:8px;overflow:hidden;margin-bottom:6px;">
                <div style="width:${pct.toFixed(1)}%;height:100%;
                            background:${alive ? 'linear-gradient(90deg,#dc2626,#10b981)' : '#525252'};
                            transition:width 0.4s ease;"></div>
            </div>
            <div style="display:flex;justify-content:space-between;
                        font-size:11px;font-family:'JetBrains Mono',monospace;">
                <span style="color:#efeff1;">❤ ${hp}/${hpMax}</span>
                <span style="color:#ffffff;">☠ ${my.kills || 0}</span>
                <span style="color:#fbbf24;">+${(my.gold_earned || 0).toLocaleString('ru-RU')}💰</span>
                <span style="color:#93c5fd;">+${(my.xp_earned || 0).toLocaleString('ru-RU')} XP</span>
            </div>
        </div>`;
}

// ===== Sprint 5.3: Турнир зрителей (BLT-style) =====
async function loadBannerlordTournament() {
    const body = document.getElementById('bannerlord-tournament-body');
    const badge = document.getElementById('bannerlord-tournament-status');
    if (!body || !badge) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/tournament`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        const data = await r.json();
        if (!data.success) {
            body.innerHTML = `<div style="color:#f87171;padding:8px;font-size:12px;">${escapeHtml(data.message || 'ошибка')}</div>`;
            return;
        }
        _bannerlordTournament = data;
        _renderBannerlordTournament(data);
    } catch (e) {
        // silent
    }
}

function _renderBannerlordTournament(data) {
    const body = document.getElementById('bannerlord-tournament-body');
    const badge = document.getElementById('bannerlord-tournament-status');
    if (!body || !badge) return;

    const state = data.state || {};
    const queue = data.queue || [];
    const cfg = data.config || {};
    const entryFee = (cfg.entry_fee_gold || 5000).toLocaleString('ru-RU');

    // Status badge
    if (state.status === 'running') {
        badge.textContent = `⚔️ раунд ${(state.current_round || 0) + 1}/4`;
        badge.style.color = '#fbbf24';
    } else {
        badge.textContent = `idle (${queue.length})`;
        badge.style.color = '#9ca3af';
    }

    if (state.status === 'running') {
        // RUNNING — показываем участников + ставки
        const participants = state.participants || [];
        const myBet = data.my_bet;

        let participantsHtml;
        if (myBet) {
            participantsHtml = `
                <div style="font-size:12px;color:#34d399;padding:6px;background:rgba(52,211,153,0.1);border-radius:4px;margin-bottom:6px;">
                    ✅ Ставка размещена: <b>${escapeHtml(myBet.target)}</b> на ${myBet.amount}⦷
                </div>`;
        } else {
            participantsHtml = `
                <div style="font-size:11px;color:#adadb8;margin-bottom:4px;">Поставь крустиков на участника (выигрыш делится пропорционально):</div>
                <div style="display:grid;grid-template-columns:1fr auto;gap:4px;align-items:center;">
                    ${participants.map(p => `
                        <span style="font-size:12px;">⚔️ ${escapeHtml(p)}</span>
                        <button class="extra-btn bnr-bet-btn" data-target="${escapeHtml(p)}"
                                style="font-size:11px;padding:3px 8px;">Поставить</button>
                    `).join('')}
                </div>`;
        }

        body.innerHTML = `
            <div style="padding:8px;">
                <div style="font-size:12px;color:#fbbf24;font-weight:700;margin-bottom:6px;">
                    🏆 Турнир идёт — раунд ${(state.current_round || 0) + 1}/4
                </div>
                ${participantsHtml}
                ${state.last_winner ? `<div style="font-size:11px;color:#adadb8;margin-top:6px;">Прошлый победитель: <b>${escapeHtml(state.last_winner)}</b></div>` : ''}
            </div>`;

        // Bind bet buttons
        body.querySelectorAll('.bnr-bet-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const target = btn.getAttribute('data-target');
                _promptBannerlordBet(target);
            });
        });
        return;
    }

    // IDLE — show queue + join button
    const inQueue = !!data.in_queue;

    const queueHtml = queue.length === 0
        ? '<div style="font-size:11px;color:#9ca3af;padding:4px 0;">очередь пуста</div>'
        : `<div style="font-size:11px;color:#adadb8;margin:4px 0 2px 0;">В очереди (${queue.length}/16):</div>` +
          queue.map((q, i) => `
            <div style="display:flex;justify-content:space-between;font-size:11px;padding:1px 6px;
                        ${q.username === data.my_username ? 'background:rgba(251,191,36,0.1);' : ''}">
                <span>${i + 1}. ${escapeHtml(q.username)}</span>
                <span style="color:#9ca3af;">${q.class_key || ''}</span>
            </div>`).join('');

    const joinBtnHtml = inQueue
        ? `<div style="font-size:12px;color:#34d399;text-align:center;padding:6px;background:rgba(52,211,153,0.1);border-radius:4px;margin-top:6px;">
                ✅ Ты в очереди, ждём пока стример запустит турнир
           </div>`
        : `<button class="extra-btn" id="bnr-join-tournament-btn"
                  title="Списывает ${entryFee} динаров у героя в игре (НЕ крустики)"
                  style="margin-top:6px;width:100%;font-size:12px;padding:8px;">
                ⚔️ Вступить в турнир (${entryFee}💰)
           </button>`;

    body.innerHTML = `
        <div style="padding:8px;">
            <div style="font-size:11px;color:#adadb8;margin-bottom:4px;">
                Когда стример запустит — все из очереди дерутся, победитель получает ${TOURNAMENT_PRIZE_GOLD.toLocaleString('ru-RU')}💰 + XP + приз. Раундовые победители получают ${TOURNAMENT_ROUND_GOLD.toLocaleString('ru-RU')}💰.
            </div>
            ${queueHtml}
            ${joinBtnHtml}
            ${state.last_winner ? `<div style="font-size:11px;color:#adadb8;margin-top:6px;text-align:center;">🏆 Прошлый победитель: <b>${escapeHtml(state.last_winner)}</b></div>` : ''}
        </div>`;

    const joinBtn = document.getElementById('bnr-join-tournament-btn');
    if (joinBtn) {
        joinBtn.addEventListener('click', () => {
            _bannerlordBuyAction('hero.join_tournament', { price: 0 });
        });
    }
}

const TOURNAMENT_PRIZE_GOLD = 50000;
const TOURNAMENT_ROUND_GOLD = 10000;
const TOURNAMENT_BET_PRESETS = [100, 500, 1000, 5000];

function _promptBannerlordBet(target) {
    // Modal-like prompt с выбором amount
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;z-index:9999;';
    overlay.innerHTML = `
        <div style="background:#18181b;border:1px solid #3d3d3f;border-radius:8px;padding:20px;max-width:320px;">
            <h3 style="margin:0 0 12px 0;font-size:14px;color:#efeff1;">💰 Ставка на @${escapeHtml(target)}</h3>
            <div style="font-size:11px;color:#adadb8;margin-bottom:10px;">
                Выбери сумму. Если @${escapeHtml(target)} победит в раунде — получишь долю pot'а.
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:10px;">
                ${TOURNAMENT_BET_PRESETS.map(amt => `
                    <button class="extra-btn bnr-bet-amount" data-amount="${amt}"
                            style="font-size:12px;padding:8px;">
                        ${amt}⦷
                    </button>
                `).join('')}
            </div>
            <button class="extra-btn" id="bnr-bet-cancel"
                    style="width:100%;font-size:11px;padding:6px;background:#3d3d3f;">
                Отмена
            </button>
        </div>`;
    document.body.appendChild(overlay);

    overlay.querySelectorAll('.bnr-bet-amount').forEach(btn => {
        btn.addEventListener('click', () => {
            const amount = parseInt(btn.getAttribute('data-amount'), 10);
            overlay.remove();
            _bannerlordBuyAction('tournament.bet', { target, amount });
        });
    });
    document.getElementById('bnr-bet-cancel').addEventListener('click', () => overlay.remove());
    overlay.addEventListener('click', e => {
        if (e.target === overlay) overlay.remove();
    });
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
        _bannerlordLastHero = data;   // 5.8: cache для progression modal
        if (!data.has_hero) {
            const CULTURES = [
                { key: 'empire',    label: 'Империя',  icon: '🏛️', desc: 'Латифундии, мечи и копья' },
                { key: 'sturgia',   label: 'Стургия',  icon: '🪓', desc: 'Севера́не, секиры, щиты' },
                { key: 'vlandia',   label: 'Вландия',  icon: '🛡️', desc: 'Рыцари и арбалетчики' },
                { key: 'aserai',    label: 'Асерай',   icon: '🐪', desc: 'Пустыня, лёгкая конница' },
                { key: 'khuzait',   label: 'Хузаит',   icon: '🐎', desc: 'Степные лучники' },
                { key: 'battania',  label: 'Баттания', icon: '🌲', desc: 'Лесные охотники, луки' },
            ];
            const cultureBtns = CULTURES.map(c => `
                <button class="extra-btn" data-bnr-culture="${c.key}"
                        title="${escapeHtml(c.desc)}"
                        style="font-size:12px;padding:6px 8px;display:flex;
                               flex-direction:column;align-items:center;gap:2px;
                               min-width:78px;">
                    <span style="font-size:18px;">${c.icon}</span>
                    <span>${escapeHtml(c.label)}</span>
                </button>`).join('');

            body.innerHTML = `
                <div style="text-align:center;padding:14px;color:#adadb8;font-size:13px;">
                    <div style="font-size:36px;margin-bottom:8px;">⚔️</div>
                    <div style="font-weight:700;color:#efeff1;margin-bottom:4px;">
                        У тебя ещё нет героя в Bannerlord
                    </div>
                    <div style="font-size:11px;margin-bottom:12px;">
                        Выбери культуру — герой родится в её землях.<br>
                        Имя в игре: <b style="color:#fbbf24;">[BLink] ${escapeHtml((window.userLogin || '').toLowerCase())}</b>
                    </div>
                    <div style="display:flex;flex-wrap:wrap;justify-content:center;gap:6px;">
                        ${cultureBtns}
                    </div>
                    <div style="margin-top:10px;font-size:10px;color:#6b7280;">
                        Можно также выбрать случайную:
                    </div>
                    <button class="extra-btn" id="bnr-adopt-random"
                            style="margin-top:6px;font-size:11px;padding:4px 12px;">
                        🎲 Случайная культура
                    </button>
                </div>`;

            // Bind culture-specific buttons
            body.querySelectorAll('[data-bnr-culture]').forEach(btn => {
                btn.addEventListener('click', () => {
                    const culture = btn.dataset.bnrCulture;
                    _bannerlordBuyAction('hero.create', { price: 0, culture });
                });
            });
            // Random button
            const randomBtn = document.getElementById('bnr-adopt-random');
            if (randomBtn) {
                randomBtn.addEventListener('click', () =>
                    _bannerlordBuyAction('hero.create', { price: 0 }));
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

        // Equipment + M21 stats: tier badge + per-type stat chips.
        // Sort: weapons → armor → horse чтобы выглядело упорядоченно.
        const _slotOrder = ['weapon0','weapon1','weapon2','weapon3',
            'head','body','leg','gloves','cape','horse','horseharness'];
        const _slotIcon = {
            weapon0:'⚔', weapon1:'⚔', weapon2:'⚔', weapon3:'⚔',
            head:'🪖', body:'👕', leg:'👢', gloves:'🧤', cape:'🧥',
            horse:'🐎', horseharness:'🐎',
        };
        const eqEntries = Object.entries(data.equipment || {})
            .sort((a, b) => (_slotOrder.indexOf(a[0]) + 100) - (_slotOrder.indexOf(b[0]) + 100));
        const eqHtml = eqEntries.length
            ? eqEntries.map(([slot, it]) => _renderEquipRow(slot, it, _slotIcon)).join('')
            : '<div style="font-size:11px;color:#adadb8;">Нет экипировки</div>';

        // Sprint M19: level / clan / kingdom badges
        // Sprint 5.11: clan/kingdom labels стали clickable — открывают modal
        // с вариантами create/join/leave (вместо inline-кнопок).
        const clanName = h.clan_name ? escapeHtml(h.clan_name)
                                     : '<span style="color:#9ca3af;">не вступил</span>';
        const kingdomName = h.kingdom_name ? escapeHtml(h.kingdom_name)
                                           : '<span style="color:#9ca3af;">не вступил</span>';
        const clanLabel = `
            <span class="bnr-clickable-row" id="bnr-clan-row"
                  title="Управление кланом"
                  style="cursor:pointer;text-decoration:underline dotted #6b7280;
                         text-underline-offset:3px;">
                ${clanName} <span style="font-size:9px;color:#9ca3af;">⚙</span>
            </span>`;
        const kingdomLabel = `
            <span class="bnr-clickable-row" id="bnr-kingdom-row"
                  title="Управление королевством"
                  style="cursor:pointer;text-decoration:underline dotted #6b7280;
                         text-underline-offset:3px;">
                ${kingdomName} <span style="font-size:9px;color:#9ca3af;">⚙</span>
            </span>`;
        // Sprint M20: gear tier indicator (cached для shop UI)
        // Sprint 5.10: inline "⚒ Улучшить" button рядом с tier label.
        const gearTier = h.gear_tier || 0;
        _bannerlordCurrentGearTier = gearTier;
        const _gtierText = gearTier === 0
            ? '<span style="color:#9ca3af;">базовое</span>'
            : `<span style="color:#fbbf24;">T${gearTier} ★</span>`;
        const _hasClass = !!_bannerlordClassesCache?.current?.class_key;
        let _gtierBtn = '';
        if (gearTier >= 6) {
            _gtierBtn = '<span style="color:#fbbf24;font-size:10px;margin-left:6px;">MAX</span>';
        } else if (_hasClass) {
            const _nextTier = gearTier + 1;
            const _cost = HERO_GOLD_TIER_COSTS[_nextTier] || 0;
            _gtierBtn = `<button class="small-btn" id="bnr-inline-upgrade-btn"
                    title="Улучшить снаряжение T${gearTier} → T${_nextTier}. Списать ${_cost.toLocaleString('ru-RU')}💰 динаров у героя."
                    style="font-size:10px;padding:2px 8px;margin-left:6px;
                           background:#3d3d3f;color:#fbbf24;">
                ⚒ T${_nextTier} (${_formatBigGold(_cost)})
            </button>`;
        } else {
            _gtierBtn = '<span style="color:#9ca3af;font-size:10px;margin-left:6px;">сначала класс</span>';
        }
        const gearTierLabel = _gtierText + _gtierBtn;

        // Sprint M21: armor summary — sum head/body/leg/arm coverage по
        // 5 armor slots (head/body/leg/gloves/cape). Engine считает
        // защиту по hitzone — viewer видит per-zone total.
        // Также avg tier по filled armor slots.
        const _armorSlots = ['head', 'body', 'leg', 'gloves', 'cape'];
        let totalHead = 0, totalBody = 0, totalLeg = 0, totalArm = 0;
        let tierSum = 0, tierCount = 0;
        for (const s of _armorSlots) {
            const eq = (data.equipment || {})[s];
            if (!eq) continue;
            const st = eq.stats || {};
            totalHead += st.head || 0;
            totalBody += st.body || 0;
            totalLeg  += st.leg  || 0;
            totalArm  += st.arm  || 0;
            if (eq.tier != null && eq.tier >= 0) {
                tierSum += eq.tier;
                tierCount++;
            }
        }
        const totalArmor = totalHead + totalBody + totalLeg + totalArm;
        const armorAvgTier = tierCount > 0 ? Math.round(tierSum / tierCount) + 1 : null;
        const armorLabel = totalArmor === 0
            ? '<span style="color:#9ca3af;">нет</span>'
            : `<span style="color:#efeff1;">🪖${totalHead} 👕${totalBody} 👢${totalLeg} 💪${totalArm}</span>` +
              (armorAvgTier ? ` <span style="color:#fbbf24;">~T${armorAvgTier}</span>` : '');

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
                <div style="display:grid;grid-template-columns:auto auto;gap:4px 8px;
                            font-size:12px;margin-bottom:8px;justify-content:start;
                            text-align:left;">
                    <span style="color:#adadb8;text-align:left;">💰 Динары:</span>
                    <span style="color:#fbbf24;font-weight:700;text-align:left;">${(h.gold || 0).toLocaleString('ru-RU')}</span>
                    <span style="color:#adadb8;text-align:left;">⭐ Уровень:</span>
                    <span style="color:#efeff1;font-weight:700;text-align:left;">${h.level || 1}</span>
                    <span style="color:#adadb8;text-align:left;">🛡 Снаряжение:</span>
                    <span style="color:#efeff1;font-weight:700;text-align:left;">${gearTierLabel}</span>
                    <span style="color:#adadb8;text-align:left;">🏰 Клан:</span>
                    <span style="color:#efeff1;text-align:left;">${clanLabel}</span>
                    <span style="color:#adadb8;text-align:left;">👑 Королевство:</span>
                    <span style="color:#efeff1;text-align:left;">${kingdomLabel}</span>
                    <span style="color:#adadb8;text-align:left;">🛡 Броня:</span>
                    <span style="text-align:left;">${armorLabel}</span>
                </div>
                <div id="bnr-battle-banner-slot"></div>
                <div id="bnr-buff-hud"></div>
                <div id="hero-class-picker-slot"></div>
                <div id="bnr-active-powers-slot"></div>
                <div id="bnr-summon-slot"></div>
                <button class="extra-btn" id="bnr-open-progression-btn"
                        title="Все скиллы с focus stars + 6 атрибутов"
                        style="width:100%;font-size:11px;padding:6px;margin-bottom:6px;">
                    🎯 Прогрессия — скиллы / фокусы / атрибуты
                </button>
                <button class="extra-btn" id="bnr-open-profile-btn"
                        title="Семейные настройки: смена пола, брак, дети"
                        style="width:100%;font-size:11px;padding:6px;margin-bottom:6px;
                               background:#1f1a30;color:#c084fc;">
                    🧬 Профиль и семья
                </button>
                <details data-bnr-details="equipment" ${_bnrDetailsAttr('equipment')}>
                    <summary style="font-size:11px;color:#adadb8;cursor:pointer;">Экипировка</summary>
                    <div style="margin-top:4px;">${eqHtml}</div>
                </details>
                <div id="bnr-retinue-slot"></div>
            </div>`;
        // Sprint M23 — render свита под equipment.
        _bannerlordLastRetinue = data.retinue || [];
        _renderRetinue(_bannerlordLastRetinue);
        renderBannerlordClassPicker();
        // Sprint 5.5: immediately repaint battle banner из cache чтобы
        // не было 0-2s gap'a после hero re-render.
        if (_bannerlordBattle) _renderBannerlordBattleBanner(_bannerlordBattle);
        // Sprint 5.5: bind toggle persistence для <details> (skills/equipment/retinue)
        _bnrBindDetailsPersistence();
        // Sprint 5.8: bind кнопку открытия progression modal
        document.getElementById('bnr-open-progression-btn')?.addEventListener('click',
            _openBannerlordProgressionModal);
        // Sprint 5.27a: profile modal (gender swap + marriage + family tree)
        document.getElementById('bnr-open-profile-btn')?.addEventListener('click',
            _openBannerlordProfileModal);
        // Sprint 5.11: bind clickable clan/kingdom rows (открывают modal)
        document.getElementById('bnr-clan-row')?.addEventListener('click',
            _openBannerlordClanModal);
        document.getElementById('bnr-kingdom-row')?.addEventListener('click',
            _openBannerlordKingdomModal);
        // Sprint 5.10: inline upgrade gear button (рядом с tier label)
        document.getElementById('bnr-inline-upgrade-btn')?.addEventListener('click', () => {
            _bannerlordBuyAction('hero.upgrade_gear', {});
        });
    } catch (e) {
        body.innerHTML = `<div style="color:#f87171;padding:10px;">Ошибка сети</div>`;
    }
}

async function loadBannerlordShop() {
    const list = document.getElementById('bannerlord-shop-list');
    const cnt  = document.getElementById('bannerlord-shop-count');
    if (!list) return;
    // Sprint M19+M20+M21: random-equip + gear-upgrade + currency (gold/XP) сверху.
    // Sprint 5.10/5.8c: gear-upgrade перенесён в hero card (inline кнопка);
    // progression — в modal (per-row + buttons). В shop остались только
    // randomEquip + currency converters.
    const randomEquipBlock = renderBannerlordRandomEquipHtml();
    const currencyBlock = renderBannerlordCurrencyHtml();
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/shop`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        const data = await r.json();
        if (!data.success) {
            list.innerHTML = randomEquipBlock + currencyBlock +
                `<div class="loading">${escapeHtml(data.message || 'Ошибка')}</div>`;
            _bindBannerlordRandomEquip();
            _bindBannerlordCurrency();
            return;
        }
        const items = data.items || [];
        // +3 random-equip + 3 give_gold + 3 add_skill = +9 fixed actions
        if (cnt) cnt.textContent = items.length + 9;
        if (items.length === 0) {
            list.innerHTML = randomEquipBlock + currencyBlock + `
                <div style="text-align:center;padding:14px;font-size:11px;color:#adadb8;border-top:1px solid #3d3d3f;margin-top:6px;">
                    Каталог пуст. Мод пришлёт shop-данные когда стример запустит игру.
                </div>`;
            _bindBannerlordRandomEquip();
            _bindBannerlordCurrency();
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
        list.innerHTML = randomEquipBlock + currencyBlock + catalogHtml;
        _bindBannerlordRandomEquip();
        _bindBannerlordCurrency();
        // Bind buy handlers для catalog items
        list.querySelectorAll('[data-bnr-buy]').forEach(btn => {
            btn.addEventListener('click', () => {
                const actionType = btn.dataset.bnrBuy;
                const price = parseInt(btn.dataset.bnrPrice || '0', 10);
                _bannerlordBuyAction(actionType, { price });
            });
        });
    } catch (e) {
        list.innerHTML = randomEquipBlock + currencyBlock +
            `<div class="loading" style="color:#f87171;">Ошибка сети</div>`;
        _bindBannerlordRandomEquip();
        _bindBannerlordCurrency();
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
