// Local browser fixture, no production requests. NODE_PATH may point at bundled playwright.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const front = path.join(root, 'Расширение/frontend');

async function main() {
    for (const shell of ['extension.html', 'mobile.html']) {
        const html = fs.readFileSync(path.join(front, shell), 'utf8');
        assert(html.includes('id="bnr-equipment-shop"'), `${shell}: lower Inventory equipment shop missing`);
        assert(html.includes('viewer-bannerlord-equipment.js'), `${shell}: shop script missing`);
    }
    const browser = await chromium.launch({headless: true});
    try {
        const page = await browser.newPage({viewport: {width: 340, height: 1000}});
        const errors = [];
        page.on('pageerror', e => errors.push(e.message));
        await page.setContent('<meta charset="utf-8"><div id="bannerlord-content"><div class="bnr-tab-pane active" data-bnr-pane="inventory"><div class="card" id="bnr-equipment-shop"></div><div id="bnr-legacy-equipment"></div></div></div>');
        await page.addStyleTag({path: path.join(front, 'viewer.css')});
        await page.evaluate(() => {
            window.API_URL = 'https://fixture.invalid'; window.authToken = 'viewer';
            window.escapeHtml = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            window.actions = [];
            window.ShedLink = {buyAction: async (...args) => {window.actions.push(args.slice(0,3));return {success:true};}};
            window.fixture = {success:true,ready:true,can_manage:true,has_hero:true,hero_level:25,gold:50000,pending:false,
                tiers:[{tier:4,required_level:25},{tier:5,required_level:30}],
                items:[{item_id:'sword',name:'Меч <img src=x onerror=alert(1)>',tier:4,required_level:25,price_gold:1234,category:'OneHandedWeapon',slots:['Weapon0','Weapon1'],stats:{weight:1.2},can_buy:true},
                    {item_id:'bow',name:'Длинный лук',tier:5,required_level:30,price_gold:5000,category:'Bow',slots:['Weapon0','Weapon1'],stats:{},can_buy:false,reason:'Нужен уровень 30'}],
                inventory:[{owned_id:'owned-sword',item_id:'sword',name:'Старый меч',tier:3,slot:null,category:'OneHandedWeapon',slots:['Weapon0','Weapon1'],stats:{}}]};
            window.fetch = async () => ({ok:true,json:async () => window.fixture});
        });
        await page.addScriptTag({path:path.join(front,'viewer-bannerlord-equipment.js')});
        await page.evaluate(() => loadBannerlordEquipmentShop());
        assert.equal(await page.locator('[data-bnr-eq-buy="sword"]').count(),1);
        assert.equal(await page.locator('[data-bnr-eq-buy="bow"]').isDisabled(),true,'tier lock is visible');
        assert.equal(await page.locator('#bnr-equipment-shop img').count(),0,'catalog text is escaped');
        assert((await page.locator('#bnr-equipment-shop').innerText()).includes('1 234'),'exact dinar price');
        await page.locator('[data-bnr-eq-search]').fill('Длинный');
        assert.equal(await page.locator('[data-bnr-eq-buy="sword"]').count(),0);
        await page.evaluate(() => loadBannerlordEquipmentShop());
        assert.equal(await page.locator('[data-bnr-eq-search]').inputValue(),'Длинный','poll preserves search');
        await page.locator('[data-bnr-eq-search]').fill('');
        await page.locator('[data-bnr-eq-buy="sword"]').click();
        assert.deepEqual(await page.evaluate(() => actions[0]),['bannerlord','hero.buy_equipment',{item_id:'sword'}]);
        await page.evaluate(() => loadBannerlordEquipmentShop());
        await page.locator('[data-bnr-eq-view="owned"]').click();
        await page.locator('[data-bnr-eq-slot="owned-sword"]').selectOption('Weapon1');
        await page.locator('[data-bnr-eq-equip="owned-sword"]').click();
        assert.deepEqual(await page.evaluate(() => actions[1]),['bannerlord','hero.equip_owned',{owned_id:'owned-sword',slot:'Weapon1'}]);
        await page.evaluate(() => {fixture.can_manage=false;fixture.reason='Игра не на связи'; return loadBannerlordEquipmentShop();});
        assert.equal(await page.locator('[data-bnr-eq-equip="owned-sword"]').isDisabled(),true);
        await page.locator('[data-bnr-eq-view="shop"]').click();
        assert.equal(await page.locator('[data-bnr-eq-buy="sword"]').isDisabled(),true,'offline refuses even stale can_buy');
        for (const width of [340,372]) {
            await page.setViewportSize({width,height:1000});
            assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),'no horizontal overflow '+width);
        }
        await page.evaluate(() => {fixture.has_hero=false;fixture.can_manage=false;fixture.inventory=[];fixture.reason='Сначала создай героя'; return loadBannerlordEquipmentShop();});
        assert((await page.locator('#bnr-equipment-shop').innerText()).includes('Сначала создай героя'));
        await page.evaluate(() => {fixture.can_manage=true;fixture.has_hero=true;fixture.reason='';return loadBannerlordEquipmentShop();});
        const evidence=path.join(root,'dist/audit/equipment-shop');fs.mkdirSync(evidence,{recursive:true});
        await page.screenshot({path:path.join(evidence,'inventory-shop-372.png'),fullPage:true});
        await page.evaluate(() => {window.fetch=async()=>{throw Error('offline')}; return loadBannerlordEquipmentShop();});
        assert.equal(await page.locator('[data-bnr-eq-buy]').count(),0,'failed refresh removes actionable stale catalog');
        assert.deepEqual(errors,[]);
        console.log('PASS: shells, exact item purchase, owned slot equip, tier/offline locks, escaping, search persistence, 340/372px, fetch failure');
    } finally {await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
