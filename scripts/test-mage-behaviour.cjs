const assert = require('assert');
const {MageAnimator} = require('../Расширение/frontend/pet-assets/mage-behaviour-v1/animator.js');
const mage = new MageAnimator();
assert.equal(mage.state,'idle');
mage.request('walk'); mage.update(1);
assert.equal(mage.state,'start');
mage.update(300); assert.equal(mage.state,'walk');
mage.update(150); mage.request('sleep'); mage.update(100);
assert.equal(mage.state,'walk','finish current stride before stop');
mage.update(550); assert.equal(mage.state,'stop');
mage.update(360); assert.equal(mage.state,'yawn');
mage.update(700); assert.equal(mage.state,'sit');
mage.update(350); assert.equal(mage.state,'sleep');
assert([8,9].includes(mage.pose().frame));
mage.request('walk'); mage.update(1); assert.equal(mage.state,'wake');
mage.update(500); assert.equal(mage.state,'rise');
mage.update(350); assert.equal(mage.state,'start');
mage.request('idle'); mage.update(300); assert.equal(mage.state,'stop','latest intent survives start transition');
mage.update(360); assert.equal(mage.state,'idle');
assert.equal(mage.speed(),0);
assert.throws(()=>mage.request('invalid'));
for(const intent of ['idle','walk','sleep']){
 const m=new MageAnimator();m.request(intent);for(let i=0;i<500;i++){m.update(37);const p=m.pose();assert(p.frame>=0&&p.frame<(p.sheet==='walk'?8:12));assert(Number.isFinite(m.speed()))}
 assert.equal(m.state,intent);
}
console.log('PASS: stride-boundary stop, sleep/wake sequence, queued intent, valid atlas frames');
