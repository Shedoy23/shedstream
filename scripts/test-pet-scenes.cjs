const assert = require('assert');
require('../Расширение/frontend/pet-assets/companions-v1/overlay-pets.js');
const {sceneAt} = global.PetCompanions;
assert.equal(typeof sceneAt, 'function');
// Rare scenes fit entirely inside a stationary interval even for shortest walks.
for (const duration of [90, 120, 150]) for (let seed=0;seed<32;seed++) {
  const iteration=seed%2;
  const start=.06+(seed%12)*.01;
  for(let frame=0;frame<6;frame++) {
    const p=start+(frame+.25)*.7/duration;
    assert.equal(sceneAt(p,iteration,duration,seed),frame);
    assert.equal(sceneAt(p,iteration+1,duration,seed),null);
  }
  assert.equal(sceneAt(start+4.3/duration,iteration,duration,seed),null);
  for(const p of [.3,.4,.5,.6,.8,.95]) assert.equal(sceneAt(p,iteration,duration,seed),null);
}
assert.equal(sceneAt(0,0,0,0),null);
console.log('PASS: all scene frames, alternate-cycle cooldown, stationary-only, duration bounds');
