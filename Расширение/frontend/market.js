let marketRefreshTimer = null;

function openSellModal(itemKey, itemName, itemEmoji, minPrice) {
    // Удаляем старый модал если есть
    const old = document.getElementById('sell-modal');
    if (old) old.remove();

    const modal = document.createElement('div');
    modal.id = 'sell-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;z-index:9999;';
    modal.innerHTML = `
        <div style="background:#1f1f23;border-radius:14px;padding:22px;width:260px;border:1px solid #3d3d3f;">
            <div style="font-size:15px;font-weight:600;margin-bottom:14px;color:#efeff1;">
                🏷️ Продать ${itemEmoji} ${itemName}
            </div>
            <div style="font-size:12px;color:#888;margin-bottom:10px;">
                Минимальная цена: ${minPrice}💎 ・ Лот 5 минут
            </div>
            <input id="sell-price-input" type="number" min="${minPrice}" value="${minPrice}"
                style="width:100%;box-sizing:border-box;background:#0e0e10;border:1px solid #444;color:#efeff1;border-radius:8px;padding:8px 10px;font-size:14px;margin-bottom:14px;"/>
            <div style="display:flex;gap:8px;">
                <button data-confirm-sell="${itemKey}" data-min-price="${minPrice}"
                    style="flex:1;background:#9147ff;border:none;color:#fff;border-radius:8px;padding:9px;font-size:13px;cursor:pointer;">
                    Выставить
                </button>
                <button data-close-sell-modal
                    style="flex:1;background:#2d2d2f;border:none;color:#efeff1;border-radius:8px;padding:9px;font-size:13px;cursor:pointer;">
                    Отмена
                </button>
            </div>
        </div>`;
    (document.getElementById("overlay-panel") || document.body).appendChild(modal);
    modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
    modal.querySelector('[data-confirm-sell]').addEventListener('click', () => {
        confirmSell(itemKey, minPrice);
    });
    modal.querySelector('[data-close-sell-modal]').addEventListener('click', () => {
        modal.remove();
    });
}

async function confirmSell(itemKey, minPrice) {
    const input = document.getElementById('sell-price-input');
    const price = parseInt(input?.value || 0);
    if (price < minPrice) { showNotification(`❌ Минимум ${minPrice}💎`, 'error'); return; }
    const modal = document.getElementById('sell-modal');
    if (modal) modal.remove();

    try {
        const res = await fetch(`${API_URL}/api/market/list`, {
            method: 'POST',
            headers: {'Content-Type':'application/json', 'X-Twitch-JWT': authToken || ''},
            body: JSON.stringify({ username: userLogin, item_name: itemKey, price })
        });
        const data = await res.json();
        showNotification(data.success ? '✅ ' + data.message : '❌ ' + data.message);
        if (data.success) {
            await loadUserData();
            loadMarket();
        }
    } catch(e) { showNotification('❌ Ошибка'); }
}

function renderMarketSellPanel() {
    const panel = document.getElementById('market-sell-panel');
    if (!panel) return;
    const sellable = _cachedInventory.filter(i => MARKET_MIN_PRICES[i.name.toLowerCase()] != null && i.quantity > 0);
    if (!sellable.length) {
        panel.innerHTML = `<div style="color:#666;font-size:12px;padding:6px 0;">Нет предметов для продажи</div>`;
        return;
    }
    const options = sellable.map(i => {
        const key = i.name.toLowerCase();
        const min = MARKET_MIN_PRICES[key];
        return `<option value="${key}" data-min="${min}">${i.emoji||'📦'} ${i.name} ×${i.quantity} (мин. ${min}💎)</option>`;
    }).join('');
    const firstMin = MARKET_MIN_PRICES[sellable[0].name.toLowerCase()];
    panel.innerHTML = `
        <div style="display:flex;flex-direction:column;gap:8px;">
            <select id="mkt-sel"
                style="background:#1a1a1c;border:1px solid #3d3d3f;color:#efeff1;border-radius:8px;padding:8px 10px;font-size:13px;cursor:pointer;">
                ${options}
            </select>
            <div style="display:flex;gap:8px;align-items:center;">
                <input id="mkt-price" type="number" min="${firstMin}" value="${firstMin}"
                    style="flex:1;background:#1a1a1c;border:1px solid #3d3d3f;color:#efeff1;border-radius:8px;padding:8px 10px;font-size:13px;"/>
                <button data-action="mkt-list-item"
                    style="background:#9147ff;border:none;color:#fff;border-radius:8px;padding:8px 14px;font-size:13px;cursor:pointer;">
                    🏷️ Выставить
                </button>
            </div>
            <div style="font-size:11px;color:#555;">Лот активен 5 мин ・ при отзыве предмет вернётся</div>
        </div>`;
    panel.querySelector('#mkt-sel')?.addEventListener('change', onMktSelChange);
}

function onMktSelChange() {
    const sel = document.getElementById('mkt-sel');
    const min = parseInt(sel?.selectedOptions[0]?.dataset.min || 0);
    const inp = document.getElementById('mkt-price');
    if (inp) { inp.min = min; inp.value = min; }
}

async function doListItem() {
    const sel   = document.getElementById('mkt-sel');
    const price = parseInt(document.getElementById('mkt-price')?.value || 0);
    if (!sel)      { showNotification('❌ Список предметов не найден', 'error'); return; }
    if (!userLogin){ showNotification('❌ Не авторизован', 'error'); return; }
    const key = sel.value;
    const min = parseInt(sel.selectedOptions[0]?.dataset.min || 0);
    if (!key)      { showNotification('❌ Выберите предмет', 'error'); return; }
    if (price < min){ showNotification(`❌ Минимум ${min}💎`, 'error'); return; }
    try {
        const payload = { username: userLogin, item_name: key, price };
        const res  = await fetch(`${API_URL}/api/market/list`, {
            method: 'POST', headers: {'Content-Type':'application/json', 'X-Twitch-JWT': authToken || ''},
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        showNotification(data.success ? '✅ ' + data.message : '❌ ' + data.message,
                         data.success ? 'success' : 'error');
        if (data.success) { loadUserData(); loadMarket(); }
    } catch(e) {
        console.error('[market/list] ERROR', e);
        showNotification('❌ ' + (e.message || 'Ошибка соединения'), 'error');
    }
}

async function loadMarket() {
    const container = document.getElementById('market-list');
    if (!container) return;

    renderMarketSellPanel(); // обновляем панель выставления

    container.innerHTML = '<div class="loading">Загрузка...</div>';

    try {
        const res = await fetch(`${API_URL}/api/market`);
        const data = await res.json();
        const listings = data.listings || [];

        if (listings.length === 0) {
            container.innerHTML = '<div class="loading" style="color:#666;">Рынок пуст</div>';
            return;
        }

        let html = '';
        const now = Date.now();
        listings.forEach(l => {
            const isOwn = l.seller === userLogin;
            const expires = new Date(l.expires_at + 'Z');
            const secsLeft = Math.max(0, Math.floor((expires - now) / 1000));
            const timeStr = secsLeft > 60 ? `${Math.floor(secsLeft/60)}м ${secsLeft%60}с` : `${secsLeft}с`;

            html += `<div style="background:#1a1a1c;border-radius:10px;padding:10px 12px;margin-bottom:8px;display:flex;align-items:center;gap:10px;">
                <span style="font-size:22px;">${l.item_emoji}</span>
                <div style="flex:1;min-width:0;">
                    <div style="font-size:13px;font-weight:600;color:#efeff1;">${escapeHtml(l.item_name)}</div>
                    <div style="font-size:11px;color:#888;">@${escapeHtml(l.seller)} ・ ⏱ ${timeStr}</div>
                </div>
                <div style="text-align:right;display:flex;flex-direction:column;align-items:flex-end;gap:5px;">
                    <div style="font-size:14px;font-weight:700;color:#9147ff;">${l.price}💎</div>
                    ${isOwn
                        ? `<button data-cancel-listing="${l.id}" style="font-size:11px;background:#3d1a1a;border:1px solid #7a2020;color:#ff6b6b;border-radius:6px;padding:3px 8px;cursor:pointer;">Отозвать</button>`
                        : `<button data-buy-listing="${l.id}" data-item-name="${escapeHtml(l.item_name)}" data-price="${l.price}" style="font-size:11px;background:#1a3a1a;border:1px solid #2d6a2d;color:#4caf50;border-radius:6px;padding:3px 8px;cursor:pointer;">Купить</button>`
                    }
                </div>
            </div>`;
        });
        container.innerHTML = html;
        container.querySelectorAll('[data-cancel-listing]').forEach(btn => {
            btn.addEventListener('click', () => cancelListing(parseInt(btn.dataset.cancelListing)));
        });
        container.querySelectorAll('[data-buy-listing]').forEach(btn => {
            btn.addEventListener('click', () => {
                buyListing(parseInt(btn.dataset.buyListing), btn.dataset.itemName, parseInt(btn.dataset.price));
            });
        });        
    } catch(e) {
        container.innerHTML = '<div class="loading" style="color:#f44;">Ошибка загрузки</div>';
    }
}

async function buyListing(listingId, itemName, price) {
    showConfirm(
        '🛒 Купить предмет',
        `Купить <b>${escapeHtml(itemName)}</b> за <b style="color:#9147ff;">${price}💎</b>?`,
        async () => {
            try {
                const res = await fetch(`${API_URL}/api/market/buy`, {
                    method: 'POST',
                    headers: {'Content-Type':'application/json', 'X-Twitch-JWT': authToken || ''},
                    body: JSON.stringify({ username: userLogin, listing_id: listingId })
                });
                const data = await res.json();
                showNotification(data.success ? '✅ ' + data.message : '❌ ' + data.message, data.success ? 'success' : 'error');
                if (data.success) { await loadUserData(); loadMarket(); }
            } catch(e) { showNotification('❌ Ошибка', 'error'); }
        }
    );
}

async function cancelListing(listingId) {
    try {
        const res = await fetch(`${API_URL}/api/market/cancel`, {
            method: 'POST',
            headers: {'Content-Type':'application/json', 'X-Twitch-JWT': authToken || ''},
            body: JSON.stringify({ username: userLogin, listing_id: listingId })
        });
        const data = await res.json();
        showNotification(data.success ? '✅ ' + data.message : '❌ ' + data.message, data.success ? 'success' : 'error');
        if (data.success) {
            await loadUserData();
            loadMarket();
        }
    } catch(e) { showNotification('❌ Ошибка', 'error'); }
}

// ===== КВЕСТЫ =====
