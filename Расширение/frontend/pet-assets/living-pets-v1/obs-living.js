// OBS adapter for the shared 20-pose animator. Twitch shells do not load this file.
(function (global) {
    'use strict';
    const Animator = typeof module !== 'undefined' && module.exports
        ? require('./animator.js').PetAnimator : global.PetAnimator;

    class Motion {
        constructor(profile, seed) {
            this.animator = new Animator(profile);
            this.seed = seed;
            this.position = 0;
            this.direction = 1;
            this.turns = 0;
            this.manual = null;
            this.rest = 6000 + seed % 8000;
            this.braking = false;
        }
        request(intent) {
            if (intent !== null && !['idle', 'walk', 'sleep'].includes(intent)) throw Error('Unknown intent');
            this.manual = intent;
        }
        update(ms, distance, scale) {
            if (!Number.isFinite(ms) || ms < 0) throw Error('Invalid delta');
            // Bound integration error and keep the same gait on slow OBS frames.
            for (let remaining = ms; remaining > 0;) {
                const dt = Math.min(20, remaining); remaining -= dt;
                if (this.braking && this.animator.state === 'idle') {
                    this.braking = false;
                    this.direction *= -1;
                    this.turns++;
                    this.rest = this.turns % 2 === 0 ? 17000 + this.seed % 7000 : 4500 + this.seed % 4000;
                }
                this.rest = Math.max(0, this.rest - dt);
                let intent = this.manual === null
                    ? (this.rest > 0 ? (this.turns > 0 && this.turns % 2 === 0 ? 'sleep' : 'idle') : 'walk')
                    : this.manual;
                if (distance < 1 || !Number.isFinite(distance)) intent = 'idle';
                const room = (this.direction > 0 ? 1 - this.position : this.position) * distance;
                // The current walk cycle completes before stop: reserve its maximum
                // remaining travel plus the short deceleration, independent of tempo.
                if (intent === 'walk' && !this.braking && this.animator.state === 'walk'
                    && room <= 26 * scale * .89) this.braking = true;
                this.animator.request(this.braking ? 'idle' : intent);
                this.animator.update(dt);
                const travel = distance >= 1 ? this.animator.speed() * .5 * scale * dt / 1000 / distance : 0;
                this.position = Math.max(0, Math.min(1, this.position + this.direction * travel));
            }
        }
    }

    if (typeof module !== 'undefined' && module.exports) { module.exports = {Motion}; return; }
    const base = 'pet-assets/living-pets-v1/';
    const records = new WeakMap(), assets = new Map();
    let profiles = null;
    if (typeof Animator !== 'function') return;
    fetch(base + 'profiles.json?v=20260927a').then(r => {
        if (!r.ok) throw Error('profiles unavailable');
        return r.json();
    }).then(list => {
        if (!Array.isArray(list)) throw Error('invalid profiles');
        profiles = new Map(list.filter(p => /^[a-z_]+$/.test(p.id) && Number.isFinite(p.tempo) && p.tempo >= .2 && p.tempo <= 3).map(p => [p.id, p]));
    }).catch(() => { profiles = new Map(); });

    function load(variant) {
        if (!assets.has(variant)) {
            const result = {walk: new Image(), behaviour: new Image(), failed: false};
            for (const [sheet, file] of [['walk', 'walk-8.png'], ['behaviour', 'behaviour-12.png']]) {
                result[sheet].onerror = () => { result.failed = true; };
                result[sheet].src = base + 'assets/' + variant + '/' + file;
            }
            assets.set(variant, result);
        }
        return assets.get(variant);
    }
    function ready(image, columns) { return image.complete && image.naturalWidth === columns * 256 && image.naturalHeight === 256; }
    function fallback(c) {
        if (c.canvas.dataset.renderMode === 'living') {
            c.card.style.animation = '';
            c.card.style.transform = '';
            delete c.canvas.dataset.state;
            c.last = '';
        }
        c.canvas.dataset.renderMode = 'fallback';
        if (c.living) c.living.lastTime = null;
        return false;
    }
    function draw(c, now) {
        const profile = profiles && profiles.get(c.variant);
        if (!profile) return fallback(c);
        const atlas = load(c.variant);
        if (atlas.failed || !ready(atlas.walk, 8) || !ready(atlas.behaviour, 12)) return fallback(c);
        const state = c.living || (c.living = {
            motion: new Motion(profile, c.seed), lastTime: null,
            nextScene: c.born + 7000 + c.seed % 5000, sceneStart: null,
            reactionUntil: 0, previousState: 'idle'
        });
        records.set(c.canvas, state);
        const dt = state.lastTime === null ? 0 : Math.max(0, Math.min(250, now - state.lastTime));
        state.lastTime = now;
        const reduced = global.matchMedia('(prefers-reduced-motion: reduce)').matches;
        const greeting = now - c.born < 3000;
        const motion = state.motion;
        const amp = parseFloat(c.card.style.getPropertyValue('--walk-amp')) || 0;
        const scale = parseFloat(c.card.style.getPropertyValue('--depth-scale')) || 1;
        const sceneReady = ready(c.scene, 6);
        if (!reduced && !greeting && sceneReady && state.sceneStart === null
            && now >= state.nextScene && motion.animator.state === 'idle') state.sceneStart = now;
        if (state.sceneStart !== null && now - state.sceneStart >= 4200) {
            state.sceneStart = null;
            state.nextScene = now + 120000 + c.seed * 90;
        }
        const scene = !reduced && state.sceneStart !== null;
        if (!reduced && !greeting && !scene && now >= state.reactionUntil) {
            motion.update(dt, Math.abs(amp) * global.innerWidth / 100, scale);
            if (state.previousState === 'rise' && !['rise', 'wake'].includes(motion.animator.state)) state.reactionUntil = now + 900;
            state.previousState = motion.animator.state;
        }
        c.card.style.animation = 'none';
        c.card.style.transform = 'translateX(' + (amp * motion.position).toFixed(5) + 'vw)';
        const pose = reduced ? {sheet: 'behaviour', frame: 0, state: 'idle'} : motion.animator.pose();
        let image = atlas[pose.sheet], frame = pose.frame, action = 'living';
        if (!reduced && greeting && ready(c.image, 6)) { image = c.image; frame = 3; action = 'greeting'; }
        else if (scene) { image = c.scene; frame = Math.min(5, Math.floor((now - state.sceneStart) / 700)); action = 'scene'; }
        else if (!reduced && now < state.reactionUntil && ready(c.image, 6)) { image = c.image; frame = 5; action = 'reaction'; }
        const flip = action === 'living' && !reduced && motion.direction * (amp < 0 ? -1 : 1) < 0;
        c.canvas.dataset.renderMode = 'living';
        c.canvas.dataset.state = pose.state;
        c.canvas.dataset.pose = String(frame);
        c.canvas.dataset.action = action;
        c.canvas.dataset.flip = String(flip);
        const key = [action, pose.sheet, frame, flip].join(':');
        if (c.last !== key) {
            const ctx = c.canvas.getContext('2d');
            ctx.clearRect(0, 0, 256, 256);
            ctx.save();
            if (flip) { ctx.translate(256, 0); ctx.scale(-1, 1); }
            ctx.imageSmoothingEnabled = false;
            ctx.drawImage(image, frame * 256, 0, 256, 256, 0, 0, 256, 256);
            ctx.restore();
            c.last = key;
        }
        return true;
    }
    global.PetLiving = {
        draw,
        request(canvas, intent) { const s = records.get(canvas); if (s) s.motion.request(intent); },
        react(canvas) { const s = records.get(canvas); if (s && s.motion.animator.state === 'idle') s.reactionUntil = performance.now() + 900; }
    };
})(typeof window !== 'undefined' ? window : globalThis);
