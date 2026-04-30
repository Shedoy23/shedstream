function _escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function isAuthUser() {
    return userLogin && userLogin !== 'testuser' && !/^U[a-zA-Z0-9]{8,}$/.test(userLogin);
}

function openCasino() {
    if (!isAuthUser()) { showNotification('⚠️ Войдите через Twitch для участия', 'warning'); return; }
    const modal = document.getElementById('casino-modal');
    if (modal) {
        const balanceEl = document.getElementById('points');
        const casinoBalanceEl = document.getElementById('casino-balance');
        if (balanceEl && casinoBalanceEl) {
            casinoBalanceEl.textContent = balanceEl.textContent;
        }
        // Сбрасываем прошлый результат
        const resultEl = document.getElementById('casino-result');
        if (resultEl) { resultEl.style.display = 'none'; resultEl.innerHTML = ''; }
        modal.classList.add('active');
    }
}

function setBet(amount) {
    const input = document.getElementById('bet-amount');
    const warningEl = document.getElementById('bet-warning');
    const balanceEl = document.getElementById('points');
    
    if (input) {
        input.value = amount;
        
        if (balanceEl && warningEl) {
            const balance = parseInt(balanceEl.textContent) || 0;
            warningEl.style.display = amount > balance ? 'block' : 'none';
        }
    }
}

function setupBetInputListener() {
    const betInput = document.getElementById('bet-amount');
    if (betInput) {
        betInput.addEventListener('input', function() {
            const warningEl = document.getElementById('bet-warning');
            const balanceEl = document.getElementById('points');
            
            if (balanceEl && warningEl) {
                const balance = parseInt(balanceEl.textContent) || 0;
                const bet = parseInt(this.value) || 0;
                warningEl.style.display = bet > balance ? 'block' : 'none';
            }
        });
    }
}

async function placeBet() {
    const amount = document.getElementById('bet-amount')?.value;
    const balanceEl = document.getElementById('points');
    const betBtn = document.getElementById('casino-bet-btn');

    if (!amount) { showNotification('❌ Введи сумму ставки!', 'error'); return; }

    if (balanceEl) {
        const balance = parseInt(balanceEl.textContent) || 0;
        if (parseInt(amount) > balance) {
            showNotification('❌ Недостаточно средств!', 'error');
            return;
        }
    }

    if (betBtn) betBtn.classList.add('casino-btn-pulsing');

    try {
        const response = await fetch(`${API_URL}/api/casino/bet`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: userLogin, amount: parseInt(amount) })
        });
        const data = await response.json();

        if (betBtn) betBtn.classList.remove('casino-btn-pulsing');

        if (data.success) {
            const resultEl = document.getElementById('casino-result');
            if (resultEl) {
                const isJackpot = data.result === 'jackpot';
                const isWin = data.result === 'win' || isJackpot;
                const icons  = { jackpot: '🎰💥', win: '🍀✨', loss: '😢' };
                const colors = { jackpot: '#ffd700', win: '#4ade80', loss: '#f87171' };

                const winHtml = data.win > 0
                    ? `<div id="casino-win-counter" style="color:#4ade80;font-size:14px;margin-top:4px;animation:countUp .35s ease both;">+${data.win}💎</div>`
                    : '';

                resultEl.innerHTML = `
                    <div style="text-align:center;padding:16px;">
                        <div style="font-size:40px;margin-bottom:8px;">${icons[data.result] || '🎲'}</div>
                        <div style="font-size:18px;font-weight:700;color:${colors[data.result]};">${_escapeHtml(data.message)}</div>
                        ${winHtml}
                    </div>`;
                resultEl.style.display = 'block';

                resultEl.classList.remove('casino-result-shake', 'casino-result-win', 'casino-result-jackpot');
                void resultEl.offsetWidth;

                if (isJackpot) {
                    resultEl.classList.add('casino-result-jackpot');
                    _spawnCoins(resultEl, 18);
                } else if (isWin) {
                    resultEl.classList.add('casino-result-win');
                    _spawnCoins(resultEl, 8);
                } else {
                    resultEl.classList.add('casino-result-shake');
                }

                if (data.win > 0) _animateCounter('casino-win-counter', data.win);
            } else {
                showNotification(data.message, data.result === 'loss' ? 'error' : 'success');
            }
            await loadUserData();
            const pts = document.getElementById('points');
            const cb  = document.getElementById('casino-balance');
            if (pts && cb) cb.textContent = pts.textContent;
        } else {
            showNotification(data.message, 'error');
        }
    } catch (e) {
        if (betBtn) betBtn.classList.remove('casino-btn-pulsing');
        showNotification('❌ Ошибка при ставке', 'error');
    }
}

function _spawnCoins(fromEl, count) {
    const rect = fromEl.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top  + rect.height / 2;
    for (let i = 0; i < count; i++) {
        const coin = document.createElement('div');
        coin.className = 'casino-coin';
        coin.textContent = '💎';
        const angle = (Math.PI * 2 / count) * i + (Math.random() - 0.5) * 0.8;
        const dist  = 50 + Math.random() * 80;
        coin.style.setProperty('--dx', Math.round(Math.cos(angle) * dist) + 'px');
        coin.style.setProperty('--dy', Math.round(Math.sin(angle) * dist - 30) + 'px');
        coin.style.left = cx + 'px';
        coin.style.top  = cy + 'px';
        coin.style.animationDelay = (Math.random() * 0.2) + 's';
        document.body.appendChild(coin);
        setTimeout(() => coin.remove(), 1100);
    }
}

function _animateCounter(elId, target) {
    const el = document.getElementById(elId);
    if (!el) return;
    const duration = 600;
    const start = Date.now();
    const tick = () => {
        const p = Math.min(1, (Date.now() - start) / duration);
        const eased = 1 - Math.pow(1 - p, 3);
        el.textContent = '+' + Math.round(eased * target) + '💎';
        if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
}




// ===== ПРОМОКОД =====
const SLOT_SYMBOLS = [
    { id: 'wood',   emoji: '🪵', label: 'Деревяшка', mult: 0,  weight: 55, color: '#8B5E3C' },
    { id: 'stone',  emoji: '🪨', label: 'Камень',    mult: 1,  weight: 25, color: '#9ca3af' },
    { id: 'amulet', emoji: '🔮', label: 'Амулет',    mult: 2,  weight: 15, color: '#9147ff' },
    { id: 'crown',  emoji: '👑', label: 'Корона',    mult: 5,  weight: 5,  color: '#fbbf24' },
];

function _slotsPickSymbol() {
    const totalWeight = SLOT_SYMBOLS.reduce((sum, s) => sum + s.weight, 0);
    let r = Math.random() * totalWeight;
    for (const s of SLOT_SYMBOLS) {
        r -= s.weight;
        if (r <= 0) return s;
    }
    return SLOT_SYMBOLS[0];
}

// ❗ РЕЗУЛЬТАТ ГЕНЕРИРУЕТСЯ ТОЛЬКО НА СЕРВЕРЕ
// Клиент только анимирует полученный результат

// Обновить плашку джекпота (вызывается при открытии модалки и после каждого спина).
// jp — опциональное значение; если не передано, фетчим с /api/casino/jackpot.
async function _updateSlotsJackpot(jp) {
    const el = document.getElementById('slots-jackpot-value');
    if (!el) return;
    try {
        if (jp === undefined) {
            const resp = await fetch(`${API_URL}/api/casino/jackpot`);
            const data = await resp.json();
            jp = data.jackpot;
        }
        if (typeof jp === 'number') {
            el.textContent = jp.toLocaleString('ru-RU') + '💎';
        }
    } catch (e) {
        el.textContent = '—';
    }
}

// Открыть модалку слотов
function openSlots() {
    if (!isAuthUser()) { showNotification('⚠️ Войдите через Twitch для участия', 'warning'); return; }
    const modal = document.getElementById('slots-modal');
    if (!modal) return;

    // Синхронизируем баланс
    const pts = document.getElementById('points');
    const sb  = document.getElementById('slots-balance');
    if (pts && sb) sb.textContent = pts.textContent;

    // Сброс барабанов в начальное состояние
    for (let i = 0; i < 3; i++) {
        const reel = document.getElementById(`reel-${i}`);
        if (reel) {
            reel.innerHTML = `<div class="slot-cell">🪵</div>`;
            reel.style.transform = '';
        }
    }

    const resultEl = document.getElementById('slots-result');
    if (resultEl) { resultEl.style.display = 'none'; resultEl.innerHTML = ''; }

    const btn = document.getElementById('slots-spin-btn');
    if (btn) { btn.disabled = false; btn.textContent = '🎲 Крутить!'; }

    // Кнопка "?" — показать/скрыть таблицу выплат. Привязываем один раз.
    const helpBtn   = document.getElementById('slots-help-btn');
    const helpPanel = document.getElementById('slots-help-panel');
    if (helpBtn && helpPanel && !helpBtn.dataset.bound) {
        helpBtn.dataset.bound = '1';
        helpBtn.addEventListener('click', () => {
            helpPanel.style.display = helpPanel.style.display === 'none' ? 'block' : 'none';
        });
    }
    // При каждом открытии модалки прячем подсказку
    if (helpPanel) helpPanel.style.display = 'none';

    // Подгружаем актуальный размер джекпота
    _updateSlotsJackpot();

    modal.classList.add('active');
}

function setSlotseBet(amount) {
    const input = document.getElementById('slots-bet-amount');
    const warn  = document.getElementById('slots-bet-warning');
    const pts   = document.getElementById('points');
    if (input) input.value = amount;
    if (warn && pts) warn.style.display = parseInt(amount) > (parseInt(pts.textContent)||0) ? 'block' : 'none';
}

// Анимация одного барабана: прокрутка N фиктивных символов, затем финальный
function _animateReel(reelEl, finalSymbol, durationMs) {
    return new Promise(resolve => {
        const cellH = 64; // высота одной ячейки px
        const spinCount = 12 + Math.floor(Math.random() * 6); // 12-17 прокруток

        // Строим длинную полосу: случайные символы + финальный в конце
        const strip = [];
        for (let i = 0; i < spinCount; i++) strip.push(_slotsPickSymbol());
        strip.push(finalSymbol);

        // Рендерим все ячейки
        reelEl.innerHTML = strip.map(s =>
            `<div class="slot-cell" style="color:${s.color};">${s.emoji}</div>`
        ).join('');

        const totalH = strip.length * cellH;
        const targetOffset = -(totalH - cellH); // финальный символ снизу → поднять до верха

        // CSS transition с ease-out (замедление в конце)
        reelEl.style.transition = 'none';
        reelEl.style.transform  = 'translateY(0)';

        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                reelEl.style.transition = `transform ${durationMs}ms cubic-bezier(0.17, 0.67, 0.12, 1.0)`;
                reelEl.style.transform  = `translateY(${targetOffset}px)`;
            });
        });

        setTimeout(() => {
            // Оставляем только финальный символ
            reelEl.style.transition = 'none';
            reelEl.style.transform  = '';
            reelEl.innerHTML = `<div class="slot-cell" style="color:${finalSymbol.color};font-size:32px;">${finalSymbol.emoji}</div>`;
            resolve();
        }, durationMs + 50);
    });
}

let _slotsSpinning = false;

async function spinSlots() {
    if (_slotsSpinning) return;
    if (!checkCooldown('spinSlots', 3000)) return;

    const input = document.getElementById('slots-bet-amount');
    const bet   = parseInt(input?.value) || 0;
    if (bet < 50) { showNotification('❌ Минимальная ставка 50💎', 'error'); return; }

    const balance = parseInt(document.getElementById('points')?.textContent) || 0;
    if (bet > balance) { showNotification('❌ Недостаточно 💎', 'error'); return; }

    _slotsSpinning = true;
    const btn = document.getElementById('slots-spin-btn');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Запрос к серверу...'; }

    const resultEl = document.getElementById('slots-result');
    if (resultEl) { resultEl.style.display = 'none'; resultEl.innerHTML = ''; }

    // 1. ЗАПРАШИВАЕМ РЕЗУЛЬТАТ У СЕРВЕРА
    let serverResult;
    try {
        const resp = await fetch(`${API_URL}/api/casino/slots`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: userLogin, bet: bet })
        });
        const data = await resp.json();
        if (!data.success) {
            showNotification(data.message || '❌ Ошибка сервера', 'error');
            _slotsSpinning = false;
            if (btn) { btn.disabled = false; btn.textContent = '🎲 Крутить!'; }
            return;
        }
        serverResult = data;
    } catch(e) {
        showNotification('❌ Нет связи с сервером', 'error');
        _slotsSpinning = false;
        if (btn) { btn.disabled = false; btn.textContent = '🎲 Крутить!'; }
        return;
    }

    // 2. Преобразуем ID в объекты для анимации
    const SERVER_MAP = {
        'wood':   { emoji: '🪵', mult: 0,   color: '#8B5E3C' },
        'stone':  { emoji: '🪨', mult: 1,   color: '#9ca3af' },
        'amulet': { emoji: '🔮', mult: 2,   color: '#9147ff' },
        'crown':  { emoji: '👑', mult: 5,   color: '#fbbf24' },
    };
    
    const finalReels = serverResult.symbols.map(id => ({ id, ...SERVER_MAP[id] }));
    if (btn && btn.textContent.includes('Запрос')) btn.textContent = '⏳ Крутится...';

    // 3. ЗАПУСКАЕМ АНИМАЦИЮ (барабаны остановятся именно на том, что сказал сервер)
    const durations = [900, 1200, 1550];
    await Promise.all([
        _animateReel(document.getElementById('reel-0'), finalReels[0], durations[0]),
        _animateReel(document.getElementById('reel-1'), finalReels[1], durations[1]),
        _animateReel(document.getElementById('reel-2'), finalReels[2], durations[2]),
    ]);

    await new Promise(r => setTimeout(r, 180));

    // 4. ПОКАЗЫВАЕМ РЕЗУЛЬТАТ
    // Сервер отдаёт два независимых поля выплаты:
    //   win       — полноценный выигрыш (тройка/пара crown/amulet, джекпот)
    //   near_miss — частичный возврат 10% ставки за пару 🪵🪵 / 🪨🪨
    // Раньше UI проверял только `win > 0` и рисовал все остальные случаи
    // как "Деревяшка... ×0, -bet💎" — даже когда на баланс реально вернулось
    // 10% ставки, игрок думал что потерял всё.
    const ids       = serverResult.symbols || [];
    const isJackpot = ids.length === 3 && ids.every(s => s === 'crown');
    const mult      = serverResult.mult;
    const win       = serverResult.win       || 0;
    const nearMiss  = serverResult.near_miss || 0;
    const net       = (win + nearMiss) - bet;   // чистое изменение баланса за спин

    // Классификация исхода
    let outcome;  // 'jackpot' | 'win' | 'near_miss' | 'wood_triple' | 'lose'
    if (isJackpot)                           outcome = 'jackpot';
    else if (win > 0)                        outcome = 'win';
    else if (nearMiss > 0)                   outcome = 'near_miss';
    else if (ids.length === 3 && ids.every(s => s === 'wood')) outcome = 'wood_triple';
    else                                     outcome = 'lose';

    let resultColor, resultIcon, resultText, amountHtml;
    switch (outcome) {
        case 'jackpot':
            resultColor = '#fbbf24'; resultIcon = '🎰💥';
            resultText  = `ДЖЕКПОТ!`;
            amountHtml  = `<div style="font-size:22px;font-weight:800;color:#fbbf24;" id="slots-win-anim">+${win.toLocaleString('ru-RU')}💎</div>`;
            break;
        case 'win':
            resultColor = '#4ade80'; resultIcon = '✨';
            resultText  = `Выигрыш! ×${mult}`;
            amountHtml  = `<div style="font-size:22px;font-weight:800;color:#4ade80;" id="slots-win-anim">+${win}💎</div>`;
            break;
        case 'near_miss':
            // 10% ставки обратно — частичный проигрыш, но не полный ноль
            resultColor = '#fbbf2488'; resultIcon = '🪙';
            resultText  = `Возврат 10% — почти!`;
            amountHtml  = `
                <div style="font-size:16px;color:#fbbf24;">возврат +${nearMiss}💎</div>
                <div style="font-size:13px;color:#f87171;margin-top:2px;">итого ${net}💎</div>`;
            break;
        case 'wood_triple':
            // Тройка 🪵 — частый (16% спинов) «псевдо-успех», платит 0
            resultColor = '#8B5E3C'; resultIcon = '🪵';
            resultText  = 'Тройка деревяшек — не платит';
            amountHtml  = `<div style="font-size:14px;color:#f87171;">-${bet}💎</div>`;
            break;
        case 'lose':
        default:
            resultColor = '#9ca3af'; resultIcon = '🎲';
            resultText  = 'Мимо';
            amountHtml  = `<div style="font-size:14px;color:#f87171;">-${bet}💎</div>`;
            break;
    }

    // Вспышка только для реальных выигрышей
    const machine = document.getElementById('slots-machine');
    if (machine && (outcome === 'jackpot' || outcome === 'win')) {
        const glowColor = outcome === 'jackpot' ? '#fbbf24' : '#9147ff';
        machine.style.boxShadow = `0 0 24px 4px ${glowColor}88`;
        setTimeout(() => { machine.style.boxShadow = ''; }, 700);
    }

    // Рендер результата
    resultEl.innerHTML = `
        <div style="padding:14px 10px;">
            <div style="font-size:36px;margin-bottom:6px;">${resultIcon}</div>
            <div style="font-size:17px;font-weight:800;color:${resultColor};margin-bottom:4px;">${resultText}</div>
            ${amountHtml}
        </div>`;
    resultEl.style.display = 'block';
    resultEl.style.visibility = 'visible';
    resultEl.style.opacity = '1';

    if (outcome === 'jackpot')      _spawnCoins(resultEl, 22);
    else if (outcome === 'win')     _spawnCoins(resultEl, 10);
    else if (outcome === 'near_miss') _spawnCoins(resultEl, 3);

    if (win > 0) _animateCounter('slots-win-anim', win);

    await loadUserData(); // Обновляем баланс в шапке
    const pts = document.getElementById('points');
    const sb  = document.getElementById('slots-balance');
    if (pts && sb) sb.textContent = pts.textContent;

    // Обновляем джекпот: после своего выигрыша он сбросится до 10k,
    // после обычного спина — вырастет на 2% нашей ставки.
    _updateSlotsJackpot(serverResult.jackpot);

    _slotsSpinning = false;
    const didWin = outcome === 'jackpot' || outcome === 'win';
    if (btn) { btn.disabled = false; btn.textContent = didWin ? '🎲 Крутить ещё!' : '🎲 Крутить!'; }
}

// ===== ИВЕНТЫ RIMWORLD =====
