import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {LogReader,loadJournal,ingest,acquireLock} from '../storage.mjs';
function setup(t){const base=path.resolve('tests/.tmp');fs.mkdirSync(base,{recursive:true});const p=fs.mkdtempSync(path.join(base,'stream-director-'));t.after(()=>{assert.equal(path.dirname(path.resolve(p)),base);fs.rmSync(p,{recursive:true,force:true});});return p;}
test('partial multibyte line waits until completed; restart does not reread',t=>{
 const dir=setup(t),file=path.join(dir,'autopilot_20260926.txt');
 const bytes=Buffer.from('12:00:00  БОЙ: штатная расстановка готова; начинаем бой\n');
 fs.writeFileSync(file,bytes.subarray(0,25));const r=new LogReader(dir);assert.equal(r.read(file,'autopilot').length,0);
 fs.appendFileSync(file,bytes.subarray(25));assert.equal(r.read(file,'autopilot').length,1);r.save();
 assert.equal(new LogReader(dir).read(file,'autopilot').length,0);
});
test('truncated source restarts at new head',t=>{
 const dir=setup(t),file=path.join(dir,'autopilot_20260926.txt');const r=new LogReader(dir);
 fs.writeFileSync(file,'12:00:00  БОЙ: штатная расстановка готова; начинаем бой\n'.repeat(2));assert.equal(r.read(file,'autopilot').length,2);
 fs.writeFileSync(file,'13:00:00  БОЙ: штатная расстановка готова; начинаем бой\n');assert.equal(r.read(file,'autopilot').length,1);
});
test('crashed journal append removes only incomplete final record',t=>{
 const dir=setup(t),file=path.join(dir,'events.jsonl');fs.writeFileSync(file,'{"id":1}\n{"id":');
 assert.deepEqual(loadJournal(file),[{id:1}]);assert.equal(fs.readFileSync(file,'utf8'),'{"id":1}\n');
});
test('failed partial append rolls back cursor and is retried without loss',t=>{
 const dir=setup(t),file=path.join(dir,'autopilot_20260926.txt'),journal=path.join(dir,'events.jsonl');
 fs.writeFileSync(file,'12:00:00  БОЙ: штатная расстановка готова; начинаем бой\n');
 const r=new LogReader(dir),events=[],seen=new Set();
 assert.throws(()=>ingest(r,[[file,'autopilot']],journal,events,seen,(p,s)=>{fs.appendFileSync(p,s.slice(0,20));throw Error('disk full');}));
 assert.equal(fs.readFileSync(journal,'utf8'),'');assert.equal(r.cursors[file],undefined);
 ingest(r,[[file,'autopilot']],journal,events,seen);assert.equal(events.length,1);assert.equal(loadJournal(journal).length,1);
});
test('second observer cannot write the same state directory',t=>{
 const dir=setup(t),release=acquireLock(dir);assert.throws(()=>acquireLock(dir),/running observer/);release();const again=acquireLock(dir);again();
});
