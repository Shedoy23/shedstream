const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium} = require('playwright');

(async () => {
    const browser = await chromium.launch({headless:true,...(process.platform === 'win32' ? {channel:'msedge'} : {})});
    try {
        const page = await browser.newPage({viewport:{width:340,height:1000}});
        const errors=[];page.on('pageerror',error=>errors.push(error.message));
        await page.setContent('<meta charset="utf-8"><div id="bannerlord-content"><div class="card" id="bnr-equipment-shop"></div></div>');
        await page.addStyleTag({path:path.join(__dirname,'../Расширение/frontend/viewer.css')});
        await page.evaluate(() => {
            window.API_URL='https://fixture.invalid';window.authToken='test';
            window.escapeHtml=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            window.actions=[];window.confirmations=[];window.choice=false;
            window._bnrConfirmDanger=async message=>{confirmations.push(message);return choice;};
            window.ShedLink={buyAction:async (...args)=>{actions.push(args.slice(0,3));return {success:true};}};
            window.fixture={success:true,ready:true,can_manage:true,hero_level:30,gold:500,pending:false,
                party_inventory:{available:false,reason:'no_party_inventory',message:'Нет багажа'},tiers:[],
                inventory:[{owned_id:'old-id',item_id:'old',name:'Старый меч',slot:'weapon0',slots:['weapon0']}],
                items:[{item_id:'sword',name:'Меч <img src=x>',category:'one_handed',tier:1,required_level:1,price_gold:1000,can_buy:true,purchase_mode:'equip',
                    purchase_options:[{slot:'weapon0',replace_owned_id:'old-id',replace_item_id:'old',replace_modifier_id:'fine',replaced_name:'Старый меч <img src=x>',trade_in_gold:600,net_price_gold:400,can_buy:true},
                        {slot:'weapon1',replace_owned_id:'',replace_item_id:'',replace_modifier_id:'',trade_in_gold:0,net_price_gold:1000,can_buy:false,reason:'insufficient_gold',message:'Недостаточно динаров героя'}]}]};
            window.fetch=async()=>({ok:true,json:async()=>structuredClone(fixture)});
        });
        await page.addScriptTag({path:path.join(__dirname,'../Расширение/frontend/viewer-bannerlord-equipment.js')});
        await page.evaluate(()=>loadBannerlordEquipmentShop());
        const buy=page.locator('[data-bnr-eq-buy="sword"]');
        assert((await buy.innerText()).includes('Купить и надеть'));
        assert((await buy.innerText()).includes('400'));
        assert.equal(await page.locator('img').count(),0);
        await page.locator('[data-bnr-eq-purchase-slot]').selectOption('weapon1');
        assert(await buy.isDisabled(),'selected unaffordable empty slot is blocked');
        await page.locator('[data-bnr-eq-purchase-slot]').selectOption('weapon0');
        await buy.click();
        assert.equal(await page.evaluate(()=>actions.length),0,'cancel does not send purchase');
        assert((await page.evaluate(()=>confirmations[0])).includes('будет продан за 600'));
        await page.evaluate(()=>{choice=true;});
        await buy.click();
        assert.deepEqual(await page.evaluate(()=>actions[0]),['bannerlord','hero.buy_equipment',{
            item_id:'sword',equip_now:true,slot:'weapon0',replace_owned_id:'old-id',replace_item_id:'old',
            replace_modifier_id:'fine',expected_price_gold:1000,expected_trade_in_gold:600}]);
        assert(await buy.isDisabled(),'in-flight purchase cannot repeat');
        await page.evaluate(()=>loadBannerlordEquipmentShop());
        await page.locator('[data-bnr-eq-view="owned"]').click();
        assert(await page.locator('[data-bnr-eq-unequip]').isDisabled(),'no baggage cannot receive unequipped gear');
        assert(await page.locator('[data-bnr-eq-discard]').isDisabled(),'shop access does not unlock unrelated inventory actions');
        await page.locator('[data-bnr-eq-view="shop"]').click();
        await page.evaluate(()=>{fixture.items[0].purchase_options[0].trade_in_gold=1200;fixture.items[0].purchase_options[0].net_price_gold=-200;return loadBannerlordEquipmentShop();});
        assert((await buy.innerText()).includes('Получишь 200'));
        await page.screenshot({path:path.join(__dirname,'../dist/audit/equipment-shop/no-party-340.png'),fullPage:true});
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false,'mobile layout fits');
        assert.deepEqual(errors,[]);
        console.log('PASS no-party shop UI: slot quotes, cancel/confirm, escaping, pending, inventory gates, mobile');
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
