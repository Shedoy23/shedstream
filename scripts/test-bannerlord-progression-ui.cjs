const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../Расширение/frontend/viewer-bannerlord.js'), 'utf8');
const escape = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const decode = value => value.replaceAll('&quot;','"').replaceAll('&#39;',"'").replaceAll('&lt;','<').replaceAll('&gt;','>').replaceAll('&amp;','&');
function harness(response) {
    let current = response;
    const elements = new Map(), calls = [];
    const matches = (node,selector) => selector.startsWith('.') ? node.className.split(' ').includes(selector.slice(1)) : selector.startsWith('[') && Object.hasOwn(node.attrs,selector.slice(1,-1));
    const element = id => {
        if(!elements.has(id)) elements.set(id,{id,_html:'',nodes:[],dataset:{},
            get innerHTML(){return this._html;},
            set innerHTML(html){this._html=html; this.nodes=[...html.matchAll(/<button\b[^>]*>/g)].map(([tag])=>{
                const attrs=Object.fromEntries([...tag.matchAll(/([\w-]+)="([^"]*)"/g)].map(([,k,v])=>[k,decode(v)]));
                const node={attrs,dataset:{},disabled:/\sdisabled(?:\s|>)/.test(tag),listeners:{},className:attrs.class||'',getAttribute:k=>attrs[k],addEventListener(k,fn){this.listeners[k]=fn;}};
                for(const [k,v] of Object.entries(attrs)) if(k.startsWith('data-')) node.dataset[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=v;
                return node;
            });},querySelector:()=>null,querySelectorAll(selector){return this.nodes.filter(n=>matches(n,selector));},addEventListener(){}});
        return elements.get(id);
    };
    const context=vm.createContext({console,window:{},ShedLink:{registerGame(){}},AbortController,setTimeout(){},clearTimeout(){},setInterval(){},clearInterval(){},
        document:{getElementById:element,addEventListener(){},querySelectorAll:selector=>[...elements.values()].flatMap(el=>el.nodes).filter(n=>matches(n,selector))},
        API_URL:'https://example.invalid',authToken:'viewer',escapeHtml:escape,_cachedUserPoints:999999,
        fetch:async url=>{
            let payload;
            if(url.endsWith('/progression')) {if(current instanceof Error) throw current; payload=current;}
            else if(url.endsWith('/shop')) payload={success:true,items:[]};
            else if(url.endsWith('/content-catalogs')) payload={success:true};
            else throw Error('Unexpected request '+url);
            return {ok:true,json:async()=>structuredClone(payload)};
        }
    });
    vm.runInContext(source,context);
    vm.runInContext('_smartInnerHTML=(el,html)=>{el.innerHTML=html;return true;};',context);
    context._bannerlordBuyAction=(action,data)=>{calls.push({action,data});};
    const realHero=context.loadBannerlordHero;
    context.loadBannerlordHero=()=>{};
    context.state={has_hero:true,hero:{gold:999999},skills:[{skill_key:'Mod.Skill',level:99,focus:7}],attributes:{'Mod.Attribute':12}};
    async function render(){await context.loadBannerlordShop();vm.runInContext('_bannerlordLastHero=state;loadBannerlordProgression();',context);}
    return {context,element,calls,render,realHero,setResponse:value=>{current=value;}};
}
function snapshot(){return {success:true,ready:true,context:{save_id:'save-A',equipment_session_id:'session-A',hero_id:'hero-A'},progression:{version:1,
    skills:[{id:'Mod.Skill',level:123,focus:7,native_focus_limit:12,focus_limit:9,focus_options:[{amount:1,cost_gold:731,available:true}],xp_available:true}],
    attributes:[{id:'Mod.Attribute',value:12,native_limit:18,limit:15,options:[{amount:1,cost_gold:913,available:true}]}],
    random_xp_available:true},xp_offers:[{id:'offer-a',crusticov:321,price:123,xp:77,available:true}]};}
test('game offers enable values above vanilla caps and show exact game prices/limits',async()=>{
    const h=harness(snapshot());await h.render();
    const slot=h.element('bnr-progression-slot');
    assert.equal(slot.querySelectorAll('.bnr-prog-focus-btn')[0].disabled,false);
    assert.equal(slot.querySelectorAll('.bnr-prog-attr-btn')[0].disabled,false);
    assert.match(slot.innerHTML,/731/);assert.match(slot.innerHTML,/913/);
    assert.match(slot.innerHTML,/123/);
    assert.doesNotMatch(slot.innerHTML,/30K|75K|50K/);
});
test('game refusal wins over local balance/value and reason is escaped',async()=>{
    const response=snapshot();const option=response.progression.skills[0].focus_options[0];
    option.available=false;option.reason_text='<locked by mod>';
    response.progression.skills[0].focus=0;
    const h=harness(response);h.context.state.skills[0].focus=0;await h.render();
    const slot=h.element('bnr-progression-slot'),button=slot.querySelectorAll('.bnr-prog-focus-btn')[0];
    assert.equal(button.disabled,true);assert.match(slot.innerHTML,/&lt;locked by mod&gt;/);
    await button.listeners.click();assert.equal(h.calls.length,0);
});
test('missing snapshot disables stat purchases and removes invented XP offers',async()=>{
    for(const response of [{success:true,ready:false,reason:'snapshot_missing',message:'Нет снимка'},new Error('offline')]) {
        const h=harness(response);h.context.state.skills[0].focus=0;h.context.state.attributes['Mod.Attribute']=1;await h.render();
        const slot=h.element('bnr-progression-slot');
        assert.equal(slot.querySelectorAll('.bnr-prog-focus-btn')[0].disabled,true);
        assert.equal(slot.querySelectorAll('.bnr-prog-attr-btn')[0].disabled,true);
        assert.match(slot.innerHTML,/99/);
        assert.equal(h.element('bannerlord-shop-list').querySelectorAll('[data-bnr-skillxp]').length,0);
    }
});
test('click captures displayed context, price and values rather than mutable later snapshot',async()=>{
    const h=harness(snapshot());await h.render();
    const focus=h.element('bnr-progression-slot').querySelectorAll('.bnr-prog-focus-btn')[0];
    const attr=h.element('bnr-progression-slot').querySelectorAll('.bnr-prog-attr-btn')[0];
    const xp=h.element('bannerlord-shop-list').querySelectorAll('[data-bnr-skillxp]')[0];
    const next=snapshot();next.context.save_id='save-B';h.setResponse(next);await h.render();
    await focus.listeners.click();await attr.listeners.click();await xp.listeners.click();
    assert.equal(h.calls[0].data.skill_key,'Mod.Skill');assert.equal(h.calls[0].data.expected_cost_gold,731);
    assert.equal(h.calls[0].data.expected_value,7);assert.equal(h.calls[0].data.amount,1);
    assert.equal(h.calls[1].data.attribute_key,'Mod.Attribute');assert.equal(h.calls[1].data.expected_cost_gold,913);assert.equal(h.calls[1].data.expected_value,12);
    assert.equal(h.calls[2].data.price,321);assert.equal(h.calls[2].data.expected_platform_price,123);
    for(const call of h.calls) assert.equal(call.data.progression_context.save_id,'save-A');
});
test('zero price is explicit and malformed/negative prices never become free',async()=>{
    for(const price of [0,null,-1,'bad']) {
        const response=snapshot();response.progression.skills[0].focus_options[0].cost_gold=price;
        const h=harness(response);await h.render();
        assert.equal(h.element('bnr-progression-slot').querySelectorAll('.bnr-prog-focus-btn')[0].disabled,price!==0);
    }
});
test('XP offers are dynamic, escaped and do not attach local affordability calculation',async()=>{
    const response=snapshot();response.xp_offers.push({id:'offer-"b',crusticov:91,price:80,xp:4,available:false,reason_text:'<no learning>'});
    const h=harness(response);await h.render();const shop=h.element('bannerlord-shop-list');
    const buttons=shop.querySelectorAll('[data-bnr-skillxp]');assert.equal(buttons.length,2);
    assert.equal(buttons[0].getAttribute('data-bnr-cost'),undefined);
    assert.equal(buttons[1].disabled,true);assert.match(shop.innerHTML,/&lt;no learning&gt;/);
    assert.equal(h.element('bannerlord-shop-count').textContent,5);
});
test('generic catalog cannot create an alternate progression purchase button',async()=>{
    const h=harness(snapshot()),fetch=h.context.fetch;
    h.context.fetch=url=>url.endsWith('/shop')?Promise.resolve({json:async()=>({success:true,items:[{action_type:'hero.add_focus',name:'Bypass',price:1},{action_type:'hero.add_skill',name:'Bypass XP',price:1},{action_type:'hero.add_attribute',name:'Bypass Attr',price:1}]})}):fetch(url);
    await h.render();assert.equal(h.element('bannerlord-shop-list').querySelectorAll('[data-bnr-buy]').length,0);
});
test('late progression response from previous viewer cannot repopulate current offers',async()=>{
    const h=harness(snapshot());let release;
    h.context.fetch=()=>new Promise(resolve=>{release=resolve;});
    const old=h.context._loadBnrProgression();
    h.context.authToken='other-viewer';
    release({ok:true,json:async()=>snapshot()});await old;
    vm.runInContext('_bannerlordLastHero=state;loadBannerlordProgression();',h.context);
    assert.equal(h.element('bnr-progression-slot').querySelectorAll('.bnr-prog-focus-btn')[0].disabled,true);
});
test('rendered purchase handlers do not send previous viewer offers after reauthorization',async()=>{
    const h=harness(snapshot());await h.render();
    const focus=h.element('bnr-progression-slot').querySelectorAll('.bnr-prog-focus-btn')[0];
    const xp=h.element('bannerlord-shop-list').querySelectorAll('[data-bnr-skillxp]')[0];
    h.context.authToken='other-viewer';
    await focus.listeners.click();await xp.listeners.click();
    assert.equal(h.calls.length,0);
});
test('outer shop response cannot bind old offers under the next viewer token',async()=>{
    const h=harness(snapshot()),fetch=h.context.fetch;let release;
    h.element('bannerlord-shop-list').innerHTML='Current viewer';
    h.context.fetch=url=>url.endsWith('/shop')?new Promise(resolve=>{release=resolve;}):fetch(url);
    const request=h.context.loadBannerlordShop();while(!release) await Promise.resolve();
    h.context.authToken='other-viewer';release({json:async()=>({success:true,items:[]})});await request;
    assert.equal(h.element('bannerlord-shop-list').innerHTML,'Current viewer');
});
test('outer hero response cannot render the previous viewer after token changes',async()=>{
    const h=harness(snapshot());let release;
    h.element('hero-body').innerHTML='Current viewer';
    h.context.fetch=()=>new Promise(resolve=>{release=resolve;});
    const request=h.realHero();h.context.authToken='other-viewer';
    release({json:async()=>({success:false,message:'Old viewer response'})});await request;
    assert.equal(h.element('hero-body').innerHTML,'Current viewer');
});
test('XP price is exact even when compact formatting would round it',async()=>{
    const response=snapshot();response.xp_offers[0].price=1234;
    const h=harness(response);await h.render();
    assert.match(h.element('bannerlord-shop-list').innerHTML,/>1[\s\u00a0\u202f]?234💎</);
});
