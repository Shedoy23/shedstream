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
// Sprint 5.31 #45 — broadcaster JWT role (Boosty admin button gating).
let _isBroadcaster = false;

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
            _isBroadcaster = (payload.role === 'broadcaster');
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
                // Sprint 5.31 #45 — broadcaster role detect для Boosty admin UI.
                _isBroadcaster = (payload.role === 'broadcaster');
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
    // Sprint 5.31 #45b: подгрузить role+sub-tier badges под ником.
    loadUserPerksBadge();
    if (!window._intervalUserPerks) {
        // Refresh каждые 5 мин (Helix sub cache TTL).
        window._intervalUserPerks = safeInterval(loadUserPerksBadge, 5 * 60 * 1000);
    }
    
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


// Sprint 5.31 #45b — обновить бейдж роли + tier'ов под ником зрителя.
// Endpoint /api/viewer/perks возвращает {role, twitch_sub_tier, boosty_tier}.
// Role: broadcaster → '👑 Стример', moderator → '🛡 Модер', else 'Зритель'.
// Tier'ы: Twitch sub → TS1/TS2/TS3 (фиолет), Boosty → BS1/BS2/BS3 (фиолет тёмнее).
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
            const bs = parseInt(d.boosty_tier || 0, 10);
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
            if (bs >= 1 && bs <= 3) {
                badges.push(
                    `<span title="Boosty Sub Tier ${bs}"
                           style="${badgeStyle('#2a0a3a','#a21caf','#e879f9',true)}">
                        BS${bs}
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
            <div style="font-size:11px;color:#adadb8;">${escapeHtml(title)}${bonus_pct > 0 ? ` (+${Number(bonus_pct) || 0}% доход)` : ''}</div>
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
let _bnrOptimisticStance = null;         // 2026-06-10 — оптимистичная боевая стойка до эха мода

// Sprint 5.5: helper для проверки battle state (для banner / future use).
function bnrIsInBattle() { return !!(_bannerlordBattle && _bannerlordBattle.in_battle); }

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
    rage:               { icon: '🔥', label: 'Ярость',    desc: 'damage ×, 45с' },
    retribution_toggle: { icon: '🪖', label: 'Стойкость', desc: '−% урона, 45с' },
    // Sprint 5.33 (BLT-parity FX) — character effects.
    poison_dot:         { icon: '☠',  label: 'Яд',        desc: 'Случ. враг DoT 45с' },
    disarm_burst:       { icon: '💥', label: 'Обезоружить', desc: 'Случ. враг роняет оружие' },
    berserker_charge:   { icon: '💨', label: 'Берсерк-рывок', desc: '+speed 45с (себе)' },
    // 2026-05-29 (BLT-parity combat powers) — active варианты.
    lifesteal_burst:    { icon: '🩸', label: 'Вампиризм',   desc: '% урона → хил, 45с' },
    ironskin_toggle:    { icon: '🛡', label: 'Железная кожа', desc: '−% урона, 45с' },
    explosive_arrows:   { icon: '🧨', label: 'Взрывные стрелы', desc: 'AoE с попаданий, 45с' },
};
const BNR_POWER_PRICES = {
    heal_burst:         100,
    shield_break_burst: 200,
    rage:               300,
    retribution_toggle: 300,
    // Sprint 5.33 FX
    poison_dot:         350,  // DoT — медленный, но total damage высокий
    disarm_burst:       250,  // disarm — disruption, не damage
    berserker_charge:   200,  // mobility self-buff
    // 2026-05-29 (BLT-parity combat powers)
    lifesteal_burst:    300,  // sustain burst
    ironskin_toggle:    300,  // defensive burst (как retribution)
    explosive_arrows:   350,  // ranged AoE burst (high value)
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

// Sprint 5.32 #46 — daily rewards. 1 раз в день (UTC) viewer выбирает либо
// 100K💰 динаров либо 50K XP в random skill. Increments engagement (открытие
// расширения раз в день за бонусом).
async function loadBannerlordDaily() {
    const slot = document.getElementById('bnr-daily-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/daily-status`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        const d = await r.json();
        if (!d || !d.success) return;  // AUDIT fix: keep last render on transient fail
        const goldAmt = (d.reward_amounts?.gold || 100000).toLocaleString('ru-RU');
        const xpAmt   = (d.reward_amounts?.xp   || 50000).toLocaleString('ru-RU');
        if (d.can_claim) {
            slot.innerHTML = `
                <div style="background:linear-gradient(135deg,#3a2a0a,#2a200a);
                            border:1px solid #92400e;border-radius:6px;padding:8px 10px;">
                    <div style="font-size:11px;color:#fbbf24;font-weight:700;margin-bottom:6px;
                                display:flex;align-items:center;gap:4px;">
                        🎁 Дейлик доступен! Выбери награду:
                    </div>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                        <button class="extra-btn" id="bnr-daily-claim-gold"
                                title="Получить ${goldAmt}💰 динаров (Hero.Gold)"
                                style="font-size:11px;padding:8px 4px;
                                       background:#3a2a0a;color:#fbbf24;font-weight:700;
                                       border:1px solid #b45309;">
                            💰 +${goldAmt} динаров
                        </button>
                        <button class="extra-btn" id="bnr-daily-claim-xp"
                                title="Получить ${xpAmt} XP в случайный скилл (class-weighted)"
                                style="font-size:11px;padding:8px 4px;
                                       background:#1e3a5f;color:#93c5fd;font-weight:700;
                                       border:1px solid #1d4ed8;">
                            📚 +${xpAmt} XP
                        </button>
                    </div>
                </div>`;
            slot.querySelector('#bnr-daily-claim-gold')?.addEventListener('click',
                () => _claimDailyReward('gold'));
            slot.querySelector('#bnr-daily-claim-xp')?.addEventListener('click',
                () => _claimDailyReward('xp'));
        } else {
            const lastRew = d.last_reward_type === 'gold'
                ? `💰 ${goldAmt} динаров`
                : `📚 ${xpAmt} XP`;
            slot.innerHTML = `
                <div style="background:rgba(58,42,10,0.3);border:1px solid #3d3d3f;
                            border-radius:6px;padding:7px 10px;font-size:11px;
                            color:#9ca3af;">
                    🎁 Сегодня уже забрал: <span style="color:#fbbf24;">${lastRew}</span>.
                    <span style="font-size:10px;display:block;margin-top:2px;">
                        Возвращайся завтра в 00:00 UTC за новым дейликом.
                    </span>
                </div>`;
        }
    } catch (e) { dbg('[BNR daily] failed', e); }
}

async function _claimDailyReward(rewardType) {
    const goldBtn = document.getElementById('bnr-daily-claim-gold');
    const xpBtn   = document.getElementById('bnr-daily-claim-xp');
    if (goldBtn) goldBtn.disabled = true;
    if (xpBtn)   xpBtn.disabled = true;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/daily-claim`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Twitch-JWT': authToken || '',
            },
            body: JSON.stringify({ reward_type: rewardType }),
        });
        const d = await r.json();
        showNotification(d.message || (d.success ? 'OK' : 'Ошибка'), d.success ? 'success' : 'error');
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    }
    // Re-load status (показывает "уже забрал" state).
    loadBannerlordDaily();
    // Refresh hero для отображения gold/level updates когда мод применит.
    setTimeout(loadBannerlordHero, 1500);
}

// Sprint 5.32 (BLT-parity FE-M2) — heir queue display.
// Backend `hero.heir_came_of_age` event пушит ребёнка adopted hero'я в очередь.
// На death героя backend auto-pick first alive heir (M2.1 ActivateHeirHandler).
// Frontend показывает кому-то в очереди наследники — пользователь видит
// continuity своего рода.
async function loadBannerlordHeirs() {
    const slot = document.getElementById('bnr-heir-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/heirs`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        const d = await r.json();
        if (!d || d.success === false) return;  // AUDIT fix: keep last on transient fail
        if (!Array.isArray(d.heirs) || d.heirs.length === 0) {
            _smartInnerHTML(slot, '');  // genuine empty — dedup, no flicker
            return;
        }
        // Sprint 5.32 (LOG-4) — info log при non-empty heirs. Silent на 0
        // (большинство пользователей без heirs, не спамим).
        console.info('[FE-HEIR] loaded', d.heirs.length, 'heirs:',
                     d.heirs.map(h => h.name).join(', '));
        const names = d.heirs.map(h => escapeHtml(h.name || '?')).join(', ');
        // Truncate если очень длинный.
        const namesDisplay = names.length > 80 ? names.slice(0, 78) + '…' : names;
        slot.innerHTML = `
            <div style="background:#1a1a2e;border:1px solid #5b21b6;border-radius:4px;
                        padding:6px 8px;font-size:11px;color:#c084fc;"
                 title="На смерть героя первый из списка автоматически унаследует имя [BLink] и стартанёт с прокачанным уровнем + clan.">
                🕯 <b>Наследников: ${d.heirs.length}</b>
                <span style="color:#a78bfa;">${namesDisplay}</span>
            </div>`;
    } catch (e) {
        console.warn('[FE-M2] loadHeirs failed (keeping last render)', e);
    }
}

// Sprint 5.33 (BLT-parity FAM) — Family section: children list + per-child actions +
// proposals (incoming/outgoing). Главный engagement loop для multi-generation streamов.
async function loadBannerlordFamily() {
    const slot = document.getElementById('bnr-family-slot');
    if (!slot) return;
    try {
        const [childrenR, proposalsR] = await Promise.all([
            fetch(`${API_URL}/api/bannerlord/my-children`, {
                headers: { 'X-Twitch-JWT': authToken || '' }
            }).then(r => r.json()).catch(() => ({success: false})),
            fetch(`${API_URL}/api/bannerlord/proposals`, {
                headers: { 'X-Twitch-JWT': authToken || '' }
            }).then(r => r.json()).catch(() => ({success: false})),
        ]);
        const children = (childrenR.success && Array.isArray(childrenR.children))
            ? childrenR.children : [];
        const incoming = (proposalsR.success && Array.isArray(proposalsR.incoming))
            ? proposalsR.incoming : [];
        const outgoing = (proposalsR.success && Array.isArray(proposalsR.outgoing))
            ? proposalsR.outgoing : [];

        // Если у viewer'а нет ни детей, ни proposals — section скрыта
        if (children.length === 0 && incoming.length === 0 && outgoing.length === 0) {
            slot.innerHTML = '';
            return;
        }
        console.info('[FE-FAM] loaded children=%d incoming=%d outgoing=%d',
                     children.length, incoming.length, outgoing.length);

        let html = `
            <div style="background:#1a1a2e;border:1px solid #5b21b6;border-radius:4px;
                        padding:8px;font-size:11px;color:#c4b5fd;">
                <div style="font-size:12px;font-weight:700;color:#a78bfa;margin-bottom:6px;">
                    🌳 Семья и потомство
                </div>`;

        // Incoming proposals (приоритет внимания)
        if (incoming.length > 0) {
            // 2026-06-07 — предложения брака inline (принять/отклонить прямо тут,
            // без модалки).
            html += `
                <div style="background:#3b0a4a;padding:6px;border-radius:3px;margin-bottom:6px;">
                    <div style="color:#f0abfc;font-weight:700;margin-bottom:4px;">
                        💍 Входящих предложений: ${incoming.length}
                    </div>
                    ${incoming.map(p => `
                        <div data-proposal-id="${p.id}"
                             style="background:#0f0a18;padding:5px 6px;border-radius:3px;margin-bottom:4px;">
                            <div style="font-size:10px;color:#e9d5ff;margin-bottom:4px;">
                                от @${escapeHtml(p.proposer_username)}: «${escapeHtml(p.proposer_child_name)} ❤ ${escapeHtml(p.target_child_name)}»
                            </div>
                            <div style="display:flex;gap:4px;">
                                <button class="bnr-prop-accept small-btn"
                                        style="flex:1;font-size:10px;padding:3px;background:#15803d;color:#dcfce7;font-weight:700;">✓ Принять</button>
                                <button class="bnr-prop-reject small-btn"
                                        style="flex:1;font-size:10px;padding:3px;background:#7f1d1d;color:#fee2e2;font-weight:700;">✗ Отклонить</button>
                            </div>
                        </div>
                    `).join('')}
                </div>`;
        }

        // Outgoing (мои pending) — Sprint 5.33 UI-Gap1: добавлена кнопка отзыва
        // (× cancel) per proposal. Раньше viewer не мог withdraw proposal — теперь может.
        if (outgoing.length > 0) {
            html += `
                <div style="font-size:10px;color:#9ca3af;margin-bottom:4px;">
                    📤 Отправлено: ${outgoing.length}
                    <span style="color:#6b7280;">(ждут ответа)</span>
                </div>
                <div style="display:flex;flex-direction:column;gap:3px;margin-bottom:6px;">
                    ${outgoing.map(p => `
                        <div data-proposal-id="${p.id}"
                             data-proposal-summary="${escapeHtml(p.proposer_child_name)} ❤ ${escapeHtml(p.target_child_name)}"
                             style="display:flex;justify-content:space-between;align-items:center;
                                    background:#0f0a18;padding:4px 6px;border-radius:3px;font-size:10px;">
                            <span style="color:#c4b5fd;">
                                к @${escapeHtml(p.target_username)}:
                                «${escapeHtml(p.proposer_child_name)} ❤ ${escapeHtml(p.target_child_name)}»
                            </span>
                            <button class="bnr-fam-cancel small-btn"
                                    title="Отозвать предложение (бесплатно)"
                                    style="font-size:9px;padding:2px 5px;background:#2d2d3f;
                                           color:#fb7185;">✕</button>
                        </div>
                    `).join('')}
                </div>`;
        }

        // Children list
        if (children.length > 0) {
            html += `
                <div style="font-size:10px;color:#9ca3af;margin-top:4px;margin-bottom:4px;">
                    👨‍👩‍👧 Взрослых детей: ${children.length}
                </div>
                <div style="display:flex;flex-direction:column;gap:3px;">
                    ${children.map(c => `
                        <div data-child-id="${escapeHtml(c.hero_id)}"
                             data-child-name="${escapeHtml(c.name)}"
                             style="display:flex;justify-content:space-between;align-items:center;
                                    background:#0f0f1e;padding:4px 6px;border-radius:3px;">
                            <span style="color:#e9d5ff;font-size:11px;">${escapeHtml(c.name)}</span>
                            <div style="display:flex;gap:3px;">
                                <button class="bnr-fam-rename small-btn" title="Переименовать (50💎)"
                                        style="font-size:9px;padding:2px 5px;background:#2d2d3f;color:#a78bfa;">✏</button>
                                <button class="bnr-fam-looks small-btn" title="Изменить внешность (200💎). Скопируй body_code из in-game character menu"
                                        style="font-size:9px;padding:2px 5px;background:#2d2d3f;color:#a78bfa;">🎨</button>
                                <button class="bnr-fam-respec small-btn" title="Респект скиллов (500💎)"
                                        style="font-size:9px;padding:2px 5px;background:#2d2d3f;color:#a78bfa;">🎯</button>
                                <button class="bnr-fam-propose small-btn" title="Предложить брак другому viewer'у (100💎)"
                                        style="font-size:9px;padding:2px 5px;background:#4c1d95;color:#fff;">💍</button>
                            </div>
                        </div>
                    `).join('')}
                </div>`;
        } else {
            html += `
                <div style="font-size:10px;color:#6b7280;margin-top:4px;">
                    Дети взрослеют через ~18 лет после make_baby. Жди.
                </div>`;
        }
        html += `</div>`;
        // FLICKER-FIX: skip rebind при identical HTML.
        if (!_smartInnerHTML(slot, html)) return;

        // Bind handlers
        slot.querySelectorAll('.bnr-prop-accept').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const id = parseInt(e.target.closest('[data-proposal-id]').dataset.proposalId, 10);
                _bannerlordBuyAction('hero.respond_marriage_proposal', { proposal_id: id, accept: true });
                setTimeout(loadBannerlordFamily, 1500);
            });
        });
        slot.querySelectorAll('.bnr-prop-reject').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const id = parseInt(e.target.closest('[data-proposal-id]').dataset.proposalId, 10);
                _bannerlordBuyAction('hero.respond_marriage_proposal', { proposal_id: id, accept: false });
                setTimeout(loadBannerlordFamily, 1500);
            });
        });
        slot.querySelectorAll('.bnr-fam-rename').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const parent = e.target.closest('[data-child-id]');
                if (!parent) return;
                _famRenameChild(parent.dataset.childId, parent.dataset.childName);
            });
        });
        slot.querySelectorAll('.bnr-fam-respec').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const parent = e.target.closest('[data-child-id]');
                if (!parent) return;
                _famRespecChild(parent.dataset.childId, parent.dataset.childName);
            });
        });
        slot.querySelectorAll('.bnr-fam-propose').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const parent = e.target.closest('[data-child-id]');
                if (!parent) return;
                _famProposeMarriage(parent.dataset.childId, parent.dataset.childName);
            });
        });
        // Sprint 5.33 UI-Gap1: cancel outgoing proposal binding
        slot.querySelectorAll('.bnr-fam-cancel').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const parent = e.target.closest('[data-proposal-id]');
                if (!parent) return;
                const proposalId = parseInt(parent.dataset.proposalId, 10);
                const summary = parent.dataset.proposalSummary || 'предложение';
                if (!await _bnrConfirm(
                    `Отозвать «${summary}»?`,
                    'Отозвать'
                )) return;
                await _bannerlordBuyAction('hero.cancel_proposal',
                    { proposal_id: proposalId });
                setTimeout(loadBannerlordFamily, 1500);
            });
        });
        // Sprint 5.33 UI-Gap2: change-looks button binding (per child)
        slot.querySelectorAll('.bnr-fam-looks').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const parent = e.target.closest('[data-child-id]');
                if (!parent) return;
                _famChangeChildLooks(parent.dataset.childId, parent.dataset.childName);
            });
        });
    } catch (e) {
        console.warn('[FE-FAM] loadFamily failed (keeping last render)', e);
    }
}

async function _famRenameChild(childId, currentName) {
    const newName = window.prompt(`Новое имя для «${currentName}»:`, currentName);
    if (!newName || newName === currentName) return;
    await _bannerlordBuyAction('hero.rename_child',
        { child_hero_id: childId, new_name: newName });
    setTimeout(loadBannerlordFamily, 1500);
}

async function _famRespecChild(childId, name) {
    if (!await _bnrConfirm(
        `Сбросить все скиллы «${name}» (500💎)? Hero вернётся к 0 levels.`,
        'Респект')) return;
    await _bannerlordBuyAction('hero.respec_child_skills',
        { child_hero_id: childId });
}

// Sprint 5.33 UI-Gap2 — change child appearance (BLT pattern body_code change).
// Mod handler expects body_code = TaleWorlds BodyProperties.FromString format —
// long hex/key string. Easiest UX: viewer copies body_code из in-game character
// creator (Profile/Looks menu имеет "Export" button в 1.3.x), pastes здесь.
async function _famChangeChildLooks(childId, name) {
    const bodyCode = window.prompt(
        `🎨 Изменить внешность «${name}» (200💎)\n\n` +
        `Вставь body_code (скопируй из in-game character menu → Export).\n` +
        `Поддерживается формат TaleWorlds BodyProperties.`,
        ''
    );
    if (!bodyCode || bodyCode.trim().length < 8) {
        if (bodyCode !== null) {
            showNotification('body_code слишком короткий или невалидный', 'warning');
        }
        return;
    }
    await _bannerlordBuyAction('hero.change_child_looks', {
        child_hero_id: childId,
        body_code: bodyCode.trim(),
    });
    setTimeout(loadBannerlordFamily, 1500);
}

async function _famProposeMarriage(myChildId, myChildName) {
    // Дети наследуют клан родителя; у бесклановых детей брак = клейтлесс-краш
    // беременности. Не даём отправить proposal без клана.
    const _h = _bannerlordLastHero?.hero || {};
    if (!_h.clan_name) {
        showNotification('Нужен клан, чтобы устраивать браки детей — сначала создай или вступи в клан (🏰).', 'warning');
        return;
    }
    const targetUser = window.prompt(
        `Предложить брак для «${myChildName}». Введи username другого viewer'а:`);
    if (!targetUser) return;
    const tu = targetUser.trim().toLowerCase().replace(/^@/, '');
    if (!tu) return;
    // Fetch their children
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/public-children?username=${encodeURIComponent(tu)}`, {
            headers: { 'X-Twitch-JWT': authToken || '' }
        });
        const d = await r.json();
        if (!d.success || !Array.isArray(d.children) || d.children.length === 0) {
            showNotification(`У @${tu} нет взрослых детей`, 'warning');
            return;
        }
        // UI choice — простой prompt с numbered list (MVP)
        const list = d.children.map((c, i) => `${i+1}. ${c.name}`).join('\n');
        const choice = window.prompt(
            `Дети @${tu}:\n${list}\n\nВведи номер (1-${d.children.length}):`);
        const idx = parseInt(choice, 10) - 1;
        if (isNaN(idx) || idx < 0 || idx >= d.children.length) return;
        const targetChild = d.children[idx];
        if (!await _bnrConfirm(
            `Предложить @${tu}: «${myChildName} ❤ ${targetChild.name}»? (100💎)`,
            'Отправить'
        )) return;
        await _bannerlordBuyAction('hero.propose_marriage', {
            price: 100,
            proposer_child_hero_id: myChildId,
            target_username: tu,
            target_child_hero_id: targetChild.hero_id,
        });
        setTimeout(loadBannerlordFamily, 1500);
    } catch (e) {
        console.warn('[FE-FAM] propose failed', e);
        showNotification('Ошибка сети', 'error');
    }
}

// 2026-06-07 — _openProposalsModal удалена: предложения брака теперь инлайн в
// секции семьи (принять/отклонить per-proposal, см. loadBannerlordFamily).

// Sprint 5.33 (BLT-parity VAS) — Vassal sub-clan management.
// Viewer-leader клана может выделить взрослого ребёнка (heir) в собственный
// vassal-clan. Прогрессия sub-clan'ов = long-term retention для donator'ов.
async function loadBannerlordVassals() {
    const slot = document.getElementById('bnr-vassals-slot');
    if (!slot) return;
    try {
        const [vassR, heirsR] = await Promise.all([
            fetch(`${API_URL}/api/bannerlord/vassals`, {
                headers: { 'X-Twitch-JWT': authToken || '' }
            }).then(r => r.json()).catch(() => ({success: false})),
            fetch(`${API_URL}/api/bannerlord/eligible-heirs`, {
                headers: { 'X-Twitch-JWT': authToken || '' }
            }).then(r => r.json()).catch(() => ({success: false})),
        ]);
        const vassals = (vassR.success && Array.isArray(vassR.vassals))
            ? vassR.vassals : [];
        const eligible = (heirsR.success && Array.isArray(heirsR.heirs))
            ? heirsR.heirs : [];

        // Hide section если нет vassals и нет eligible heirs.
        if (vassals.length === 0 && eligible.length === 0) {
            slot.innerHTML = '';
            return;
        }
        console.info('[FE-VAS] loaded vassals=%d eligible=%d',
                     vassals.length, eligible.length);

        let html = `
            <div style="background:#1a1f2e;border:1px solid #1e40af;border-radius:4px;
                        padding:8px;font-size:11px;color:#bfdbfe;">
                <div style="font-size:12px;font-weight:700;color:#60a5fa;margin-bottom:6px;">
                    🏰 Вассальные кланы
                </div>`;
        if (vassals.length > 0) {
            html += `
                <div style="display:flex;flex-direction:column;gap:3px;margin-bottom:6px;">
                    ${vassals.map(v => `
                        <div data-vassal-id="${v.id}"
                             data-vassal-name="${escapeHtml(v.vassal_name)}"
                             style="display:flex;justify-content:space-between;align-items:center;
                                    background:#0f1730;padding:4px 6px;border-radius:3px;">
                            <span style="color:#dbeafe;font-size:11px;">🏰 ${escapeHtml(v.vassal_name)}</span>
                            <button class="bnr-vas-rename small-btn"
                                    title="Переименовать (100💎)"
                                    style="font-size:9px;padding:2px 5px;background:#1e3a8a;color:#bfdbfe;">✏</button>
                        </div>
                    `).join('')}
                </div>`;
        }
        if (eligible.length > 0 && vassals.length < 5) {
            // 2026-06-07 — создание вассала инлайн (lazy <details>): <select>-наследник
            // + text-имя переживают 8s-poll (форма рендерится при раскрытии).
            html += `
                <details data-bnr-details="vas-create" ${_bnrDetailsAttr('vas-create')}>
                    <summary title="Выделить взрослого ребёнка в собственный sub-clan (250K💰 у героя)"
                             style="list-style:none;cursor:pointer;width:100%;
                                    font-size:11px;padding:6px;background:#1e3a8a;box-sizing:border-box;
                                    color:#fff;font-weight:700;border-radius:3px;text-align:center;">
                        🏰 Создать вассала (250K💰) — ${eligible.length} наследников доступно
                    </summary>
                    <div id="bnr-vas-create-slot" style="padding-top:6px;"></div>
                </details>`;
        } else if (vassals.length >= 5) {
            html += `
                <div style="font-size:10px;color:#6b7280;text-align:center;">
                    Максимум вассалов (5/5)
                </div>`;
        }
        html += `</div>`;
        // 2026-06-07 FLICKER — пока форма создания вассала раскрыта, НЕ перерисовываем
        // секцию (иначе repaint стирает выбор наследника / ввод имени).
        if (slot.querySelector('[data-bnr-details="vas-create"]')?.open) return;
        // FLICKER-FIX: skip rebind при identical HTML.
        if (!_smartInnerHTML(slot, html)) return;

        // Bind rename buttons
        slot.querySelectorAll('.bnr-vas-rename').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const parent = e.target.closest('[data-vassal-id]');
                if (!parent) return;
                const id = parseInt(parent.dataset.vassalId, 10);
                const oldName = parent.dataset.vassalName || '';
                const newName = window.prompt(`Новое имя для «${oldName}»:`, oldName);
                if (!newName || newName === oldName) return;
                await _bannerlordBuyAction('hero.rename_vassal', {
                    vassal_id: id,
                    new_name: newName,
                });
                setTimeout(loadBannerlordVassals, 1500);
            });
        });

        // Bind create — lazy inline форма (heir select + name) при раскрытии.
        const _vasDet = slot.querySelector('[data-bnr-details="vas-create"]');
        if (_vasDet) {
            _vasDet.addEventListener('toggle', () => { if (_vasDet.open) _renderCreateVassalInline(eligible); });
            if (_vasDet.open) _renderCreateVassalInline(eligible);
        }
    } catch (e) {
        console.warn('[FE-VAS] loadVassals failed (keeping last render)', e);
    }
}

// удалена: инлайн lazy-форма вассала (_renderCreateVassalInline) вместо модалки.
function _renderCreateVassalInline(eligibleHeirs) {
    const slot = document.getElementById('bnr-vas-create-slot');
    if (!slot) return;
    if (!eligibleHeirs || eligibleHeirs.length === 0) { slot.innerHTML = ''; return; }
    slot.innerHTML = `
        <div style="background:#1a1f2e;border:1px solid #1e40af;border-radius:4px;
                    padding:10px;color:#bfdbfe;">
            <div style="font-size:11px;color:#9ca3af;margin-bottom:8px;">
                Выдели взрослого наследника в собственный sub-clan.
                Он станет лидером, ваш клан получает 25% от его доходов.
            </div>
            <label style="font-size:11px;color:#dbeafe;display:block;margin-bottom:4px;">
                Наследник:
            </label>
            <select id="bnr-vas-heir-pick"
                    style="width:100%;padding:6px;font-size:12px;background:#0f1730;
                           color:#dbeafe;border:1px solid #1e40af;margin-bottom:8px;">
                ${eligibleHeirs.map(h =>
                    `<option value="${escapeHtml(h.hero_id)}">${escapeHtml(h.name)}</option>`
                ).join('')}
            </select>
            <label style="font-size:11px;color:#dbeafe;display:block;margin-bottom:4px;">
                Имя нового клана:
            </label>
            <input id="bnr-vas-name-input" type="text" maxlength="50"
                   placeholder="Дом ..." value=""
                   style="width:100%;padding:6px;font-size:12px;background:#0f1730;
                          color:#dbeafe;border:1px solid #1e40af;margin-bottom:10px;
                          box-sizing:border-box;">
            <button id="bnr-vas-confirm" class="extra-btn"
                    style="width:100%;font-size:11px;padding:6px;
                           background:#1e40af;color:#fff;font-weight:700;">
                🏰 Создать (250K💰)
            </button>
        </div>`;
    document.getElementById('bnr-vas-confirm')?.addEventListener('click', async () => {
        const heirId = document.getElementById('bnr-vas-heir-pick')?.value;
        const name = document.getElementById('bnr-vas-name-input')?.value?.trim();
        if (!heirId || !name || name.length < 2) {
            showNotification('Выбери наследника и имя (≥2 символа)', 'warning');
            return;
        }
        // 2026-06-07 FLICKER — закрыть форму ДО refresh (иначе freeze-guard
        // заблокирует перерисовку) + мгновенный фидбек на клик.
        document.querySelector('[data-bnr-details="vas-create"]')?.removeAttribute('open');
        await _bannerlordBuyAction('hero.create_vassal_clan', {
            heir_hero_id: heirId,
            vassal_name: name,
        });
        setTimeout(loadBannerlordVassals, 2000);  // engine apply takes ~1s
    });
}

// ───────────────────────────────────────────────────────────────────────────
// Sprint 5.33 (BLT-parity SIEGE) — Party orders panel.
// Viewer-leader партии может выдать своей MobileParty стратегический приказ:
// siege / defend / raid / garrison / patrol. Backend хранит active order
// (UNIQUE per viewer), mod выставляет engine SetMove* API.
async function loadBannerlordPartyOrders() {
    const slot = document.getElementById('bnr-party-orders-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/party-orders`, {
            headers: { 'X-Twitch-JWT': authToken || '' }
        }).then(r => r.json()).catch(() => ({success: false}));

        // FLICKER-FIX v6 (2026-05-29): на backend error НЕ clear slot — оставляем
        // last known good render видимым. Иначе при transient network blip
        // секция мерцает blank → render → blank каждые несколько секунд.
        if (!r || r.success === false) return;

        const active = r.active ? r.active : null;

        const orderEmoji = {
            siege: '🏰', defend: '🛡', raid: '🔥',
            garrison: '🏛', patrol: '🐎',
        };
        const orderLabel = {
            siege: 'Осада', defend: 'Защита', raid: 'Грабёж',
            garrison: 'Гарнизон', patrol: 'Патруль',
        };

        let html = `
            <div style="background:#2a1a0a;border:1px solid #92400e;border-radius:4px;
                        padding:8px;font-size:11px;color:#fed7aa;">
                <div style="font-size:12px;font-weight:700;color:#fb923c;margin-bottom:6px;">
                    ⚔ Приказы моего отряда на карте
                </div>`;

        // 2026-06-10 — текущий отряд (число воинов + задача движка) из hero-state push.
        const pinfo = (_bannerlordLastHero?.hero?.party_info) || null;
        const taskLabel = {
            GoToSettlement: 'идёт в поселение', BesiegeSettlement: 'осаждает',
            RaidSettlement: 'грабит', DefendSettlement: 'защищает',
            PatrolAroundPoint: 'патрулирует', Hold: 'стоит на месте',
            EngageParty: 'преследует отряд', GoToPoint: 'движется',
            FleeToPoint: 'отступает', GoAroundParty: 'маневрирует',
            JoinArmy: 'идёт в армию', EscortParty: 'сопровождает',
        };
        if (pinfo) {
            const taskTxt = taskLabel[pinfo.task] || pinfo.task || '—';
            const tgtTxt  = pinfo.target ? ` → ${escapeHtml(pinfo.target)}` : '';
            const armyTxt = pinfo.in_army ? ' · <span style="color:#fbbf24;">в армии</span>' : '';
            html += `
                <div style="background:#1a0f08;padding:6px 8px;border-radius:3px;margin-bottom:6px;font-size:11px;">
                    <span style="color:#9ca3af;">Отряд:</span>
                    <strong style="color:#fed7aa;">${pinfo.size} 🪖</strong>
                    <span style="color:#9ca3af;"> · задача:</span>
                    <strong style="color:#fed7aa;">${taskTxt}${tgtTxt}</strong>${armyTxt}
                </div>`;
        } else {
            html += `
                <div style="font-size:10px;color:#6b7280;margin-bottom:6px;">
                    Нет отряда на карте (герой без партии — создай отряд в Династии)
                </div>`;
        }

        if (active) {
            const emoji = orderEmoji[active.order_type] || '⚔';
            const lbl = orderLabel[active.order_type] || active.order_type;
            html += `
                <div style="background:#1a0f08;padding:6px 8px;border-radius:3px;
                            margin-bottom:6px;display:flex;justify-content:space-between;
                            align-items:center;">
                    <span style="color:#fed7aa;font-size:11px;">
                        ${emoji} <strong>${lbl}</strong>
                        <span style="color:#9ca3af;"> →
                            ${escapeHtml(active.target_settlement_name || active.target_settlement_id)}
                        </span>
                    </span>
                    <button id="bnr-order-cancel" class="extra-btn"
                            title="Отменить приказ (бесплатно)"
                            style="font-size:9px;padding:2px 6px;background:#2d2d3f;
                                   color:#fed7aa;">🏳 Отменить</button>
                </div>`;
        } else {
            html += `
                <div style="font-size:10px;color:#9ca3af;margin-bottom:6px;text-align:center;">
                    Партия действует автономно
                </div>`;
        }

        // 2026-06-07 — назначение приказа инлайн (lazy <details>): radio-приказ +
        // text-поле поселения переживают 8s-poll (форма рендерится при раскрытии,
        // не на каждом тике — иначе введённый текст стирался бы).
        html += `
            <details data-bnr-details="party-order" ${_bnrDetailsAttr('party-order')}>
                <summary style="list-style:none;cursor:pointer;width:100%;
                           font-size:11px;padding:6px;background:#92400e;box-sizing:border-box;
                           color:#fff;font-weight:700;border-radius:3px;text-align:center;">
                    ⚔ ${active ? 'Изменить приказ' : 'Назначить приказ'} (500💎)
                </summary>
                <div id="bnr-party-order-slot" style="padding-top:6px;"></div>
            </details>
            </div>`;
        // 2026-06-07 FLICKER — пока раскрыта форма приказа (radio + text-поселение),
        // НЕ перерисовываем секцию: смена active-order между poll'ами стёрла бы ввод.
        if (slot.querySelector('[data-bnr-details="party-order"]')?.open) return;
        // FLICKER-FIX: skip rebind при identical HTML.
        if (!_smartInnerHTML(slot, html)) return;

        // Bind buttons.
        document.getElementById('bnr-order-cancel')?.addEventListener('click', async () => {
            await _bannerlordBuyAction('hero.party_order_release', {});
            setTimeout(loadBannerlordPartyOrders, 1500);
        });
        const _poDet = slot.querySelector('[data-bnr-details="party-order"]');
        if (_poDet) {
            _poDet.addEventListener('toggle', () => { if (_poDet.open) _renderPartyOrderInline(active); });
            if (_poDet.open) _renderPartyOrderInline(active);
        }
    } catch (e) {
        // FLICKER-FIX v6 — НЕ clear на network exception. Last good render
        // остаётся видимым пока poll не recover'нет.
        console.warn('[FE-SIEGE] loadPartyOrders failed (keeping last render):', e);
    }
}

// удалена: инлайн lazy-форма приказа (_renderPartyOrderInline) вместо модалки.
function _renderPartyOrderInline(currentActive) {
    const slot = document.getElementById('bnr-party-order-slot');
    if (!slot) return;
    const preType = currentActive?.order_type || 'siege';
    const preName = currentActive?.target_settlement_name || '';
    const preId = currentActive?.target_settlement_id || '';

    const orderOptions = [
        { v: 'siege',    e: '🏰', l: 'Осада',     desc: 'Атаковать поселение врага' },
        { v: 'defend',   e: '🛡', l: 'Защита',    desc: 'Защищать поселение' },
        { v: 'raid',     e: '🔥', l: 'Грабёж',    desc: 'Налёт на деревню (требуется война)' },
        { v: 'garrison', e: '🏛', l: 'Гарнизон',  desc: 'Войти в поселение и стоять' },
        { v: 'patrol',   e: '🐎', l: 'Патруль',   desc: 'Патрулировать вокруг поселения' },
    ];

    slot.innerHTML = `
        <div style="background:#1a1208;border:1px solid #92400e;border-radius:4px;
                    padding:10px;color:#fed7aa;">
            <div style="font-size:11px;color:#9ca3af;margin-bottom:10px;">
                Партия следует приказу пока активен. Заменяет предыдущий.
                Sieges/raids требуют состояния войны с владельцем цели.
            </div>
            <div style="display:flex;flex-direction:column;gap:4px;margin-bottom:10px;">
                ${orderOptions.map(o => `
                    <label style="display:flex;align-items:center;gap:6px;
                                  background:#0f0805;padding:5px 8px;border-radius:3px;
                                  cursor:pointer;font-size:11px;">
                        <input type="radio" name="bnr-order-type" value="${o.v}"
                               ${o.v === preType ? 'checked' : ''}>
                        <span style="color:#fed7aa;">
                            ${o.e} <strong>${o.l}</strong>
                            <span style="color:#6b7280;font-size:10px;"> — ${o.desc}</span>
                        </span>
                    </label>
                `).join('')}
            </div>
            <label style="font-size:11px;color:#fed7aa;display:block;margin-bottom:4px;">
                Поселение (название или ID):
            </label>
            <input id="bnr-order-target-name" type="text" maxlength="80"
                   placeholder="например: Lycaron / Sargot / Marunath"
                   value="${escapeHtml(preName || preId)}"
                   style="width:100%;padding:6px;font-size:12px;background:#0f0805;
                          color:#fed7aa;border:1px solid #92400e;margin-bottom:6px;
                          box-sizing:border-box;">
            <div style="font-size:9px;color:#6b7280;margin-bottom:10px;">
                Mod ищет по точному ID или fuzzy-name match (≥3 символа).
                ⚠ Только лидер клана может выдавать приказы своей партии.
            </div>
            <button id="bnr-order-confirm" class="extra-btn"
                    style="width:100%;font-size:11px;padding:6px;
                           background:#92400e;color:#fff;font-weight:700;">
                ⚔ Выдать приказ (500💎)
            </button>
        </div>`;
    document.getElementById('bnr-order-confirm')?.addEventListener('click', async () => {
        const orderType = slot.querySelector('input[name="bnr-order-type"]:checked')?.value;
        const tgtRaw = (document.getElementById('bnr-order-target-name')?.value || '').trim();
        if (!orderType || !tgtRaw || tgtRaw.length < 3) {
            showNotification('Выбери приказ и укажи цель (≥3 символа)', 'warning');
            return;
        }
        // 2026-06-07 FLICKER — закрыть форму ДО refresh (иначе freeze-guard
        // заблокирует перерисовку) + мгновенный фидбек на клик.
        document.querySelector('[data-bnr-details="party-order"]')?.removeAttribute('open');
        await _bannerlordBuyAction('hero.party_order_set', {
            order_type:              orderType,
            target_settlement_id:    tgtRaw,
            target_settlement_name:  tgtRaw,
        });
        setTimeout(loadBannerlordPartyOrders, 2000);
    });
}

// ───────────────────────────────────────────────────────────────────────────
// Sprint 5.33 (BLT-parity DIPLO) — Kingdom politics panel.
// King/clan-leader может купить enact политики (toggle add/remove) для своего
// kingdom'а или предложить peace с enemy. Все viewers могут chip in в ransom
// pool captured heroes (отдельная section).

// Curated set vanilla 1.3.x policies — popular & impactful. Mod валидирует
// PolicyObject.StringId через MBObjectManager.GetObject<PolicyObject>.
const _BNR_POLICIES = [
    { id: 'forgiveness_of_debts', name: 'Forgiveness of Debts',
      desc: 'Loyalty +1, Tax -10%. Дёшево, но кланы недовольны.' },
    { id: 'land_grants', name: 'Land Grants',
      desc: 'Clan tier влияет на fief share. Поддержка крупных кланов.' },
    { id: 'precarial_land_tenure', name: 'Precarial Land Tenure',
      desc: 'Notables +5 power per fief. Влияние стороннее.' },
    { id: 'royal_guard', name: 'Royal Guard',
      desc: 'Король получает +50 кавалерии. Силовая опора трона.' },
    { id: 'sacred_majesty', name: 'Sacred Majesty',
      desc: 'King influence +2/day, others -1. Авторитарный режим.' },
    { id: 'trial_by_jury', name: 'Trial by Jury',
      desc: 'Loyalty +0.5, Security +1. Народная популярность.' },
    { id: 'imperial_towns', name: 'Imperial Towns',
      desc: 'Town prosperity +5%. Городам — вино!' },
    { id: 'noble_retinues', name: 'Noble Retinues',
      desc: 'Clan +10 party size. Большие армии.' },
    { id: 'lords_privy_council', name: 'Lords Privy Council',
      desc: 'Lords +1 influence/day. Феодальная демократия.' },
    { id: 'state_pilgrims', name: 'State Pilgrims',
      desc: 'Town loyalty +1.5 in same culture. Культурный буст.' },
    { id: 'serfdom', name: 'Serfdom',
      desc: 'Village hearth +10%. Низшие классы работают за двоих.' },
    { id: 'citizenship', name: 'Citizenship',
      desc: 'Town loyalty +1 в same culture. Гражданская честь.' },
];

async function loadBannerlordDiplomacy() {
    const slot = document.getElementById('bnr-diplo-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/kingdom-state`, {
            headers: { 'X-Twitch-JWT': authToken || '' }
        }).then(r => r.json()).catch(() => ({success: false}));
        if (r.success === false) return;  // AUDIT fix: keep last on transient fail
        if (!r.has_hero) { _smartInnerHTML(slot, ''); return; }  // genuine — no hero
        if (!r.kingdom_id) {
            slot.innerHTML = `
                <div style="background:#1a1208;border:1px solid #92400e;border-radius:4px;
                            padding:6px;font-size:10px;color:#9ca3af;text-align:center;">
                    🏛 Политика kingdom'а доступна когда герой вступит в королевство
                </div>`;
            return;
        }
        const canEnact = r.is_king || r.is_clan_leader;
        const canMakePeace = r.is_king;

        let html = `
            <div style="background:#1a1208;border:1px solid #92400e;border-radius:4px;
                        padding:8px;font-size:11px;color:#fed7aa;">
                <div style="font-size:12px;font-weight:700;color:#fb923c;margin-bottom:6px;">
                    🏛 Политика — ${escapeHtml(r.kingdom_name || r.kingdom_id)}
                    ${r.is_king ? '<span style="color:#fbbf24;font-size:9px;"> 👑 КОРОЛЬ</span>' : ''}
                </div>`;

        if ((r.policies_enacted || []).length > 0) {
            html += `
                <div style="font-size:10px;color:#9ca3af;margin-bottom:3px;">Активные политики:</div>
                <div style="display:flex;flex-wrap:wrap;gap:3px;margin-bottom:6px;">
                    ${r.policies_enacted.map(p => `
                        <span style="background:#0f0805;padding:2px 5px;border-radius:3px;
                                     font-size:10px;color:#fed7aa;border:1px solid #92400e;">
                            ${escapeHtml(p.policy_name || p.policy_id)}
                        </span>
                    `).join('')}
                </div>`;
        }

        if ((r.policies_pending || []).length > 0) {
            html += `
                <div style="font-size:10px;color:#fbbf24;margin-bottom:3px;">⏳ На обсуждении:</div>
                <div style="display:flex;flex-wrap:wrap;gap:3px;margin-bottom:6px;">
                    ${r.policies_pending.map(p => `
                        <span style="background:#1a1208;padding:2px 5px;border-radius:3px;
                                     font-size:10px;color:#fbbf24;border:1px dashed #92400e;">
                            ${escapeHtml(p.policy_name || p.policy_id)}
                        </span>
                    `).join('')}
                </div>`;
        }

        if (canEnact) {
            // 2026-06-07 — активация политики инлайн (style A): каждая политика —
            // кликабельная строка, действие срабатывает сразу (toggle add/remove).
            // Список — внутри lazy <details> чтобы не разворачивать всю секцию.
            const _enactedIds = new Set((r.policies_enacted || []).map(p => p.policy_id));
            const _pendingIds = new Set((r.policies_pending || []).map(p => p.policy_id));
            html += `
                <details data-bnr-details="diplo-policy" ${_bnrDetailsAttr('diplo-policy')} style="margin-bottom:4px;">
                    <summary style="list-style:none;cursor:pointer;width:100%;
                               font-size:11px;padding:6px;background:#92400e;box-sizing:border-box;
                               color:#fff;font-weight:700;border-radius:3px;text-align:center;">
                        📜 Активировать политику (1500💎)
                    </summary>
                    <div style="font-size:9px;color:#9ca3af;margin:6px 0 4px;">
                        Клик по политике = toggle (активна → отозвать). 1500💎 за действие.
                    </div>
                    <div style="display:flex;flex-direction:column;gap:3px;">
                        ${_BNR_POLICIES.map(p => {
                            const active = _enactedIds.has(p.id);
                            const pending = _pendingIds.has(p.id);
                            return `
                            <div class="bnr-diplo-policy-row" data-policy-id="${p.id}"
                                 data-policy-name="${escapeHtml(p.name)}"
                                 ${pending ? 'data-policy-pending="1"' : ''}
                                 style="background:${active ? '#1a2008' : '#0f0805'};
                                        padding:5px 8px;border-radius:3px;
                                        cursor:${pending ? 'not-allowed' : 'pointer'};
                                        ${pending ? 'opacity:0.5;' : ''}
                                        border:1px solid ${active ? '#4ade80' : '#1a1208'};">
                                ${active ? '<span style="color:#4ade80;">✓ </span>' : ''}
                                <strong style="color:#fed7aa;font-size:11px;">${escapeHtml(p.name)}</strong>
                                ${pending ? '<span style="color:#fbbf24;font-size:9px;"> (на обсуждении)</span>' : ''}
                                <div style="font-size:10px;color:#9ca3af;margin-top:2px;">
                                    ${escapeHtml(p.desc)}
                                </div>
                            </div>`;
                        }).join('')}
                    </div>
                </details>`;
        }
        if (canMakePeace) {
            // 2026-06-07 — предложение peace инлайн (lazy <details>): target kingdom
            // (text) + tribute (number) переживают 8s-poll, форма рендерится при
            // раскрытии.
            html += `
                <details data-bnr-details="diplo-peace" ${_bnrDetailsAttr('diplo-peace')}>
                    <summary style="list-style:none;cursor:pointer;width:100%;
                               font-size:11px;padding:6px;background:#1e3a5f;box-sizing:border-box;
                               color:#fff;font-weight:700;border-radius:3px;text-align:center;">
                        🕊 Предложить peace (2000💎)
                    </summary>
                    <div id="bnr-diplo-peace-slot" style="padding-top:6px;"></div>
                </details>`;
        }
        // Backlog #1 (BLT-RC22 C.5) — kingdom tax: king задаёт ставку. Вассальные
        // кланы королевства ежедневно платят % дневной прибыли в казну короля.
        if (r.is_king) {
            const curTax = r.kingdom_tax_pct || 0;
            const presets = [0, 10, 25, 50];
            html += `
                <div style="margin-top:6px;border-top:1px solid #3d2a0a;padding-top:6px;">
                    <div style="font-size:10px;color:#fbbf24;margin-bottom:3px;">
                        👑 Налог королевства: <b>${curTax}%</b>
                        <span style="color:#9ca3af;font-size:9px;"> — % дневной прибыли вассалов → тебе</span>
                    </div>
                    <div style="display:flex;gap:3px;">
                        ${presets.map(p => `
                            <button class="bnr-tax-btn extra-btn" data-tax-pct="${p}"
                                    style="flex:1;font-size:10px;padding:4px;
                                           background:${p === curTax ? '#b45309' : '#2d2d3f'};
                                           color:#fed7aa;font-weight:${p === curTax ? '700' : '400'};">
                                ${p}%
                            </button>`).join('')}
                    </div>
                </div>`;
        }
        html += `</div>`;
        // 2026-06-07 FLICKER — пока раскрыта форма peace (text target + number tribute),
        // НЕ перерисовываем секцию: смена kingdom-state между poll'ами стёрла бы ввод.
        // diplo-policy НЕ морозим — это click-list (style A), без in-progress state.
        if (slot.querySelector('[data-bnr-details="diplo-peace"]')?.open) return;
        // FLICKER-FIX: skip rebind при identical HTML.
        if (!_smartInnerHTML(slot, html)) return;

        // 2026-06-07 — клик по строке политики = toggle enact/revoke сразу (style A).
        slot.querySelectorAll('.bnr-diplo-policy-row').forEach(row => {
            row.addEventListener('click', async () => {
                if (row.dataset.policyPending) return;  // на обсуждении — нельзя
                await _bannerlordBuyAction('hero.enact_policy', {
                    policy_id:   row.dataset.policyId,
                    policy_name: row.dataset.policyName,
                });
                setTimeout(loadBannerlordDiplomacy, 2000);
            });
        });
        // 2026-06-07 — peace инлайн lazy-форма (text+tribute переживают poll).
        const _peaceDet = slot.querySelector('[data-bnr-details="diplo-peace"]');
        if (_peaceDet) {
            _peaceDet.addEventListener('toggle', () => { if (_peaceDet.open) _renderMakePeaceInline(); });
            if (_peaceDet.open) _renderMakePeaceInline();
        }
        slot.querySelectorAll('.bnr-tax-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const pct = parseInt(btn.dataset.taxPct, 10) || 0;
                await _bannerlordBuyAction('kingdom.set_tax_rate', { tax_rate_pct: pct });
                setTimeout(loadBannerlordDiplomacy, 1200);
            });
        });
    } catch (e) {
        console.warn('[FE-DIPLO] loadDiplomacy failed (keeping last render)', e);
    }
}

// удалена: инлайн-список политик (строки в loadBannerlordDiplomacy, style A).

// удалена: инлайн lazy-форма peace (_renderMakePeaceInline) вместо модалки.
function _renderMakePeaceInline() {
    const slot = document.getElementById('bnr-diplo-peace-slot');
    if (!slot) return;
    slot.innerHTML = `
        <div style="background:#0f1730;border:1px solid #1e40af;border-radius:4px;
                    padding:10px;color:#bfdbfe;">
            <div style="font-size:11px;color:#9ca3af;margin-bottom:10px;">
                Мод resolve'ит target kingdom по name или StringId.
                Tribute может быть отрицательным (они платят нам).
            </div>
            <label style="font-size:11px;color:#dbeafe;display:block;margin-bottom:4px;">
                Target kingdom (название или ID):
            </label>
            <input id="bnr-peace-target" type="text" maxlength="80"
                   placeholder="например: Vlandia / Sturgia / Aserai"
                   style="width:100%;padding:6px;font-size:12px;background:#0a0f1a;
                          color:#bfdbfe;border:1px solid #1e40af;margin-bottom:8px;
                          box-sizing:border-box;">
            <label style="font-size:11px;color:#dbeafe;display:block;margin-bottom:4px;">
                Tribute (золото/день, можно отрицательное):
            </label>
            <input id="bnr-peace-tribute" type="number" value="0"
                   min="-10000" max="10000" step="100"
                   style="width:100%;padding:6px;font-size:12px;background:#0a0f1a;
                          color:#bfdbfe;border:1px solid #1e40af;margin-bottom:10px;
                          box-sizing:border-box;">
            <button id="bnr-peace-confirm" class="extra-btn"
                    style="width:100%;font-size:11px;padding:6px;
                           background:#1e40af;color:#fff;font-weight:700;">
                🕊 Заключить (2000💎)
            </button>
        </div>`;
    document.getElementById('bnr-peace-confirm')?.addEventListener('click', async () => {
        const tgt = (document.getElementById('bnr-peace-target')?.value || '').trim();
        const trb = parseInt(document.getElementById('bnr-peace-tribute')?.value || '0', 10) || 0;
        if (!tgt || tgt.length < 2) {
            showNotification('Укажи target kingdom (≥2 символа)', 'warning');
            return;
        }
        // 2026-06-07 FLICKER — закрыть форму ДО refresh (иначе freeze-guard
        // заблокирует перерисовку) + мгновенный фидбек на клик.
        document.querySelector('[data-bnr-details="diplo-peace"]')?.removeAttribute('open');
        await _bannerlordBuyAction('hero.make_peace', {
            target_kingdom_id:   tgt,
            target_kingdom_name: tgt,
            offered_tribute:     trb,
        });
        setTimeout(loadBannerlordDiplomacy, 2000);
    });
}

// ─── Ransom pool section — captured viewers + chip-in button ──────────────────
async function loadBannerlordRansomPool() {
    const slot = document.getElementById('bnr-ransom-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/ransom-pool`, {
            headers: { 'X-Twitch-JWT': authToken || '' }
        }).then(r => r.json()).catch(() => ({success: false}));
        const captures = (r.success && Array.isArray(r.captures)) ? r.captures : [];
        if (captures.length === 0) { slot.innerHTML = ''; return; }

        let html = `
            <div style="background:#2a0a0a;border:1px solid #b91c1c;border-radius:4px;
                        padding:8px;font-size:11px;color:#fecaca;">
                <div style="font-size:12px;font-weight:700;color:#fb7185;margin-bottom:6px;">
                    ⛓ В плену — собираем выкуп
                </div>
                <div style="display:flex;flex-direction:column;gap:4px;">
                ${captures.map(c => {
                    const pct = Math.min(100, Math.floor(100 * (c.pool_total || 0) / Math.max(1, c.ransom_cost)));
                    return `
                    <div data-captured="${escapeHtml(c.captured_hero)}"
                         style="background:#0f0505;padding:6px 8px;border-radius:3px;">
                        <div style="display:flex;justify-content:space-between;
                                    align-items:center;margin-bottom:3px;">
                            <span style="color:#fecaca;font-size:11px;">
                                ⛓ @${escapeHtml(c.captured_hero)}
                                <span style="color:#9ca3af;font-size:10px;">
                                    T${c.gear_tier || 1} · lvl ${c.level || 0}
                                </span>
                            </span>
                            <button class="bnr-ransom-pay small-btn"
                                    title="Внести 500💎 в pool выкупа"
                                    style="font-size:9px;padding:2px 6px;background:#b91c1c;
                                           color:#fee2e2;">💰 +500💎</button>
                        </div>
                        <div style="background:#1a0505;height:5px;border-radius:2px;overflow:hidden;">
                            <div style="background:linear-gradient(90deg,#fb7185,#fbbf24);
                                        height:100%;width:${pct}%;transition:width 0.3s;"></div>
                        </div>
                        <div style="font-size:9px;color:#9ca3af;margin-top:2px;">
                            ${c.pool_total || 0} / ${c.ransom_cost}💎 pool
                            ${c.contributors > 0 ? ` · ${c.contributors} участников` : ''}
                        </div>
                    </div>`;
                }).join('')}
                </div>
            </div>`;
        // FLICKER-FIX: skip rebind при identical HTML.
        if (!_smartInnerHTML(slot, html)) return;

        slot.querySelectorAll('.bnr-ransom-pay').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const parent = e.target.closest('[data-captured]');
                if (!parent) return;
                const captured = parent.dataset.captured;
                await _bannerlordBuyAction('hero.pay_ransom', {
                    captured_hero: captured,
                });
                setTimeout(loadBannerlordRansomPool, 1200);
            });
        });
    } catch (e) {
        console.warn('[FE-RANSOM] loadRansom failed (keeping last render)', e);
    }
}

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

// Sprint 5.33 WORKSHOP-FIX (2026-05-28): IDs aligned с engine spworkshops.xml.
// Раньше silversmith/wood_workshop возвращали MBObjectManager null →
// мод REFUSE'нул с refund. Engine использует silversmithy + wood_WorkshopType
// (последнее — TaleWorlds vanilla typo, не наш). Все ID проверены против
// SandBox/ModuleData/spworkshops.xml для 1.3.15.
const _BNR_WORKSHOP_TYPES = [
    { id: 'brewery',          name: 'Пивоварня',         emoji: '🍺' },
    { id: 'smithy',           name: 'Кузница',           emoji: '⚒' },
    { id: 'wool_weavery',     name: 'Шерстяная ткацкая', emoji: '🐑' },
    { id: 'linen_weavery',    name: 'Льняная ткацкая',   emoji: '🌾' },
    { id: 'tannery',          name: 'Дубильня',          emoji: '🐄' },
    { id: 'pottery_shop',     name: 'Гончарня',          emoji: '🏺' },
    { id: 'olive_press',      name: 'Маслодавильня',     emoji: '🫒' },
    { id: 'wine_press',       name: 'Винодельня',        emoji: '🍷' },
    { id: 'velvet_weavery',   name: 'Бархатная ткацкая', emoji: '👘' },
    { id: 'silversmithy',     name: 'Серебряных дел',    emoji: '🥈' },
    { id: 'wood_WorkshopType', name: 'Древоделия',       emoji: '🪵' },
];

async function loadBannerlordWorkshops() {
    const slot = document.getElementById('bnr-workshops-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/my-workshops`, {
            headers: { 'X-Twitch-JWT': authToken || '' }
        }).then(r => r.json()).catch(() => ({success: false}));

        // FLICKER-FIX v6 (2026-05-29): skip update на backend error — last good
        // render остаётся. Иначе section мерцает каждые ~8s при transient blip.
        if (!r || r.success === false) return;

        const workshops = Array.isArray(r.workshops) ? r.workshops : [];
        const maxWorkshops = r.max_workshops || 3;

        // Sprint 5.33 CURRENCY-1 — clear price display + Hero.Gold visible.
        const WORKSHOP_CRUSTIC = 2500;     // 2026-05-29: чистая 💎 (цена поднята 1000→2500)
        const WORKSHOP_DINAR_EST = 0;      // капитал НЕ списывался — миф убран
        const wsAfford = _bnrAfford(WORKSHOP_CRUSTIC, WORKSHOP_DINAR_EST);

        // FLICKER-FIX v4: НЕ показываем live balance strip в header.
        // Balance меняется каждый poll → html string differs → cache miss →
        // repaint каждые 8s — видимый flicker. Balance виден в buy modal
        // и в main extension header (там обновляется ниже poll throttle).
        let html = `
            <div style="background:#1a2008;border:1px solid #65a30d;border-radius:4px;
                        padding:8px;font-size:11px;color:#d9f99d;">
                <div style="font-size:12px;font-weight:700;color:#84cc16;margin-bottom:4px;">
                    🏭 Мои мастерские (${workshops.length}/${maxWorkshops})
                </div>
                <div style="font-size:9px;color:#9ca3af;margin-bottom:6px;">
                    Пассивный доход в 💰 динарах — копятся в Hero.Gold (на gear/smith/marriage)
                </div>`;

        if (workshops.length > 0) {
            html += `<div style="display:flex;flex-direction:column;gap:4px;margin-bottom:6px;">`;
            for (const w of workshops) {
                const typeEntry = _BNR_WORKSHOP_TYPES.find(t => t.id === w.workshop_type)
                                  || { emoji: '🏭', name: w.workshop_type_name || w.workshop_type };
                html += `
                    <div data-workshop-id="${w.id}"
                         style="background:#0a1308;padding:6px 8px;border-radius:3px;
                                display:flex;justify-content:space-between;align-items:center;">
                        <div style="flex:1;">
                            <div style="color:#d9f99d;font-size:11px;">
                                ${typeEntry.emoji} <strong>${escapeHtml(typeEntry.name)}</strong>
                                <span style="color:#9ca3af;"> · ${escapeHtml(w.settlement_name || w.settlement_id)}</span>
                            </div>
                            <div style="font-size:10px;color:#65a30d;margin-top:2px;">
                                <span style="color:#9ca3af;">Заработано:</span>
                                <span style="color:#fbbf24;font-weight:700;">💰 ${(w.total_profit || 0).toLocaleString('ru-RU')}</span>
                            </div>
                        </div>
                        <button class="bnr-ws-sell small-btn"
                                title="Продать (50% refund от engine)"
                                style="font-size:9px;padding:2px 6px;background:#9a3412;
                                       color:#fed7aa;">💸 Продать</button>
                    </div>`;
            }
            html += `</div>`;
        }

        if (workshops.length < maxWorkshops) {
            const btnBg = wsAfford.ok ? '#65a30d' : '#3f3f0b';
            const btnOpacity = wsAfford.ok ? '1' : '0.65';
            // 2026-06-07 — покупка мастерской инлайн (lazy <details>): radio-тип +
            // <select>-город переживают 8s-poll (форма рендерится при раскрытии).
            html += `
                <details data-bnr-details="ws-buy" ${_bnrDetailsAttr('ws-buy')}>
                    <summary title="${escapeHtml(_bnrAffordTooltip(WORKSHOP_CRUSTIC, WORKSHOP_DINAR_EST))}"
                             style="list-style:none;cursor:pointer;width:100%;
                                    font-size:11px;padding:6px;background:${btnBg};box-sizing:border-box;
                                    color:#fff;font-weight:700;opacity:${btnOpacity};
                                    border-radius:3px;text-align:center;">
                        🏭 Купить мастерскую — ${_bnrPriceHtml(WORKSHOP_CRUSTIC, WORKSHOP_DINAR_EST)}
                    </summary>
                    <div id="bnr-ws-buy-slot" style="padding-top:6px;"></div>
                </details>`;
        } else {
            html += `
                <div style="font-size:10px;color:#6b7280;text-align:center;">
                    Лимит мастерских (${maxWorkshops}/${maxWorkshops})
                </div>`;
        }
        html += `</div>`;
        // 2026-06-07 FLICKER — пока форма покупки раскрыта, НЕ перерисовываем секцию
        // (иначе тик дохода стирает выбор/ввод). Возобновится когда юзер закроет форму.
        if (slot.querySelector('[data-bnr-details="ws-buy"]')?.open) return;
        // FLICKER-FIX: dedupe — skip rebind если HTML identical (избежать
        // double-handlers на sell/buy buttons).
        if (!_smartInnerHTML(slot, html)) return;

        // Bind sell buttons.
        slot.querySelectorAll('.bnr-ws-sell').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const parent = e.target.closest('[data-workshop-id]');
                if (!parent) return;
                if (!await _bnrConfirm('Продать мастерскую? Получишь ~50% refund.')) return;
                const wsId = parseInt(parent.dataset.workshopId, 10);
                await _bannerlordBuyAction('hero.sell_workshop', { workshop_id: wsId });
                setTimeout(loadBannerlordWorkshops, 1500);
            });
        });

        const _wsDet = slot.querySelector('[data-bnr-details="ws-buy"]');
        if (_wsDet) {
            _wsDet.addEventListener('toggle', () => { if (_wsDet.open) _renderBuyWorkshopInline(); });
            if (_wsDet.open) _renderBuyWorkshopInline();
        }
    } catch (e) {
        // FLICKER-FIX v6 — НЕ clear на exception. Last good render survives.
        console.warn('[FE-SHOP] loadWorkshops failed (keeping last render):', e);
    }
}

// удалена: инлайн lazy-форма покупки мастерской (_renderBuyWorkshopInline).
function _renderBuyWorkshopInline() {
    const slot = document.getElementById('bnr-ws-buy-slot');
    if (!slot) return;
    slot.innerHTML = `
        <div style="background:#1a2008;border:1px solid #65a30d;border-radius:4px;
                    padding:10px;color:#d9f99d;">
            <div style="display:flex;gap:6px;font-size:11px;margin-bottom:10px;
                        background:#0a1308;padding:6px 8px;border-radius:3px;">
                <div style="flex:1;">
                    <div style="color:#9ca3af;font-size:9px;">Стоимость:</div>
                    <div style="font-size:13px;font-weight:700;">
                        ${_bnrPriceHtml(1000, 20000)}
                    </div>
                </div>
                <div style="flex:1;border-left:1px solid #1f2937;padding-left:8px;">
                    <div style="color:#9ca3af;font-size:9px;">У тебя:</div>
                    <div style="font-size:11px;">
                        <span style="color:#a5f3fc;">💎 ${(_cachedUserPoints||0).toLocaleString('ru-RU')}</span>
                        <span style="color:#6b7280;">|</span>
                        <span style="color:#fbbf24;">💰 ${((_bannerlordLastHero?.hero?.gold)||0).toLocaleString('ru-RU')}</span>
                    </div>
                </div>
            </div>
            <div style="font-size:10px;color:#9ca3af;margin-bottom:10px;line-height:1.4;">
                <div>💎 — entry fee, списывается с твоего 💎 балланса</div>
                <div>💰 — initial capital, списывается с Hero.Gold (engine)</div>
                <div>📈 Профит копится в Hero.Gold (динары — на gear/smith/marriage)</div>
            </div>
            <label style="font-size:11px;color:#d9f99d;display:block;margin-bottom:4px;">
                Тип мастерской:
            </label>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:3px;margin-bottom:10px;">
                ${_BNR_WORKSHOP_TYPES.map((t, i) => `
                    <label style="display:flex;align-items:center;gap:4px;
                                  background:#0a1308;padding:5px 6px;border-radius:3px;
                                  cursor:pointer;font-size:10px;">
                        <input type="radio" name="bnr-ws-type" value="${t.id}"
                               data-name="${escapeHtml(t.name)}" ${i === 0 ? 'checked' : ''}>
                        <span style="color:#d9f99d;">${t.emoji} ${escapeHtml(t.name)}</span>
                    </label>
                `).join('')}
            </div>
            <label style="font-size:11px;color:#d9f99d;display:block;margin-bottom:4px;">
                Town (выбери из engine catalog):
            </label>
            <div id="bnr-ws-town-slot" style="margin-bottom:10px;">
                <div style="font-size:11px;color:#9ca3af;padding:6px;">
                    ⏳ Загружается список городов...
                </div>
            </div>
            <button id="bnr-ws-buy-confirm" class="extra-btn"
                    style="width:100%;font-size:11px;padding:6px;
                           background:#65a30d;color:#fff;font-weight:700;">
                🏭 Купить — ${_bnrPriceHtml(1000, 20000)}
            </button>
        </div>`;
    // CATALOG-3: load real engine towns в dropdown
    _bnrFetchSettlements().then(byType => {
        const townSlot = document.getElementById('bnr-ws-town-slot');
        if (townSlot) {
            townSlot.innerHTML = _bnrRenderSettlementSelect(byType.town || [],
                { id: 'bnr-ws-town' });
        }
    });
    document.getElementById('bnr-ws-buy-confirm')?.addEventListener('click', async () => {
        const typeSel = slot.querySelector('input[name="bnr-ws-type"]:checked');
        const townSel = document.getElementById('bnr-ws-town');
        const townId = (townSel?.value || '').trim();
        const townName = townSel?.tagName === 'SELECT'
            ? (townSel.options[townSel.selectedIndex]?.dataset?.name || townId)
            : townId;
        if (!typeSel) {
            showNotification('Выбери тип мастерской', 'warning');
            return;
        }
        if (!townId) {
            showNotification('Выбери town из списка', 'warning');
            return;
        }
        // 2026-06-07 FLICKER — закрыть форму ДО refresh, иначе freeze-guard
        // заблокирует перерисовку секции (и даёт мгновенный фидбек на клик).
        document.querySelector('[data-bnr-details="ws-buy"]')?.removeAttribute('open');
        await _bannerlordBuyAction('hero.buy_workshop', {
            settlement_id:      townId,
            settlement_name:    townName,
            workshop_type:      typeSel.value,
            workshop_type_name: typeSel.dataset.name,
        });
        setTimeout(loadBannerlordWorkshops, 2000);
    });
}

// ───────────────────────────────────────────────────────────────────────────
// Sprint 5.33 (BLT-parity FIEF) — Fief tribute passive income panel.
// Read-only view (owned fiefs come from in-game ownership). Active feature:
// tribute_boost — 2000💎 → 7-day +50% multiplier на один fief.

async function loadBannerlordFiefs() {
    const slot = document.getElementById('bnr-fiefs-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/my-fiefs`, {
            headers: { 'X-Twitch-JWT': authToken || '' }
        }).then(r => r.json()).catch(() => ({success: false}));

        // FLICKER-FIX v6 (2026-05-29): skip update на backend error — last good
        // render остаётся видимым через transient blips.
        if (!r || r.success === false) return;

        const fiefs = Array.isArray(r.fiefs) ? r.fiefs : [];
        // FLICKER-FIX v6: при genuine empty state (0 fiefs) — render stable
        // placeholder через _smartInnerHTML вместо slot.innerHTML='' (последний
        // вариант → repaint каждый poll → flicker). _smartInnerHTML dedupe
        // identical HTML → repaint только при изменении.
        if (fiefs.length === 0) {
            _smartInnerHTML(slot, '');  // dedupe even empty
            return;
        }

        const typeEmoji = { town: '🏛', castle: '🏰', village: '🏘' };
        const typeLabel = { town: 'Город', castle: 'Замок', village: 'Деревня' };
        const boostPct  = Math.round(((r.boost_mult || 1.5) - 1) * 100);
        const boostDays = r.boost_days || 7;

        // FLICKER-FIX v4: balance strip убран.
        let html = `
            <div style="background:#1a1308;border:1px solid #b45309;border-radius:4px;
                        padding:8px;font-size:11px;color:#fed7aa;">
                <div style="font-size:12px;font-weight:700;color:#f59e0b;margin-bottom:4px;">
                    👑 Мои владения
                </div>
                <div style="font-size:9px;color:#9ca3af;margin-bottom:6px;">
                    Tribute passive в 💰 динарах — копятся в Hero.Gold
                </div>
                <div style="display:flex;flex-direction:column;gap:4px;margin-bottom:6px;">
                ${fiefs.map(f => {
                    const emoji = typeEmoji[f.fief_type] || '🏛';
                    const lbl   = typeLabel[f.fief_type] || f.fief_type;
                    return `
                    <div data-fief-id="${f.id}"
                         style="background:#0f0805;padding:6px 8px;border-radius:3px;
                                display:flex;justify-content:space-between;align-items:center;
                                ${f.boost_active ? 'border:1px solid #facc15;' : ''}">
                        <div style="flex:1;">
                            <div style="color:#fed7aa;font-size:11px;">
                                ${emoji} <strong>${escapeHtml(f.fief_name || f.fief_id)}</strong>
                                <span style="color:#9ca3af;font-size:10px;"> · ${lbl}</span>
                                ${f.boost_active ? '<span style="color:#facc15;font-size:9px;font-weight:700;"> ⚡ BOOST</span>' : ''}
                            </div>
                            <div style="font-size:10px;margin-top:2px;">
                                <span style="color:#9ca3af;">Заработано:</span>
                                <span style="color:#fbbf24;font-weight:700;">💰 ${(f.total_collected_dinars || 0).toLocaleString('ru-RU')}</span>
                            </div>
                        </div>
                        ${/* Sprint 5.33 DECOUPLE-1: Tribute boost deprecated —
                            бустер 💎-output смысла не имеет когда 💎 output = 0. */ ''}
                    </div>`;
                }).join('')}
                </div>
                <div style="font-size:9px;color:#6b7280;text-align:center;">
                    Динары → Hero.Gold (на gear/smith). 💎 не выдаётся пассивно.
                </div>
            </div>`;
        // FLICKER-FIX: skip rebind при identical HTML.
        if (!_smartInnerHTML(slot, html)) return;

        slot.querySelectorAll('.bnr-fief-boost').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const parent = e.target.closest('[data-fief-id]');
                if (!parent) return;
                if (!await _bnrConfirm(`Купить boost +${boostPct}% на ${boostDays} дней? (2000💎)`)) return;
                const fiefRowId = parseInt(parent.dataset.fiefId, 10);
                await _bannerlordBuyAction('hero.tribute_boost', {
                    fief_id_internal: fiefRowId,
                });
                setTimeout(loadBannerlordFiefs, 1200);
            });
        });
    } catch (e) {
        // FLICKER-FIX v6 — НЕ clear на exception. Last good render остаётся.
        console.warn('[FE-FIEF] loadFiefs failed (keeping last render):', e);
    }
}

// ───────────────────────────────────────────────────────────────────────────
// Sprint 5.33 (BLT-parity CARAVAN) — Mobile passive income trilogy closer.
// SHOP = static personal | FIEF = territorial | CARAVAN = mobile с риском.
// Caravan может быть destroyed бандитами → rescue pool (parallel to ransom).

async function loadBannerlordCaravans() {
    const slot = document.getElementById('bnr-caravans-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/my-caravans`, {
            headers: { 'X-Twitch-JWT': authToken || '' }
        }).then(r => r.json()).catch(() => ({success: false}));

        // FLICKER-FIX v6 (2026-05-29): skip update на backend error — last good
        // render остаётся видимым. Иначе section мерцает каждые ~8s при transient blip.
        if (!r || r.success === false) return;

        const caravans = Array.isArray(r.caravans) ? r.caravans : [];
        const maxC = r.max_caravans || 2;

        // Sprint 5.33 CURRENCY-1 — clear price display + Hero.Gold visible.
        const CARAVAN_CRUSTIC = 4000;      // 2026-05-29: чистая 💎 (цена поднята 1500→4000)
        const CARAVAN_DINAR   = 0;         // 15K капитал НЕ списывался — миф убран
        const cAfford = _bnrAfford(CARAVAN_CRUSTIC, CARAVAN_DINAR);

        // FLICKER-FIX v4: balance strip убран (см. workshops комментарий).
        let html = `
            <div style="background:#1a1820;border:1px solid #7c3aed;border-radius:4px;
                        padding:8px;font-size:11px;color:#ddd6fe;">
                <div style="font-size:12px;font-weight:700;color:#a78bfa;margin-bottom:4px;">
                    🐪 Мои караваны (${caravans.filter(c => c.status === 'active').length}/${maxC})
                </div>
                <div style="font-size:9px;color:#9ca3af;margin-bottom:6px;">
                    Mobile passive в 💰 динарах — копятся в Hero.Gold. ⚠ Бандиты могут уничтожить.
                </div>`;

        if (caravans.length > 0) {
            html += `<div style="display:flex;flex-direction:column;gap:4px;margin-bottom:6px;">`;
            for (const c of caravans) {
                const isDest = c.status === 'destroyed';
                html += `
                    <div data-caravan-id="${c.id}"
                         style="background:${isDest ? '#2a0a0a' : '#0f0d18'};
                                padding:6px 8px;border-radius:3px;
                                display:flex;justify-content:space-between;align-items:center;
                                ${isDest ? 'border:1px solid #b91c1c;' : ''}">
                        <div style="flex:1;">
                            <div style="color:${isDest ? '#fecaca' : '#ddd6fe'};font-size:11px;">
                                ${isDest ? '💀' : '🐪'} <strong>${escapeHtml(c.home_settlement_name || 'Caravan')}</strong>
                                ${isDest ? '<span style="color:#fb7185;font-size:9px;font-weight:700;"> УНИЧТОЖЕН</span>' : ''}
                            </div>
                            <div style="font-size:10px;margin-top:2px;">
                                <span style="color:#9ca3af;">Заработано:</span>
                                <span style="color:${isDest ? '#fb7185' : '#fbbf24'};font-weight:700;">💰 ${(c.total_collected_dinars || 0).toLocaleString('ru-RU')}</span>
                            </div>
                        </div>
                        ${!isDest ? `
                            <button class="bnr-caravan-sell small-btn"
                                    title="Продать (engine handles refund)"
                                    style="font-size:9px;padding:2px 6px;background:#5b21b6;
                                           color:#ddd6fe;">💸 Продать</button>
                        ` : ''}
                    </div>`;
            }
            html += `</div>`;
        }

        const activeCount = caravans.filter(c => c.status === 'active').length;
        if (activeCount < maxC) {
            const btnBg = cAfford.ok ? '#7c3aed' : '#2d1b5a';
            const btnOpacity = cAfford.ok ? '1' : '0.65';
            // 2026-06-07 — покупка каравана инлайн (lazy <details>): <select>-город
            // переживает 8s-poll (форма рендерится при раскрытии).
            html += `
                <details data-bnr-details="caravan-buy" ${_bnrDetailsAttr('caravan-buy')}>
                    <summary title="${escapeHtml(_bnrAffordTooltip(CARAVAN_CRUSTIC, CARAVAN_DINAR))}"
                             style="list-style:none;cursor:pointer;width:100%;
                                    font-size:11px;padding:6px;background:${btnBg};box-sizing:border-box;
                                    color:#fff;font-weight:700;opacity:${btnOpacity};
                                    border-radius:3px;text-align:center;">
                        🐪 Купить караван — ${_bnrPriceHtml(CARAVAN_CRUSTIC, CARAVAN_DINAR)}
                    </summary>
                    <div id="bnr-caravan-buy-slot" style="padding-top:6px;"></div>
                </details>`;
        } else {
            html += `
                <div style="font-size:10px;color:#6b7280;text-align:center;">
                    Лимит караванов (${maxC}/${maxC})
                </div>`;
        }
        html += `</div>`;
        // 2026-06-07 FLICKER — пока форма покупки раскрыта, НЕ перерисовываем секцию
        // (иначе тик дохода стирает выбор города). Возобновится при закрытии формы.
        if (slot.querySelector('[data-bnr-details="caravan-buy"]')?.open) return;
        // FLICKER-FIX: skip rebind при identical HTML.
        if (!_smartInnerHTML(slot, html)) return;

        slot.querySelectorAll('.bnr-caravan-sell').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const parent = e.target.closest('[data-caravan-id]');
                if (!parent) return;
                if (!await _bnrConfirm('Продать караван?')) return;
                const cId = parseInt(parent.dataset.caravanId, 10);
                await _bannerlordBuyAction('hero.sell_caravan', { caravan_id: cId });
                setTimeout(loadBannerlordCaravans, 1500);
            });
        });
        const _carDet = slot.querySelector('[data-bnr-details="caravan-buy"]');
        if (_carDet) {
            _carDet.addEventListener('toggle', () => { if (_carDet.open) _renderBuyCaravanInline(); });
            if (_carDet.open) _renderBuyCaravanInline();
        }
    } catch (e) {
        // FLICKER-FIX v6 — НЕ clear на exception. Last good render остаётся.
        console.warn('[FE-CARAVAN] loadCaravans failed (keeping last render):', e);
    }
}

// удалена: инлайн lazy-форма покупки каравана (_renderBuyCaravanInline).
function _renderBuyCaravanInline() {
    const slot = document.getElementById('bnr-caravan-buy-slot');
    if (!slot) return;
    slot.innerHTML = `
        <div style="background:#1a1820;border:1px solid #7c3aed;border-radius:4px;
                    padding:10px;color:#ddd6fe;">
            <div style="display:flex;gap:6px;font-size:11px;margin-bottom:10px;
                        background:#0f0d18;padding:6px 8px;border-radius:3px;">
                <div style="flex:1;">
                    <div style="color:#9ca3af;font-size:9px;">Стоимость:</div>
                    <div style="font-size:13px;font-weight:700;">
                        ${_bnrPriceHtml(1500, 15000)}
                    </div>
                </div>
                <div style="flex:1;border-left:1px solid #1f2937;padding-left:8px;">
                    <div style="color:#9ca3af;font-size:9px;">У тебя:</div>
                    <div style="font-size:11px;">
                        <span style="color:#a5f3fc;">💎 ${(_cachedUserPoints||0).toLocaleString('ru-RU')}</span>
                        <span style="color:#6b7280;">|</span>
                        <span style="color:#fbbf24;">💰 ${((_bannerlordLastHero?.hero?.gold)||0).toLocaleString('ru-RU')}</span>
                    </div>
                </div>
            </div>
            <div style="font-size:10px;color:#9ca3af;margin-bottom:10px;line-height:1.4;">
                <div>💎 — entry fee, списывается с твоего 💎 балланса</div>
                <div>💰 — capital (15K), списывается с Hero.Gold (engine)</div>
                <div>📈 Profit копится в Hero.Gold (динары на gear/smith/marriage)</div>
                <div style="color:#fb7185;">⚠ Бандиты могут уничтожить — viewers собирают rescue pool</div>
            </div>
            <label style="font-size:11px;color:#ddd6fe;display:block;margin-bottom:4px;">
                Home town (выбери из engine catalog):
            </label>
            <div id="bnr-caravan-home-slot" style="margin-bottom:10px;">
                <div style="font-size:11px;color:#9ca3af;padding:6px;">
                    ⏳ Загружается список городов...
                </div>
            </div>
            <button id="bnr-caravan-buy-confirm" class="extra-btn"
                    style="width:100%;font-size:11px;padding:6px;
                           background:#7c3aed;color:#fff;font-weight:700;">
                🐪 Купить — ${_bnrPriceHtml(1500, 15000)}
            </button>
        </div>`;
    // CATALOG-3: load real engine towns в caravan home dropdown
    _bnrFetchSettlements().then(byType => {
        const homeSlot = document.getElementById('bnr-caravan-home-slot');
        if (homeSlot) {
            homeSlot.innerHTML = _bnrRenderSettlementSelect(byType.town || [],
                { id: 'bnr-caravan-home' });
            // Re-style the <select> для caravan theme
            const sel = document.getElementById('bnr-caravan-home');
            if (sel && sel.tagName === 'SELECT') {
                sel.style.background = '#0f0d18';
                sel.style.color = '#ddd6fe';
                sel.style.borderColor = '#7c3aed';
            }
        }
    });
    document.getElementById('bnr-caravan-buy-confirm')?.addEventListener('click', async () => {
        const homeSel = document.getElementById('bnr-caravan-home');
        const home = (homeSel?.value || '').trim();
        const homeName = homeSel?.tagName === 'SELECT'
            ? (homeSel.options[homeSel.selectedIndex]?.dataset?.name || home)
            : home;
        if (!home) {
            showNotification('Выбери home town из списка', 'warning');
            return;
        }
        // 2026-06-07 FLICKER — закрыть форму ДО refresh (иначе freeze-guard
        // заблокирует перерисовку) + мгновенный фидбек на клик.
        document.querySelector('[data-bnr-details="caravan-buy"]')?.removeAttribute('open');
        await _bannerlordBuyAction('hero.buy_caravan', {
            home_settlement_id:   home,
            home_settlement_name: homeName,
        });
        setTimeout(loadBannerlordCaravans, 2000);
    });
}

// ─── Caravan rescue pool ──────────────────────────────────────────────────────
async function loadBannerlordCaravanRescues() {
    const slot = document.getElementById('bnr-caravan-rescue-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/caravan-rescues`, {
            headers: { 'X-Twitch-JWT': authToken || '' }
        }).then(r => r.json()).catch(() => ({success: false}));
        const rescues = (r.success && Array.isArray(r.rescues)) ? r.rescues : [];
        if (rescues.length === 0) { slot.innerHTML = ''; return; }

        let html = `
            <div style="background:#2a0a0a;border:1px solid #b91c1c;border-radius:4px;
                        padding:8px;font-size:11px;color:#fecaca;">
                <div style="font-size:12px;font-weight:700;color:#fb7185;margin-bottom:6px;">
                    💀 Уничтоженные караваны — соберём rescue?
                </div>
                <div style="display:flex;flex-direction:column;gap:4px;">
                ${rescues.map(rs => {
                    const pct = Math.min(100, Math.floor(100 * (rs.pool_total || 0) / Math.max(1, rs.rescue_cost)));
                    return `
                    <div data-caravan-id="${rs.caravan_id}"
                         style="background:#0f0505;padding:6px 8px;border-radius:3px;">
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
                            <span style="color:#fecaca;font-size:11px;">
                                🐪 @${escapeHtml(rs.owner)} <span style="color:#9ca3af;">— ${escapeHtml(rs.home_name || '?')}</span>
                            </span>
                            <button class="bnr-caravan-rescue-pay small-btn"
                                    title="Вложить 500💎 в pool rescue"
                                    style="font-size:9px;padding:2px 6px;background:#b91c1c;
                                           color:#fee2e2;">💰 +500💎</button>
                        </div>
                        <div style="background:#1a0505;height:5px;border-radius:2px;overflow:hidden;">
                            <div style="background:linear-gradient(90deg,#fb7185,#a78bfa);
                                        height:100%;width:${pct}%;transition:width 0.3s;"></div>
                        </div>
                        <div style="font-size:9px;color:#9ca3af;margin-top:2px;">
                            ${rs.pool_total || 0} / ${rs.rescue_cost}💎 pool
                            ${rs.contributors > 0 ? ` · ${rs.contributors} участников` : ''}
                        </div>
                    </div>`;
                }).join('')}
                </div>
            </div>`;
        // FLICKER-FIX: skip rebind при identical HTML.
        if (!_smartInnerHTML(slot, html)) return;

        slot.querySelectorAll('.bnr-caravan-rescue-pay').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const parent = e.target.closest('[data-caravan-id]');
                if (!parent) return;
                const cId = parseInt(parent.dataset.caravanId, 10);
                await _bannerlordBuyAction('hero.pay_caravan_rescue', { caravan_id: cId });
                setTimeout(loadBannerlordCaravanRescues, 1200);
                setTimeout(loadBannerlordCaravans, 1500);
            });
        });
    } catch (e) {
        console.warn('[FE-CARAVAN-RESCUE] loadRescues failed (keeping last render)', e);
    }
}

// ───────────────────────────────────────────────────────────────────────────
// Sprint 5.33 (BLT-parity HERITAGE) — Inheritance log section.
// Когда viewer умирает + heir активируется, parent's workshops/caravans/fiefs
// transfer'ятся к heir engine-side (mod ActivateHeirHandler). Backend logs
// каждый asset в bannerlord_inheritance_log — frontend показывает recent
// inheritance события для transparency + dopamine.

async function loadBannerlordInheritance() {
    const slot = document.getElementById('bnr-inheritance-slot');
    if (!slot) return;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/inheritance-log?limit=15`, {
            headers: { 'X-Twitch-JWT': authToken || '' }
        }).then(r => r.json()).catch(() => ({success: false}));
        const items = (r.success && Array.isArray(r.items)) ? r.items : [];
        if (items.length === 0) { slot.innerHTML = ''; return; }

        const typeEmoji = { workshop: '🏭', caravan: '🐪', fief: '🏛' };
        const typeColor = { workshop: '#84cc16', caravan: '#a78bfa', fief: '#f59e0b' };

        // Group by inherited_at date (день).
        const groups = new Map();
        for (const it of items) {
            const day = (it.inherited_at || '').substring(0, 10);
            if (!groups.has(day)) groups.set(day, []);
            groups.get(day).push(it);
        }

        let html = `
            <div style="background:#1a1614;border:1px solid #92400e;border-radius:4px;
                        padding:8px;font-size:11px;color:#fde68a;">
                <div style="font-size:12px;font-weight:700;color:#facc15;margin-bottom:6px;">
                    ⚱ Наследие — переходило к моим heir'ам
                </div>`;
        for (const [day, dayItems] of groups) {
            const totalValue = dayItems.reduce((s, x) => s + (x.total_value || 0), 0);
            html += `
                <div style="margin-bottom:6px;">
                    <div style="font-size:10px;color:#fbbf24;font-weight:700;margin-bottom:3px;">
                        ${escapeHtml(day || 'recent')}
                        ${totalValue > 0 ? `<span style="color:#9ca3af;font-weight:normal;">
                            — ${totalValue.toLocaleString('ru-RU')} дин. total</span>` : ''}
                    </div>
                    <div style="display:flex;flex-direction:column;gap:2px;">
                    ${dayItems.map(it => {
                        const emoji = typeEmoji[it.asset_type] || '⚱';
                        const color = typeColor[it.asset_type] || '#fde68a';
                        return `
                            <div style="background:#0f0c0a;padding:4px 6px;border-radius:3px;
                                        font-size:10px;border-left:2px solid ${color};">
                                ${emoji} <span style="color:${color};">${escapeHtml(it.asset_name || it.asset_type)}</span>
                                ${(it.total_value || 0) > 0 ? `<span style="color:#9ca3af;float:right;">
                                    ${it.total_value.toLocaleString('ru-RU')} дин.</span>` : ''}
                            </div>`;
                    }).join('')}
                    </div>
                </div>`;
        }
        html += `
                <div style="font-size:9px;color:#6b7280;text-align:center;margin-top:3px;">
                    Empire transcends death — assets re-claimed engine-side
                </div>
            </div>`;
        // FLICKER-FIX: dedupe (no bindings here, just paint).
        _smartInnerHTML(slot, html);
    } catch (e) {
        console.warn('[FE-HERITAGE] loadInheritance failed (keeping last render)', e);
    }
}

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
async function loadBannerlordClasses() {
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/classes`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        const data = await r.json();
        if (data.success) _bannerlordClassesCache = data;
        // Re-render hero body если он уже отображён — picker появится
        renderBannerlordClassPicker();
    } catch (e) {
        // Sprint 5.29 audit fix #36: silent → warn
        console.warn('[BNR loadBannerlordClasses]', e);
    }
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

    // Sprint 5.32 — class progression info (level 1/2/3 from primary skill).
    // primary_skill_level показывает текущее значение, next_threshold — что
    // нужно достичь для следующего уровня класса.
    let progressionHtml = '';
    if (current && current.class_level) {
        const cl = current.class_level;
        const ps = current.primary_skill;
        const psLevel = current.primary_skill_level || 0;
        const nextT = current.next_threshold;
        const stars = '★'.repeat(cl) + '☆'.repeat(3 - cl);
        const progress = nextT
            ? `${ps} ${psLevel}/${nextT} → lvl ${cl + 1}`
            : `${ps} ${psLevel} (MAX)`;
        progressionHtml = `
            <div style="margin-top:4px;font-size:10px;color:#adadb8;
                        background:rgba(251,191,36,0.05);border-radius:4px;
                        padding:4px 8px;display:flex;justify-content:space-between;
                        align-items:center;gap:6px;">
                <span><span style="color:#fbbf24;">${stars}</span> класс lvl ${cl}</span>
                <span style="color:#9ca3af;font-size:9px;" title="Качай ${ps} чтобы апгрейднуть class lvl и усилить активки. Bow / Riding / OneHanded / TwoHanded / Polearm в зависимости от класса.">
                    ${escapeHtml(progress)}
                </span>
            </div>`;
    }

    slot.innerHTML = `
        <div style="display:flex;align-items:center;gap:6px;margin-top:8px;margin-bottom:4px;">
            <span style="font-size:11px;color:#adadb8;white-space:nowrap;">🎖️ Класс:</span>
            <select id="bnr-class-select"
                    style="flex:1;background:#2d2d2f;color:#efeff1;border:1px solid #3d3d3f;
                           padding:5px 8px;font-size:12px;border-radius:4px;cursor:pointer;
                           ${currentKey ? '' : 'border-color:#fbbf24;'}">
                ${placeholderOpt}
                ${optionsHtml}
            </select>
        </div>
        ${progressionHtml}
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
    if (!slot) {
        dbg('[BNR activePowers] slot не найден в DOM');
        return;
    }
    if (!_bannerlordClassesCache) {
        dbg('[BNR activePowers] _bannerlordClassesCache не загружен');
        slot.innerHTML = '';
        return;
    }
    const powers = _bannerlordClassesCache.current_powers || [];
    dbg('[BNR activePowers] received', powers.length, 'powers:', powers);
    if (!powers.length) {
        slot.innerHTML = `<div style="font-size:11px;color:#9ca3af;margin:8px 0;text-align:center;">
            Способности появятся после выбора класса (Прокачка → Класс)
        </div>`;
        return;
    }

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
            ? ` <span style="color:#9ca3af;">${_bnrCdLabel(Math.ceil(cdRem))}</span>`
            : ` <span style="color:#fbbf24;">${price}💎</span>`;
        return `
            <button class="small-btn"
                    data-bnr-power="${escapeHtml(p.power_key)}"
                    data-bnr-price="${price}"
                    data-bnr-cost="${price},0"
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
    const ALLY_PRICE = 50;     // 5.27i: 100→50 (×0.5)
    const ENEMY_PRICE = 100;   // 5.27i: 200→100 (×0.5, 2× тролл-tax сохранён)
    const cdRem = (_bannerlordCooldowns.find(c => c.power_key === 'player.spawn') || {}).remaining_s || 0;
    const onCooldown = cdRem > 0;
    const cdLabel = onCooldown
        ? `<span style="color:#9ca3af;">${_bnrCdLabel(Math.ceil(cdRem))}</span>`
        : '';

    slot.innerHTML = `
        <div style="display:flex;flex-direction:column;gap:4px;margin-top:6px;">
            <button class="modal-btn" id="bnr-summon-ally-btn"
                    data-bnr-cost="${ALLY_PRICE},0"
                    ${onCooldown ? 'disabled' : ''}
                    title="Призвать героя в бой на сторону стримера"
                    style="width:100%;padding:7px;font-size:12px;
                           ${onCooldown ? 'opacity:0.5;cursor:not-allowed;' : ''}">
                📯 Призвать за стримера
                ${onCooldown ? cdLabel : `<span style="color:#fbbf24;">${ALLY_PRICE}💎</span>`}
            </button>
            <button class="modal-btn" id="bnr-summon-enemy-btn"
                    data-bnr-cost="${ENEMY_PRICE},0"
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
        ? 'Только для конных классов (cavalry / horse_archer / camel_* / knight). 1 000 000💰 у героя в игре (T5–T6 конь).'
        : 'Случайный скакун из high-tier пула (T5–T6). Списывается 1 000 000💰 у героя в игре.';

    return `
        <div style="padding:6px 10px 10px 10px;">
            <div style="font-size:11px;color:#adadb8;margin-bottom:4px;">
                🎁 Случайный товар — оплата in-game динарами героя
            </div>
            <div style="display:flex;flex-direction:column;gap:4px;">
                <button class="extra-btn" id="bnr-random-weapon"
                        title="Случайное оружие из high-tier пула (T5–T6). Списывается 1 000 000💰 у героя в игре."
                        style="font-size:12px;padding:6px;">
                    🗡 Купить оружие <span style="color:#fbbf24;">1 000 000💰</span>
                </button>
                <button class="extra-btn" id="bnr-random-armor"
                        title="Случайная броня (любой slot) из high-tier пула (T5–T6). Списывается 500 000💰 у героя в игре."
                        style="font-size:12px;padding:6px;">
                    🛡 Купить броню <span style="color:#fbbf24;">500 000💰</span>
                </button>
                <button class="extra-btn" id="bnr-random-horse"
                        ${horseDisabled}
                        title="${horseTitle}"
                        style="font-size:12px;padding:6px;${horseStyle}">
                    🐎 Купить коня <span style="color:#fbbf24;">1 000 000💰</span>
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
// Sprint 5.27h — TIER_COSTS из mod-side RecruitTroopsHandler.TIER_COSTS.
// Используется UI чтобы вывести требуемые dinars в кнопке + disable если
// hero.Gold < cost.
const RETINUE_TIER_DINARS = [5_000, 10_000, 20_000, 30_000, 50_000, 80_000];
const RETINUE_ELITE_MULT = 3;
function _computeRetinueDinarCost(slots, isElite, isAdd) {
    let tier = 0;
    if (!isAdd) {
        const sameType = slots.filter(s => !!s.is_elite === isElite);
        if (sameType.length === 0) return 0;
        tier = Math.min(...sameType.map(s => s.tier || 0));
    }
    const base = RETINUE_TIER_DINARS[Math.min(tier, RETINUE_TIER_DINARS.length - 1)];
    return isElite ? base * RETINUE_ELITE_MULT : base;
}
// 2026-05-29 (BLT TrainingBehavior) — оценка стоимости bulk-тренировки: сумма
// цены апгрейда каждого НЕ-maxed слота. Потолок ветки зависит от типа: basic-линии
// топятся на движковом Tier 5, elite/ноблы — на Tier 6 (напр. Battania: фиан T5 ещё
// апается в чемпиона T6). Мод делает реальную проверку UpgradeTargets/affordability.
function _computeTrainCost(slots) {
    let total = 0;
    for (const s of (slots || [])) {
        const tier = s.tier || 0;
        if (tier >= (s.is_elite ? 6 : 5)) continue;   // вершина ветки — пропускаем
        const base = RETINUE_TIER_DINARS[Math.min(tier, RETINUE_TIER_DINARS.length - 1)];
        total += s.is_elite ? base * RETINUE_ELITE_MULT : base;
    }
    return total;
}
function _fmtDinars(n) {
    return n.toLocaleString('ru-RU').replace(/,/g, ' ');
}
function _renderRetinue(retinue) {
    const slot = document.getElementById('bnr-retinue-slot');
    if (!slot) return;
    // 2026-06-10 — кэп свиты = 5 + retinue_size_bonus от clan-апгрейдов (backend
    // отдаёт в hero.retinue_cap). Раньше был захардкожен 5 → апгрейд «Усиленная
    // свита» не открывал слот.
    const MAX_SLOTS = (_bannerlordLastHero?.hero?.retinue_cap) || 5;
    const list = retinue || [];
    // /my-hero shape: { hero: {gold:N, ...}, retinue: [...] } — gold вложен в .hero
    const heroGold = (_bannerlordLastHero?.hero?.gold) || 0;

    const rows = list.length === 0
        ? '<div style="font-size:11px;color:#9ca3af;padding:2px 0;">пусто</div>'
        : list.map(t => {
            const eliteBadge = t.is_elite
                ? '<span style="color:#fbbf24;font-size:9px;margin-right:4px;" title="Elite troop (EliteBasicTroop chain)">★</span>'
                : '';
            return `
                <div style="display:flex;justify-content:space-between;font-size:11px;padding:1px 0;">
                    <span>${eliteBadge}${escapeHtml(t.troop_name || t.troop_id)}</span>
                    <span style="color:#fbbf24;">T${(t.tier || 0)}★</span>
                </div>`;
        }).join('');

    const isMaxed = list.length >= MAX_SLOTS;
    // separate maxed checks для basic / elite
    const basicSlots = list.filter(t => !t.is_elite);
    const eliteSlots = list.filter(t => t.is_elite);
    // maxed = слот на вершине своей ветки. Basic-линии топятся на движковом Tier 5,
    // elite/ноблы — на Tier 6 (Battania: фиан T5 ещё апается в чемпиона T6). Раньше
    // обе ветки шли с >=5 → фиан ложно считался maxed, кнопка апа гасла → игровой
    // ТИР 6 был недостижим (репорт 2026-06-06).
    const basicAllMax = basicSlots.length > 0 && basicSlots.every(t => (t.tier || 0) >= 5);
    const eliteAllMax = eliteSlots.length > 0 && eliteSlots.every(t => (t.tier || 0) >= 6);

    // Dinar costs (mod-side RecruitTroopsHandler логика).
    const basicCost = _computeRetinueDinarCost(list, false, !isMaxed);
    const eliteCost = _computeRetinueDinarCost(list, true,  !isMaxed);
    const basicLow  = heroGold < basicCost;
    const eliteLow  = heroGold < eliteCost;

    const basicLabel = basicAllMax && isMaxed
        ? '✓ Basic maxed'
        : (eliteSlots.length === 0 && basicSlots.length === 0 && isMaxed
            ? '✓ Basic maxed'
            : `${!isMaxed ? '➕ Нанять' : '⬆ Прокачать'} basic
               <div style="font-size:10px;font-weight:normal;margin-top:2px;opacity:0.85;">
                   ${_fmtDinars(basicCost)}💰
                   ${basicLow ? `<span style="color:#f87171;"> (не хватает ${_fmtDinars(basicCost - heroGold)}💰)</span>` : ''}
               </div>`);
    const eliteLabel = eliteAllMax && isMaxed
        ? '✓ Elite maxed'
        : (basicSlots.length === 0 && eliteSlots.length === 0 && isMaxed
            ? '✓ Elite maxed'
            : `${!isMaxed ? '★ Нанять' : '⬆ Прокачать'} elite
               <div style="font-size:10px;font-weight:normal;margin-top:2px;opacity:0.85;">
                   ${_fmtDinars(eliteCost)}💰
                   ${eliteLow ? `<span style="color:#f87171;"> (не хватает ${_fmtDinars(eliteCost - heroGold)}💰)</span>` : ''}
               </div>`);

    const basicDisabled = (isMaxed && (basicSlots.length === 0 || basicAllMax)) || basicLow;
    const eliteDisabled = (isMaxed && (eliteSlots.length === 0 || eliteAllMax)) || eliteLow;

    // 2026-05-29 (BLT TrainingBehavior) — bulk-тренировка свиты.
    const trainCost = _computeTrainCost(list);
    const trainLow = heroGold < trainCost;
    // Активна только если есть кого качать (непустая свита + не вся maxed) и хватает динаров.
    const trainDisabled = list.length === 0 || trainCost <= 0 || trainLow;

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
                            data-bnr-cd="hero.recruit_troops"
                            ${basicDisabled ? 'disabled' : ''}
                            title="Basic troop (battanian_recruit / khuzait_nomad / etc). Списать ${_fmtDinars(basicCost)}💰 динаров у героя."
                            style="flex:1;font-size:11px;padding:6px;line-height:1.2;
                                   ${basicDisabled ? 'opacity:0.5;cursor:not-allowed;' : ''}">
                        ${basicLabel}
                    </button>
                    <button class="extra-btn" id="bnr-recruit-elite-btn"
                            data-bnr-cd="hero.recruit_troops"
                            ${eliteDisabled ? 'disabled' : ''}
                            title="Elite troop (battanian_oathsworn / vlandian_squire / etc) — другая ветка прокачки. 3× стоимость. Списать ${_fmtDinars(eliteCost)}💰 динаров у героя."
                            style="flex:1;font-size:11px;padding:6px;line-height:1.2;background:#5c2d12;color:#fbbf24;
                                   ${eliteDisabled ? 'opacity:0.5;cursor:not-allowed;' : ''}">
                        ${eliteLabel}
                    </button>
                </div>
                <button class="extra-btn" id="bnr-train-troops-btn"
                        data-bnr-cd="hero.train_troops"
                        ${trainDisabled ? 'disabled' : ''}
                        title="Тренировать всю свиту: каждый слот апается на тир. Списать у героя ~${_fmtDinars(trainCost)}💰 динаров (точную сумму считает игра, maxed-слоты пропускаются)."
                        style="width:100%;margin-top:4px;font-size:11px;padding:6px;line-height:1.2;background:#1e3a2f;color:#86efac;
                               ${trainDisabled ? 'opacity:0.5;cursor:not-allowed;' : ''}">
                    🎯 Тренировать свиту
                    <div style="font-size:10px;font-weight:normal;margin-top:2px;opacity:0.85;">
                        ${list.length === 0
                            ? 'свита пуста'
                            : (trainCost <= 0
                                ? 'вся свита maxed'
                                : `~${_fmtDinars(trainCost)}💰${trainLow ? ` <span style="color:#f87171;">(не хватает ${_fmtDinars(trainCost - heroGold)}💰)</span>` : ''}`)}
                    </div>
                </button>
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
    document.getElementById('bnr-train-troops-btn')?.addEventListener('click', () => {
        if (trainDisabled) return;
        _bannerlordBuyAction('hero.train_troops', {});
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
                data-bnr-cost="${o.crusticov},0"
                title="Дать +${o.dinars.toLocaleString('ru-RU')} динаров герою в игре"
                style="font-size:11px;padding:5px;">
            💰 +${_formatBigGold(o.dinars)}
            <span style="color:#fbbf24;">${_formatBigPrice(o.crusticov)}</span>
        </button>`).join('');

    const xpRows = ADD_SKILL_OPTIONS.map(o => `
        <button class="extra-btn" data-bnr-skillxp="${o.crusticov}"
                data-bnr-cost="${o.crusticov},0"
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
        btn.dataset.bnrCd = 'hero.add_skill';   // кулдаун на кнопке
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
    'Athletics', 'Riding', 'Crafting', 'Scouting', 'Tactics', 'Roguery',
    'Charm', 'Leadership', 'Trade', 'Steward', 'Medicine', 'Engineering',
];
const BNR_SKILL_LABELS_RU = {
    OneHanded: 'Одноручное', TwoHanded: 'Двуручное', Polearm: 'Древковое',
    Bow: 'Лук', Crossbow: 'Арбалет', Throwing: 'Метательное',
    Athletics: 'Атлетика', Riding: 'Верховая езда', Crafting: 'Кузнечное',
    Scouting: 'Разведка', Tactics: 'Тактика', Roguery: 'Бесчестие',
    Charm: 'Обаяние', Leadership: 'Лидерство', Trade: 'Торговля',
    Steward: 'Управление', Medicine: 'Медицина', Engineering: 'Инженерия',
};
const BNR_ATTRIBUTES = ['Vigor', 'Control', 'Endurance', 'Cunning', 'Social', 'Intelligence'];
const BNR_ATTR_LABELS_RU = {
    Vigor: 'Сила', Control: 'Точность',
    Endurance: 'Выносливость', Cunning: 'Хитрость',
    Social: 'Социальность', Intelligence: 'Интеллект',
};
// Sprint 5.17: vanilla Bannerlord skill→attribute mapping. Атрибут даёт
// +1 cap к skill за каждое очко (max 30 cap при attr=10).
const BNR_ATTR_TO_SKILLS = {
    Vigor:        ['OneHanded', 'TwoHanded', 'Polearm'],
    Control:      ['Bow', 'Crossbow', 'Throwing'],
    Endurance:    ['Riding', 'Athletics', 'Crafting'],
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
// внутрь progression-секции (per-row + buttons). См. loadBannerlordProgression.

// Sprint 5.8: Progression modal — отображает все скиллы (level + focus stars)
// + 6 атрибутов. Открывается по кнопке "🎯 Прогрессия" в hero card.
function loadBannerlordProgression() {
    const slot = document.getElementById('bnr-progression-slot');
    if (!slot) return;
    const data = _bannerlordLastHero;
    if (!data || !data.has_hero) { _smartInnerHTML(slot, ''); return; }
    const skills = data.skills || [];
    const attrs = data.attributes || {};

    // Sprint 5.27v: runtime canary — словить contract drift сразу. Если
    // backend начнёт отдавать другой shape (e.g. изменится capitalization
    // или ключи), DevTools console сразу покажет проблему вместо тихого
    // "0/10 везде". Это профилактика для skills/equipment/etc. в будущем.
    const attrKeys = Object.keys(attrs);
    if (attrKeys.length > 0 && BNR_ATTRIBUTES.every(k =>
            attrs[k] === undefined && attrs[k.toLowerCase()] === undefined)) {
        console.warn('[BNR contract drift] attributes object has keys but ' +
                     'none match expected:', attrKeys,
                     'expected one of:', BNR_ATTRIBUTES);
    }

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
    // Sprint 5.27u: case-insensitive lookup — backend хранит attribute keys в
    // lowercase (engine StringId), frontend BNR_ATTRIBUTES в PascalCase.
    // Без fallback'а на toLowerCase() все viewer'ы видели 0/10 несмотря на
    // корректные value в БД.
    const groupedRows = BNR_ATTRIBUTES.map(attrKey => {
        const val = attrs[attrKey] ?? attrs[attrKey.toLowerCase()] ?? 0;
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

    const html = `
        <div style="font-size:11px;color:#adadb8;margin-bottom:6px;line-height:1.4;">
            💪 Атрибут (50K💰) — cap трёх скиллов · 🎯 Фокус (30-75K💰) — скорость скилла.
        </div>
        <div>${groupedRows}</div>`;
    if (!_smartInnerHTML(slot, html)) return;   // repaint+rebind лишь при изменении

    slot.querySelectorAll('.bnr-prog-focus-btn').forEach(btn => {
        btn.dataset.bnrCd = 'hero.add_focus';
        btn.addEventListener('click', () => {
            _bannerlordBuyAction('hero.add_focus', { skill_key: btn.getAttribute('data-skill'), amount: 1 });
            if (typeof loadBannerlordHero === 'function') loadBannerlordHero();
        });
    });
    slot.querySelectorAll('.bnr-prog-attr-btn').forEach(btn => {
        btn.dataset.bnrCd = 'hero.add_attribute';
        btn.addEventListener('click', () => {
            _bannerlordBuyAction('hero.add_attribute', { attribute_key: btn.getAttribute('data-attr'), amount: 1 });
            if (typeof loadBannerlordHero === 'function') loadBannerlordHero();
        });
    });
}

// Sprint 5.11: общий helper для открытия modal — clan / kingdom management.
// Содержит варианты create / join / leave в зависимости от текущего state.
// 2026-06-07 — модалка управления кланом УДАЛЕНА: всё инлайн во вкладке «Династия»
// (секция 🏰 Клан для лидера; locked-actions создать/вступить/покинуть для
// clanless/участника). Имя клана — через _renderCreateClanInline/_renderJoinInline.

// 2026-06-07 — общий рендер дерева апгрейдов клана (tier-группы + bulk-чекбоксы).
// Используется ИНЛАЙН-секцией «Династия → 🏆 Апгрейды клана» (_renderClanUpgradesInline).
// Footer на КЛАССАХ (не id) — чтобы не конфликтовать с id-версией в модалке, если
// обе в DOM одновременно. Чистый HTML, scoped bind ниже.
function _clanUpgradesTreeHtml(upgrades, heroGold) {
    const byTier = {};
    (upgrades || []).forEach(u => {
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
            const isSelectable = !u.owned && !u.locked && canAfford;
            const ownedBadge = u.owned
                ? `<span style="color:#34d399;font-weight:700;font-size:11px;">✓ ВЛАДЕЕШЬ</span>`
                : u.locked
                    ? `<span style="color:#6b7280;font-size:11px;">🔒 Нужен предыдущий</span>`
                    : isSelectable
                        ? `<label style="display:flex;align-items:center;gap:6px;cursor:pointer;
                                       font-size:11px;color:#fbbf24;font-weight:700;">
                              <input type="checkbox" class="bnr-upg-check"
                                     data-bnr-upg-id="${u.upgrade_id}"
                                     data-bnr-upg-cost="${u.gold_cost}"
                                     data-bnr-upg-name="${escapeHtml(u.name)}"
                                     style="cursor:pointer;width:14px;height:14px;">
                              ${u.gold_cost.toLocaleString('ru-RU')}💰
                           </label>`
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
    const bulkFooter = `
        <div style="
            position:sticky;bottom:0;background:#0f0f12;padding:8px;margin-top:6px;
            border-top:1px solid #5b21b6;border-radius:0 0 6px 6px;
            display:flex;justify-content:space-between;align-items:center;gap:8px;">
            <div style="font-size:11px;color:#adadb8;">
                Выбрано: <b class="bnr-bulk-count" style="color:#fbbf24;">0</b> ·
                Стоимость: <b class="bnr-bulk-total" style="color:#fbbf24;">0💰</b>
            </div>
            <button class="bnr-bulk-buy" disabled
                    style="background:#5b21b6;color:#9ca3af;padding:6px 12px;font-size:11px;
                           font-weight:700;border-radius:4px;border:none;cursor:not-allowed;">
                💰 Купить все выбранные
            </button>
        </div>`;
    return (tierHtml || '<div style="color:#adadb8;text-align:center;font-size:11px;padding:6px;">Каталог апгрейдов пуст.</div>')
           + bulkFooter;
}
// Scoped bind для bulk-чекбоксов + кнопки покупки внутри `root` (overlay ИЛИ slot).
// onSuccess() вызывается после удачной покупки (модалка → reopen; инлайн → re-render).
function _clanUpgradesBindBulk(root, heroGold, onSuccess) {
    const recalc = () => {
        const checked = root.querySelectorAll('.bnr-upg-check:checked');
        let count = 0, total = 0;
        checked.forEach(cb => { count++; total += parseInt(cb.dataset.bnrUpgCost || '0', 10); });
        const countEl = root.querySelector('.bnr-bulk-count');
        const totalEl = root.querySelector('.bnr-bulk-total');
        const buyBtn  = root.querySelector('.bnr-bulk-buy');
        if (countEl) countEl.textContent = count;
        if (totalEl) totalEl.textContent = total.toLocaleString('ru-RU') + '💰';
        if (buyBtn) {
            const enabled = count > 0 && count <= 10 && total <= heroGold;
            buyBtn.disabled = !enabled;
            buyBtn.style.cursor = enabled ? 'pointer' : 'not-allowed';
            buyBtn.style.color = enabled ? '#fbbf24' : '#9ca3af';
            if (count > 10)            buyBtn.textContent = `❌ Макс 10 за раз (выбрано ${count})`;
            else if (total > heroGold) buyBtn.textContent = `❌ Не хватает ${(total - heroGold).toLocaleString('ru-RU')}💰`;
            else if (count === 0)      buyBtn.textContent = '💰 Купить все выбранные';
            else                       buyBtn.textContent = `💰 Купить ${count} апгрейдов`;
        }
    };
    root.querySelectorAll('.bnr-upg-check').forEach(cb => cb.addEventListener('change', recalc));
    const buyBtn = root.querySelector('.bnr-bulk-buy');
    buyBtn?.addEventListener('click', async () => {
        const ids = Array.from(root.querySelectorAll('.bnr-upg-check:checked'))
                         .map(cb => cb.dataset.bnrUpgId);
        if (ids.length === 0) return;
        buyBtn.disabled = true;
        buyBtn.textContent = '⏳ Покупаем ' + ids.length + '...';
        try {
            const r = await fetch(`${API_URL}/api/bannerlord/clan-upgrades/buy`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
                body: JSON.stringify({upgrade_ids: ids}),
            });
            const d = await r.json();
            showNotification(d.message, d.success ? 'success' : 'error', d.success ? 5000 : 6000);
            if (d.success) {
                if (typeof onSuccess === 'function') onSuccess();
                if (typeof loadBannerlordHero === 'function') loadBannerlordHero();
            } else {
                buyBtn.disabled = false;
                recalc();
            }
        } catch (e) {
            showNotification('Ошибка сети', 'error');
            buyBtn.disabled = false;
            recalc();
        }
    });
}
// Инлайн-дерево апгрейдов во вкладке «Династия». LAZY: вызывается при раскрытии
// <details data-bnr-details="dyn-upgrades"> (и после покупки), НЕ каждый poll —
// иначе 8-сек репейнт сбрасывал бы выбор чекбоксов (см. choice пользователя).
async function _renderClanUpgradesInline() {
    const slot = document.getElementById('bnr-clan-upgrades-slot');
    if (!slot) return;
    slot.innerHTML = '<div style="font-size:11px;color:#adadb8;padding:6px;">⏳ Загрузка апгрейдов…</div>';
    let data;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/clan-upgrades`, {
            headers: {'X-Twitch-JWT': authToken || ''},
        });
        data = await r.json();
    } catch (e) {
        slot.innerHTML = '<div style="font-size:11px;color:#f87171;padding:6px;">Ошибка загрузки</div>';
        return;
    }
    if (!data || !data.success) {
        slot.innerHTML = `<div style="font-size:11px;color:#f87171;padding:6px;">${escapeHtml(data?.message || 'Не удалось загрузить')}</div>`;
        return;
    }
    const heroGold = data.hero_gold || 0;
    slot.innerHTML = `
        <div style="font-size:10px;color:#9ca3af;margin-bottom:6px;">
            💰 ${heroGold.toLocaleString('ru-RU')} динаров · отметь галочками и купи разом (до 10)
        </div>
        ${_clanUpgradesTreeHtml(data.upgrades || [], heroGold)}`;
    _clanUpgradesBindBulk(slot, heroGold, () => _renderClanUpgradesInline());
}

// 2026-06-07 — _openBannerlordClanUpgradesModal удалена (orphan): апгрейды теперь инлайн (_renderClanUpgradesInline).

// Sprint 5.27a: profile modal — gender swap (+ marriage/family tree в 5.27b/c).
// Sprint 5.29 BLT-parity #6 phase B — Auctions modal.
// 2026-06-07 — _openBannerlordAuctionsModal удалена (orphan, аукционы убраны из UI ранее).

// Sprint 5.29 BLT-parity #6 — Smithing forge modal (trophy collection).
// MVP: backend-only trophies, no in-game ItemObject yet. Future iteration
// добавит actual Bannerlord equipment integration + auction.
async function _renderForgeInline() {
    const slot = document.getElementById('bnr-forge-slot');
    if (!slot) return;
    if (!isAuthUser()) {
        slot.innerHTML = '<div style="font-size:11px;color:#adadb8;padding:6px;">Войдите через Twitch</div>';
        return;
    }
    slot.innerHTML = '<div style="font-size:11px;color:#adadb8;padding:6px;">⏳ Загрузка…</div>';
    let data;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/custom-items`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        data = await r.json();
        if (!data.success) {
            slot.innerHTML = `<div style="font-size:11px;color:#f87171;padding:6px;">${escapeHtml(data.message || 'Не удалось загрузить')}</div>`;
            return;
        }
    } catch (e) {
        slot.innerHTML = '<div style="font-size:11px;color:#f87171;padding:6px;">Ошибка сети</div>';
        return;
    }
    const items = data.items || [];
    const slotsUsed = items.length;
    const slotsMax = data.max_slots || 50;
    const itemsHtml = items.length === 0
        ? '<div style="color:#adadb8;text-align:center;padding:14px;font-size:12px;">Пустая кузница. Скуй первый трофей!</div>'
        : items.map(it => {
            // Sprint 5.33 (BLT-parity ITEM) — rolled stats display.
            const statParts = [];
            if (it.damage_bonus > 0) statParts.push(`⚔ +${it.damage_bonus}`);
            if (it.armor_bonus > 0)  statParts.push(`🛡 +${it.armor_bonus}`);
            if (it.weight_factor && Math.abs(it.weight_factor - 1.0) > 0.001) {
                const pct = ((it.weight_factor - 1.0) * 100).toFixed(0);
                statParts.push(`⚖ ${pct >= 0 ? '+' : ''}${pct}%`);
            }
            if (it.speed_factor && Math.abs(it.speed_factor - 1.0) > 0.001) {
                const pct = ((it.speed_factor - 1.0) * 100).toFixed(0);
                statParts.push(`💨 +${pct}%`);
            }
            const statsLine = statParts.length
                ? `<div style="font-size:10px;color:#fbbf24;margin-top:2px;">${statParts.join(' · ')}</div>`
                : '';
            // Phase B — источник предмета + состояние "получен в игре".
            const srcBadge = it.source === 'tournament'
                ? '<span style="color:#fbbf24;"> · 🏆 турнир</span>'
                : '<span style="color:#9ca3af;"> · 🔨 кузница</span>';
            const claimedBadge = it.claimed
                ? '<span style="color:#34d399;"> · ✓ в игре</span>' : '';
            const equipBtn = it.claimed
                ? '<span title="Уже в инвентаре героя" style="font-size:12px;padding:3px 8px;color:#6b7280;">✓</span>'
                : `<button class="extra-btn bnr-equip-trophy" data-item-id="${it.id}"
                        title="Получить в игре — реальный предмет в инвентарь героя + бонус в бою"
                        style="font-size:10px;padding:3px 8px;color:#34d399;">📥</button>`;
            return `
            <div style="display:flex;align-items:center;gap:8px;
                        background:rgba(58,58,62,0.3);border:1px solid ${it.color};
                        border-radius:6px;padding:6px 10px;margin-bottom:4px;
                        ${it.claimed ? 'opacity:0.7;' : ''}">
                <div style="font-size:18px;">${escapeHtml(it.icon || '')}</div>
                <div style="flex:1;min-width:0;">
                    <div style="font-size:12px;color:${it.color};font-weight:700;
                                overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                        ${escapeHtml(it.custom_name)}
                    </div>
                    <div style="font-size:10px;color:#adadb8;">
                        ${escapeHtml(it.base_type)} / ${it.rarity} / T${it.tier}${srcBadge}${claimedBadge}
                    </div>
                    ${statsLine}
                </div>
                ${equipBtn}
                <button class="extra-btn bnr-discard-item" data-item-id="${it.id}"
                        title="Дискарди (удалить безвозвратно)"
                        style="font-size:10px;padding:3px 8px;color:#f87171;">
                    ✗
                </button>
            </div>
        `;}).join('');
    const SMITH_PRICE = 500;   // mirror ACTION_PRICES_DEFAULT
    const body = `
        <div style="margin-bottom:10px;font-size:11px;color:#adadb8;text-align:center;">
            Куй случайные трофеи — оружие / броню / коня. Rarity рандом
            (common 60% → legendary 1%). Трофеи копятся в инвентаре.
            Слотов: <b>${slotsUsed}/${slotsMax}</b>.
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:10px;">
            <button class="extra-btn bnr-smith-btn" data-base="weapon"
                    style="font-size:12px;padding:8px;background:#3a1a1a;color:#fbbf24;">
                ⚔ Оружие<br><span style="font-size:10px;">${SMITH_PRICE}💎</span>
            </button>
            <button class="extra-btn bnr-smith-btn" data-base="armor"
                    style="font-size:12px;padding:8px;background:#1a2a3a;color:#93c5fd;">
                🛡 Броня<br><span style="font-size:10px;">${SMITH_PRICE}💎</span>
            </button>
            <button class="extra-btn bnr-smith-btn" data-base="horse"
                    style="font-size:12px;padding:8px;background:#1a3a1a;color:#86efac;">
                🐎 Конь<br><span style="font-size:10px;">${SMITH_PRICE}💎</span>
            </button>
        </div>
        <div style="font-size:11px;color:#adadb8;margin-bottom:4px;">Инвентарь:</div>
        <div style="max-height:340px;overflow-y:auto;">${itemsHtml}</div>
    `;
    slot.innerHTML = body;
    slot.querySelectorAll('.bnr-smith-btn').forEach(btn => {
        btn.dataset.bnrCd = 'hero.smith_item';
        btn.addEventListener('click', () => {
            _bannerlordBuyAction('hero.smith_item', { base_type: btn.dataset.base });
            setTimeout(_renderForgeInline, 1200);   // показать новый трофей
        });
    });
    slot.querySelectorAll('.bnr-equip-trophy').forEach(btn => {
        btn.dataset.bnrCd = 'hero.equip_trophy';
        btn.addEventListener('click', () => {
            _bannerlordBuyAction('hero.equip_trophy', { custom_item_id: parseInt(btn.dataset.itemId, 10) });
            setTimeout(_renderForgeInline, 1200);
        });
    });
    slot.querySelectorAll('.bnr-discard-item').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = parseInt(btn.dataset.itemId, 10);
            if (!await _bnrConfirm('Дискарди трофей? Безвозвратно.', '🗑 Уничтожить')) return;
            try {
                const r = await fetch(`${API_URL}/api/bannerlord/custom-items/discard`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
                    body: JSON.stringify({ item_id: id }),
                });
                const res = await r.json();
                showNotification(res.message || (res.success ? 'OK' : 'Не удалось'),
                    res.success ? 'success' : 'error');
                if (res.success) setTimeout(_renderForgeInline, 200);
            } catch (e) {
                showNotification('Ошибка сети', 'error');
            }
        });
    });
}

// Sprint 5.29 BLT-parity #5 — Achievements modal.
async function _renderAchievementsInline() {
    const slot = document.getElementById('bnr-achievements-slot');
    if (!slot) return;
    if (!isAuthUser()) {
        slot.innerHTML = '<div style="font-size:11px;color:#adadb8;padding:6px;">Войдите через Twitch</div>';
        return;
    }
    slot.innerHTML = '<div style="font-size:11px;color:#adadb8;padding:6px;">⏳ Загрузка…</div>';
    let data;
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/achievements`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        data = await r.json();
        if (!data.success) {
            slot.innerHTML = `<div style="font-size:11px;color:#f87171;padding:6px;">${escapeHtml(data.message || 'Не удалось загрузить')}</div>`;
            return;
        }
    } catch (e) {
        slot.innerHTML = '<div style="font-size:11px;color:#f87171;padding:6px;">Ошибка сети</div>';
        return;
    }
    const items = (data.achievements || []).map(a => {
        const pct = a.threshold > 0
            ? Math.min(100, Math.round(a.current_value / a.threshold * 100))
            : 0;
        const cardBg = a.unlocked ? 'rgba(251,191,36,0.10)' : 'rgba(58,58,62,0.4)';
        const opacity = a.unlocked ? '1' : '0.55';
        const progressBar = a.unlocked
            ? `<div style="background:#fbbf24;height:4px;border-radius:2px;width:100%;"></div>`
            : `<div style="background:#3a3a3e;height:4px;border-radius:2px;position:relative;">
                   <div style="background:#9ca3af;height:4px;border-radius:2px;width:${pct}%;"></div>
               </div>`;
        return `
        <div style="background:${cardBg};border:1px solid #3d3d3f;border-radius:6px;
                    padding:8px 10px;margin-bottom:6px;opacity:${opacity};">
            <div style="display:flex;align-items:center;gap:8px;">
                <div style="font-size:22px;">${a.icon || '🏆'}</div>
                <div style="flex:1;">
                    <div style="font-size:12px;color:${a.unlocked ? '#fbbf24' : '#efeff1'};
                                font-weight:700;">
                        ${escapeHtml(a.name)} ${a.unlocked ? '✓' : ''}
                    </div>
                    <div style="font-size:10px;color:#adadb8;">${escapeHtml(a.description)}</div>
                </div>
                <div style="font-size:10px;color:#9ca3af;text-align:right;min-width:60px;">
                    ${a.current_value.toLocaleString('ru-RU')} / ${a.threshold.toLocaleString('ru-RU')}
                </div>
            </div>
            <div style="margin-top:5px;">${progressBar}</div>
        </div>`;
    }).join('');
    slot.innerHTML = `
        <div style="font-size:10px;color:#9ca3af;margin-bottom:6px;">Открыто ${data.unlocked_count}/${data.total}</div>
        ${items || '<div style="color:#adadb8;text-align:center;padding:12px;">Нет данных</div>'}`;
}

// 2026-06-02 (CLAN-GATE) — смена пола НЕ кланово-зависима → вынесена из
// профиль-модалки (она в запертой Династии) в Hero-вкладку, доступна всем.
function loadBannerlordGender() {
    const slot = document.getElementById('bnr-gender-slot');
    if (!slot) return;
    const h = _bannerlordLastHero?.hero || {};
    const heroGold = h.gold || 0;
    const GENDER_COST = 50000;
    const canAfford = heroGold >= GENDER_COST;
    const currentLabel = h.is_female === true ? '♀ Женский'
                       : h.is_female === false ? '♂ Мужской'
                       : '— (не известно)';
    const html = `
        <div style="font-size:11px;color:#adadb8;margin-bottom:6px;">
            Текущий: <b style="color:#efeff1;">${currentLabel}</b> ·
            <b style="color:#fbbf24;">${GENDER_COST.toLocaleString('ru-RU')}💰</b>
            (у тебя ${heroGold.toLocaleString('ru-RU')}💰)
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
            <button class="extra-btn bnr-gender-set" data-gender-set="male" ${canAfford ? '' : 'disabled'}
                    style="font-size:12px;padding:7px;background:${canAfford ? '#1e3a5f' : '#2d2d2f'};
                           color:${canAfford ? '#93c5fd' : '#6b7280'};${canAfford ? '' : 'cursor:not-allowed;'}">
                ♂ Мужской
            </button>
            <button class="extra-btn bnr-gender-set" data-gender-set="female" ${canAfford ? '' : 'disabled'}
                    style="font-size:12px;padding:7px;background:${canAfford ? '#5b21b6' : '#2d2d2f'};
                           color:${canAfford ? '#f472b6' : '#6b7280'};${canAfford ? '' : 'cursor:not-allowed;'}">
                ♀ Женский
            </button>
        </div>
        <div style="font-size:10px;color:#6b7280;margin-top:6px;">
            Есть супруг(а) — engine перевернёт их пол, чтобы брак остался валиден.
        </div>`;
    if (_smartInnerHTML(slot, html)) {
        slot.querySelectorAll('.bnr-gender-set').forEach(btn => {
            btn.dataset.bnrCd = 'hero.set_gender';
            btn.addEventListener('click', () => {
                _bannerlordBuyAction('hero.set_gender', { gender: btn.dataset.genderSet });
            });
        });
    }
}

function loadBannerlordProfileFamily() {
    const slot = document.getElementById('bnr-profile-slot');
    if (!slot) return;
    const h = _bannerlordLastHero?.hero || {};
    const heroGold = h.gold || 0;
    const hasClan = !!h.clan_name;   // брак/дети требуют клан (см. ниже)

    // 2026-06-02 (CLAN-GATE) — секция «смена пола» вынесена в Hero-вкладку
    // (_openBannerlordGenderModal): она не кланово-зависима, а эта модалка живёт
    // в запертой Династии. Здесь остаётся только семья (брак/дети — gated hasClan).
    const body = `
        <div style="background:#1a1a1c;border:1px solid #3a3a3e;border-radius:6px;
                    padding:10px;margin-bottom:8px;">
            <div style="font-size:12px;color:#adadb8;margin-bottom:6px;">
                💍 <b style="color:#efeff1;">Семейное положение</b>
            </div>
            ${h.spouse_name ? `
                <div style="font-size:11px;color:#adadb8;margin-bottom:8px;">
                    Супруг(а): <b style="color:#fbbf24;">${escapeHtml(h.spouse_name)}</b>
                </div>
                <button class="extra-btn" id="bnr-divorce-btn"
                        style="width:100%;font-size:11px;padding:8px;
                               background:#7f1d1d;color:#fca5a5;">
                    💔 Развестись (бесплатно)
                </button>
            ` : `
                <div style="font-size:11px;color:#adadb8;margin-bottom:8px;">
                    ${hasClan
                        ? 'Не в браке. Engine найдёт случайную подходящую NPC противоположного пола.'
                        : '⚠️ Брак доступен только герою с кланом — сначала создай или вступи в клан (🏰 Управление кланом). Бесклановый брак ломает игру.'}
                </div>
                <button class="extra-btn" id="bnr-marry-btn"
                        ${(hasClan && heroGold >= 50000) ? '' : 'disabled'}
                        title="${hasClan ? 'Engine выберет случайную подходящую NPC. Спишет 50K💰.' : 'Нужен клан: бесклановый замужний герой крашит ванильную модель беременности.'}"
                        style="width:100%;font-size:12px;padding:8px;
                               background:${(hasClan && heroGold >= 50000) ? '#5b21b6' : '#2d2d2f'};
                               color:${(hasClan && heroGold >= 50000) ? '#f472b6' : '#6b7280'};
                               ${(hasClan && heroGold >= 50000) ? '' : 'cursor:not-allowed;'}">
                    💍 Жениться/выйти замуж (50K💰)${hasClan ? '' : ' — нужен клан'}
                </button>
            `}
        </div>
        ${_renderFamilyTreeHtml(h)}
    `;

    if (_smartInnerHTML(slot, body)) {
        slot.querySelector('#bnr-marry-btn')?.addEventListener('click', () => {
            _bannerlordBuyAction('hero.marry', {});
        });
        slot.querySelector('#bnr-divorce-btn')?.addEventListener('click', () => {
            _bannerlordBuyAction('hero.divorce', {});
        });
        slot.querySelector('#bnr-make-baby-btn')?.addEventListener('click', () => {
            _bannerlordBuyAction('hero.make_baby', {});
        });
    }
}

// Sprint 5.27c: рендер family tree section для profile modal
function _renderFamilyTreeHtml(h) {
    const fi = h.family_info || {};
    const spouse = fi.spouse;
    const children = Array.isArray(fi.children) ? fi.children : [];
    const father = fi.father;
    const mother = fi.mother;
    const siblings = fi.sibling_count || 0;
    const heroGold = h.gold || 0;
    const BABY_COST = 100000;
    const hasClan = !!h.clan_name;   // дети рождаются в клан родителя; без клана — краш беременности
    const aliveChildren = children.filter(c => c?.is_alive);
    const canMakeBaby = hasClan && !!spouse && spouse.is_alive && aliveChildren.length < 5 && heroGold >= BABY_COST;
    const noBabyReason =
        !hasClan ? 'нужен клан'
        : !spouse ? 'нет супруга(и)'
        : !spouse.is_alive ? 'супруг(а) мёртв(а)'
        : aliveChildren.length >= 5 ? 'максимум 5 детей в клане'
        : heroGold < BABY_COST ? 'не хватает 💰'
        : null;

    const heroEmoji = (p) => p?.is_female ? '♀' : '♂';
    const heroLine = (p) => p
        ? `<div style="font-size:11px;color:${p.is_alive ? '#efeff1' : '#6b7280'};">
              ${heroEmoji(p)} ${escapeHtml(p.name || '?')} · ${p.age || '?'} лет
              ${p.is_alive ? '' : '☠️'}
              ${p.is_pregnant ? '🤰' : ''}
           </div>`
        : '<div style="font-size:11px;color:#6b7280;">—</div>';

    let childrenHtml;
    if (children.length === 0) {
        childrenHtml = '<div style="font-size:11px;color:#6b7280;">Детей пока нет</div>';
    } else {
        childrenHtml = children.map(c => `
            <div style="font-size:11px;color:${c.is_alive ? '#efeff1' : '#6b7280'};
                        padding:2px 0;">
                ${heroEmoji(c)} ${escapeHtml(c.name || '?')} · ${c.age || '?'} лет
                ${c.is_alive ? '' : '☠️'}
            </div>
        `).join('');
    }

    return `
        <div style="background:#1a1a1c;border:1px solid #3a3a3e;border-radius:6px;
                    padding:10px;">
            <div style="font-size:12px;color:#adadb8;margin-bottom:8px;">
                👨‍👩‍👧 <b style="color:#efeff1;">Семья</b>
            </div>

            <div style="display:grid;grid-template-columns:auto 1fr;gap:4px 8px;
                        font-size:11px;margin-bottom:10px;">
                <span style="color:#adadb8;">👴 Отец:</span> ${heroLine(father)}
                <span style="color:#adadb8;">👵 Мать:</span> ${heroLine(mother)}
                ${siblings > 0
                    ? `<span style="color:#adadb8;">👫 Братья/сёстры:</span>
                       <span style="color:#efeff1;">${siblings}</span>` : ''}
            </div>

            <div style="font-size:11px;color:#adadb8;margin-bottom:4px;">
                👶 Дети (${aliveChildren.length} живых из ${children.length}):
            </div>
            <div style="background:#0e0e10;border-radius:4px;padding:6px;margin-bottom:10px;
                        max-height:120px;overflow-y:auto;">
                ${childrenHtml}
            </div>

            <button class="extra-btn" id="bnr-make-baby-btn"
                    ${canMakeBaby ? '' : 'disabled'}
                    style="width:100%;font-size:12px;padding:8px;
                           background:${canMakeBaby ? '#5b21b6' : '#2d2d2f'};
                           color:${canMakeBaby ? '#f472b6' : '#6b7280'};
                           ${canMakeBaby ? '' : 'cursor:not-allowed;'}">
                🤰 Зачать ребёнка (100K💰)
                ${noBabyReason ? ` — ${noBabyReason}` : ''}
            </button>
            <div style="font-size:10px;color:#6b7280;margin-top:6px;text-align:center;">
                Через ~36 in-game дней появится ребёнок (engine PregnancyCampaignBehavior).
            </div>
        </div>
    `;
}

// 2026-06-07 — модалка управления королевством УДАЛЕНА: всё инлайн в секции
// 👑 Королевство вкладки «Династия» (покинуть / создать / вступить). Имя — через
// _renderCreateKingdomInline / _renderJoinInline('kingdom', ...).

// 2026-06-07 — инлайн-секции «Династия → 🏰 Клан / 👑 Королевство». Live-инфо
// из _bannerlordLastHero (без сети) + lazy-формы создать/вступить раскрываются
// прямо в секции (clanless/независимый клан — через _render*Inline).
// Гейтятся isClanLeader в poll'е (как остальные суб-слоты Династии).
// 2026-06-07 — locked-state Династии (не-лидер): clanless → создать/вступить;
// участник чужого клана → инфо + покинуть. Создать/вступить — lazy-формы инлайн
// (модалки клана/королевства удалены).
function loadBannerlordDynastyLockedActions() {
    const slot = document.getElementById('bnr-dynasty-locked-actions');
    if (!slot) return;
    const h = _bannerlordLastHero?.hero || {};
    const inClan = !!h.clan_name;
    // 2026-06-07 — создать/вступить инлайн (lazy <details>): поле имени переживает
    // 8s-poll (форма рендерится при раскрытии, не на каждом тике).
    const html = !inClan
        ? `<details data-bnr-details="locked-create" ${_bnrDetailsAttr('locked-create')} style="margin-bottom:6px;">
                <summary style="list-style:none;cursor:pointer;width:100%;box-sizing:border-box;
                           font-size:12px;padding:9px;border-radius:3px;
                           background:#7c2d12;color:#fbbf24;font-weight:700;border:1px solid #b45309;">
                    🏰 Создать клан (1M💰)
                </summary>
                <div id="bnr-locked-create-slot" style="padding-top:6px;"></div>
           </details>
           <details data-bnr-details="locked-join" ${_bnrDetailsAttr('locked-join')}>
                <summary style="list-style:none;cursor:pointer;width:100%;box-sizing:border-box;
                           font-size:12px;padding:9px;border-radius:3px;background:#1e3a5f;color:#93c5fd;">
                    🤝 Вступить в клан (50K💰)
                </summary>
                <div id="bnr-locked-join-slot" style="padding-top:6px;"></div>
           </details>`
        : `<div style="font-size:11px;color:#adadb8;margin-bottom:8px;">
                Ты в клане <b style="color:#fbbf24;">${escapeHtml(h.clan_name)}</b>, но не глава.
                Полная Династия открыта главе клана.
           </div>
           <button class="extra-btn bnr-locked-leave"
                   style="width:100%;font-size:12px;padding:9px;background:#7f1d1d;color:#fca5a5;">
                🚪 Покинуть клан
           </button>`;
    // 2026-06-07 FLICKER — пока раскрыта форма create/join, НЕ перерисовываем секцию
    // (html тут стабилен, но guard для единообразия/надёжности — безвреден).
    if (slot.querySelector('[data-bnr-details="locked-create"]')?.open
        || slot.querySelector('[data-bnr-details="locked-join"]')?.open) return;
    if (_smartInnerHTML(slot, html)) {
        const _lcDet = slot.querySelector('[data-bnr-details="locked-create"]');
        if (_lcDet) {
            _lcDet.addEventListener('toggle', () => { if (_lcDet.open) _renderCreateClanInline(); });
            if (_lcDet.open) _renderCreateClanInline();
        }
        const _ljDet = slot.querySelector('[data-bnr-details="locked-join"]');
        if (_ljDet) {
            _ljDet.addEventListener('toggle', () => { if (_ljDet.open) _renderJoinInline('clan', 'bnr-locked-join-slot'); });
            if (_ljDet.open) _renderJoinInline('clan', 'bnr-locked-join-slot');
        }
        slot.querySelector('.bnr-locked-leave')?.addEventListener('click', () => _bannerlordBuyAction('hero.leave_clan', {}));
    }
}
function loadBannerlordClanMgmt() {
    const slot = document.getElementById('bnr-clan-mgmt-slot');
    if (!slot) return;
    const h = _bannerlordLastHero?.hero || {};
    const info = h.clan_info || null;
    const infoGrid = info ? `
        <div style="display:grid;grid-template-columns:auto 1fr;gap:3px 10px;font-size:11px;margin-bottom:6px;">
            <span style="color:#adadb8;">⭐ Tier:</span><span style="color:#efeff1;">${info.tier || 0}</span>
            <span style="color:#adadb8;">🏆 Renown:</span><span style="color:#efeff1;">${(info.renown || 0).toLocaleString('ru-RU')}</span>
            <span style="color:#adadb8;">👥 Героев:</span><span style="color:#efeff1;">${info.members_count || 0}</span>
            <span style="color:#adadb8;">⚔ Отрядов:</span><span style="color:#efeff1;">${info.parties_count || 0}</span>
            <span style="color:#adadb8;">🏰 Поселений:</span><span style="color:#efeff1;">${info.fiefs_count || 0}</span>
        </div>`
        : `<div style="font-size:11px;color:#adadb8;margin-bottom:6px;">Нет данных о клане.</div>`;
    const isLeader = !!info?.is_leader;
    const hasParties = (info?.parties_count || 0) > 0;
    const partyBtn = (isLeader && !hasParties)
        ? `<button class="extra-btn bnr-clan-party"
                   title="Hero выйдет на карту как AI-lord. 200K💰 + retinue в roster."
                   style="width:100%;font-size:12px;padding:7px;margin-bottom:4px;background:#1e3a5f;color:#93c5fd;font-weight:700;">
                ⚔ Создать отряд (200K💰)
           </button>`
        : (isLeader && hasParties)
            ? `<div style="font-size:11px;color:#34d399;text-align:center;padding:4px;">✅ Отрядов у клана: ${info.parties_count}</div>`
            : '';
    const html = `
        <div style="font-size:12px;color:#fbbf24;font-weight:700;margin-bottom:4px;text-align:center;">
            ${escapeHtml(info?.name || h.clan_name || '—')}
        </div>
        ${infoGrid}
        ${partyBtn}
        <button class="extra-btn bnr-clan-leave"
                title="Покинуть клан. Лидерство передастся старшему non-hero, или клан распустится."
                style="width:100%;font-size:12px;padding:7px;background:#7f1d1d;color:#fca5a5;">
            🚪 Покинуть клан
        </button>`;
    if (_smartInnerHTML(slot, html)) {
        slot.querySelector('.bnr-clan-party')?.addEventListener('click', () => _bannerlordBuyAction('hero.create_party', {}));
        slot.querySelector('.bnr-clan-leave')?.addEventListener('click', () => _bannerlordBuyAction('hero.leave_clan', {}));
    }
}
function loadBannerlordKingdomMgmt() {
    const slot = document.getElementById('bnr-kingdom-mgmt-slot');
    if (!slot) return;
    const h = _bannerlordLastHero?.hero || {};
    const info = h.kingdom_info || null;
    const hasKingdom = !!h.kingdom_name;
    const infoGrid = (hasKingdom && info) ? `
        <div style="display:grid;grid-template-columns:auto 1fr;gap:3px 10px;font-size:11px;margin-bottom:6px;">
            <span style="color:#adadb8;">👑 Правитель:</span><span style="color:#efeff1;">${escapeHtml(info.ruler_name || '?')}${info.is_ruler ? ' <b style="color:#fbbf24;">(ты)</b>' : ''}</span>
            <span style="color:#adadb8;">🏰 Кланов:</span><span style="color:#efeff1;">${info.clans_count || 0}</span>
            <span style="color:#adadb8;">🌆 Поселений:</span><span style="color:#efeff1;">${info.fiefs_count || 0}</span>
            <span style="color:#adadb8;">⚔ Война с:</span><span style="color:${(info.at_war_count || 0) > 0 ? '#f87171' : '#efeff1'};">${info.at_war_count || 0} корол.</span>
        </div>`
        : `<div style="font-size:11px;color:#adadb8;margin-bottom:6px;">Клан независим — без королевства.</div>`;
    // 2026-06-07 — создать/вступить инлайн (lazy <details>): поле имени переживает
    // 8s-poll (форма рендерится при раскрытии, не на каждом тике).
    const actions = hasKingdom
        ? `<button class="extra-btn bnr-kingdom-leave"
                   title="Вывести клан из королевства — бесплатно."
                   style="width:100%;font-size:12px;padding:7px;background:#7f1d1d;color:#fca5a5;">
                🚪 Покинуть королевство
           </button>`
        : `<details data-bnr-details="kingdom-create" ${_bnrDetailsAttr('kingdom-create')} style="margin-bottom:4px;">
                <summary title="Создать своё королевство (5M💰). Клан становится правящим."
                         style="list-style:none;cursor:pointer;width:100%;box-sizing:border-box;
                                font-size:12px;padding:7px;border-radius:3px;background:#7c2d12;color:#fbbf24;font-weight:700;">
                    👑 Создать королевство (5M💰)
                </summary>
                <div id="bnr-kingdom-create-slot" style="padding-top:6px;"></div>
           </details>
           <details data-bnr-details="kingdom-join" ${_bnrDetailsAttr('kingdom-join')}>
                <summary title="Вступить в существующее королевство (100K💰)."
                         style="list-style:none;cursor:pointer;width:100%;box-sizing:border-box;
                                font-size:12px;padding:7px;border-radius:3px;background:#1e3a5f;color:#93c5fd;">
                    🤝 Вступить в королевство (100K💰)
                </summary>
                <div id="bnr-kingdom-join-slot" style="padding-top:6px;"></div>
           </details>`;
    const html = `
        <div style="font-size:12px;color:#93c5fd;font-weight:700;margin-bottom:4px;text-align:center;">
            ${hasKingdom ? escapeHtml(info?.name || h.kingdom_name) : '— нет королевства —'}
        </div>
        ${infoGrid}
        ${actions}`;
    // 2026-06-07 FLICKER — пока раскрыта форма create/join, НЕ перерисовываем секцию
    // (иначе repaint стирает ввод имени). Любая из двух форм блокирует repaint.
    if (slot.querySelector('[data-bnr-details="kingdom-create"]')?.open
        || slot.querySelector('[data-bnr-details="kingdom-join"]')?.open) return;
    if (_smartInnerHTML(slot, html)) {
        slot.querySelector('.bnr-kingdom-leave')?.addEventListener('click', () => _bannerlordBuyAction('hero.leave_kingdom', {}));
        const _kcDet = slot.querySelector('[data-bnr-details="kingdom-create"]');
        if (_kcDet) {
            _kcDet.addEventListener('toggle', () => { if (_kcDet.open) _renderCreateKingdomInline(); });
            if (_kcDet.open) _renderCreateKingdomInline();
        }
        const _kjDet = slot.querySelector('[data-bnr-details="kingdom-join"]');
        if (_kjDet) {
            _kjDet.addEventListener('toggle', () => { if (_kjDet.open) _renderJoinInline('kingdom', 'bnr-kingdom-join-slot'); });
            if (_kjDet.open) _renderJoinInline('kingdom', 'bnr-kingdom-join-slot');
        }
    }
}

// Sprint 5.31 #45b — Boosty admin перенесён на /streamer/dashboard.
// Sprint 5.31 #45f (codegraph dead-code audit) — модал удалён, ~205 строк.
// История: первый деплой Boosty имел админ-UI внутри расширения, потом
// перенесли на дашборд (cookie-сессия), а кнопка в расширении тоже убрана.
// Если нужно вернуть — git log по этому файлу до 2026-05-25.

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
// удалена: инлайн lazy-поле имени королевства (_renderCreateKingdomInline).
function _renderCreateKingdomInline() {
    const slot = document.getElementById('bnr-kingdom-create-slot');
    if (!slot) return;
    slot.innerHTML = `
        <div style="background:#18181b;border:1px solid #3d3d3f;border-radius:6px;padding:12px;">
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
            <button id="bnr-k-confirm" class="extra-btn"
                    style="width:100%;font-size:12px;padding:7px;background:#7c2d12;
                           color:#fbbf24;font-weight:700;">
                👑 Создать (5M💰)
            </button>
        </div>`;
    const input = document.getElementById('bnr-kingdom-name-input');
    const confirm = () => {
        const kingdom_name = (input?.value || '').trim();
        // 2026-06-07 FLICKER — закрыть форму ДО действия (иначе freeze-guard
        // заблокирует следующий repaint секции) + мгновенный фидбек на клик.
        document.querySelector('[data-bnr-details="kingdom-create"]')?.removeAttribute('open');
        _bannerlordBuyAction('hero.create_kingdom', { kingdom_name });
    };
    document.getElementById('bnr-k-confirm')?.addEventListener('click', confirm);
    input?.addEventListener('keydown', e => { if (e.key === 'Enter') confirm(); });
}

// удалена: инлайн lazy-поле join (_renderJoinInline) — type 'clan'|'kingdom'.
function _renderJoinInline(type, slotId) {
    const slot = document.getElementById(slotId);
    if (!slot) return;
    const isClan = type === 'clan';
    const config = isClan
        ? { icon: '🤝', cost: '50K💰',
            actionType: 'hero.join_clan', field: 'clan_name',
            placeholder: 'например: Vlandian Royal Clan',
            hint: 'Введи (часть) имя существующего клана. Mod fuzzy-matches.' }
        : { icon: '🤝', cost: '100K💰',
            actionType: 'hero.join_kingdom', field: 'kingdom_name',
            placeholder: 'например: Vlandia',
            hint: 'Введи (часть) имя королевства. Твой clan присоединится как вассал.' };
    slot.innerHTML = `
        <div style="background:#18181b;border:1px solid #3d3d3f;border-radius:6px;padding:12px;">
            <div style="font-size:11px;color:#adadb8;margin-bottom:10px;line-height:1.4;">
                ${config.hint} Списать <b style="color:#fbbf24;">${config.cost} динаров</b>.
            </div>
            <input id="bnr-join-name-input" type="text" maxlength="64"
                   placeholder="${config.placeholder}"
                   style="width:100%;background:#2d2d2f;color:#efeff1;
                          border:1px solid #3d3d3f;border-radius:4px;
                          padding:6px 8px;font-size:12px;margin-bottom:12px;
                          box-sizing:border-box;">
            <button id="bnr-j-confirm" class="extra-btn"
                    style="width:100%;font-size:12px;padding:7px;background:#1e3a5f;
                           color:#93c5fd;font-weight:700;">
                ${config.icon} Вступить (${config.cost})
            </button>
        </div>`;
    const input = document.getElementById('bnr-join-name-input');
    // 2026-06-07 FLICKER — ключ <details> зависит от контекста: kingdom-join (королевство)
    // или locked-join (клан). Закрыть форму ДО действия, иначе freeze-guard секции
    // заблокирует следующий repaint. + мгновенный фидбек на клик.
    const _joinDetKey = isClan ? 'locked-join' : 'kingdom-join';
    const confirm = () => {
        const name = (input?.value || '').trim();
        if (!name) return;
        document.querySelector(`[data-bnr-details="${_joinDetKey}"]`)?.removeAttribute('open');
        _bannerlordBuyAction(config.actionType, { [config.field]: name });
    };
    document.getElementById('bnr-j-confirm')?.addEventListener('click', confirm);
    input?.addEventListener('keydown', e => { if (e.key === 'Enter') confirm(); });
}

// удалена: инлайн lazy-поле имени клана (_renderCreateClanInline).
function _renderCreateClanInline() {
    const slot = document.getElementById('bnr-locked-create-slot');
    if (!slot) return;
    slot.innerHTML = `
        <div style="background:#18181b;border:1px solid #3d3d3f;border-radius:6px;padding:12px;">
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
            <button id="bnr-clan-confirm" class="extra-btn"
                    style="width:100%;font-size:12px;padding:7px;background:#7c2d12;
                           color:#fbbf24;font-weight:700;">
                🏰 Создать (1M💰)
            </button>
        </div>`;
    const input = document.getElementById('bnr-clan-name-input');
    const confirm = () => {
        const clan_name = (input?.value || '').trim();
        // 2026-06-07 FLICKER — закрыть форму ДО действия (иначе freeze-guard
        // заблокирует следующий repaint секции) + мгновенный фидбек на клик.
        document.querySelector('[data-bnr-details="locked-create"]')?.removeAttribute('open');
        _bannerlordBuyAction('hero.create_clan', { clan_name });
    };
    document.getElementById('bnr-clan-confirm')?.addEventListener('click', confirm);
    input?.addEventListener('keydown', e => { if (e.key === 'Enter') confirm(); });
}

function _bindBannerlordRandomEquip() {
    const MOUNTED = new Set(['cavalry', 'camel_cavalry', 'horse_archer', 'camel_archer', 'knight']);
    const currentKey = _bannerlordClassesCache?.current?.class_key || '';
    const isMounted = MOUNTED.has(currentKey);

    // Кулдаун на кнопке (player.equip_item — общий CD на все три).
    ['bnr-random-weapon', 'bnr-random-armor', 'bnr-random-horse'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.dataset.bnrCd = 'player.equip_item';
    });

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
// Sprint 5.29 audit fix #37: store absolute expires_at_ms на каждый fetch
// чтобы ticker мог recompute remaining = (expires_at_ms - Date.now())/1000.
// Раньше client-side декремент drift'ил когда tab throttled — viewer видел
// power как "unlocked" пока CD реально active, кликал → backend rejects.
async function loadBannerlordBuffs() {
    try {
        const r = await fetch(`${API_URL}/api/bannerlord/my-buffs`, {
            headers: { 'X-Twitch-JWT': authToken || '' },
        });
        const data = await r.json();
        if (data.success) {
            const now = Date.now();
            _bannerlordBuffs = (data.buffs || []).map(b => ({
                ...b,
                expires_at_ms: now + (b.remaining_s || 0) * 1000,
            }));
            _bannerlordCooldowns = (data.cooldowns || []).map(c => ({
                ...c,
                expires_at_ms: now + (c.remaining_s || 0) * 1000,
            }));
            _renderBannerlordBuffs();
            renderBannerlordActivePowers();
        }
    } catch (e) {
        // Sprint 5.29 audit fix #36: было silent — теперь warn (HUD-poll)
        console.warn('[BNR loadBannerlordBuffs]', e);
    }
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
        // Sprint 5.29 audit fix #36: badge silent OK, но логируем для диагностики
        console.warn('[BNR loadBannerlordStatus]', e);
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
        // Sprint 5.32 (BLT-parity DET-4) — render detachment commands если
        // viewer в активном Mission'е (alive=true). Иначе hide secion.
        _renderBannerlordDetachmentPanel(data);
    } catch (e) {
        // Sprint 5.29 audit fix #36: silent → warn
        console.warn('[BNR loadBannerlordBattleStatus]', e);
    }
}

// Sprint 5.32 (BLT-parity DET-4) — Detachment-команды для viewer'а в Mission.
// 6 кнопок: detach/attach + hold/charge + walls/gate. Caller — кнопка → POST
// `hero.detach_X` action → backend pricing → mod handler → HeroDetachmentBehavior.
//
// Disabled state если viewer не alive в текущей mission (`data.my_stats.alive`).
function _renderBannerlordDetachmentPanel(battleData) {
    const slot = document.getElementById('bnr-detachment-slot');
    if (!slot) return;
    const alive = !!(battleData && battleData.in_battle
                     && battleData.my_stats && battleData.my_stats.alive);
    // Если не в бою / не alive → не рендерим panel. Reduce clutter.
    if (!alive) {
        // Sprint 5.32 (LOG-4) — log только при transition (panel был — стал hidden).
        if (slot.innerHTML !== '') {
            console.info('[FE-DET] panel HIDE (alive=false or not in_battle)');
        }
        slot.innerHTML = '';
        return;
    }
    // Sprint 5.32 (LOG-4) — log при first render (panel пустой → станет filled).
    const wasEmpty = slot.innerHTML === '';
    if (wasEmpty) {
        console.info('[FE-DET] panel SHOW (battle started, viewer alive)');
    }
    slot.innerHTML = `
        <div style="font-size:12px;color:#fbbf24;font-weight:700;margin-bottom:6px;
                    border-top:1px solid #3d3d3f;padding-top:8px;">
            🎯 Команды отряда
            <span style="font-size:10px;color:#9ca3af;font-weight:normal;
                         margin-left:6px;">(управляй своим героем в бою)</span>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;
                    font-size:11px;">
            <button class="extra-btn bnr-det-btn" data-det-act="hero.detach_hold"
                    data-det-cost="30"
                    title="Стоять на текущей позиции. Полезно archer'ам — sniper-mode не отступает."
                    style="background:#1e3a8a;color:#bfdbfe;padding:6px;">
                ⛔ Стоять (30💎)
            </button>
            <button class="extra-btn bnr-det-btn" data-det-act="hero.detach_charge"
                    data-det-cost="30"
                    title="Бежать на ближайшее enemy formation. Berserk'и заходят первыми, ломают фронт."
                    style="background:#7c1d1d;color:#fecaca;padding:6px;">
                ⚔ В атаку (30💎)
            </button>
            <button class="extra-btn bnr-det-btn" data-det-act="hero.attach"
                    data-det-cost="10"
                    title="Вернуть hero в parent formation стримера. Подчиняется AI commander снова."
                    style="background:#1f4a35;color:#a7f3d0;padding:6px;">
                🔄 В строй (10💎)
            </button>
            <button class="extra-btn bnr-det-btn" data-det-act="hero.detach_walls"
                    data-det-cost="30"
                    title="🏰 Siege only: лезть на стены/лестницы/башни. Archer'ам — defense top."
                    style="background:#3d2e0a;color:#fde68a;padding:6px;">
                🪜 К стенам (30💎)
            </button>
            <button class="extra-btn bnr-det-btn" data-det-act="hero.detach_gate"
                    data-det-cost="30"
                    title="🏰 Siege only: к ближайшим воротам / баррикаде. Tank'ам — открыть gate."
                    style="background:#3d1e0a;color:#fdba74;padding:6px;">
                🚪 К воротам (30💎)
            </button>
            <button class="extra-btn bnr-det-btn" data-det-act="hero.detach"
                    data-det-cost="10"
                    title="Выйти из строя в собственный отряд. После — выбери одну из 4 команд выше. Также авто-detach при любой из выше команд."
                    style="background:#2d2d2f;color:#d1d5db;padding:6px;">
                🚶 Отделиться (10💎)
            </button>
        </div>`;
    // Bind handlers — каждая кнопка POST'ит свой action.
    slot.querySelectorAll('.bnr-det-btn').forEach(btn => {
        if (btn.dataset.detAct) btn.dataset.bnrCd = btn.dataset.detAct;   // кулдаун на кнопке
        btn.addEventListener('click', async (ev) => {
            const act = btn.dataset.detAct;
            const cost = parseInt(btn.dataset.detCost || '0', 10);
            if (!act) return;
            // Sprint 5.32 (LOG-4) — log на click чтобы в DevTools видеть
            // последовательность нажатий: '[FE-DET] click hero.detach_charge cost=30'
            console.info('[FE-DET] click', act, 'cost=' + cost);
            await _bannerlordBuyAction(act, { price: cost });
        });
    });
}

// 2026-06-10 — ⚔ боевая стойка (per-viewer): defensive/balanced/aggressive.
// Живёт во вкладке «Бой» (combat-пейн), наполняется из hero-поллинга
// (_bannerlordLastHero). Сдвигает боевой ИИ СВОЕГО бойца (блок/парри vs атака).
// Server-эхо догоняет клик через мод (~сек) → оптимистичная подсветка.
function _renderBannerlordStance() {
    const slot = document.getElementById('bnr-combat-stance-slot');
    if (!slot) return;
    const h = (_bannerlordLastHero && _bannerlordLastHero.hero) || null;
    if (!h) return;
    if (h.combat_stance && h.combat_stance === _bnrOptimisticStance) _bnrOptimisticStance = null;
    const active = _bnrOptimisticStance || h.combat_stance || 'balanced';
    const btn = (key, icon, label, tip) =>
        `<button class="small-btn bnr-stance-btn" data-stance="${key}" title="${label} — ${tip}" `
        + `style="font-size:11px;padding:3px 9px;`
        + `background:${active === key ? '#3d3d1f' : '#2d2d2f'};`
        + `color:${active === key ? '#fbbf24' : '#adadb8'};`
        + `border:1px solid ${active === key ? '#fbbf24' : '#3d3d3f'};">${icon} ${label}</button>`;
    const html = `
        <div style="display:flex;gap:5px;align-items:center;flex-wrap:wrap;
                    padding:6px 8px;background:#18181b;border:1px solid #2d2d2f;border-radius:4px;">
            <span style="font-size:11px;color:#adadb8;font-weight:700;">⚔ Стойка боя:</span>
            ${btn('defensive', '🛡', 'Оборона', 'выше блок/парри, меньше атаки')}
            ${btn('balanced', '⚖', 'Баланс', 'ровно по классу')}
            ${btn('aggressive', '⚔', 'Натиск', 'выше атака, ниже защита')}
        </div>`;
    if (_smartInnerHTML(slot, html)) {
        slot.querySelectorAll('.bnr-stance-btn').forEach(b => {
            b.addEventListener('click', () => {
                const st = b.getAttribute('data-stance');
                _bnrOptimisticStance = st;
                _bannerlordBuyAction('hero.set_combat_stance', { stance: st });
                slot.querySelectorAll('.bnr-stance-btn').forEach(x => {
                    const on = x.getAttribute('data-stance') === st;
                    x.style.background = on ? '#3d3d1f' : '#2d2d2f';
                    x.style.color = on ? '#fbbf24' : '#adadb8';
                    x.style.border = '1px solid ' + (on ? '#fbbf24' : '#3d3d3f');
                });
            });
        });
    }
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
    // Sprint 5.28: цена в крустиках. Backend шлёт config.join_price (default 1000).
    const joinPrice = (cfg.join_price ?? 1000);
    const joinPriceText = joinPrice.toLocaleString('ru-RU');

    // Status badge
    if (state.status === 'running') {
        badge.textContent = `⚔️ раунд ${(state.current_round || 0) + 1}/4`;
        badge.style.color = '#fbbf24';
    } else {
        badge.textContent = `idle (${queue.length})`;
        badge.style.color = '#9ca3af';
    }

    if (state.status === 'running') {
        // RUNNING — участники + прогноз победителя (бесплатно)
        const participants = state.participants || [];
        const myBet = data.my_bet;

        let participantsHtml;
        if (myBet) {
            participantsHtml = `
                <div style="font-size:12px;color:#34d399;padding:6px;background:rgba(52,211,153,0.1);border-radius:4px;margin-bottom:6px;">
                    🔮 Твой прогноз: <b>${escapeHtml(myBet.target)}</b>
                </div>`;
        } else {
            participantsHtml = `
                <div style="font-size:11px;color:#adadb8;margin-bottom:4px;">🔮 Угадай победителя — бесплатно, за верный прогноз бонус:</div>
                <div style="display:grid;grid-template-columns:1fr auto;gap:4px;align-items:center;">
                    ${participants.map(p => `
                        <span style="font-size:12px;">⚔️ ${escapeHtml(p)}</span>
                        <button class="extra-btn bnr-predict-btn" data-target="${escapeHtml(p)}"
                                style="font-size:11px;padding:3px 8px;">Прогноз</button>
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

        // Bind prediction buttons
        body.querySelectorAll('.bnr-predict-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const target = btn.getAttribute('data-target');
                _promptBannerlordPredict(target);
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
                  title="${joinPrice > 0 ? `Списывает ${joinPriceText} крустиков` : 'Бесплатно'}"
                  style="margin-top:6px;width:100%;font-size:12px;padding:8px;">
                ⚔️ Вступить в турнир${joinPrice > 0 ? ` (${joinPriceText}💎)` : ' (бесплатно)'}
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
        joinBtn.dataset.bnrCd = 'hero.join_tournament';   // кулдаун на кнопке
        joinBtn.addEventListener('click', () => {
            // Sprint 5.28: backend сам ставит price=1000💎; шлём 0 — он перепишет.
            _bannerlordBuyAction('hero.join_tournament', { price: 0 });
        });
    }
}

const TOURNAMENT_PRIZE_GOLD = 50000;
const TOURNAMENT_ROUND_GOLD = 10000;

function _promptBannerlordPredict(target) {
    // Подтверждение прогноза победителя — бесплатно, без ставки.
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;z-index:9999;';
    overlay.innerHTML = `
        <div style="background:#18181b;border:1px solid #3d3d3f;border-radius:8px;padding:20px;max-width:320px;">
            <h3 style="margin:0 0 12px 0;font-size:14px;color:#efeff1;">🔮 Прогноз: победит @${escapeHtml(target)}?</h3>
            <div style="font-size:11px;color:#adadb8;margin-bottom:12px;">
                Бесплатно — крустики не тратятся. Угадаешь победителя турнира — получишь бонус.
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                <button class="extra-btn" id="bnr-predict-confirm" style="font-size:12px;padding:8px;">Сделать прогноз</button>
                <button class="extra-btn" id="bnr-predict-cancel" style="font-size:12px;padding:8px;background:#3d3d3f;">Отмена</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);

    document.getElementById('bnr-predict-confirm').addEventListener('click', () => {
        overlay.remove();
        _bannerlordBuyAction('tournament.bet', { target });
    });
    document.getElementById('bnr-predict-cancel').addEventListener('click', () => overlay.remove());
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
        _bnrNotifyRefunds(data.recent_refunds);   // 2026-06-10 — тост причины отказа

        // FLICKER-FIX v5 (2026-05-28): MINIMAL struct hash — только truly rare
        // events. Раньше включал location (меняется при движении по карте
        // → body rewrite → sub-slot DIVs (workshops/caravans/etc.) становятся
        // empty → sub-loader fetch 100-500ms → 0.2-0.5 сек blank flicker).
        //
        // Now hash = ONLY то что реально нужно re-render body:
        //   - has_hero    (adopted ли)
        //   - level       (level-up rare)
        //   - clan_id     (joined/left clan)
        //   - kingdom_id  (joined/left kingdom)
        //   - alive       (death/respawn)
        //   - prisoner    (capture/release)
        //
        // Excluded: name (set on adopt + never changes), culture (same),
        // location (changes constantly), retinue_n (changes часто), gold/hp
        // (every poll). Эти будут stale в header'е до next struct change —
        // НО они уже видны актуально в sub-slot панелях или modal'ах.
        const _h = data.hero || {};
        const _structHash = JSON.stringify({
            has_hero:    data.has_hero,
            level:       _h.level,
            clan_id:     _h.clan_id,
            kingdom_id:  _h.kingdom_id,
            alive:       _h.is_alive,
            prisoner:    _h.is_prisoner,
            // 2026-06-01 FIX — экипировка не входила в hash → смена гира
            // (класс/апгрейд/предмет) не меняла _structChanged → тело не
            // перерисовывалось → снаряжение залипало. Сигнатура slot:item:tier:value
            // меняется ТОЛЬКО при смене гира (не каждый poll → flicker не
            // возвращается; sub-слоты сохраняет _preserveSlots).
            equip: Object.keys(data.equipment || {}).sort().map(s => {
                const it = data.equipment[s] || {};
                return `${s}:${it.item_id || ''}:${it.tier}:${it.item_value || ''}`;
            }).join('|'),
        });
        const _structChanged = (body._bnrLastStruct !== _structHash);
        body._bnrLastStruct = _structHash;

        // FLICKER-FIX v5 PRESERVE: на body innerHTML rewrite сохраняем
        // существующее содержимое sub-slot'ов чтобы избежать blank gap
        // во время sub-loader fetch.
        const _preserveSlots = (cb) => {
            if (!_structChanged) return cb(false);
            // Capture current sub-slot innerHTMLs (если они уже rendered).
            const slotIds = ['bnr-daily-slot','bnr-heir-slot','bnr-family-slot',
                'bnr-vassals-slot','bnr-party-orders-slot','bnr-diplo-slot',
                'bnr-ransom-slot','bnr-workshops-slot','bnr-fiefs-slot',
                'bnr-caravans-slot','bnr-caravan-rescue-slot','bnr-inheritance-slot',
                'bnr-clan-mgmt-slot','bnr-kingdom-mgmt-slot','bnr-progression-slot','bnr-gender-slot',
                'bnr-profile-slot','bnr-dynasty-locked-actions'];
            const snapshot = {};
            for (const id of slotIds) {
                const el = document.getElementById(id);
                if (el && el.innerHTML) snapshot[id] = el.innerHTML;
            }
            const result = cb(true);
            // Restore sub-slot innerHTMLs back into fresh DOM.
            for (const id of Object.keys(snapshot)) {
                const el = document.getElementById(id);
                if (el && !el.innerHTML) {
                    el.innerHTML = snapshot[id];
                    // 2026-06-02 FIX — innerHTML-restore создаёт НОВЫЙ DOM →
                    // click-хендлеры суб-лоадеров (sell/buy караванов/мастерских,
                    // party-orders, daily…) ТЕРЯЮТСЯ. _smartInnerHTML потом
                    // пропускал rebind (тот же html в кэше + innerHTML.length>0)
                    // → кнопки мёртвые (продажа не работала). Сбрасываем кэш →
                    // следующий poll суб-лоадера перерисует И ПЕРЕПРИВЯЖЕТ.
                    delete _smartHtmlCache[id];
                }
            }
            return result;
        };

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

        // Sprint 5.29 BLT-parity #7: dead hero → show heir succession UI
        // вместо stats. Click "Возрождение" → POST hero.create → new wanderer.
        if (h && h.is_alive === false) {
            const iter = h.iteration || 1;
            const nextIter = iter + 1;
            body.innerHTML = `
                <div style="text-align:center;padding:14px;color:#adadb8;font-size:13px;">
                    <div style="font-size:48px;margin-bottom:8px;">💀</div>
                    <div style="font-weight:700;color:#f87171;margin-bottom:4px;">
                        Поколение ${iter} мёртв
                    </div>
                    <div style="font-size:11px;margin-bottom:14px;color:#9ca3af;">
                        ${escapeHtml(h.display_name || '[BLink] ' + (window.userLogin || ''))}
                        ${h.clan_name ? `(${escapeHtml(h.clan_name)})` : ''}
                    </div>
                    <div style="font-size:12px;margin-bottom:8px;color:#fbbf24;">
                        🕯️ Возродиться героем поколения ${nextIter} (бесплатно)
                    </div>
                    <div style="font-size:10px;color:#6b7280;margin-bottom:10px;">
                        Новый герой родится с 0 уровня, без снаряжения. Имя то же.
                    </div>
                    <button class="extra-btn" id="bnr-heir-respawn"
                            style="font-size:12px;padding:8px 14px;
                                   background:#7c2d12;color:#fbbf24;font-weight:700;">
                        🕯️ Возродить героя
                    </button>
                </div>`;
            const respawnBtn = document.getElementById('bnr-heir-respawn');
            if (respawnBtn) {
                respawnBtn.addEventListener('click', async () => {
                    if (!await _bnrConfirm(
                        'Возродить героя? Новый wanderer от 0 уровня (имя то же).',
                        '🕯️ Возродить'
                    )) return;
                    _bannerlordBuyAction('hero.create', { price: 0 });
                });
            }
            return;
        }

        // Sprint 5.32 — 4-state badge:
        //   💚 жив        — IsAlive=true, IsWounded=false (active)
        //   🟡 ранен в бою — IsAlive=true, IsWounded=true (KO'd, восстановится)
        //   ⛓ в плену     — IsPrisoner=true (orthogonal flag, может быть alive+prisoner)
        //   💀 мёртв      — IsAlive=false (permanent death, триггер "Создать нового")
        let aliveBadge;
        if (!h.is_alive) {
            aliveBadge = `<span style="color:#f87171;">💀&nbsp;мёртв</span>`;
        } else if (h.is_wounded) {
            aliveBadge = `<span style="color:#fbbf24;" title="Ранен в бою — оживёт через несколько дней. Не permanent death.">🟡&nbsp;ранен</span>`;
        } else {
            aliveBadge = `<span style="color:#34d399;">●&nbsp;жив</span>`;
        }
        const prisonerBadge = h.is_prisoner
            ? ` <span style="color:#fbbf24;">⛓ в плену</span>` : '';

        // Top-5 skills
        const topSkills = (data.skills || []).slice(0, 5).map(s =>
            `<div style="display:flex;justify-content:space-between;font-size:11px;padding:1px 0;">
                <span>${escapeHtml(BNR_SKILL_LABELS_RU[s.skill_key] || s.skill_key)}</span>
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
        // 2026-06-07 — строки-инфо (read-only). Управление кланом/королевством —
        // во вкладке «Династия» (секции/locked-actions), модалок больше нет.
        const clanLabel = `<span>${clanName}</span>`;
        const kingdomLabel = `<span>${kingdomName}</span>`;
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
                    data-bnr-cd="hero.upgrade_gear"
                    data-bnr-cost="0,${_cost}"
                    title="Улучшить снаряжение T${gearTier} → T${_nextTier}. Списать ${_cost.toLocaleString('ru-RU')}💰 динаров у героя."
                    style="font-size:10px;padding:2px 8px;margin-left:6px;
                           background:#3d3d3f;color:#fbbf24;">
                ⚒ T${_nextTier} (${_formatBigGold(_cost)})
            </button>`;
        } else {
            _gtierBtn = '<span style="color:#9ca3af;font-size:10px;margin-left:6px;">сначала класс</span>';
        }
        // 2026-05-29 — «переформировать снаряжение» (BLT ReequipInsteadOfUpgrade):
        // ре-ролл всех слотов на ТЕКУЩЕМ тире (бесплатно), фикс кривой/залипшей
        // экипировки. Доступно только при выбранном классе, в т.ч. на MAX.
        const _reequipBtn = _hasClass
            ? `<button class="small-btn" id="bnr-reequip-btn"
                    data-bnr-cd="hero.reequip_gear"
                    title="Переформировать снаряжение: ре-ролл всех слотов на текущем тире (T${gearTier || 0}). Бесплатно — фикс если экипировка кривая/залипла. Турнирные призы и крафт сохраняются."
                    style="font-size:10px;padding:2px 6px;margin-left:4px;
                           background:#2d3a2d;color:#86efac;">
                🔄 пересбор
            </button>`
            : '';
        const gearTierLabel = _gtierText + _gtierBtn + _reequipBtn;

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
            : `<span style="color:#efeff1;" title="Броня по зонам: 🪖 голова · 👕 тело · 👢 ноги · 💪 руки">🪖${totalHead} 👕${totalBody} 👢${totalLeg} 💪${totalArm}</span>` +
              (armorAvgTier ? ` <span style="color:#fbbf24;">~T${armorAvgTier}</span>` : '');

        // Sprint 5.32 — content split на 4 panes + always-visible header.
        // Header (#hero-body): name + status + culture + location (compact).
        // Sprint 5.33 FLICKER-FIX (2026-05-28) — _smartInnerHTML skip'ит
        // identical rewrite; результат используется чтобы не re-bind'ить
        // listeners на тех же nodes (избегаем double-handlers).
        const _bnrHeroHtml = `
            <div style="font-weight:700;font-size:14px;line-height:1.2;
                        overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                ${escapeHtml(h.display_name || '—')}
            </div>
            <div style="font-size:11px;color:#adadb8;margin-top:2px;">
                ${aliveBadge}${prisonerBadge}${h.culture ? ' · ' + escapeHtml(h.culture) : ''}${h.location ? ' · 📍 ' + escapeHtml(h.location) : ''}
            </div>`;

        // 🛡 Герой pane — stats grid + daily reward + profile button.
        // Sprint 5.32 (revised) — battle banner перенесён в Combat pane.
        // Sprint 5.32 #46 — daily reward slot для виральности.
        // Render UNCONDITIONAL (gold/HP/level updates каждый poll) — но
        // bindings для clan-row/kingdom-row/upgrade-btn (внизу) тоже
        // unconditional, потому что DOM-узлы recreated на каждом poll.
        // FLICKER-FIX v7 (2026-05-29): РАЗДЕЛЯЕМ volatile stats grid и stable
        // sub-slots. Раньше `paneHero.innerHTML = ...` переписывался КАЖДЫЙ
        // poll (gold/level live-updates), что УНИЧТОЖАЛО 12 sub-slot DIV'ов
        // (workshops/caravans/fiefs/party-orders/heir/...) → они становились
        // empty → async sub-loader fetch 100-500ms → видимый blank flicker
        // каждые 8s ("пропадают и снова загружаются"). _preserveSlots не
        // помогал т.к. он обёрнут вокруг записи в #hero-body (header), а слоты
        // живут в ОТДЕЛЬНОМ #bnr-pane-hero-body.
        //
        // Теперь: skeleton (slots + profile button) строится ОДИН раз и больше
        // не пересоздаётся; каждый poll обновляется только #bnr-pane-hero-stats
        // через _smartInnerHTML (dedupe → repaint лишь при изменении gold/etc).
        const paneHero = document.getElementById('bnr-pane-hero-body');
        if (paneHero) {
            // (1) Build stable skeleton ОДИН раз — sub-slots НЕ пересоздаются.
            if (!document.getElementById('bnr-pane-hero-stats')) {
                paneHero.innerHTML = `
                    <div style="padding:6px;">
                        <div id="bnr-pane-hero-stats" style="margin-bottom:10px;"></div>
                        <div id="bnr-daily-slot" style="margin-bottom:8px;"></div>
                        <div id="hero-class-picker-slot" style="margin-bottom:10px;"></div>
                        <details data-bnr-details="hero-progression" ${_bnrDetailsAttr('hero-progression')} style="margin-bottom:6px;">
                            <summary style="font-size:12px;padding:8px;box-sizing:border-box;cursor:pointer;
                                       background:#1e3a5f;color:#93c5fd;font-weight:700;list-style:none;
                                       border:1px solid #1e40af;border-radius:4px;">
                                🎯 Прогрессия — скиллы / фокусы / атрибуты
                            </summary>
                            <div id="bnr-progression-slot" style="padding-top:6px;"></div>
                        </details>
                        <details data-bnr-details="hero-gender" ${_bnrDetailsAttr('hero-gender')} style="margin-top:6px;">
                            <summary style="font-size:12px;padding:8px;box-sizing:border-box;cursor:pointer;
                                       background:#2a1a30;color:#f472b6;font-weight:700;list-style:none;
                                       border:1px solid #7c3aed;border-radius:4px;">
                                ⚧ Сменить пол
                            </summary>
                            <div id="bnr-gender-slot" style="padding-top:6px;"></div>
                        </details>
                    </div>`;
                // 2026-05-31 IA-реорг: класс/прогрессия переехали в «Герой»,
                // династия/экономика — в отдельную вкладку «Династия» (build-once
                // skeleton ниже). Кнопка прогрессии в стабильном skeleton → bind
                // ОДИН раз (не в if(_bnrChanged) — там был бы дубль-handler).
                // 2026-06-07 — Прогрессия теперь inline-секция (loadBannerlordProgression),
                // наполняется в poll'е (sub-loader ниже). Кнопка-модалка убрана.
                // 2026-06-07 — смена пола теперь inline-секция (loadBannerlordGender),
                // наполняется в poll'е (sub-loader ниже). Кнопка-модалка убрана.
            }
            // (2) Volatile stats grid — обновляется каждый poll, но это
            //     ИЗОЛИРОВАННЫЙ под-элемент; sub-slots рядом не трогаются.
            const _statsHtml = `
                <div style="display:grid;grid-template-columns:auto 1fr;gap:6px 10px;
                            font-size:12px;align-items:center;">
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
                    <span style="color:#adadb8;">🛡 Броня:</span>
                    <span>${armorLabel}</span>
                    ${(h.tournament_wins || 0) > 0 ? `
                        <span style="color:#adadb8;">🏆 Турниры:</span>
                        <span style="color:#fbbf24;font-weight:700;" title="Wins за всю историю канала. Note: ×0.7-0.85 HP penalty в next турнире — анти-сноубол.">${h.tournament_wins}${h.tournament_wins >= 3 ? ' <span style="font-size:10px;color:#fb923c;">ветеран</span>' : ''}</span>
                    ` : ''}
                </div>`;
            // (3) Rebind clan/kingdom/upgrade ТОЛЬКО когда grid реально
            //     перерисован (новые DOM nodes). _smartInnerHTML returns true
            //     лишь при изменении → нет дублей listener'ов.
            const _statsSlot = document.getElementById('bnr-pane-hero-stats');
            if (_smartInnerHTML(_statsSlot, _statsHtml)) {
                document.getElementById('bnr-inline-upgrade-btn')?.addEventListener('click', () => {
                    _bannerlordBuyAction('hero.upgrade_gear', {});
                });
                document.getElementById('bnr-reequip-btn')?.addEventListener('click', () => {
                    _bannerlordBuyAction('hero.reequip_gear', {});
                });
            }
        }

        // 🏰 Династия pane — клан/королевство/семья/экономика/политика.
        // BUILD-ONCE skeleton (как Hero): 11 sub-slot'ов живут стабильно,
        // sub-loaders наполняют их каждый poll. НЕ в if(_bnrChanged) — иначе
        // вернётся flicker (см. FLICKER-FIX v7 выше).
        // 2026-06-02 (CLAN-GATE) — вся Династия завязана на клане → вкладка
        // работает ТОЛЬКО у ГЛАВЫ клана. Не лидер (бесклановый ИЛИ участник
        // чужого клана) → тело заперто с CTA «Создать клан» (ключ от вкладки).
        // is_leader приходит в clan_info (мод HeroStateSync → clan_info_json →
        // h.clan_info). Маркеры bnr-dynasty-locked / -built взаимно затирают друг
        // друга при смене состояния (создал/потерял клан) — innerHTML перезапись.
        const isClanLeader = !!(h.clan_info && h.clan_info.is_leader);
        const paneDyn = document.getElementById('bnr-pane-dynasty-body');
        if (paneDyn) {
            if (!isClanLeader && !document.getElementById('bnr-dynasty-locked')) {
                paneDyn.innerHTML = `
                    <div id="bnr-dynasty-locked" style="padding:14px 10px;text-align:center;">
                        <div style="font-size:30px;margin-bottom:6px;">🏰🔒</div>
                        <div style="font-size:13px;color:#efeff1;font-weight:700;margin-bottom:6px;">
                            Династия — для главы клана
                        </div>
                        <div style="font-size:11px;color:#adadb8;line-height:1.5;margin-bottom:12px;">
                            Клан, королевство, отряды, фьефы, караваны и мастерские —
                            доступны <b style="color:#fbbf24;">главе клана</b>.
                        </div>
                        <div id="bnr-dynasty-locked-actions"></div>
                    </div>`;
                // 2026-06-07 — действия (создать/вступить/покинуть) наполняет
                // loadBannerlordDynastyLockedActions в poll'е (clanless vs member).
            } else if (isClanLeader && !document.getElementById('bnr-dynasty-built')) {
                paneDyn.innerHTML = `
                    <div id="bnr-dynasty-built" style="padding:6px;">
                        <details data-bnr-details="dyn-clan" open style="margin-bottom:8px;">
                            <summary style="font-size:12px;color:#fbbf24;font-weight:700;cursor:pointer;padding:2px 0;">🏰 Клан</summary>
                            <div id="bnr-clan-mgmt-slot" style="padding-top:6px;"></div>
                        </details>
                        <details data-bnr-details="dyn-kingdom" open style="margin-bottom:8px;">
                            <summary style="font-size:12px;color:#93c5fd;font-weight:700;cursor:pointer;padding:2px 0;">👑 Королевство</summary>
                            <div id="bnr-kingdom-mgmt-slot" style="padding-top:6px;"></div>
                        </details>
                        <details data-bnr-details="dyn-upgrades" ${_bnrDetailsAttr('dyn-upgrades')} style="margin-bottom:10px;">
                            <summary style="font-size:12px;color:#c084fc;font-weight:700;cursor:pointer;padding:2px 0;">🏆 Апгрейды клана</summary>
                            <div id="bnr-clan-upgrades-slot" style="padding-top:6px;"></div>
                        </details>
                        <div id="bnr-heir-slot" style="margin-bottom:8px;"></div>
                        <div id="bnr-family-slot" style="margin-bottom:8px;"></div>
                        <div id="bnr-vassals-slot" style="margin-bottom:8px;"></div>
                        <div id="bnr-party-orders-slot" style="margin-bottom:8px;"></div>
                        <div id="bnr-diplo-slot" style="margin-bottom:8px;"></div>
                        <div id="bnr-ransom-slot" style="margin-bottom:8px;"></div>
                        <div id="bnr-workshops-slot" style="margin-bottom:8px;"></div>
                        <div id="bnr-fiefs-slot" style="margin-bottom:8px;"></div>
                        <div id="bnr-caravans-slot" style="margin-bottom:8px;"></div>
                        <div id="bnr-caravan-rescue-slot" style="margin-bottom:8px;"></div>
                        <div id="bnr-inheritance-slot" style="margin-bottom:8px;"></div>
                        <details data-bnr-details="dyn-profile" ${_bnrDetailsAttr('dyn-profile')} style="margin-top:4px;">
                            <summary style="font-size:12px;padding:8px;box-sizing:border-box;cursor:pointer;
                                       background:#1f1a30;color:#c084fc;font-weight:700;list-style:none;
                                       border:1px solid #5b21b6;border-radius:4px;">
                                🧬 Профиль и семья
                            </summary>
                            <div id="bnr-profile-slot" style="padding-top:6px;"></div>
                        </details>
                    </div>`;
                // 2026-06-07 — Профиль/семья теперь inline-секция (loadBannerlordProfileFamily),
                // наполняется в poll'е (sub-loader в isClanLeader-блоке). Кнопка-модалка убрана.
                // 2026-06-07 — lazy-render дерева апгрейдов при раскрытии секции
                // (skeleton строится ОДИН раз → bind toggle тоже один раз, без дублей).
                const _upDet = paneDyn.querySelector('[data-bnr-details="dyn-upgrades"]');
                if (_upDet) {
                    _upDet.addEventListener('toggle', () => { if (_upDet.open) _renderClanUpgradesInline(); });
                    if (_upDet.open) _renderClanUpgradesInline();
                }
            }
        }

        // FLICKER-FIX v5: structural change wrapped в _preserveSlots — sub-slot
        // content NOT destroyed во время body rewrite.
        const _bnrChanged = _preserveSlots(() =>
            _structChanged && _smartInnerHTML(body, _bnrHeroHtml));
      if (_bnrChanged) {
        // 🎒 Инвентарь pane — Экипировка + Свита + Достижения + Кузница + Аукционы.
        const paneInv = document.getElementById('bnr-pane-inventory-body');
        if (paneInv) paneInv.innerHTML = `
            <div style="padding:6px;">
                <div style="font-size:12px;color:#fbbf24;font-weight:700;margin-bottom:6px;">
                    🎽 Экипировка
                </div>
                <div style="margin-bottom:10px;">${eqHtml}</div>
                <div id="bnr-retinue-slot" style="margin-bottom:10px;"></div>
                <details data-bnr-details="inv-achievements" ${_bnrDetailsAttr('inv-achievements')} style="margin-bottom:6px;">
                    <summary style="font-size:12px;padding:8px;box-sizing:border-box;cursor:pointer;
                               background:#3a2a0a;color:#fbbf24;font-weight:700;list-style:none;
                               border:1px solid #92400e;border-radius:4px;">
                        🏆 Достижения
                    </summary>
                    <div id="bnr-achievements-slot" style="padding-top:6px;"></div>
                </details>
                <details data-bnr-details="inv-forge" ${_bnrDetailsAttr('inv-forge')} style="margin-bottom:6px;">
                    <summary style="font-size:12px;padding:8px;box-sizing:border-box;cursor:pointer;
                               background:#2a1a0a;color:#fb923c;font-weight:700;list-style:none;
                               border:1px solid #9a3412;border-radius:4px;">
                        🔨 Кузница (трофеи)
                    </summary>
                    <div id="bnr-forge-slot" style="padding-top:6px;"></div>
                </details>
            </div>`;

        // ⚔ Бой pane — battle banner (HP / kills / gold / XP) + buffs + powers + summon.
        // Sprint 5.32 (revised) — battle banner здесь (раньше был в Hero pane).
        // Это первая видимая вкладка → viewer сразу видит боевой статус.
        const paneCombat = document.getElementById('bnr-pane-combat-body');
        if (paneCombat) paneCombat.innerHTML = `
            <div style="padding:6px;">
                <div id="bnr-battle-banner-slot"></div>
                <div id="bnr-combat-stance-slot" style="margin-bottom:8px;"></div>
                <div id="bnr-buff-hud"></div>
                <div id="bnr-active-powers-slot"></div>
                <div id="bnr-summon-slot"></div>
                <div id="bnr-detachment-slot" style="margin-top:10px;"></div>
            </div>`;

        // 2026-05-31 IA-реорг: класс-picker + кнопка прогрессии переехали в Hero
        // pane (build-once skeleton выше); бывший progression pane стал
        // «Династией» (build-once skeleton выше). Здесь больше ничего не строим.
        // Sprint M23 — render свита под equipment.
        _bannerlordLastRetinue = data.retinue || [];
        _renderRetinue(_bannerlordLastRetinue);
        renderBannerlordClassPicker();
      }  // ← end of `if (_bnrChanged)` for panes + retinue + class picker
        // ↓ Sub-loaders ALWAYS run — они дедуплируются сами через _smartInnerHTML
        //   на своих slot'ах. Видят свежие данные даже когда hero pane не сменился.
        // Sprint 5.32 #46 — refill daily slot (recreated на re-render Hero pane).
        loadBannerlordDaily();
        // 2026-06-10 — боевая стойка (в combat-пейне), наполняется из hero-поллинга.
        _renderBannerlordStance();
        // 2026-06-07 — Прогрессия (скиллы/фокусы/атрибуты) live-секция в Hero pane.
        loadBannerlordProgression();
        // 2026-06-07 — Смена пола — inline-секция в Hero pane.
        loadBannerlordGender();
        // 2026-06-02 (CLAN-GATE) — sub-loaders Династии грузим ТОЛЬКО у главы
        // клана (тело вкладки иначе заперто, грузить нечего). loadBannerlordDaily
        // выше — Hero-pane, НЕ гейтим.
        if (isClanLeader) {
            // 2026-06-07 — инлайн-секции клан/королевство (live-инфо + manage-кнопка).
            loadBannerlordClanMgmt();
            loadBannerlordKingdomMgmt();
            // 2026-06-07 — Профиль/семья (брак/дети) — inline-секция в Династии.
            loadBannerlordProfileFamily();
            // Sprint 5.32 (BLT-parity FE-M2) — refill heir slot.
            loadBannerlordHeirs();
            // Sprint 5.33 (BLT-parity FAM) — Family section (children + proposals).
            loadBannerlordFamily();
            // Sprint 5.33 (BLT-parity VAS) — Vassal sub-clans section.
            loadBannerlordVassals();
            // Sprint 5.33 (BLT-parity SIEGE) — Party orders section.
            loadBannerlordPartyOrders();
            // Sprint 5.33 (BLT-parity DIPLO) — Kingdom politics + ransom pool.
            loadBannerlordDiplomacy();
            loadBannerlordRansomPool();
            // Sprint 5.33 (BLT-parity SHOP) — Workshops passive income panel.
            loadBannerlordWorkshops();
            // Sprint 5.33 (BLT-parity FIEF) — Fief tribute passive income.
            loadBannerlordFiefs();
            // Sprint 5.33 (BLT-parity CARAVAN) — Mobile passive income trilogy closer.
            loadBannerlordCaravans();
            loadBannerlordCaravanRescues();
            // Sprint 5.33 (BLT-parity HERITAGE) — Inheritance log.
            loadBannerlordInheritance();
        } else {
            // 2026-06-07 — не-лидер: locked-state actions (clanless создать/вступить,
            // участник — покинуть). Заменяет вход через Hero-row модалку.
            loadBannerlordDynastyLockedActions();
        }
        // Sprint 5.5: immediately repaint battle banner из cache чтобы
        // не было 0-2s gap'a после hero re-render.
        if (_bannerlordBattle) _renderBannerlordBattleBanner(_bannerlordBattle);
      if (_bnrChanged) {  // ← bindings ТОЛЬКО при actual DOM rewrite (избежать
                          //   double-handlers — addEventListener allows duplicates).
        // Sprint 5.5: bind toggle persistence для <details> (skills/equipment/retinue)
        _bnrBindDetailsPersistence();
        // 2026-05-31: progression-btn теперь в build-once Hero skeleton → биндится
        // там ОДИН раз (здесь повторно НЕ биндим, иначе дубль-handler).
        // Sprint 5.27a: profile modal — FLICKER-FIX v7: binding перенесён в
        // skeleton-build (paneHero выше). Кнопка живёт в стабильном skeleton,
        // биндится ОДИН раз → здесь повторно НЕ биндим (избегаем дублей).
        // 2026-06-07 — Достижения / Кузница теперь inline-секции (lazy-render при
        // раскрытии <details>). Бинды в if(_bnrChanged) → DOM свежий на каждом rewrite.
        const _achDet = document.querySelector('[data-bnr-details="inv-achievements"]');
        if (_achDet) {
            _achDet.addEventListener('toggle', () => { if (_achDet.open) _renderAchievementsInline(); });
            if (_achDet.open) _renderAchievementsInline();
        }
        const _forgeDet = document.querySelector('[data-bnr-details="inv-forge"]');
        if (_forgeDet) {
            _forgeDet.addEventListener('toggle', () => { if (_forgeDet.open) _renderForgeInline(); });
            if (_forgeDet.open) _renderForgeInline();
        }
        // 2026-05-29 — аукцион (P2P trade) убран из UI ради Twitch-комплаенса.
        // Sprint 5.31 #45b: Boosty admin перенесён на /streamer/dashboard.
        // Sprint 5.11: clan/kingdom row + upgrade-btn bindings перенесены
        // ВЫШЕ за пределы if(_bnrChanged) — DOM пересоздаётся каждый poll.
      }  // ← end of `if (_bnrChanged)` for bindings
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
        console.log('[BNR action]', actionType,
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
        // Sprint 5.32 (BLT-parity FE-M7) — role-gate refuse с понятным icon.
        // Backend ROLE_PRIORITY проверка возвращает required_role / your_role
        // когда viewer'у не хватает прав (e.g. set_gender для не-sub'а).
        // Показываем 🔒 + клейм роли в toast чтобы это не выглядело как обычная
        // ошибка ("действие не выполнено") а как **gate** (есть путь — стань sub).
        if (!result.success && result.required_role) {
            const roleLabel = {
                subscriber:   '⭐ Tier 1+ sub',
                moderator:    '🛡 модераторов',
                broadcaster:  '👑 стримера',
            }[result.required_role] || result.required_role;
            toastMsg = `🔒 ${toastMsg}`;
            // Sprint 5.32 (LOG-4) — categorized prefix [FE-GATE] для grep'а.
            console.warn('[FE-GATE]', actionType,
                         `required=${result.required_role} your=${result.your_role}`);
        }
        // Sprint 5.32 (LOG-4) — log на idempotent_replay (H1) чтобы видно
        // когда retry реально срабатывает (дебаг network blip / proxy issues).
        if (result.idempotent_replay) {
            console.info('[FE-IDEM] retry hit', actionType,
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
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
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
