// Executes the shipped renderers against mocked API/DOM; no game or CDN claims.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = readFileSync(new URL('../Расширение/frontend/viewer-bannerlord.js', import.meta.url), 'utf8');
const equipment = readFileSync(new URL('../Расширение/frontend/viewer-bannerlord-equipment.js', import.meta.url), 'utf8');
const escape = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const catalog = entries => ({available:true, reason:null, entries});
function harness(catalogs = {}) {
    const elements = new Map();
    const element = id => {
        if (!elements.has(id)) elements.set(id, {id, innerHTML:'', querySelector:()=>null, querySelectorAll:()=>[], addEventListener(){}, replaceChildren(){}});
        return elements.get(id);
    };
    const requests = [];
    const context = vm.createContext({console, window:{}, ShedLink:{registerGame(){}}, setInterval(){}, clearInterval(){},
        document:{getElementById:element, addEventListener(){}},
        API_URL:'https://example.invalid', authToken:'test-token', escapeHtml:escape,
        fetch: async url => {
            requests.push(url);
            if (url.endsWith('/content-catalogs')) {
                if (catalogs instanceof Error) throw catalogs;
                return {ok:true, json:async()=>({success:true, ...catalogs})};
            }
            if (url.endsWith('/my-hero')) return {json:async()=>({success:true,has_hero:false})};
            if (url.endsWith('/kingdom-state')) return {json:async()=>({success:true,has_hero:true,kingdom_id:'mod_kingdom',is_clan_leader:true,policies_enacted:[],policies_pending:[]})};
            throw Error(`Unexpected request ${url}`);
        }
    });
    vm.runInContext(source, context);
    vm.runInContext('_smartInnerHTML = (el, html) => { el.innerHTML=html; return false; }; _bnrNotifyRefunds = () => {};', context);
    return {context, element, requests};
}
test('creation renders the game catalog and escapes mod labels/IDs; no vanilla substitutes', async()=>{
    const h=harness({cultures:catalog([{id:'mod_"culture',name:'<img src=x>',description:'" title',available:true},{id:'no_template',name:'Unavailable',available:false}])});
    await h.context.loadBannerlordHero();
    const html=h.element('hero-body').innerHTML;
    assert.ok(h.requests.some(url=>url.endsWith('/content-catalogs')));
    assert.match(html,/mod_&quot;culture/);
    assert.match(html,/&lt;img src=x&gt;/);
    assert.doesNotMatch(html,/data-bnr-culture="empire"|<img src=x>/);
    assert.match(html,/<button[^>]*data-bnr-culture="no_template"[^>]*disabled/s);
});
test('missing or failed culture catalogs never invent six cultures', async()=>{
    for (const response of [{}, {cultures:{available:false,reason:'not_synced',entries:[]}}, new Error('offline')]) {
        const h=harness(response);
        await h.context.loadBannerlordHero();
        const html=h.element('hero-body').innerHTML;
        assert.doesNotMatch(html,/data-bnr-culture="(?:empire|battania|aserai)"/);
        assert.match(html,/недоступ|не получен|не переда|не загруз/i);
    }
});
test('kingdom policy choices use mod catalog descriptions and preserve IDs', async()=>{
    const h=harness({policies:catalog([{id:'law_"mod',name:'Mod Law',description:'<script>bad</script>'}])});
    await h.context.loadBannerlordDiplomacy();
    const html=h.element('bnr-diplo-slot').innerHTML;
    assert.match(html,/data-policy-id="law_&quot;mod"/);
    assert.match(html,/Mod Law/);
    assert.match(html,/&lt;script&gt;bad&lt;\/script&gt;/);
    assert.doesNotMatch(html,/data-policy-id="royal_guard"/);
});
test('progression renders only received keys, including unknown values above vanilla ranges', ()=>{
    const h=harness();
    vm.runInContext(`_bannerlordLastHero = {has_hero:true,skills:[{skill_key:'ModMagic',label:'<Magic>',level:999,focus:7}],attributes:{mod_wisdom:12}};loadBannerlordProgression();`,h.context);
    const html=h.element('bnr-progression-slot').innerHTML;
    assert.match(html,/data-skill="ModMagic"/);
    assert.match(html,/data-attr="mod_wisdom"/);
    assert.match(html,/999/);
    assert.match(html,/12/);
    assert.doesNotMatch(html,/data-skill="OneHanded"|data-attr="Vigor"/);
});
test('non-finite or negative progression values cannot crash the renderer', ()=>{
    const h=harness();
    for(const value of [-4,NaN,Infinity,1.5,99999]) {
        h.context.input=value;
        vm.runInContext('_bannerlordLastHero={has_hero:true,skills:[{skill_key:"OneHanded",level:input,focus:input}],attributes:{vigor:input}};loadBannerlordProgression();',h.context);
        assert.ok(h.element('bnr-progression-slot').innerHTML.length < 30000);
    }
});
test('equipment includes unknown stats, zero and negative values with escaped names', ()=>{
    const from=equipment.indexOf('const statNames =');
    const names=equipment.slice(from,equipment.indexOf('let snapshot',from));
    const functions=equipment.slice(equipment.indexOf('function stats(item)'),equipment.indexOf('function itemHtml('));
    const context=vm.createContext({text:escape});
    vm.runInContext(names+functions,context);
    const item={stats:{swing_dmg:25,'mod_<magic>':50,penalty:-3,zero:0,flavour:'<fire>'}};
    const html=context.stats(item);
    assert.match(html,/mod_&lt;magic&gt; 50/);
    assert.match(html,/penalty -3/);
    assert.match(html,/zero 0/);
    assert.match(html,/&lt;fire&gt;/);
    assert.equal(context.numericStats(item)['mod_<magic>'],50);
    assert.match(context.comparedStats(item,{stats:{'mod_<magic>':30}}),/mod_&lt;magic&gt;/);
});
