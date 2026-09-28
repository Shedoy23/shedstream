const SERVER = 'https://shedoy23.ru';
let _channelId = null;
let _jwt = null;
let _petsEnabled = null;

// Twitch Extension config callback
if (window.Twitch && Twitch.ext) {
    Twitch.ext.onAuthorized(auth => {
        _channelId = parseInt(auth.channelId, 10);
        _jwt = auth.token;
        _refreshPetsToggle();
    });
} else {
    // Standalone preview — пробуем взять channel_id из URL
    _channelId = parseInt(new URLSearchParams(location.search).get('channel_id') || '0', 10);
    if (_channelId > 0) _refreshPetsToggle();
}

async function _refreshPetsToggle() {
    if (!_channelId) return;
    try {
        const r = await fetch(`${SERVER}/api/overlay/pets?channel_id=${_channelId}`);
        const data = await r.json();
        _petsEnabled = !!data.enabled;
        _renderPetsToggle();
    } catch (e) {
        _setPetsStatus('Не удалось загрузить статус', '#f87171');
    }
}

function _renderPetsToggle() {
    const lbl = document.getElementById('pets-toggle-label');
    const btn = document.getElementById('pets-toggle-btn');
    if (!lbl || !btn) return;
    lbl.textContent = _petsEnabled ? '✅ Включено' : '⛔ Выключено';
    btn.textContent = _petsEnabled ? 'Выключить' : 'Включить';
    btn.className = 'toggle-btn ' + (_petsEnabled ? 'on' : 'off');
    btn.onclick = () => _togglePets();
    _setPetsStatus('', '#adadb8');
}

async function _togglePets() {
    if (!_jwt) {
        _setPetsStatus('Нет авторизации Twitch', '#f87171');
        return;
    }
    const newState = !_petsEnabled;
    try {
        // Self-serve через Twitch config view: шлём broadcaster-JWT, бэк берёт
        // channel_id ИЗ токена (нельзя переключить чужой канал).
        const r = await fetch(`${SERVER}/api/streamer/pets/overlay-toggle`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': _jwt },
            body: JSON.stringify({ enabled: newState }),
        });
        if (r.status === 401 || r.status === 403) {
            _setPetsStatus('Открой настройки от имени бродкастера канала', '#fbbf24');
            return;
        }
        const data = await r.json();
        if (data.success) {
            _petsEnabled = data.enabled;
            _renderPetsToggle();
            _setPetsStatus('Сохранено', '#34d399');
        } else {
            _setPetsStatus(data.message || 'Ошибка', '#f87171');
        }
    } catch (e) {
        _setPetsStatus('Ошибка сети', '#f87171');
    }
}

function _setPetsStatus(msg, color) {
    const el = document.getElementById('pets-toggle-status');
    if (el) { el.textContent = msg; el.style.color = color; }
}
