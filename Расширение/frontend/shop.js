let shopAllItems = [];
let shopSearchQuery = '';
let shopCurrentFilter = 'all';

async function loadShopCatalog() {
    try {
        const usernameParam = userLogin ? `?username=${encodeURIComponent(userLogin)}` : '';
        const r = await fetch(`${API_URL}/api/rimworld/catalog${usernameParam}`);
        const data = await r.json();
        // Нормализуем поля: API шлёт label/def_name/category, JS ждёт name/def/type
        // neurotrainer → кнопка 🧠 в карточке пешки
        // xenotype     → кнопка 🧬 в карточке пешки
        // gene         → остаётся в магазине (🔬)
        const SHOP_EXCLUDED = new Set(['neurotrainer', 'xenotype']);
        shopAllItems = (data.items || [])
            .filter(item => !SHOP_EXCLUDED.has(item.category || item.type || ''))
            .map(item => {
            const price = item.price || item.cost || 0;
            return {
                ...item,
                name:      item.name      || item.label    || item.def_name || '',
                def:       item.def       || item.def_name || '',
                type:      item.type      || item.category || 'misc',
                price:     price,
                cost:      price,          // renderShop использует item.cost
                slot:      item.slot       || item.tech_level || '',
                trait_def: item.trait_def || (item.category === 'trait' ? item.def_name : undefined),
                degree:    item.degree    || 0,
            };
        });

        const countEl = document.getElementById('shop-count');
        if (countEl) countEl.textContent = shopAllItems.length;

        applyShopFilters();
    } catch (e) {
        const list = document.getElementById('shop-list');
        if (list) list.innerHTML = '<div class="loading">Каталог недоступен — RimWorld не запущен</div>';
    }
}

function filterShop(cat) {
    shopCurrentFilter = cat;
    document.querySelectorAll('.filter-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.cat === cat);
    });
    applyShopFilters();
}

function applyShopFilters() {
    let filtered = shopCurrentFilter === 'all' ? shopAllItems : shopAllItems.filter(i => i.type === shopCurrentFilter);
    if (shopSearchQuery) {
        const q = shopSearchQuery.toLowerCase();
        filtered = filtered.filter(i => (i.name || '').toLowerCase().includes(q) || (i.def || '').toLowerCase().includes(q));
    }
    renderShop(filtered);
}

function onShopSearch(val) {
    shopSearchQuery = val.trim();
    applyShopFilters();
}

function renderShop(items) {
    const container = document.getElementById('shop-list');
    if (!container) return;

    if (!items || items.length === 0) {
        const isAll = shopCurrentFilter === 'all';
        container.innerHTML = `
            <div style="text-align:center;padding:24px;">
                <div style="font-size:36px;margin-bottom:8px;">${isAll ? '🌌' : '📦'}</div>
                <div style="color:#adadb8;font-size:13px;margin-bottom:12px;">
                    ${isAll
                        ? 'Каталог пуст — запусти RimWorld с модом RimLink,<br>предметы загрузятся автоматически'
                        : 'Нет предметов в этой категории'}
                </div>
                ${isAll ? `<button class="buy-btn" data-action="refresh-shop-catalog" style="padding:8px 16px;">🔄 Обновить каталог</button>` : ''}
            </div>
        `;
        return;
    }

    const rawPts = document.getElementById('points')?.textContent || '0';
    const userPoints = parseInt(rawPts.replace(/[^0-9]/g, '')) || 0;

    // Строим карту установленных имплантов из кэша пешки:
    // key = def_name (нижний регистр), value = массив { is_left }
    const installedImplants = {};
    // Импланты живут в hediffs (is_paired/is_left). Фильтруем прямо здесь.
    const _allHediffs = window._lastPawnData?.hediffs || [];
    const pawnImplants = _allHediffs.filter(h => h.is_paired !== undefined && h.def_name);
    pawnImplants.forEach(imp => {
        const key = (imp.def_name || '').toLowerCase();
        if (!installedImplants[key]) installedImplants[key] = [];
        installedImplants[key].push(imp);
    });

    const typeIcons = {
        apparel: '👕',
        weapon: '⚔️',
        implant: '🔧',
        neurotrainer: '🧠',
        trait: '🎭',
        gene: '🧬',
    };

    const typeLabels = {
        apparel: 'Одежда',
        weapon: 'Оружие',
        implant: 'Имплант',
        neurotrainer: 'Навык',
        trait: 'Черта',
        gene: 'Ген',
    };

    let html = '';
    items.forEach(item => {
        const icon = typeIcons[item.type] || '📦';
        const canAfford = userPoints >= item.cost;
        const typeBadge = `<span class="type-badge type-${item.type}">${typeLabels[item.type] || item.type}</span>`;

        // Проверяем установленность (только для имплантов)
        let installedBadge = '';
        let itemStyle = '';
        if (item.type === 'implant') {
            const defKey = (item.def_name || item.def || '').toLowerCase();
            const installed = installedImplants[defKey] || [];
            if (installed.length > 0) {
                // Формируем метки сторон
                const sideLabels = installed.map(imp => {
                    if (imp.is_paired === true) {
                        return imp.is_left === true ? '🤲 Лев.' : imp.is_left === false ? '🤱 Прав.' : '✓';
                    }
                    return '✓';
                }).join(' ');

                installedBadge = `<span style="font-size:10px;background:#1a2a3a;color:#60a5fa;border-radius:4px;padding:2px 6px;margin-left:4px;font-weight:600;">🔊 Установлен ${sideLabels}</span>`;
                // Слегка выделяем строку синеватым фоном
                itemStyle = 'border-left:3px solid #60a5fa;background:rgba(96,165,250,0.06);';
            }
        }

        const tooltipText = item.tooltip || item.description || '';
        html += `
            <div class="shop-item" style="${itemStyle}">
                ${tooltipText ? `<div class="shop-tooltip">${escapeHtml(tooltipText)}</div>` : ''}
                <div class="shop-item-icon">${icon}</div>
                <div class="shop-item-info">
                    <div class="shop-item-name" title="${escapeHtml(item.name || item.def)}">${escapeHtml(item.name || item.def)}</div>
                    <div class="shop-item-desc">${typeBadge} ${item.slot ? '・ ' + item.slot : ''}${installedBadge}</div>
                </div>
                <div class="shop-item-buy">
                    <div class="shop-item-price">${item.cost}💎</div>
                    <button class="buy-btn shop-buy-btn" ${!canAfford ? 'disabled' : ''}
                        data-type="${escapeHtml(item.type || 'item')}"
                        data-def="${escapeHtml(item.def_name || item.def || '')}"
                        data-name="${escapeHtml(item.name || item.def_name || item.def || '')}"
                        data-traitdef="${escapeHtml(item.trait_def || item.def_name || item.def || '')}"
                        data-degree="${item.degree || 0}"
                        data-cost="${item.cost || 0}"
                        data-paired="${item.is_paired ? 'true' : 'false'}">
                        ${canAfford ? 'Купить' : 'Мало 💎'}
                    </button>
                </div>
            </div>
        `;
    });


    container.innerHTML = html;

    // Event delegation — читаем параметры из data-атрибутов, не из onclick
    container.querySelectorAll('.shop-buy-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const type     = btn.dataset.type;
            const def      = btn.dataset.def;
            const name     = btn.dataset.name;
            const traitDef = btn.dataset.traitdef;
            const degree   = parseInt(btn.dataset.degree) || 0;
            const cost     = parseInt(btn.dataset.cost) || 0;
            const paired   = btn.dataset.paired === 'true';
            if (type === 'implant')      buyImplant(def, name, paired);
            else if (type === 'neurotrainer') buyNeurotrainer(def);
            else if (type === 'trait')   buyTrait(traitDef, degree, name, cost);
            else if (type === 'gene')    buyGene(def, name, cost);
            else                         buyShopItem(def);
        });
    });
}

async function buyShopItem(itemDef) {
    await _rwBuyItem(`${API_URL}/api/rimworld/buy-item`, { username: userLogin, item_def: itemDef }, 'buyItem', 3000);
}




async function buyImplant(itemDef, itemName, isPaired) {
    // isPaired передаётся из data-атрибута каталога (is_paired из C#)
    if (!isPaired) {
        // Одиночный имплант — сразу покупаем без выбора стороны
        await _rwBuyItem(`${API_URL}/api/rimworld/buy-implant`, { username: userLogin, item_def: itemDef }, 'buyImplant', 3000);
        return;
    }

    // Парный имплант — определяем занятость сторон через implants[] пешки
    let occupiedLeft = false, occupiedRight = false;
    try {
        const resp = await fetch(`${API_URL}/api/rimworld/my-pawn/${userLogin}`);
        const data = await resp.json();
        if (data.exists) {
            // Импланты хранятся в hediffs (is_paired + is_left)
            const sourceList = data.hediffs || [];
            sourceList.forEach(imp => {
                const sameItem = (imp.def_name || '').toLowerCase() === itemDef.toLowerCase()
                    || (imp.part_def || '').toLowerCase() === itemDef.toLowerCase();
                if (sameItem && imp.is_paired) {
                    if (imp.is_left === true)  occupiedLeft  = true;
                    if (imp.is_left === false) occupiedRight = true;
                }
            });
        }
    } catch(e) { console.error('[implant slot detection]', e); }

    const makeTag = (occupied) => occupied
        ? `<span style="font-size:10px;background:#3a1a1a;color:#f87171;border-radius:4px;padding:2px 7px;margin-top:5px;display:inline-block;">занята</span>`
        : `<span style="font-size:10px;background:#1a2d1a;color:#4ade80;border-radius:4px;padding:2px 7px;margin-top:5px;display:inline-block;">свободна</span>`;

    const modal = document.createElement('div');
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.82);display:flex;align-items:center;justify-content:center;z-index:9999;';
    modal.innerHTML = `
        <div style="background:#1f1f23;border:1px solid #9147ff;border-radius:16px;padding:22px 20px;max-width:280px;width:90%;text-align:center;">
            <div style="font-size:24px;margin-bottom:8px;">🦾</div>
            <div style="font-size:15px;font-weight:700;margin-bottom:4px;">Выбери сторону</div>
            <div style="color:#adadb8;font-size:12px;margin-bottom:20px;">${escapeHtml(itemName || itemDef)}</div>
            <div style="display:flex;gap:10px;margin-bottom:14px;">
                <button id="btn-left" style="flex:1;background:${occupiedLeft?'#2a1a1a':'#1a2d2a'};border:1px solid ${occupiedLeft?'#f87171':'#4ade80'};border-radius:10px;padding:12px 8px;cursor:pointer;transition:all 0.15s;">
                    <div style="font-size:18px;margin-bottom:4px;">🤲</div>
                    <div style="font-size:13px;font-weight:700;color:${occupiedLeft?'#f87171':'#4ade80'};">Левая</div>
                    ${makeTag(occupiedLeft)}
                </button>
                <button id="btn-right" style="flex:1;background:${occupiedRight?'#2a1a1a':'#1a2d2a'};border:1px solid ${occupiedRight?'#f87171':'#4ade80'};border-radius:10px;padding:12px 8px;cursor:pointer;transition:all 0.15s;">
                    <div style="font-size:18px;margin-bottom:4px;">🤱</div>
                    <div style="font-size:13px;font-weight:700;color:${occupiedRight?'#f87171':'#4ade80'};">Правая</div>
                    ${makeTag(occupiedRight)}
                </button>
            </div>
            <button id="btn-cancel" style="width:100%;background:transparent;color:#adadb8;border:1px solid #3d3d3f;border-radius:8px;padding:9px;cursor:pointer;font-size:13px;">✕ Отмена</button>
        </div>
    `;
    document.body.appendChild(modal);
    // Отмена: modal.remove() работает независимо от того, куда был добавлен элемент
    modal.querySelector('#btn-cancel').onclick = () => modal.remove();
    modal.querySelector('#btn-left').onclick  = async () => { modal.remove(); await _rwBuyItem(`${API_URL}/api/rimworld/buy-implant`, { username: userLogin, item_def: itemDef, part_hint: 'left'  }, 'buyImplant', 3000); };
    modal.querySelector('#btn-right').onclick = async () => { modal.remove(); await _rwBuyItem(`${API_URL}/api/rimworld/buy-implant`, { username: userLogin, item_def: itemDef, part_hint: 'right' }, 'buyImplant', 3000); };
}

async function buyNeurotrainer(itemDef) {
    await _rwBuyItem(`${API_URL}/api/rimworld/train-skill`, { username: userLogin, item_def: itemDef }, 'buyNeuro', 3000);
}

// 2026-07-22: имя с префиксом _rw* НЕ трогать. Раньше называлась _buyItem и
// конфликтовала с одноимённой функцией в pets.js: оба файла — обычные скрипты,
// делят глобальную область, pets.js грузится позже (extension.html:469 против
// 461) и ЗАТИРАЛ эту функцию. Весь магазин RimWorld уходил в /api/pet/purchase
// и получал «Предмет не найден в каталоге» — 33 такие покупки в логе прода.
async function _rwBuyItem(url, body, cooldownKey = null, cooldownMs = 5000) {
    // КД управляется снаружи (cooldownKey=null → без проверки внутри)
    if (cooldownKey) {
        const btn = document.activeElement instanceof HTMLButtonElement ? document.activeElement : null;
        if (!checkCooldown(cooldownKey, cooldownMs, btn)) return;
    }
    try {
        const r = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify(body)
        });
        const data = await r.json();
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) {
            loadUserData();
            // Перерисовываем магазин с актуальным балансом
            setTimeout(() => applyShopFilters(), 500);
        }
    } catch (e) {
        showNotification('❌ Ошибка покупки', 'error');
    }
}

// ===== УТИЛИТА: ОКНО ПОДТВЕРЖДЕНИЯ =====
