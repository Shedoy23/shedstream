// pets.js — Pets MVP UI (Phase 7, 2026-05-12)
//
// Cross-channel mechanic — pet/inventory state не зависит от текущего канала.
// MVP: показываем pet (egg + надетые косметики), inventory, catalog с покупкой.
//
// Compliance:
//   - §6.2.4: catalog показывает specific item_id, НЕ mystery box
//   - §6.2.8: catalog read-only — никакой uploadable UI
//   - §5.2:   Bits-mode (если PETS_BITS_REQUIRED=true) или mock (dev)
//
// Tab states: 'pet' | 'catalog'

let _petsState = {
    tab: 'pet',
    data: null,         // { pet, inventory, equipped }
    catalog: null,      // { items, bits_required }
    buying: false,
};

async function openPetsModal() {
    if (!isAuthUser()) {
        showNotification('⚠️ Войдите через Twitch', 'warning');
        return;
    }
    _renderPetsModal();
    await _refreshPets();
}

function _renderPetsModal() {
    let modal = document.getElementById('pets-modal');
    if (modal) modal.remove();
    modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'pets-modal';
    modal.innerHTML = `
        <div class="modal-content" style="max-width:520px;max-height:90vh;overflow-y:auto;">
            <h2>🐾 Питомец</h2>
            <div style="display:flex;gap:4px;margin-bottom:12px;">
                <button class="modal-btn" id="pets-tab-pet"     style="flex:1;padding:8px;">🥚 Мой</button>
                <button class="modal-btn" id="pets-tab-catalog" style="flex:1;padding:8px;">🛍️ Магазин</button>
            </div>
            <div id="pets-content"><div class="loading">Загрузка...</div></div>
            <button class="modal-btn cancel" id="pets-close-btn" style="margin-top:10px;">Закрыть</button>
        </div>
    `;
    (document.getElementById('overlay-panel') || document.body).appendChild(modal);
    document.getElementById('pets-close-btn').addEventListener('click', () => modal.remove());
    document.getElementById('pets-tab-pet').addEventListener('click', () => {
        _petsState.tab = 'pet'; _renderPetsContent();
    });
    document.getElementById('pets-tab-catalog').addEventListener('click', () => {
        _petsState.tab = 'catalog'; _renderPetsContent();
    });
}

async function _refreshPets() {
    try {
        const headers = { 'X-Twitch-JWT': authToken || '' };
        const [petR, catR] = await Promise.all([
            fetch(`${API_URL}/api/pet/my`, { headers }),
            fetch(`${API_URL}/api/pet/catalog`, { headers }),
        ]);
        const petJson = await petR.json();
        const catJson = await catR.json();
        if (!petJson.success || !catJson.success) {
            _renderPetsError(petJson.message || catJson.message || 'Ошибка');
            return;
        }
        _petsState.data    = petJson;
        _petsState.catalog = catJson;
        _renderPetsContent();
    } catch (e) {
        _renderPetsError('Ошибка сети');
    }
}

function _renderPetsContent() {
    const el = document.getElementById('pets-content');
    if (!el) return;
    if (_petsState.tab === 'pet') {
        el.innerHTML = _renderPetView();
        _bindPetActions(el);
    } else {
        el.innerHTML = _renderCatalogView();
        _bindCatalogActions(el);
    }
}

function _renderPetView() {
    const data = _petsState.data;
    if (!data) return '<div class="loading">…</div>';

    const pet       = data.pet      || { pet_type: 'egg', name: null };
    const inventory = data.inventory || [];
    const equipped  = data.equipped || {};   // {slot: item}

    const petEmoji = pet.pet_type === 'egg' ? '🥚' : '🐣';
    const nameDisplay = pet.name
        ? `<span style="color:#fbbf24;">${escapeHtml(pet.name)}</span>`
        : `<span style="color:#adadb8;font-style:italic;">без имени</span>`;

    // visual stack: background → pet → head/accessory overlays
    const bgItem  = equipped.background;
    const headItem = equipped.head;
    const accItem  = equipped.accessory;

    const petCard = `
        <div style="
            background:${bgItem ? 'rgba(145,71,255,.18)' : '#1a1a1c'};
            border:1px solid ${bgItem ? 'rgba(145,71,255,.5)' : '#3a3a3e'};
            border-radius:12px;padding:18px;text-align:center;margin-bottom:12px;">
            <div style="font-size:14px;color:#adadb8;margin-bottom:4px;">
                ${bgItem ? bgItem.emoji + ' ' + escapeHtml(bgItem.name) : 'фон не надет'}
            </div>
            <div style="font-size:64px;line-height:1;margin:8px 0;">
                ${headItem ? `<span style="position:relative;top:-4px;font-size:32px;">${headItem.emoji}</span>` : ''}
                ${petEmoji}
                ${accItem ? `<span style="font-size:32px;">${accItem.emoji}</span>` : ''}
            </div>
            <div style="font-weight:700;font-size:16px;margin-top:6px;">${nameDisplay}</div>
            <button class="small-btn" data-pet-action="rename" style="margin-top:8px;">✏️ Переименовать</button>
        </div>
    `;

    // Equipped slots panel
    const slotsHtml = ['head', 'accessory', 'background'].map(slot => {
        const item = equipped[slot];
        const slotLabel = { head: 'Голова', accessory: 'Аксессуар', background: 'Фон' }[slot];
        if (!item) {
            return `<div style="background:#1a1a1c;border:1px dashed #3a3a3e;border-radius:6px;padding:8px;text-align:center;font-size:11px;color:#adadb8;">
                ${slotLabel}: пусто
            </div>`;
        }
        return `<div style="background:#1a1a1c;border:1px solid #3a3a3e;border-radius:6px;padding:8px;text-align:center;">
            <div style="font-size:24px;">${item.emoji}</div>
            <div style="font-size:11px;color:#adadb8;margin:2px 0;">${slotLabel}</div>
            <div style="font-size:11px;font-weight:600;">${escapeHtml(item.name)}</div>
            <button class="small-btn" data-pet-action="unequip" data-slot="${slot}" style="margin-top:4px;font-size:10px;">🗑️ Снять</button>
        </div>`;
    }).join('');

    const equippedPanel = `
        <div style="margin-bottom:12px;">
            <div style="font-size:12px;color:#adadb8;margin-bottom:6px;">Надето:</div>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;">
                ${slotsHtml}
            </div>
        </div>
    `;

    // Inventory (owned but not equipped)
    const equippedItemIds = new Set(
        Object.values(equipped).filter(Boolean).map(it => it.item_id)
    );
    const unequippedOwned = inventory.filter(it => !equippedItemIds.has(it.item_id));

    const invHtml = unequippedOwned.length ? unequippedOwned.map(it => `
        <div style="background:#1a1a1c;border:1px solid #3a3a3e;border-radius:6px;padding:8px;
                    display:flex;align-items:center;gap:8px;margin-bottom:4px;">
            <div style="font-size:22px;">${it.emoji || '🎁'}</div>
            <div style="flex:1;">
                <div style="font-size:13px;font-weight:600;">${escapeHtml(it.name)}</div>
                <div style="font-size:11px;color:#adadb8;">${_slotRu(it.slot)} · ${_rarityRu(it.rarity)}</div>
            </div>
            <button class="small-btn" data-pet-action="equip" data-item-id="${it.item_id}">Надеть</button>
        </div>
    `).join('') : `
        <div style="font-size:12px;color:#adadb8;text-align:center;padding:10px;">
            Нет неиспользуемых косметик. Загляни в 🛍️ Магазин.
        </div>
    `;

    return `
        ${petCard}
        ${equippedPanel}
        <div style="font-size:12px;color:#adadb8;margin-bottom:6px;">
            Инвентарь (${unequippedOwned.length}):
        </div>
        <div>${invHtml}</div>
    `;
}

function _renderCatalogView() {
    const cat = _petsState.catalog;
    if (!cat) return '<div class="loading">…</div>';
    const items = cat.items || [];
    const bitsRequired = cat.bits_required;

    const headerNote = bitsRequired
        ? `<div style="background:#1f2937;border:1px solid #3b82f6;border-radius:6px;padding:8px;
                       margin-bottom:10px;font-size:11px;color:#93c5fd;">
              💎 Покупка через Twitch Bits. Цены указаны в Bits.
           </div>`
        : `<div style="background:#1f1f1f;border:1px solid #fbbf24;border-radius:6px;padding:8px;
                       margin-bottom:10px;font-size:11px;color:#fbbf24;">
              ⚙️ Тестовый режим: покупки бесплатные (Bits будут включены при релизе).
           </div>`;

    const itemsHtml = items.map(it => {
        const owned = it.owned;
        const rarityColor = {
            common:    '#9ca3af',
            rare:      '#3b82f6',
            epic:      '#a855f7',
            legendary: '#fbbf24',
        }[it.rarity] || '#9ca3af';

        const cta = owned
            ? `<button class="small-btn" disabled style="opacity:.5;cursor:default;">✅ Уже есть</button>`
            : `<button class="small-btn" data-pet-action="buy" data-item-id="${it.item_id}">
                   ${bitsRequired ? `💎 ${it.price_bits}` : 'Получить'}
               </button>`;

        return `
            <div style="background:#1a1a1c;border:1px solid ${rarityColor};border-radius:8px;
                        padding:10px;display:flex;align-items:center;gap:10px;margin-bottom:6px;">
                <div style="font-size:30px;">${it.emoji || '🎁'}</div>
                <div style="flex:1;">
                    <div style="font-size:13px;font-weight:700;">${escapeHtml(it.name)}</div>
                    <div style="font-size:11px;color:${rarityColor};">
                        ${_slotRu(it.slot)} · ${_rarityRu(it.rarity)}
                    </div>
                </div>
                ${cta}
            </div>
        `;
    }).join('');

    return `
        ${headerNote}
        ${itemsHtml || '<div style="color:#adadb8;text-align:center;padding:14px;">Каталог пуст.</div>'}
    `;
}

function _bindPetActions(root) {
    root.querySelectorAll('[data-pet-action]').forEach(btn => {
        const action = btn.dataset.petAction;
        if (action === 'rename') {
            btn.addEventListener('click', _promptPetRename);
        } else if (action === 'equip') {
            btn.addEventListener('click', () => _equipItem(btn.dataset.itemId));
        } else if (action === 'unequip') {
            btn.addEventListener('click', () => _unequipSlot(btn.dataset.slot));
        }
    });
}

function _bindCatalogActions(root) {
    root.querySelectorAll('[data-pet-action="buy"]').forEach(btn => {
        btn.addEventListener('click', () => _buyItem(btn.dataset.itemId));
    });
}

function _promptPetRename() {
    const current = _petsState.data?.pet?.name || '';
    const name = prompt('Имя питомца (макс 24 символа, пусто чтобы убрать):', current);
    if (name === null) return;
    _setPetName(name.trim() || null);
}

async function _setPetName(name) {
    try {
        const r = await fetch(`${API_URL}/api/pet/name`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ name }),
        });
        const data = await r.json();
        if (data.success) {
            showNotification(name ? `✨ Имя обновлено: ${name}` : '🗑️ Имя удалено', 'success');
            await _refreshPets();
        } else {
            showNotification(data.message || 'Ошибка', 'error');
        }
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    }
}

async function _equipItem(itemId) {
    try {
        const r = await fetch(`${API_URL}/api/pet/equip`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ item_id: itemId }),
        });
        const data = await r.json();
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) await _refreshPets();
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    }
}

async function _unequipSlot(slot) {
    try {
        const r = await fetch(`${API_URL}/api/pet/equip`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ item_id: null, slot }),
        });
        const data = await r.json();
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) await _refreshPets();
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    }
}

async function _buyItem(itemId) {
    if (_petsState.buying) return;
    _petsState.buying = true;
    try {
        // MVP: bits_receipt не передаём — на бэке mock-mode либо TODO real Bits flow
        const r = await fetch(`${API_URL}/api/pet/purchase`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ item_id: itemId }),
        });
        const data = await r.json();
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) await _refreshPets();
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    } finally {
        setTimeout(() => { _petsState.buying = false; }, 400);
    }
}

function _renderPetsError(msg) {
    const el = document.getElementById('pets-content');
    if (el) el.innerHTML = `<div style="color:#f87171;text-align:center;padding:14px;">${escapeHtml(msg)}</div>`;
}

function _slotRu(slot) {
    return { head: 'голова', accessory: 'аксессуар', background: 'фон', body: 'тело' }[slot] || slot;
}

function _rarityRu(rarity) {
    return { common: 'обычный', rare: 'редкий', epic: 'эпический', legendary: 'легендарный' }[rarity] || rarity;
}

window.openPetsModal = openPetsModal;
