// cases.js — UI для системы кейсов (Phase 2, 2026-05-11)
//
// Compliance: §5.3 Twitch Extension Guidelines — loot boxes free, content
// без monetary value. Превью наград видно ДО открытия (детерминированный prize).
// Анимация открытия — простое раскрытие сундука, БЕЗ roulette-style spin.

const CASE_TIER_META = {
    common: {
        label: 'Обычный',
        color: '#9ca3af',
        emoji: '🎁',
        bgGradient: 'linear-gradient(135deg, rgba(156,163,175,.18), rgba(156,163,175,.06))',
        borderColor: 'rgba(156,163,175,.45)',
    },
    rare: {
        label: 'Редкий',
        color: '#3b82f6',
        emoji: '💎',
        bgGradient: 'linear-gradient(135deg, rgba(59,130,246,.20), rgba(59,130,246,.06))',
        borderColor: 'rgba(59,130,246,.55)',
    },
    epic: {
        label: 'Эпический',
        color: '#a855f7',
        emoji: '💠',
        bgGradient: 'linear-gradient(135deg, rgba(168,85,247,.22), rgba(168,85,247,.06))',
        borderColor: 'rgba(168,85,247,.6)',
    },
    legendary: {
        label: 'Легендарный',
        color: '#fbbf24',
        emoji: '👑',
        bgGradient: 'linear-gradient(135deg, rgba(251,191,36,.24), rgba(251,191,36,.06))',
        borderColor: 'rgba(251,191,36,.65)',
    },
};

const CASE_SOURCE_LABEL = {
    quest:           'Дневной квест',
    streak:          'Streak milestone',
    watch_milestone: 'Часы просмотра',
    season_top:      'Сезонный топ',
    drop:            'Удачный дроп',
    admin_grant:     'Подарок админа',
    promo:           'Промокод',
};

let _casesData = null;          // {cases: [...], unopened_counts: {...}}
let _casesLoading = false;
let _casesOpening = new Set();  // case_id'ы которые сейчас в процессе открытия

async function openCasesModal() {
    if (!isAuthUser()) {
        showNotification('⚠️ Войдите через Twitch', 'warning');
        return;
    }

    // Создаём modal-контейнер
    let modal = document.getElementById('cases-modal');
    if (modal) modal.remove();
    modal = document.createElement('div');
    modal.className = 'modal active';
    modal.id = 'cases-modal';
    modal.innerHTML = `
        <div class="modal-content" style="max-width:520px;max-height:90vh;overflow-y:auto;">
            <h2 style="display:flex;align-items:center;justify-content:space-between;">
                <span>🎁 Кейсы</span>
                <span id="cases-badge-total" style="font-size:13px;color:#adadb8;font-weight:500;">—</span>
            </h2>
            <div id="cases-tier-summary" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px;font-size:11px;"></div>
            <div id="cases-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;margin-bottom:14px;">
                <div class="loading" style="grid-column:1/-1;">Загрузка кейсов...</div>
            </div>
            <details style="margin-bottom:10px;background:#1a1a1c;border-radius:6px;padding:8px 12px;">
                <summary style="cursor:pointer;font-size:12px;color:#adadb8;">💡 Что внутри каждого тира?</summary>
                <div id="cases-tier-preview" style="margin-top:8px;font-size:12px;line-height:1.6;">
                    <div>Загрузка...</div>
                </div>
            </details>
            <button class="modal-btn cancel" data-action="close-modal">Закрыть</button>
        </div>
    `;
    (document.getElementById('overlay-panel') || document.body).appendChild(modal);

    await loadCases();
    await loadTierPreview();
}

async function loadCases() {
    if (_casesLoading) return;
    _casesLoading = true;
    try {
        const headers = { 'X-Twitch-JWT': authToken || '' };
        const r = await fetch(`${API_URL}/api/viewer/cases`, { headers });
        const data = await r.json();
        if (!data.success) {
            renderCasesError(data.message || 'Ошибка загрузки');
            return;
        }
        _casesData = data;
        renderCases();
    } catch (e) {
        renderCasesError('Не удалось загрузить кейсы');
        console.error('[cases] loadCases error:', e);
    } finally {
        _casesLoading = false;
    }
}

function renderCases() {
    const grid = document.getElementById('cases-grid');
    const badge = document.getElementById('cases-badge-total');
    const summary = document.getElementById('cases-tier-summary');
    if (!grid || !_casesData) return;

    const counts = _casesData.unopened_counts || {};
    const total = counts.total || 0;
    if (badge) badge.textContent = total > 0 ? `${total} закрытых` : 'все открыты';

    // Tier badges
    if (summary) {
        const parts = ['common', 'rare', 'epic', 'legendary']
            .filter(t => (counts[t] || 0) > 0)
            .map(t => {
                const meta = CASE_TIER_META[t];
                return `<span style="background:${meta.bgGradient};border:1px solid ${meta.borderColor};border-radius:12px;padding:3px 10px;color:${meta.color};">
                    ${meta.emoji} ${meta.label}: ${counts[t]}
                </span>`;
            });
        summary.innerHTML = parts.length
            ? parts.join('')
            : '<span style="color:#adadb8;">Нет закрытых кейсов</span>';
    }

    const cases = _casesData.cases || [];
    if (!cases.length) {
        // Sprint 5.28: backend теперь шлёт только закрытые. Empty-state
        // зависит от lifetime_count — если > 0 значит юзер всё открыл,
        // иначе ещё ни одного не выпало.
        const lifetime = _casesData.lifetime_count || 0;
        grid.innerHTML = lifetime > 0
            ? `<div style="grid-column:1/-1;text-align:center;color:#adadb8;padding:16px;">
                   🎉 Все кейсы открыты! Заходи завтра за новым дневным квестом.
               </div>`
            : `<div style="grid-column:1/-1;text-align:center;color:#adadb8;padding:16px;">
                   Пока нет кейсов. Выполняй квесты и держи streak — кейсы появятся!
               </div>`;
        return;
    }

    grid.innerHTML = cases.map(c => renderCaseCard(c)).join('');

    // Bind click handlers только для НЕ открытых
    grid.querySelectorAll('[data-open-case-id]').forEach(card => {
        card.addEventListener('click', () => {
            const id = parseInt(card.dataset.openCaseId, 10);
            if (id && !_casesOpening.has(id)) openCase(id, card);
        });
    });
}

function renderCaseCard(c) {
    const meta = CASE_TIER_META[c.tier] || CASE_TIER_META.common;
    const isOpened = !!c.opened_at;
    const sourceLabel = CASE_SOURCE_LABEL[c.source] || c.source;

    if (isOpened) {
        // Открытый: dimmed, показывает что было внутри
        return `
            <div style="background:${meta.bgGradient};border:1px solid ${meta.borderColor};border-radius:10px;padding:10px;text-align:center;opacity:0.5;">
                <div style="font-size:28px;margin-bottom:4px;">${meta.emoji}</div>
                <div style="font-size:11px;color:${meta.color};font-weight:600;">${meta.label}</div>
                <div style="font-size:10px;color:#adadb8;margin-top:2px;">${sourceLabel}</div>
                <div style="font-size:10px;color:#4ade80;margin-top:4px;">✅ +${(c.reward_points || 0).toLocaleString('ru-RU')}💎</div>
            </div>
        `;
    }

    // Не открытый: clickable, hover effect
    return `
        <div data-open-case-id="${c.id}"
             style="background:${meta.bgGradient};border:1px solid ${meta.borderColor};border-radius:10px;padding:10px;text-align:center;cursor:pointer;transition:transform .15s, box-shadow .15s;"
             onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 4px 12px ${meta.borderColor}';"
             onmouseout="this.style.transform='';this.style.boxShadow='';">
            <div style="font-size:36px;margin-bottom:6px;">${meta.emoji}</div>
            <div style="font-size:12px;color:${meta.color};font-weight:700;">${meta.label}</div>
            <div style="font-size:10px;color:#adadb8;margin-top:2px;">${sourceLabel}</div>
            <div style="font-size:10px;color:${meta.color};margin-top:6px;font-weight:600;">▸ Открыть</div>
        </div>
    `;
}

async function openCase(caseId, cardEl) {
    if (_casesOpening.has(caseId)) return;
    _casesOpening.add(caseId);

    // Простая анимация раскрытия (БЕЗ roulette spin):
    // 1. Card "вздрагивает" (scale-up)
    // 2. Server отвечает с результатом
    // 3. Cards меняется на reveal-стейт с +N💎
    if (cardEl) {
        cardEl.style.pointerEvents = 'none';
        cardEl.style.transform = 'scale(1.05)';
        cardEl.style.transition = 'transform 0.3s ease-out';
    }

    try {
        const r = await fetch(`${API_URL}/api/viewer/case/open`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authToken || '' },
            body: JSON.stringify({ case_id: caseId }),
        });
        const data = await r.json();

        if (!data.success) {
            showNotification(data.message || 'Не удалось открыть', 'error');
            // Revert animation
            if (cardEl) {
                cardEl.style.transform = '';
                cardEl.style.pointerEvents = '';
            }
            return;
        }

        // Reveal animation
        const meta = CASE_TIER_META[data.tier] || CASE_TIER_META.common;
        if (cardEl) {
            cardEl.style.transform = 'scale(1.1)';
            setTimeout(() => {
                cardEl.innerHTML = `
                    <div style="font-size:36px;margin-bottom:6px;">${meta.emoji}</div>
                    <div style="font-size:14px;color:${meta.color};font-weight:800;">+${data.reward_points.toLocaleString('ru-RU')}💎</div>
                    <div style="font-size:10px;color:#adadb8;margin-top:4px;">${meta.label}</div>
                `;
                cardEl.style.transform = '';
                cardEl.style.opacity = '0.7';
                cardEl.style.pointerEvents = '';
            }, 300);
        }

        showNotification(`${meta.emoji} +${data.reward_points.toLocaleString('ru-RU')}💎!`, 'success');

        // Update balance if function exists
        if (typeof loadUserData === 'function') {
            setTimeout(loadUserData, 400);
        }

        // Refresh cases list через 700ms (после анимации)
        setTimeout(loadCases, 700);
    } catch (e) {
        showNotification('Ошибка сети', 'error');
        if (cardEl) {
            cardEl.style.transform = '';
            cardEl.style.pointerEvents = '';
        }
        console.error('[cases] openCase error:', e);
    } finally {
        _casesOpening.delete(caseId);
    }
}

async function loadTierPreview() {
    try {
        const r = await fetch(`${API_URL}/api/case/preview`);
        const data = await r.json();
        const container = document.getElementById('cases-tier-preview');
        if (!container || !data.success) return;
        container.innerHTML = data.tiers.map(t => {
            const meta = CASE_TIER_META[t.tier] || CASE_TIER_META.common;
            return `<div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;">
                <span style="color:${t.color};">${meta.emoji} ${t.label}</span>
                <span style="color:#adadb8;">${t.reward_points.toLocaleString('ru-RU')}💎</span>
            </div>`;
        }).join('');
    } catch (e) {
        // Silent fail — preview не критичен
    }
}

function renderCasesError(msg) {
    const grid = document.getElementById('cases-grid');
    if (!grid) return;
    grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;color:#f87171;padding:14px;">${escapeHtml(msg)}</div>`;
}

// Badge poll: обновляет счётчик закрытых кейсов в action-card (не открывая modal)
async function pollCasesBadge() {
    if (!isAuthUser()) return;
    try {
        const headers = { 'X-Twitch-JWT': authToken || '' };
        const r = await fetch(`${API_URL}/api/viewer/cases/unopened-count`, { headers });
        const data = await r.json();
        if (!data.success) return;
        const total = (data.counts && data.counts.total) || 0;
        const badgeEl = document.getElementById('cases-action-badge');
        if (badgeEl) {
            badgeEl.textContent = total > 0 ? `${total} ждут` : 'пусто';
            badgeEl.style.color = total > 0 ? '#fbbf24' : '#adadb8';
        }
    } catch (e) {
        // Silent fail — badge не критичен
    }
}

// Make global
window.openCasesModal = openCasesModal;
window.pollCasesBadge = pollCasesBadge;
