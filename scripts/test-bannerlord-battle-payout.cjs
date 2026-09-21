const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const s=fs.readFileSync(require('node:path').join(__dirname,'../Расширение/frontend/viewer-bannerlord.js'),'utf8');
const ctx={};vm.createContext(ctx);vm.runInContext(s.slice(s.indexOf('function _bnrBattlePayoutText('),s.indexOf('function _renderBannerlordBattleBanner(')),ctx);
const render=ctx._bnrBattlePayoutText;
assert.match(render({gold_earned:123}),/123/);
assert.match(render({payout_version:2,payout_estimate_min:100,payout_estimate_max:120}),/После боя: ≈100–120/);
assert.match(render({payout_version:2,payout_status:'paid',gold_earned:100}),/Получено: 100/);
assert.match(render({payout_version:2,payout_status:'failed',gold_earned:100}),/Не удалось/);
assert.doesNotMatch(render({payout_version:2,payout_estimate_min:'<img>',payout_estimate_max:-1}),/<img>|-1/);
assert.match(render({payout_version:2,payout_status:'unavailable'}),/Нет подтверждённого/);
console.log('PASS payout UI: legacy, estimates, payment, failure, missing result, numeric escaping');

const slot={innerHTML:''};ctx.document={getElementById:()=>slot};
vm.runInContext(s.slice(s.indexOf('function _renderBannerlordBattleBanner('),s.indexOf('// ===== Shop',s.indexOf('function _renderBannerlordBattleBanner('))),ctx);
ctx._renderBannerlordBattleBanner({in_battle:false,last_payout:{payout_version:2,payout_status:'paid',gold_earned:154800,payout_participation:60000,payout_personal:60000,payout_retinue:34800}});
assert.match(slot.innerHTML,/Получено/);assert.match(slot.innerHTML,/Свита:/);
ctx._renderBannerlordBattleBanner({in_battle:false});assert.equal(slot.innerHTML,'');
console.log('PASS final payout card and expiry');
