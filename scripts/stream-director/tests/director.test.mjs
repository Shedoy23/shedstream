import test from 'node:test';
import assert from 'node:assert/strict';
import {parseLog, buildEpisodes, locate, report, thoughtState} from '../director.mjs';
const parse=(s,k='link')=>parseLog(s,k,`${k}_20260926.txt`);
const mission='[23:59:50.000] MissionBehaviors registered: Powers + KillReward + Detachment';
const join=u=>`[23:59:51.000] [KillReward] @${u} entered Mission (side=player, tracking)`;
const payout='[00:00:10.000] [BattlePayout v2] battle=abc @alice enemies=700 siege=True won=True personalPoints=5';
const end='[00:00:10.100] [Participation] applied to 1/2 participants (playerVictory=True)';
test('midnight rollover uses next date',()=>{
 const e=parse([mission,join('alice'),payout,end].join('\n'));
 assert.equal(e.at(-1).at,'2026-09-26T19:00:10.100Z');
});
test('date comes from filename, not a dated backup directory',()=>{
 const e=parseLog(mission,'link','C:/backup-20260927/bannerlordlink_20260926.txt');assert.equal(e[0].at,'2026-09-26T18:59:50.000Z');
});
test('one battle, distinct heroes, dead included, resolved outcome',()=>{
 const e=buildEpisodes(parse([mission,join('alice'),join('alice'),join('bob'),payout,end].join('\n')));
 assert.equal(e.length,1);assert.equal(e[0].participants,2);assert.equal(e[0].outcome,'victory');assert.equal(e[0].enemyStart,700);assert.equal(e[0].siege,true);
});
test('enemy viewer victory is not player victory',()=>{
 const e=buildEpisodes(parse([mission,join('alice').replace('player','enemy'),payout,end.replace('True','False')].join('\n')))[0];
 assert.equal(e.outcome,'defeat');assert.equal(e.enemyStart,null);
});
test('mission without resolved payout does not claim defeat or battle',()=>{
 assert.equal(buildEpisodes(parse([mission,join('alice'),end.replace('True','False')].join('\n'))).length,0);
});
test('deployment without final result is an unfinished battle',()=>{
 const e=buildEpisodes(parse('12:00:00  БОЙ: штатная расстановка готова; начинаем бой','autopilot'))[0];
 assert.equal(e.outcome,'unknown');assert.equal(e.end,null);
});
test('payout without start never invents battle start',()=>{
 const e=buildEpisodes(parse(payout))[0];assert.equal(e.start,null);assert.equal(e.end,null);
});
test('talking about assault never proves actual assault',()=>{
 assert.equal(buildEpisodes(parse('12:00:00  [UI] Штурмуем крепость!','autopilot')).length,0);
});
test('pauses, disconnected clock and restart are not extrapolated',()=>{
 const s=[{at:1000,ms:10000,session:'one',active:true,paused:false},{at:2000,ms:11000,session:'one',active:true,paused:false},{at:3000,ms:11000,session:'one',active:true,paused:true},{at:4000,ms:0,session:'two',active:true,paused:false}];
 assert.equal(locate(1500,s).seconds,10.5);assert.equal(locate(2500,s),null);assert.equal(locate(20000,s),null);assert.equal(locate(3500,s),null);
 assert.equal(locate(3000,[s[2]]),null); // Even an exact paused sample is not recorded footage.
});
test('split recording boundary not mapped across files',()=>{
 assert.equal(locate(1500,[{at:1000,ms:10000,session:'a',active:true},{at:2000,ms:0,session:'b',active:true}]),null);
});
test('stale or empty thoughts do not show as current AI orders',()=>{
 assert.equal(thoughtState('',0,1000).visible,false);
 assert.equal(thoughtState('ИГРАЕТ ИИ\n• штурмуем',0,181000).visible,false);
 assert.equal(thoughtState('ИГРАЕТ ИИ\n• штурмуем\n• отдых',1000,2000).thought,'штурмуем');
});
test('no clock means explicit unsynced, never wall clock as video time',()=>{
 const e=buildEpisodes(parse([mission,join('alice'),payout,end].join('\n')));
 const r=report(e,[]);assert.equal(r[0].video,null);assert.ok(r[0].reasons.includes('Осада'));assert.ok(r[0].reasons.some(x=>x.includes('700')));
});
test('final Participation side overrides preliminary spawn side',()=>{
 const lines=[mission,join('alice'),payout,'[00:00:10.001] [Participation] @alice side=enemy result=🏆WIN: +10',end];
 assert.equal(buildEpisodes(parse(lines.join('\n')))[0].enemyStart,null);
});
test('unresolved mission and next battle never share heroes',()=>{
 const lines=[mission,join('alice'),mission.replace('23:59:50','23:59:55'),join('bob').replace('23:59:51','23:59:56'),payout.replace('alice','bob'),end.replace('1/2','1/1')];
 assert.equal(buildEpisodes(parse(lines.join('\n')))[0].participants,1);
});
test('deduplicated journal replay does not duplicate episodes',()=>{
 const e=parse([mission,join('alice'),payout,end].join('\n'));assert.equal(buildEpisodes([...e,...e]).length,1);
});
test('rounded deployment timestamp joins link mission in same second',()=>{
 const a=parse('12:00:00  БОЙ: штатная расстановка готова; начинаем бой','autopilot');
 const l=parse('[12:00:00.800] MissionBehaviors registered: Powers + KillReward\n[12:00:02.000] [KillReward] @alice entered Mission (side=player, tracking)');
 const b=buildEpisodes([...a,...l]);assert.equal(b.length,1);assert.equal(b[0].participants,1);
});
test('full date in session overrides midnight inference',()=>{
 const e=parse('23:59:00  БОЙ: штатная расстановка готова; начинаем бой\n00:01:00  СЕАНС 2026-09-28 00:01:00 — загрузка\n00:02:00  БОЙ: штатная расстановка готова; начинаем бой','autopilot');
 assert.equal(e[1].at,'2026-09-27T19:02:00.000Z');
});
test('report marks internal recording gap and refuses a continuous clip',()=>{
 const b={id:'x',start:new Date(1500).toISOString(),end:new Date(7500).toISOString(),observed:new Date(1500).toISOString(),participants:1,deaths:[],evidence:[],outcome:'unknown'};
 const s=[[1000,1000,false],[2000,2000,false],[3000,2000,true],[6000,2000,false],[7000,3000,false],[8000,4000,false]].map(([at,ms,paused])=>({at,ms,paused,active:true,session:'a'}));
 const r=report([b],s)[0];assert.ok(r.video);assert.equal(r.clip,null);assert.equal(r.recordingGap,true);
});
