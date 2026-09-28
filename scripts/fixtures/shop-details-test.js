/* Open shop-details.html through a local static server. No network or real purchases. */
function escapeHtml(value) {
    return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}
(() => {
    const log = [];
    const assert = (ok, label) => { if (!ok) throw new Error(label); log.push('PASS ' + label); };
    const list = document.getElementById('shop-list');
    const calls = [];
    buyShopItem = (...args) => calls.push(['item', ...args]);
    buyTrait = (...args) => calls.push(['trait', ...args]);
    buyGene = (...args) => calls.push(['gene', ...args]);
    const item = { type: 'apparel', name: 'Защитная маска', def: 'mask', cost: 50,
        description: '<img src=x onerror=alert(1)>', tooltip: 'Слот: тело\nЗащита +5%' };
    const trait = {type: 'trait', name: 'Быстроход', def: 'Speed', trait_def: 'Speed', degree: 1, cost: 60, description: '{PAWN_nameDef} быстро ходит. {PAWN_pronoun} успевает больше.', tooltip: 'Скорость +0,2'};
    const gene = {type: 'gene', name: 'Ген холода', def: 'Cold', cost: 200};
    const items = [item, trait, {...trait, degree: 2}, gene];
    try {
        renderShop(items);
        const controls = list.querySelectorAll('.rw-shop-inspect');
        assert(list.querySelectorAll('.rw-shop-details:not([hidden])').length === 0, 'collapsed initially');
        controls[0].click();
        assert(calls.length === 0, 'inspection never purchases');
        assert(!document.getElementById(controls[0].getAttribute('aria-controls')).hidden, 'item opens');
        assert(!list.querySelector('img'), 'catalog markup is escaped');
        controls[1].click();
        assert(list.querySelectorAll('.rw-shop-details:not([hidden])').length === 1, 'only one open');
        assert(!list.querySelector('.rw-shop-details:not([hidden])').textContent.includes('{PAWN_'), 'known pawn placeholders are readable');
        controls[2].click();
        assert(controls[1].getAttribute('aria-expanded') === 'false', 'trait degrees have separate identity');
        renderShop([...items].reverse());
        assert(list.querySelector('.rw-shop-inspect[aria-expanded=true]').dataset.itemKey.includes(',2]'), 'open item survives reorder');
        renderShop(items);
        list.querySelectorAll('.shop-buy-btn')[0].click();
        list.querySelectorAll('.shop-buy-btn')[1].click();
        assert(JSON.stringify(calls) === JSON.stringify([['item','mask'],['trait','Speed',1,'Быстроход',60]]), 'purchase routing and parameters preserved');
        assert(list.querySelectorAll('.shop-buy-btn')[3].disabled, 'unaffordable purchase stays disabled');
        list.querySelectorAll('.rw-shop-inspect')[3].click();
        assert(list.querySelector('.rw-shop-details:not([hidden])').textContent.includes('не хватает 100'), 'shortfall explained');
        assert(list.querySelector('.rw-shop-details:not([hidden])').textContent.includes('не передала описание'), 'missing description is explicit');
        list.querySelectorAll('.rw-shop-inspect')[0].click();
        document.getElementById('result').textContent = log.join('\n');
    } catch (error) { document.getElementById('result').textContent = log.join('\n') + '\nFAIL ' + error.message; throw error; }
})();
