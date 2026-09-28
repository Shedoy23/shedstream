// OBS-only companion animation. Never loaded by the frozen Twitch shells.
(function (global) {
    'use strict';
    const VARIANTS = ['wayfarer', 'crimson_knight', 'colony_engineer', 'lantern_mage', 'shadow_rogue', 'rain_fisher', 'necro_cat', 'chest_mimic', 'mushroom_grandpa', 'baker_dragon', 'blanket_ghost', 'frog_samurai'];
    const images = new Map();
    let cards = [], running = false, lastDraw = 0;

    function supports(variant) { return VARIANTS.includes(variant); }
    function render(variant) {
        if (!supports(variant)) return '';
        return `<canvas class="pet-companion" width="256" height="256" data-pet-variant="${variant}" aria-label="Питомец" style="display:block;width:128px;height:128px;image-rendering:pixelated;margin:auto"></canvas>`;
    }
    function poseAt(progress, seconds, direction, variant, greeting) {
        const p = ((progress % 1) + 1) % 1;
        const walking = (p >= 0.3 && p < 0.5) || p >= 0.8;
        if (walking) return {frame: 1 + Math.floor(seconds / 0.22) % 2, flip: (p >= 0.8 ? -direction : direction) < 0};
        if (greeting) return {frame: 3, flip: false};
        if ((p > 0.55 && p < 0.72) || (variant === 'lantern_mage' && p > 0.04 && p < 0.24)) return {frame: 4, flip: false};
        if (p >= 0.72 && p < 0.78) return {frame: 5, flip: false};
        return {frame: 0, flip: false};
    }
    function sceneAt(progress, iteration, duration, seed) {
        if (!Number.isFinite(duration) || duration < 30 || (iteration + seed) % 2 !== 0) return null;
        const elapsed = (progress - (.06 + (seed % 12) * .01)) * duration;
        return elapsed >= 0 && elapsed < 4.2 ? Math.min(5, Math.floor(elapsed / .7)) : null;
    }
    function draw(now) {
        cards = cards.filter(c => c.canvas.isConnected);
        if (!cards.length) { running = false; return; }
        if (now - lastDraw >= 80) {
            lastDraw = now;
            for (const c of cards) {
                if (global.PetLiving && global.PetLiving.draw(c, now)) continue;
                if (!c.image.complete || !c.image.naturalWidth) continue;
                const animation = c.card.getAnimations().find(a => a.animationName === 'pet-walk');
                const timing = animation && animation.effect.getComputedTiming();
                const p = timing && timing.progress !== null ? timing.progress : 0;
                const reduced = global.matchMedia('(prefers-reduced-motion: reduce)').matches;
                const greeting = now - c.born < 3000;
                let pose = reduced ? {frame: 0, flip: false} : poseAt(p, now / 1000, c.direction, c.variant, greeting);
                const scene = !reduced && !greeting && timing && c.scene.complete && c.scene.naturalWidth
                    ? sceneAt(p, timing.currentIteration, Number(animation.effect.getTiming().duration) / 1000, c.seed) : null;
                const activeScene = scene !== null;
                if (activeScene) pose = {frame: scene, flip: false};
                const key = activeScene + ':' + pose.frame + ':' + pose.flip;
                if (key === c.last) continue;
                c.last = key;
                c.canvas.dataset.pose = String(pose.frame);
                c.canvas.dataset.action = activeScene ? 'scene' : 'base';
                const ctx = c.canvas.getContext('2d');
                ctx.clearRect(0, 0, 256, 256);
                ctx.save();
                if (pose.flip) { ctx.translate(256, 0); ctx.scale(-1, 1); }
                ctx.imageSmoothingEnabled = false;
                ctx.drawImage(activeScene ? c.scene : c.image, pose.frame * 256, 0, 256, 256, 0, 0, 256, 256);
                ctx.restore();
            }
        }
        global.requestAnimationFrame(draw);
    }
    function attach(strip) {
        const old = new Map(cards.map(c => [c.canvas, c]));
        const previous = new Map(cards.map(c => [c.identity, c]));
        cards = Array.from(strip.querySelectorAll('.pet-companion')).map(canvas => {
            if (old.has(canvas)) return old.get(canvas);
            const variant = canvas.dataset.petVariant;
            if (!images.has(variant)) {
                const image = new Image();
                image.src = `pet-assets/v2/${variant}/${variant === 'blanket_ghost' ? 'animation' : 'animation-v2'}.png`;
                images.set(variant, image);
                const scene = new Image();
                scene.src = `pet-assets/v2/${variant}/scene-v1.png`;
                images.set(variant + ':scene', scene);
            }
            const card = canvas.closest('.pet-card');
            // Level updates rebuild the strip. Keep each viewer's animation state,
            // but a new skin gets its own greeting and controller.
            const identity = (card.querySelector('.pet-card-name')?.textContent || '').replace(/^\[\d+\s*lvl\]\s*/, '') + ':' + variant;
            const seed = Array.from(identity).reduce((h,ch) => ((h * 31 + ch.charCodeAt(0)) >>> 0), 0) % 1000;
            canvas.dataset.sceneSeed = String(seed);
            const prior = previous.get(identity);
            return {canvas, card, variant, identity, seed, image: images.get(variant), scene: images.get(variant + ':scene'), direction: parseFloat(card.style.getPropertyValue('--walk-amp')) < 0 ? -1 : 1, born: prior ? prior.born : performance.now(), living: prior && prior.living, last: ''};
        });
        if (!running && cards.length) { running = true; global.requestAnimationFrame(draw); }
    }
    global.PetCompanions = {supports, render, attach, poseAt, sceneAt};
})(typeof window !== 'undefined' ? window : globalThis);
