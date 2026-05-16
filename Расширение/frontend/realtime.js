// frontend/realtime.js — Twitch Extension PubSub client (Phase C, 2026-05-17).
//
// Subscribes на Twitch.ext.listen('broadcast') + 'whisper-<opaqueId>',
// парсит envelopes от backend/pubsub.py, dedupe по seq per (channel, type),
// диспатчит подписанным handler'ам.
//
// Envelope contract (см. backend/pubsub.py:_make_envelope):
//   {v: 1, type: "<event>", seq: N, ts: <unix_ms>, data: {...}}
//
// Public API:
//   RealtimeBus.init() — вызвать после Twitch.ext.onAuthorized
//   RealtimeBus.on(type, fn) — подписаться (fn(data, envelope))
//   RealtimeBus.off(type, fn) — отписаться
//
// Wire:
//   <script src="realtime.js?v=..."></script>  ПЕРЕД viewer.js
//   В viewer.js onAuthorized:  RealtimeBus.init(auth.userId);
//
// Security:
//   - НЕ доверять envelope.data как authoritative для финансовых операций
//   - НЕ использовать innerHTML с data из payload (XSS) — только textContent
//   - Frontend всё ещё refresh'ит state через JWT-protected API для critical actions

(function (global) {
    'use strict';

    const RealtimeBus = {
        _handlers: Object.create(null),     // {type: [fn, fn, ...]}
        _lastSeq:  Object.create(null),     // {type: N} — последний seen seq per type
        _ready:    false,
        _opaqueId: null,
        _debug:    false,                   // включи в DevTools: RealtimeBus._debug = true
    };

    function _log() {
        if (!RealtimeBus._debug) return;
        const args = ['[realtime]'].concat(Array.from(arguments));
        console.log.apply(console, args);
    }

    function _onMessage(target, contentType, message) {
        // target = 'broadcast' или 'whisper-<opaqueId>'
        // contentType = 'application/json' (мы всегда шлём JSON)
        // message = raw string envelope
        let env;
        try {
            env = JSON.parse(message);
        } catch (e) {
            console.warn('[realtime] bad envelope JSON:', e.message);
            return;
        }
        if (!env || env.v !== 1 || !env.type) {
            console.warn('[realtime] invalid envelope shape:', env);
            return;
        }

        // Dedupe по seq per type. Out-of-order или повторно — drop.
        // PubSub при network issue может re-deliver; backend monotonic seq.
        const lastSeq = RealtimeBus._lastSeq[env.type] || 0;
        if (env.seq && env.seq <= lastSeq) {
            _log('drop stale', env.type, 'seq=', env.seq, '<=', lastSeq);
            return;
        }
        RealtimeBus._lastSeq[env.type] = env.seq;

        _log('recv', env.type, 'seq=', env.seq, 'data=', env.data);

        const handlers = RealtimeBus._handlers[env.type];
        if (!handlers || !handlers.length) {
            _log('no handlers for', env.type);
            return;
        }
        for (let i = 0; i < handlers.length; i++) {
            try {
                handlers[i](env.data || {}, env);
            } catch (e) {
                console.error('[realtime] handler error for', env.type, e);
            }
        }
    }

    RealtimeBus.init = function (opaqueUserId) {
        if (RealtimeBus._ready) {
            _log('init called twice — ignored');
            return;
        }
        if (typeof Twitch === 'undefined' || !Twitch.ext || !Twitch.ext.listen) {
            console.warn('[realtime] Twitch.ext.listen недоступен — PubSub отключён');
            return;
        }
        try {
            Twitch.ext.listen('broadcast', _onMessage);
            _log('listening broadcast');
        } catch (e) {
            console.warn('[realtime] listen(broadcast) failed:', e);
        }
        // Whisper: персональный канал. Twitch.ext.listen('whisper-<opaqueId>'),
        // не listen('whisper'). opaqueUserId формата 'U<digits>'.
        if (opaqueUserId) {
            RealtimeBus._opaqueId = opaqueUserId;
            try {
                Twitch.ext.listen('whisper-' + opaqueUserId, _onMessage);
                _log('listening whisper-' + opaqueUserId);
            } catch (e) {
                console.warn('[realtime] listen(whisper-) failed:', e);
            }
        }
        RealtimeBus._ready = true;
    };

    RealtimeBus.on = function (type, fn) {
        if (typeof fn !== 'function') return;
        const arr = RealtimeBus._handlers[type] || (RealtimeBus._handlers[type] = []);
        arr.push(fn);
    };

    RealtimeBus.off = function (type, fn) {
        const arr = RealtimeBus._handlers[type];
        if (!arr) return;
        const idx = arr.indexOf(fn);
        if (idx >= 0) arr.splice(idx, 1);
    };

    // Удобный helper для модулей: подписаться + auto-cleanup при close.
    // Например, в voting modal `unsub = RealtimeBus.subscribe('vote_tick', applyTick)`
    // и при закрытии модалки `unsub()`.
    RealtimeBus.subscribe = function (type, fn) {
        RealtimeBus.on(type, fn);
        return function unsub() { RealtimeBus.off(type, fn); };
    };

    global.RealtimeBus = RealtimeBus;
})(window);
