const assert=require('assert');
const {Motion}=require('../Расширение/frontend/pet-assets/living-pets-v1/obs-living.js');
const profiles=require('../Расширение/frontend/pet-assets/living-pets-v1/profiles.json');
for(const profile of profiles){
 const m=new Motion(profile,17),states=new Set(),frames=new Set();m.request('walk');
 for(let n=0;n<200;n++){m.update(20,400,1);states.add(m.animator.state);if(m.animator.state==='walk')frames.add(m.animator.pose().frame);assert(m.position>=0&&m.position<=1)}
 assert(states.has('start')&&states.has('walk'),profile.id+' starts');assert.equal(frames.size,8,profile.id+' full gait');
 m.request('sleep');states.clear();for(let n=0;n<350;n++){m.update(20,400,1);states.add(m.animator.state)}
 for(const s of ['stop','yawn','sit','sleep'])assert(states.has(s),profile.id+' '+s);
 const x=m.position;for(let n=0;n<100;n++)m.update(20,400,1);assert.equal(m.position,x,'sleep stays still');
 m.request('walk');states.clear();for(let n=0;n<200;n++){m.update(20,400,1);states.add(m.animator.state)}
 for(const s of ['wake','rise','start','walk'])assert(states.has(s),profile.id+' '+s);
 for(let n=0;n<3000;n++){m.update(20,40,1);assert(m.position>=0&&m.position<=1)}
 assert(m.turns>0,profile.id+' turns inside lane');
 m.request('idle');for(let n=0;n<100;n++)m.update(20,40,1);assert.equal(m.animator.state,'idle');
}
const a=new Motion(profiles[0],1),b=new Motion(profiles[1],2);a.request('walk');b.request('sleep');for(let i=0;i<150;i++){a.update(20,300,1);b.update(20,300,1)}assert.equal(a.animator.state,'walk');assert.equal(b.animator.state,'sleep');
for(const profile of profiles){const m=new Motion(profile,123),states=new Set();for(let i=0;i<6000;i++){const x=m.position,dir=m.direction;m.update(20,160,.8);states.add(m.animator.state);if(dir===m.direction)assert((m.position-x)*dir>=-1e-9,'travel follows facing');}for(const s of ['idle','start','walk','stop','yawn','sit','sleep','wake','rise'])assert(states.has(s),profile.id+' autonomous '+s);}
console.log('PASS: all 12 OBS motion controllers; full gait, queued sleep/wake, independent state, lane bounds and turns');
