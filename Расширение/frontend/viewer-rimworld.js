// viewer-rimworld.js — RimWorld-специфичный код, вынесенный из viewer.js (ROADMAP 2.4).
//
// Грузится ПОСЛЕ viewer.js — использует его CORE-глобалы (API_URL, safeInterval,
// showNotification, и т.д.), которые к моменту парса этого файла уже определены.
// Поведение НЕ менялось — только перенос (split 7k-строчного viewer.js на
// core / bannerlord / rimworld). По одному куску за сессию.
//
// Чанк 1 (2026-06-13): RimWorld online-status + identity-запрос.

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


// ===== RIMWORLD ИВЕНТЫ (магазин событий) — split чанк 2 (2026-06-13) =====
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
                <div class="shop-item-icon" style="font-size:22px;">${escapeHtml((ev.name||'').split(' ')[0])}</div>
                <div class="shop-item-info">
                    <div class="shop-item-name">${escapeHtml((ev.name||'').replace(/^\S+\s*/, ''))}</div>
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
                headers: {'Content-Type':'application/json', 'X-Twitch-JWT': authToken || ''},
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
