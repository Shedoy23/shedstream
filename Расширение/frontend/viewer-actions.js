/* viewer-actions.js — ОДИН платный путь для всех игровых модулей.
 *
 * Зачем (анализ 2026-08-19, docs/FRONTEND_MODULE_ARCH_PLAN.md §1):
 * каждая игра писала покупку заново и каждая копия теряла часть защит.
 * Bannerlord имел идемпотентность, серверный кулдаун, отказ по роли и
 * обновление баланса; ShedColony — только идемпотентность (и показывал
 * устаревший баланс после покупки); RimWorld не шлёт client_action_id вовсе.
 * Механизм расхождения: новая игра копирует соседнюю и берёт не всё.
 * Лечится не дисциплиной, а одной функцией.
 *
 * Грузится ПЕРЕД viewer.js. Namespace `window.ShedLink` — файл намеренно
 * не объявляет глобальных функций (линтер check_frontend_global_collisions:
 * плоские <script> живут в одном пространстве имён, два одинаковых имени
 * молча съедают друг друга — так 22.07 сломались покупки в магазине).
 *
 * При загрузке НЕ трогает document — поэтому тестируется в node без браузера:
 * `node tests/test_buy_action.js` рядом с этим файлом.
 *
 * Зависимости берутся из global в момент вызова (showNotification, loadUserData,
 * isAuthUser, API_URL, authToken, fetch), а не при загрузке — чтобы порядок
 * <script> не имел значения и чтобы тест мог их подменить.
 */
(function (global) {
    'use strict';

    var ShedLink = global.ShedLink || (global.ShedLink = {});

    // Ключ "игра:действие" → true, пока запрос в полёте. Дабл-клик по одной
    // кнопке = два charge'а на бэке, второй ответ мог прийти отказом, а деньги
    // списаны дважды. Single-flight на клиенте — первый барьер, идемпотентность
    // на бэке — второй.
    var _inflight = {};

    function _notify(msg, type, ms) {
        if (typeof global.showNotification === 'function') {
            global.showNotification(msg, type, ms);
        }
    }

    function _dbg() {
        if (typeof global.dbg === 'function') {
            global.dbg.apply(null, arguments);
        }
    }

    // crypto.randomUUID есть на HTTPS (Twitch Extension всегда HTTPS).
    // Fallback — время+random, для локальной отладки по http.
    ShedLink.newClientActionId = function () {
        if (global.crypto && typeof global.crypto.randomUUID === 'function') {
            return global.crypto.randomUUID();
        }
        return Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
    };

    /**
     * Платное действие игрового модуля: POST /api/<game>/action.
     *
     * @param {string} game        id модуля ('bannerlord' | 'shedcolony' | ...)
     * @param {string} actionType  тип действия, как его знает бэкенд
     * @param {object} data        полезная нагрузка (client_action_id добавится сам)
     * @param {object} [opts]
     *   successMessage      — текст тоста на успехе вместо result.message.
     *                         ОБЯЗАТЕЛЕН для отложенных действий: зритель должен
     *                         понять, что это заявка, а не «ничего не произошло»
     *                         (баги #16/#17 — зритель объявил войну 4 раза подряд).
     *   failMessage         — текст тоста на отказе, если бэк молчит.
     *   successToastMs / errorToastMs / networkToastMs — длительности тостов.
     *   networkErrorMessage — текст на сетевой ошибке.
     *   onCooldown(key, s)  — проставить кулдаун на кнопке (у кого он есть).
     *   cooldownAttr        — атрибут кнопки с отсчётом ('data-bnr-cd').
     *                         Если такая кнопка есть, отказ по кулдауну НЕ
     *                         показывает тост: отсчёт уже виден на кнопке.
     *   onSuccess(result)   — что перечитать после успеха (панель игры).
     *
     * @returns {Promise<object|null>} ответ бэкенда; null — не отправляли
     *          (не авторизован / дубль клика) или сеть/JSON упали.
     */
    ShedLink.buyAction = async function (game, actionType, data, opts) {
        opts = opts || {};

        if (typeof global.isAuthUser === 'function' && !global.isAuthUser()) {
            _notify('⚠️ Войдите через Twitch', 'warning');
            return null;
        }

        var key = game + ':' + actionType;
        if (_inflight[key]) {
            console.warn('[buyAction] duplicate-click guarded', key);
            return null;
        }
        _inflight[key] = true;

        // Идемпотентность: бэк держит UNIQUE (channel_id, module_id,
        // client_action_id) — ретрай после сетевого сбоя или proxy-replay
        // вернёт тот же action_id вместо второго списания.
        var clientActionId = ShedLink.newClientActionId();
        var payload = Object.assign({}, data || {}, { client_action_id: clientActionId });

        try {
            var r = await global.fetch(global.API_URL + '/api/' + game + '/action', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Twitch-JWT': global.authToken || '',
                },
                body: JSON.stringify({ action_type: actionType, data: payload }),
            });
            var result = await r.json();

            _dbg('[' + game + ' action]', actionType,
                 result.success ? '✓' : '✗',
                 result.message || '(no message)',
                 result.perk ? '(perk=' + result.perk + ' ×' + result.perk_price_mult + ')' : '');

            var toastMsg = (result.success && opts.successMessage)
                || result.message
                || (result.success ? 'OK' : (opts.failMessage || 'Действие не выполнено'));

            // Скидка по роли канала (broadcaster/moderator). Подписки — только
            // косметика и в этот путь не попадают (Twitch ToS).
            if (result.success && result.perk && result.perk_price_mult < 1.0) {
                var perkIcons = { broadcaster: '👑', moderator: '🛡️' };
                var icon = perkIcons[result.perk] || '✨';
                toastMsg = toastMsg + ' (' + icon + ' ×' + result.perk_price_mult.toFixed(2) + ' price)';
            }

            // Отказ по роли — помечаем замком, чтобы зритель не думал, что баг.
            if (!result.success && result.required_role) {
                toastMsg = '🔒 ' + toastMsg;
                _dbg('[FE-GATE]', actionType,
                     'required=' + result.required_role + ' your=' + result.your_role);
            }

            if (result.idempotent_replay) {
                _dbg('[FE-IDEM] retry hit', actionType, 'action_id=' + result.action_id);
            }

            // Кулдаун: на успехе запускаем отсчёт сразу, на отказе по кулдауну
            // синхронизируем остаток. Тост в этом случае лишний — кнопка тикает.
            var isCdReject = !result.success
                && typeof result.cooldown_remaining_s === 'number'
                && result.cooldown_remaining_s > 0;
            if (typeof opts.onCooldown === 'function') {
                if (result.success
                    && typeof result.cooldown_applied_s === 'number'
                    && result.cooldown_applied_s > 0) {
                    opts.onCooldown(actionType, result.cooldown_applied_s);
                }
                if (isCdReject) {
                    opts.onCooldown(actionType, result.cooldown_remaining_s);
                }
            }
            var hasCdBtn = false;
            if (opts.cooldownAttr && global.document) {
                try {
                    hasCdBtn = !!global.document.querySelector(
                        '[' + opts.cooldownAttr + '="' + actionType + '"]');
                } catch (_) { hasCdBtn = false; }
            }

            if (!(isCdReject && hasCdBtn)) {
                _notify(toastMsg,
                        result.success ? 'success' : 'error',
                        result.success
                            ? (opts.successToastMs || 3500)
                            : (opts.errorToastMs || 6000));
            }

            if (result.success) {
                // Баланс крустиков — ВСЕГДА и для всех игр. Именно этой строки
                // не было у ShedColony: панель рисовала баланс из кэша, который
                // обновлялся раз в 60 с, зритель видел непотраченные крустики и
                // жал покупку второй раз.
                if (typeof global.loadUserData === 'function') global.loadUserData();
                if (typeof opts.onSuccess === 'function') opts.onSuccess(result);
            }

            return result;
        } catch (e) {
            console.error('[' + game + ' action] network/json error', actionType, e);
            _notify(opts.networkErrorMessage || ('Ошибка сети: ' + (e.message || e)),
                    'error', opts.networkToastMs);
            return null;
        } finally {
            delete _inflight[key];
        }
    };

    // Для node-теста: сбросить single-flight между кейсами.
    ShedLink._resetInflight = function () { _inflight = {}; };

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = ShedLink;
    }
})(typeof window !== 'undefined' ? window : globalThis);
