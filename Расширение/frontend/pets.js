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

// Inject CSS для анимаций (hatch-burst, equip-bounce, NEW-badge).
// Делаем один раз — guard через id.
(function injectPetsStyles() {
    if (document.getElementById('pets-anim-styles')) return;
    const style = document.createElement('style');
    style.id = 'pets-anim-styles';
    style.textContent = `
        .pet-visual-anim.hatch-burst {
            animation: pet-hatch 1.3s cubic-bezier(.34, 1.6, .64, 1) 1;
        }
        @keyframes pet-hatch {
            0%   { transform: scale(1)    rotate(0deg); }
            18%  { transform: scale(1.35) rotate(-8deg); filter: brightness(1.5); }
            34%  { transform: scale(1.05) rotate(6deg);  filter: brightness(1.2); }
            54%  { transform: scale(1.25) rotate(-4deg); }
            76%  { transform: scale(1.05) rotate(2deg); }
            100% { transform: scale(1)    rotate(0deg);  filter: brightness(1); }
        }
        .pet-card-equip-bounce {
            animation: pet-bounce .45s cubic-bezier(.34, 1.6, .64, 1) 1;
        }
        @keyframes pet-bounce {
            0%   { transform: scale(1); }
            50%  { transform: scale(1.06); }
            100% { transform: scale(1); }
        }
        .pet-new-badge {
            display: inline-block;
            background: #f87171;
            color: #fff;
            font-size: 9px;
            font-weight: 700;
            padding: 1px 5px;
            border-radius: 3px;
            letter-spacing: .5px;
            margin-left: 4px;
            vertical-align: middle;
        }
    `;
    document.head.appendChild(style);
})();

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

    const nameDisplay = pet.name
        ? `<span style="color:#fbbf24;">${escapeHtml(pet.name)}</span>`
        : `<span style="color:#adadb8;font-style:italic;">без имени</span>`;

    // Sprint 5.21: shared PetStage компонент рендерит creature + slots.
    // Заменяет старый stacked-emoji подход (head + petEmoji + accessory
    // в одной строке без позиционирования).
    const stageHtml = (typeof PetStage !== 'undefined' && PetStage.renderHtml)
        ? PetStage.renderHtml(pet, equipped, {size: 180, className: 'pet-visual-anim'})
        : `<div class="pet-visual-anim" style="font-size:64px;">${pet.pet_type === 'egg' ? '🥚' : '🐣'}</div>`;

    const petCard = `
        <div style="background:#1a1a1c;border:1px solid #3a3a3e;border-radius:12px;
                    padding:14px;text-align:center;margin-bottom:12px;">
            <div style="margin:0 auto 6px;">
                ${stageHtml}
            </div>
            <div style="font-weight:700;font-size:16px;margin-top:6px;">${nameDisplay}</div>
            <button class="small-btn" data-pet-action="rename" style="margin-top:8px;">✏️ Переименовать</button>
        </div>
    `;

    // Equipped slots panel — показываем ТОЛЬКО занятые слоты (пустые прячем, чтобы
    // карточка не захламлялась пятью «пусто»; экипировка идёт из инвентаря/магазина).
    const slotOrder = ['head', 'face', 'body', 'accessory', 'background', 'aura'];
    const slotLabels = {
        head: 'Голова', face: 'Лицо', body: 'Грудь',
        accessory: 'Сбоку', background: 'Фон', aura: 'Аура'
    };
    const equippedSlots = slotOrder.filter(slot => equipped[slot]);
    const slotsHtml = equippedSlots.map(slot => {
        const item = equipped[slot];
        const slotLabel = slotLabels[slot];
        return `<div style="background:#1a1a1c;border:1px solid #3a3a3e;border-radius:6px;padding:8px;text-align:center;">
            <div style="font-size:24px;">${item.emoji || '🎁'}</div>
            <div style="font-size:11px;color:#adadb8;margin:2px 0;">${slotLabel}</div>
            <div style="font-size:11px;font-weight:600;">${escapeHtml(item.name)}</div>
            <button class="small-btn" data-pet-action="unequip" data-slot="${slot}" style="margin-top:4px;font-size:10px;">🗑️ Снять</button>
        </div>`;
    }).join('');

    const equippedPanel = equippedSlots.length ? `
        <div style="margin-bottom:12px;">
            <div style="font-size:12px;color:#adadb8;margin-bottom:6px;">Надето:</div>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;">
                ${slotsHtml}
            </div>
        </div>
    ` : '';

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
    const headerNote = `<div style="background:#1f1f1f;border:1px solid #2d2d2f;border-radius:6px;padding:8px;
                       margin-bottom:10px;font-size:11px;color:#adadb8;">
              Косметика покупается за 💎 крустики — цена зависит от редкости.
           </div>`;

    const itemsHtml = items.map(it => {
        const owned = it.owned;
        const rarityColor = {
            common:    '#9ca3af',
            rare:      '#3b82f6',
            epic:      '#a855f7',
            legendary: '#fbbf24',
            mythic:    '#ef4444',
        }[it.rarity] || '#9ca3af';

        const priceLabel = (it.price_crustics || 0).toLocaleString('ru-RU');
        const cta = owned
            ? `<button class="small-btn" disabled style="opacity:.5;cursor:default;">✅ Уже есть</button>`
            : `<button class="small-btn" data-pet-action="buy" data-item-id="${it.item_id}">
                   ${priceLabel}💎
               </button>`;

        // NEW-badge для never-owned (для эпик/легендарных пометить ярче)
        const showNewBadge = !owned && (it.rarity === 'epic' || it.rarity === 'legendary');
        const newBadge = showNewBadge ? `<span class="pet-new-badge">NEW</span>` : '';

        return `
            <div style="background:#1a1a1c;border:1px solid ${rarityColor};border-radius:8px;
                        padding:10px;display:flex;align-items:center;gap:10px;margin-bottom:6px;">
                <div style="width:46px;height:46px;display:flex;align-items:center;justify-content:center;font-size:30px;flex-shrink:0;">${
                    it.png_path
                        ? `<img src="${it.png_path}" style="width:46px;height:46px;object-fit:contain;image-rendering:pixelated;" alt="">`
                        : (it.emoji || '🎁')
                }</div>
                <div style="flex:1;">
                    <div style="font-size:13px;font-weight:700;">
                        ${escapeHtml(it.name)}${newBadge}
                    </div>
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
        if (data.success) {
            await _refreshPets();
            // bounce-эффект на petCard после перерисовки
            setTimeout(() => {
                const visual = document.querySelector('#pets-modal .pet-visual-anim');
                if (visual) {
                    visual.classList.add('pet-card-equip-bounce');
                    setTimeout(() => visual.classList.remove('pet-card-equip-bounce'), 500);
                }
            }, 60);
        }
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
        // bits_receipt не передаём — backend в mock-mode или
        // DEFERRED [BITS-SIG] в routes/pets.py docstring
        const r = await fetch(`${API_URL}/api/pet/purchase`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ item_id: itemId }),
        });
        const data = await r.json();
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) {
            await _refreshPets();
            // Hatch-celebration: переключаемся на «Мой» tab + punch animation
            if (data.hatched) {
                _petsState.tab = 'pet';
                _renderPetsContent();
                _triggerHatchCelebration();
            }
        }
    } catch (e) {
        showNotification('Ошибка сети', 'error');
    } finally {
        setTimeout(() => { _petsState.buying = false; }, 400);
    }
}

function _triggerHatchCelebration() {
    // Найти pet-visual в DOM (последний рендер «Мой») и проиграть hatch-pulse
    setTimeout(() => {
        const visual = document.querySelector('#pets-modal .pet-visual-anim');
        if (!visual) return;
        visual.classList.add('hatch-burst');
        setTimeout(() => visual.classList.remove('hatch-burst'), 1400);
    }, 80);  // ждём пока _refreshPets перерисует
}

function _renderPetsError(msg) {
    const el = document.getElementById('pets-content');
    if (el) el.innerHTML = `<div style="color:#f87171;text-align:center;padding:14px;">${escapeHtml(msg)}</div>`;
}

function _slotRu(slot) {
    return {
        head: 'голова', face: 'лицо', body: 'грудь',
        accessory: 'сбоку', background: 'фон', aura: 'аура'
    }[slot] || slot;
}

function _rarityRu(rarity) {
    return { common: 'обычный', rare: 'редкий', epic: 'эпический', legendary: 'легендарный' }[rarity] || rarity;
}

window.openPetsModal = openPetsModal;
