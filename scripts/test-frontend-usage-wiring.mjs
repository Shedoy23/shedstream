// Execute the actual UI entry points: polling/rendering must not count as clicks,
// and a statistics failure must never block an action or leak its payload.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {parseHTML} from 'linkedom';
const front = new URL('../Расширение/frontend/', import.meta.url);
const source = name => readFileSync(new URL(name, front), 'utf8');
const tests = [];
function test(name, fn) { tests.push([name, fn]); }
function actionContext(usage) {
    let resolve;
    const requests = [];
    const context = vm.createContext({window:{ShedLink:{usage}}, console:{warn(){},log(){}},
        API_URL:'https://fixture.invalid', authToken:'fake-test-token', isAuthUser:()=>true,
        crypto:{randomUUID:()=> 'test-action-id'},
        fetch:(url,init)=>{requests.push([url,JSON.parse(init.body)]);return new Promise(done=>{resolve=done;});}});
    vm.runInContext(source('viewer-actions.js'), context);
    return {api:context.window.ShedLink,requests,finish:()=>resolve({json:async()=>({success:false,message:'test refusal'})})};
}
test('count attempts including duplicate guard, without recording action data', async()=>{
    const events=[];
    const c=actionContext({trackAction:(...args)=>events.push(args)});
    const first=c.api.buyAction('bannerlord','hero.rename_vassal',{new_name:'private-text',vassal_id:42});
    await c.api.buyAction('bannerlord','hero.rename_vassal',{new_name:'private-text',vassal_id:42});
    c.finish();await first;
    assert.deepEqual(events,[['bannerlord:hero.rename_vassal'],['bannerlord:hero.rename_vassal']]);
    assert.equal(c.requests.length,1,'stats cannot weaken duplicate-action guard');
});
test('telemetry exception does not prevent the original request',async()=>{
    const c=actionContext({trackAction:()=>{throw Error('stats unavailable')}});
    const pending=c.api.buyAction('bannerlord','hero.heal',{price:10});
    assert.equal(c.requests.length,1);
    c.finish();await pending;
});
test('real tab changes count once; restored/current tabs are not opens',()=>{
    const {document}=parseHTML('<button class="tab active" data-tab="bot"></button><button class="tab" data-tab="rimworld"></button><button class="tab" data-tab="stats"></button><div id="bot-tab" class="tab-content active"></div><div id="rimworld-tab" class="tab-content"></div><div id="stats-tab" class="tab-content"></div>');
    const events=[],panels=[];
    const context=vm.createContext({document,_activeIntegrationModule:'bannerlord',isAuthUser:()=>true,
        ShedLink:{usage:{trackSection:k=>events.push(k),trackPanel:k=>panels.push(k)}},
        loadMyPawn(){},shopAllItems:[1],loadStats(){}});
    const text=source('viewer.js');
    const begin=text.indexOf('function _trackVisibleUsagePanel()');
    assert(begin>=0,'missing authenticated visible-panel denominator');
    const end=text.indexOf('// ===== НАСТРОЙКА ОТСЛЕЖИВАНИЯ АКТИВНОСТИ',begin);
    vm.runInContext(text.slice(begin,end),context);
    context.switchTab(document.querySelector('[data-tab="bot"]'));
    context.switchTab(document.querySelector('[data-tab="rimworld"]'));
    context.switchTab(document.querySelector('[data-tab="rimworld"]'));
    context.switchTab(document.querySelector('[data-tab="stats"]'));
    assert.deepEqual(events,['core:tab.integration','core:tab.stats']);
    assert(panels.includes('bannerlord'));
});
test('both future shells load one usage collector before action dispatcher',()=>{
    for(const name of ['extension.html','mobile.html']) {
        const html=source(name);
        const collector=html.match(/<script src="viewer-usage\.js\?v=([^\"]+)"/g)||[];
        assert.equal(collector.length,1,name+' has one collector');
        assert(html.indexOf('viewer-usage.js')<html.indexOf('viewer-actions.js'));
    }
});
test('Bannerlord tabs/details count user transitions, not restore or render',()=>{
    const {document,Event}=parseHTML('<button class="bnr-tab-btn active" data-bnr-tab="combat"></button><button class="bnr-tab-btn" data-bnr-tab="dynasty"></button><div data-bnr-pane="combat" class="bnr-tab-pane active"></div><div data-bnr-pane="dynasty" class="bnr-tab-pane"></div><details data-bnr-details="retinue"></details><details data-bnr-section="army"></details>');
    const events=[];
    const context=vm.createContext({document,ShedLink:{usage:{trackSection:k=>events.push(k)}},
        localStorage:{setItem(){},getItem(){return 'combat'}},loadBannerlordEquipmentShop(){},_loadBannerlordDynasty(){}});
    const text=source('viewer-bannerlord.js');
    vm.runInContext(text.slice(text.indexOf('function _setBnrInnerTab('),text.indexOf('function _startBannerlordPolling(')),context);
    vm.runInContext(text.slice(text.indexOf('const _bannerlordDetailsOpen ='),text.indexOf('// Sprint M21')),context);
    vm.runInContext(text.slice(text.indexOf('const _bnrSectionCollapsed ='),text.indexOf('function loadBannerlordArmy()')),context);
    context._bindBnrInnerTabs();
    assert.equal(events.length,0,'tab restoration is not a click');
    document.querySelector('[data-bnr-tab="dynasty"]').click();
    document.querySelector('[data-bnr-tab="dynasty"]').click();
    const detail=document.querySelector('[data-bnr-details]'); detail.open=false;
    const section=document.querySelector('[data-bnr-section]'); section.open=true;
    context._bnrBindDetailsPersistence();context._bnrBindSectionToggle();
    section.dispatchEvent(new Event('toggle'));
    assert.deepEqual(events,['bannerlord:tab.dynasty'],'initial open section is not a click');
    detail.open=true;detail.dispatchEvent(new Event('toggle'));
    section.open=false;section.dispatchEvent(new Event('toggle'));
    section.open=true;section.dispatchEvent(new Event('toggle'));
    assert.deepEqual(events,['bannerlord:tab.dynasty','bannerlord:details.retinue','bannerlord:section.army']);
});
let failed=0;
for(const [name,run] of tests) {
    try {await run();console.log('PASS '+name);} catch(error) {failed++;console.error('FAIL '+name+'\n'+error.stack);}
}
console.log(`${tests.length-failed}/${tests.length} usage wiring cases passed`);
process.exitCode=failed?1:0;
