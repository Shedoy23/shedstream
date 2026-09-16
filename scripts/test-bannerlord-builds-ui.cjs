const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root=path.resolve(__dirname,'..');
const front=path.join(root,'Расширение/frontend');
async function main() {
    for (const file of ['extension.html','mobile.html'])
        assert(fs.readFileSync(path.join(front,file),'utf8').includes('viewer-bannerlord-builds.js'),file+': new build UI is not connected');
    const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});
    try {
        const page=await browser.newPage({viewport:{width:340,height:1050}});
        const errors=[];page.on('pageerror',e=>errors.push(e.message));
        await page.setContent('<meta charset="utf-8"><div class="card" id="hero-class-picker-slot"></div><div class="card" id="bnr-active-powers-slot"></div>');
        await page.addStyleTag({path:path.join(front,'viewer.css')});
        await page.evaluate(()=>{
            window.API_URL='https://fixture.invalid';window.authToken='test';
            window.escapeHtml=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            window._bannerlordCooldowns=[];window._bannerlordBuffs=[];window.battleReady=false;
            window.bnrCanUseActivePowers=()=>battleReady;window.calls=[];
            window._bannerlordBuyAction=async(type,payload)=>{calls.push([type,payload]);return {success:true};};
            window.fixture={success:true,ready:true,has_hero:true,can_manage:true,pending:false,build:{version:1,
                specialization:'guardian',selected_weapon_type:'two_handed',selected_power:'cleave',starter_claimed:false,
                can_manage:true,in_battle:false,weapon_power_cooldown_until:0,
                specializations:[{id:'guardian',label:'Защитник',description:'+15% здоровья'},{id:'assault',label:'Натиск',description:'+10% урона в ближнем бою'}],
                power_options:[{weapon_type:'two_handed',power_key:'cleave',label:'Рассечение',description:'Удар по соседним противникам',skill:'TwoHanded',skill_level:75,rank:2,value:0.4,price:250,available:true},
                    {weapon_type:'bow',power_key:'explosive_arrows',label:'Взрывные стрелы',description:'Взрыв при попадании',skill:'Bow',skill_level:5,rank:1,value:0.25,price:300,available:false,reason:'Надень лук и стрелы'}],
                starter_kits:[{id:'infantry',label:'Меч и щит',available:true,items:[{name:'Простой меч <img src=x>'},{name:'Щит'}]},
                    {id:'archer',label:'Лучник',available:false,reason:'Нет базовых стрел',items:[]}],
                common_powers:[{power_key:'heal_burst',label:'Лечение',price:125,value:50,description:'Восстановить здоровье'}]}};
            window.fetch=async()=>({ok:true,json:async()=>structuredClone(fixture)});
        });
        await page.addScriptTag({path:path.join(front,'viewer-bannerlord-builds.js')});
        const mainSource=fs.readFileSync(path.join(front,'viewer-bannerlord.js'),'utf8');
        await page.addScriptTag({content:mainSource.slice(mainSource.indexOf('function _renderBannerlordDetachmentPanel('),mainSource.indexOf('function _renderBannerlordStance('))});
        await page.evaluate(()=>loadBannerlordBuild());
        await page.evaluate(()=>{
            document.body.insertAdjacentHTML('beforeend','<div id="bnr-detachment-slot"></div>');
            window._bannerlordClassesCache={current:null};window._bnrPrice=(_,fallback)=>fallback;
            fixture.build.is_mounted=true;fixture.build.power_options[1].available=true;
            return loadBannerlordBuild();
        });
        await page.evaluate(()=>_renderBannerlordDetachmentPanel({in_battle:true,my_stats:{alive:true}}));
        assert.equal(await page.locator('[data-det-act="hero.detach_raid"]').count(),1,'mounted free build can raid without legacy class');
        assert.equal(await page.locator('[data-det-act="hero.detach_skirmish"]').count(),1,'ranged free build can skirmish without legacy class');
        await page.evaluate(()=>{fixture.build.is_mounted=false;fixture.build.power_options[1].available=false;document.getElementById('bnr-detachment-slot').remove();return loadBannerlordBuild();});
        assert.equal(await page.locator('[data-bnr-build-spec="guardian"]').getAttribute('aria-pressed'),'true');
        assert.equal(await page.locator('[data-bnr-build-starter="archer"]').isDisabled(),true);
        assert.equal(await page.locator('img').count(),0);
        await page.locator('[data-bnr-build-spec="assault"]').click();
        assert.deepEqual(await page.evaluate(()=>calls[0]),['hero.set_specialization',{specialization:'assault'}]);
        assert.equal(await page.locator('[data-bnr-build-starter="infantry"]').isDisabled(),true,'pending action serializes configuration');
        await page.evaluate(()=>loadBannerlordBuild());
        await page.locator('[data-bnr-build-starter="infantry"]').click();
        assert.deepEqual(await page.evaluate(()=>calls[1]),['hero.claim_starter',{starter_kit:'infantry'}]);
        await page.evaluate(()=>{fixture.build.starter_claimed=true;return loadBannerlordBuild();});
        assert.equal(await page.locator('[data-bnr-build-starter]').count(),0,'claimed kit cannot be claimed again');
        assert.equal(await page.locator('[data-bnr-build-select="bow"]').isDisabled(),true);
        await page.evaluate(()=>{fixture.build.selected_weapon_type='';fixture.build.selected_power='';return loadBannerlordBuild();});
        await page.locator('[data-bnr-build-select="two_handed"]').click();
        assert.deepEqual(await page.evaluate(()=>calls[2]),['hero.select_weapon_power',{weapon_type:'two_handed'}]);
        await page.evaluate(()=>{fixture.build.selected_weapon_type='two_handed';fixture.build.selected_power='cleave';return loadBannerlordBuild();});
        assert.equal(await page.locator('[data-bnr-build-activate="cleave"]').isDisabled(),true,'no active hero in battle');
        await page.evaluate(()=>{battleReady=true;return loadBannerlordBuild();});
        await page.locator('[data-bnr-build-activate="cleave"]').click();
        assert.deepEqual(await page.evaluate(()=>calls[3]),['power.activate',{power_key:'cleave'}]);
        await page.evaluate(()=>{fixture.build.weapon_power_cooldown_until=Date.now()/1000+89;return loadBannerlordBuild();});
        assert.equal(await page.locator('[data-bnr-build-activate="cleave"]').isDisabled(),true,'shared weapon cooldown visible');
        assert.equal(await page.locator('[data-bnr-build-activate="heal_burst"]').isDisabled(),false,'healing cooldown independent');
        await page.evaluate(()=>{fixture.build.weapon_power_cooldown_until=0;fixture.cooldown_remaining_s=88;return loadBannerlordBuild();});
        assert.equal(await page.locator('[data-bnr-build-activate="cleave"]').isDisabled(),true,'server cooldown survives refresh before save snapshot');
        await page.evaluate(()=>{fixture.build.in_battle=true;fixture.can_manage=false;fixture.reason='Менять сборку можно между боями';return loadBannerlordBuild();});
        assert.equal(await page.locator('[data-bnr-build-spec="assault"]').isDisabled(),true);
        for(const width of [340,372]) {await page.setViewportSize({width,height:1050});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no overflow '+width);}
        const evidence=path.join(root,'dist/audit/free-builds');fs.mkdirSync(evidence,{recursive:true});
        await page.screenshot({path:path.join(evidence,'builds-372.png'),fullPage:true});
        await page.evaluate(()=>{fetch=async()=>{throw Error('network')};return loadBannerlordBuild();});
        assert.equal(await page.locator('[data-bnr-build-activate]').count(),0,'network failure removes stale action buttons');
        await page.evaluate(()=>{fetch=async()=>({ok:true,json:async()=>({success:true,enabled:true,ready:false,build:{}})});return loadBannerlordBuild();});
        assert.equal(await page.evaluate(()=>BnrBuilds.renderHero()),true,'equipment session with missing snapshot cannot show legacy class picker');
        assert.equal(await page.locator('[data-bnr-build-spec]').count(),0);
        assert.deepEqual(errors,[]);
        console.log('PASS: specialization, one-time starter, weapon selection, shared cooldown, healing, battle gate, escaping, narrow layout, stale network');
    } finally {await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
