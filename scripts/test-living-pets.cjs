const assert=require('assert');
const {PetAnimator}=require('../Расширение/frontend/pet-assets/living-pets-v1/animator.js');
const profiles=require('../Расширение/frontend/pet-assets/living-pets-v1/profiles.json');
assert.equal(profiles.length,12);
for(const profile of profiles){
 const p=new PetAnimator(profile);p.request('walk');p.update(350/profile.tempo);assert.equal(p.state,'walk');
 p.request('sleep');let seen=new Set();for(let i=0;i<300;i++){p.update(20);seen.add(p.state);const pose=p.pose();assert(pose.frame>=0&&pose.frame<(pose.sheet==='walk'?8:12))}
 for(const state of ['stop','yawn','sit','sleep'])assert(seen.has(state),profile.id+' '+state);
 p.request('walk');seen=new Set();for(let i=0;i<150;i++){p.update(20);seen.add(p.state)}
 for(const state of ['wake','rise','start','walk'])assert(seen.has(state),profile.id+' '+state);
 assert(p.speed()>0);p.request('idle');p.update(3000);assert.equal(p.state,'idle');assert.equal(p.speed(),0);
}
assert.throws(()=>new PetAnimator({tempo:0}));
console.log('PASS:12 profiles, different tempos, queued stop/sleep/wake, valid frames');
