import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
fs.mkdirSync('tests/.tmp',{recursive:true});const root=fs.mkdtempSync(path.resolve('tests/.tmp/live-'));fs.mkdirSync(path.join(root,'game','Logs'),{recursive:true});fs.mkdirSync(path.join(root,'game','Configs','ModLogs'),{recursive:true});
const game=path.join(root,'game'),state=path.join(root,'state'),port=17864;
const date='20260927',auto=path.join(game,'Logs',`autopilot_${date}.txt`),link=path.join(game,'Configs','ModLogs',`bannerlordlink_${date}.txt`);
fs.writeFileSync(auto,'12:00:02  БОЙ: штатная расстановка готова; начинаем бой\n');
fs.writeFileSync(link,'[12:00:01.000] MissionBehaviors registered: Powers + KillReward\n[12:00:03.000] [KillReward] @alice entered Mission (side=player, tracking)\n');
const thought=path.join(game,'Logs','autopilot_stream.txt');fs.writeFileSync(thought,'ИГРАЕТ ИИ\n• Идём на штурм');
function launch(){return spawn(process.execPath,['server.mjs','serve','--no-obs','--state',state,'--game',game,'--port',String(port)],{stdio:['ignore','pipe','pipe'],windowsHide:true});}
async function waitFor(fn){for(let i=0;i<50;i++){try{const r=await fn();if(r)return r;}catch{}await new Promise(r=>setTimeout(r,100));}throw Error('Timed out');}
const api=()=>fetch(`http://127.0.0.1:${port}/api/state`).then(r=>r.json());
let proc=launch();
try{
 await waitFor(async()=>{const s=await api();return s.moments.length===1&&s});
 fs.appendFileSync(link,'[12:05:00.000] [BattlePayout v2] battle=abc @alice enemies=400 siege=True won=True personalPoints=5\n[12:05:00.010] [Participation] @alice side=ally result=🏆WIN: +10\n[12:05:00.020] [Participation] applied to 1/1 participants (playerVictory=True)\n');
 const s=await waitFor(async()=>{const x=await api();return x.moments[0]?.outcome==='victory'&&x});assert.equal(s.moments[0].participants,1);assert.equal(s.moments[0].enemyStart,400);assert.equal(s.moments[0].video,null);assert.equal(s.thoughts.visible,true);
 fs.writeFileSync(thought,'');await waitFor(async()=>!(await api()).thoughts.visible);
 const bytes=fs.statSync(path.join(state,'events.jsonl')).size;
 proc.kill();await new Promise(r=>proc.once('exit',r));proc=launch();
 await waitFor(async()=>{const x=await api();return x.moments.length===1&&x.moments[0].outcome==='victory';});
 assert.equal(fs.statSync(path.join(state,'events.jsonl')).size,bytes);
 assert.equal((await fetch(`http://127.0.0.1:${port}/api/state`,{method:'POST'})).status,405);
 assert.equal((await fetch(`http://127.0.0.1:${port}/unknown`)).status,404);
 fs.writeFileSync('evidence/live-check.json',JSON.stringify({passed:true,checks:['incremental two-log ingestion','late outcome and participant side','blank thought hides','restart preserves one episode without journal duplicates','no fake timecode','POST rejected','unknown routes rejected']},null,2));
}finally{proc.kill();}
