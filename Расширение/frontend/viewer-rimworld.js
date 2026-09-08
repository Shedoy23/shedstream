// viewer-rimworld.js — RimWorld-специфичный код, вынесенный из viewer.js (ROADMAP 2.4).
//
// Грузится ПОСЛЕ viewer.js — использует его CORE-глобалы (API_URL, safeInterval,
// showNotification, и т.д.), которые к моменту парса этого файла уже определены.
// Поведение НЕ менялось — только перенос (split 7k-строчного viewer.js на
// core / bannerlord / rimworld). По одному куску за сессию.
//
// Чанк 1 (2026-06-13): RimWorld online-status + identity-запрос.

// ===== ЦЕНЫ RIMWORLD — ТОЛЬКО С СЕРВЕРА =====
// Цены жили копиями во фронте, и 24.07 копии разошлись: кнопка удаления черты
// рисовала 2000 крустиков при реальных 300. Бэкенд с тех пор отдаёт их одним
// местом — /api/rimworld/config — но фронт эндпоинт так и не подключил, и все
// числа оставались зашитыми в разметке и в pawn.js (найдено владельцем 05.09).
// Фронт замерзает на CDN Twitch до следующего ревью, поэтому менять цену можно
// только на сервере, а рисовать — только то, что он прислал. Зашитые значения
// остаются лишь как запасные, если конфиг не доехал.
let rimworldPrices = null;

function rimworldPrice(key, fallback) {
    const raw = rimworldPrices ? rimworldPrices[key] : null;
    if (raw == null || raw === '') return fallback;
    const v = Number(raw);
    return Number.isFinite(v) ? v : fallback;
}

async function loadRimworldPrices() {
    try {
        const r = await fetch(`${API_URL}/api/rimworld/config`);
        if (!r.ok) return;
        rimworldPrices = await r.json();
        applyRimworldPriceLabels();
        if (typeof loadMyPawn === 'function') loadMyPawn();
    } catch (e) {
        // Молча остаёмся на запасных числах: без цен панель полезнее, чем пустая.
    }
}

// Подписи кнопок, которые лежат в разметке обеих оболочек, а не рисуются JS.
function applyRimworldPriceLabels() {
    const heal = document.getElementById('heal-pawn-btn');
    if (heal) heal.innerHTML = `<span>💊</span> Лечить (${rimworldPrice('heal_cost', 150)}💎)`;
    const res = document.getElementById('btn-resurrect');
    if (res) res.innerHTML = `<span>✨</span> Воскресить (${rimworldPrice('resurrect_cost', 500)}💎)`;
    const create = document.getElementById('create-pawn-btn');
    if (create) create.textContent = `✨ Создать пешку (${rimworldPrice('spawn_cost', 200)}💎)`;
}

// ===== RIMWORLD ONLINE STATUS =====
let rimworldOnline = false;

async function checkRimworldStatus() {
    try {
        const r = await fetch(`${API_URL}/api/rimworld/status`, {
            headers: {'X-Twitch-JWT': authToken || ''}
        });
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

// Module lifecycle. Раньше интервал запускался сразу при парсе файла, а core
// безусловно грузил pawn/shop/events после auth. Поэтому Bannerlord-панель весь
// стрим опрашивала неактивный RimWorld и плодила 401. Теперь RimWorld вообще не
// делает сетевых запросов, пока backend не вернул active_module='rimworld'.
window._startRimworldPolling = function _startRimworldPolling() {
    if (window._rimworldStatusInterval) return;

    checkRimworldStatus();
    loadRimworldPrices();
    loadColonists();
    loadMyPawn();
    loadShopCatalog();
    loadRimworldEvents();
    window._intervalRimStatus = window._rimworldStatusInterval =
        safeInterval(checkRimworldStatus, 30000);
};

window._stopRimworldPolling = function _stopRimworldPolling() {
    if (window._rimworldStatusInterval) {
        clearInterval(window._rimworldStatusInterval);
        window._rimworldStatusInterval = null;
        window._intervalRimStatus = null;
    }
    if (_pawnRefreshTimer) {
        clearInterval(_pawnRefreshTimer);
        _pawnRefreshTimer = null;
    }
};

// 2026-08-19: игра объявляет себя ядру сама (viewer-registry.js).
ShedLink.registerGame('rimworld', {
    rootId: 'rimworld-content',
    title:  '🧬 RimWorld',
    start:  function () { window._startRimworldPolling(); },
    stop:   function () { window._stopRimworldPolling(); },
});

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
        const r = await fetch(`${API_URL}/api/rimworld/events`, {
            headers: {'X-Twitch-JWT': authToken || ''}
        });
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
    if (_activeIntegrationModule !== 'rimworld') return;
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


// ===== ЧЕРТЫ / ГЕНЫ МАРАКЕРА — split чанк 3 (2026-06-13) =====
// Вызываются из shop.js (buyTrait/buyGene) и pawn.js (removeMyTrait/removeMyGene)
// через рантайм-клики; viewer-rimworld.js грузится последним, функции доступны.
async function removeMyTrait(traitDef, degree, label) {
    const removeCost = rimworldPrice('trait_remove_cost', 300);
    showConfirm('🗑️ Удалить черту', `Удалить черту <b>${escapeHtml(label)}</b> за <b style="color:#f87171;">${removeCost}💎</b>?`, async () => {
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
    // Цена приходит с бэка. Раньше на пустом ответе подставлялась выдуманная
    // (500💎) — зритель видел цену, которой не существует, и списывалась другая.
    // Нет цены → честно говорим «уточняем», а не врём числом.
    const hasPrice = (price != null && price !== '');
    showConfirm('✨ Купить черту', `Добавить черту <b>${escapeHtml(label)}</b> ${hasPrice ? `за <b style="color:#9147ff;">${price}💎</b>` : "<b>(цену уточняем)</b>"}?`, async () => {
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
    // Цена приходит с бэка. Раньше на пустом ответе подставлялась выдуманная
    // (5000💎) — зритель видел цену, которой не существует, и списывалась другая.
    // Нет цены → честно говорим «уточняем», а не врём числом.
    const hasPrice = (price != null && price !== '');
    showConfirm('🧬 Купить ген', `Установить ген <b>${escapeHtml(geneLabel)}</b> ${hasPrice ? `за <b style="color:#9147ff;">${price}💎</b>` : "<b>(цену уточняем)</b>"}?`, async () => {
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
    const removeCost = rimworldPrice('gene_remove_cost', 3000);
    const overriddenNote = isOverridden
        ? '<br><span style="color:#f59e0b;font-size:11px;">⚠️ Ген сейчас подавлен другим геном, но будет удалён из генома.</span>'
        : '';
    showConfirm('🗑️ Удалить ген',
        `Удалить ген <b>${escapeHtml(geneLabel)}</b> за <b style="color:#f87171;">${removeCost}💎</b>?${overriddenNote}`,
        async () => {
            try {
                const r = await fetch(`${API_URL}/api/rimworld/remove-gene`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || ''},
                    body: JSON.stringify({ username: userLogin, def_name: geneDef, label: geneLabel })
                });
                const d = await r.json();
                showNotification(d.message, d.success ? 'success' : 'error');
            if (d.success) { loadUserData(); startPawnRefresh(); }
            } catch(e) { showNotification('❌ Ошибка', 'error'); }
        }
    );
}


// ===== RIMWORLD: rich-text, навыки, создание пешки — split чанк 4 (2026-06-13) =====

// RimWorld rich-text → HTML: теги <color=#hex>текст</color>, <b>,<i>,<size=N>.
// Зовётся из pawn.js при рендере. escapeHtml — core (viewer.js).
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

// ===== СОЗДАНИЕ ПЕШКИ =====
function showCreatePawnModal() {
    const balance = parseInt(document.getElementById('points')?.textContent || '0');
    const spawnCost = rimworldPrice('spawn_cost', 200);
    if (balance < spawnCost) {
        showNotification(`❌ Нужно ${spawnCost}💎 для создания пешки!`, 'error');
        return;
    }
    showConfirm('✨ Создание пешки', `Создать пешку за <b style="color:#9147ff;">${spawnCost}💎</b>?<br><span style="color:#4ade80;">Ник: ${escapeHtml(userLogin)}</span>`, () => createPawn(userLogin));
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
