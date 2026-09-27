import test from 'node:test';
import assert from 'node:assert/strict';
import {ObsClock,authentication} from '../obs.mjs';
class FakeSocket extends EventTarget {sent=[];send(s){this.sent.push(JSON.parse(s));}close(){this.dispatchEvent(new Event('close'));}}
test('OBS only asks for status; password absent from requests after auth',t=>{
 const samples=[],c=new ObsClock({WebSocketClass:FakeSocket,onSample:s=>samples.push(s),password:'example'});c.connect();t.after(()=>c.close());
 c.message({op:0,d:{authentication:{salt:'salt',challenge:'challenge'}}});assert.equal(c.ws.sent[0].op,1);assert.ok(!JSON.stringify(c.ws.sent).includes('example'));
 c.message({op:2,d:{}});assert.equal(c.ws.sent.at(-1).d.requestType,'GetRecordStatus');
 c.message({op:7,d:{requestId:c.pendingId,requestStatus:{result:true},responseData:{outputActive:true,outputDuration:5000,outputPaused:false}}});
 assert.equal(c.valid,false);assert.equal(samples.length,0); // Connected mid-recording: no invented start.
 c.message({op:5,d:{eventType:'RecordStateChanged',eventData:{outputState:'OBS_WEBSOCKET_OUTPUT_STARTED'}}});
 c.message({op:7,d:{requestId:c.pendingId,requestStatus:{result:true},responseData:{outputActive:true,outputDuration:6000,outputPaused:false}}});
 assert.equal(samples.at(-1).active,true);
 c.message({op:5,d:{eventType:'RecordFileChanged',eventData:{newOutputPath:'part2.mp4'}}});
 c.poll();c.message({op:7,d:{requestId:c.pendingId,requestStatus:{result:true},responseData:{outputActive:true,outputDuration:7000,outputPaused:false}}});assert.equal(samples.at(-1).active,false);
 assert.ok(c.ws.sent.filter(x=>x.op===6).every(x=>x.d.requestType==='GetRecordStatus'));
});
test('OBS connection restricted to loopback',()=>assert.throws(()=>new ObsClock({url:'ws://example.com:4455'}),/localhost/));
// Fixture independently calculated with Python hashlib + base64 per OBS protocol.
test('auth matches known deterministic challenge',()=>{assert.equal(authentication('password','salt','challenge'),'zTM5ki6L2vVvBQiTG9ckH1Lh64AbnCf6XZ226UmnkIA=');});
test('late old-recording reply is ignored after restart',t=>{
 const samples=[],c=new ObsClock({WebSocketClass:FakeSocket,onSample:s=>samples.push(s)});c.connect();t.after(()=>c.close());c.message({op:2,d:{}});
 const old=c.pendingId;
 c.message({op:5,d:{eventType:'RecordStateChanged',eventData:{outputState:'OBS_WEBSOCKET_OUTPUT_STOPPED'}}});
 c.message({op:5,d:{eventType:'RecordStateChanged',eventData:{outputState:'OBS_WEBSOCKET_OUTPUT_STARTED'}}});
 c.message({op:7,d:{requestId:old,requestStatus:{result:true},responseData:{outputActive:true,outputDuration:100000}}});
 assert.ok(!samples.some(s=>s.ms===100000));
 c.message({op:7,d:{requestId:c.pendingId,requestStatus:{result:true},responseData:{outputActive:true,outputDuration:1000}}});
 assert.equal(c.valid,true);assert.equal(samples.at(-1).ms,1000);
});
