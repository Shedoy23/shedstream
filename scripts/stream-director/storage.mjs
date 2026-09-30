import fs from 'node:fs';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {newClock,parseLine} from './director.mjs';
export function atomic(file,data) {
 fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file+'.tmp',data);fs.renameSync(file+'.tmp',file);
}
export function acquireLock(dir) {
 const file=path.join(dir,'observer.lock');
 if(fs.existsSync(file)) {
  const old=fs.readFileSync(file,'utf8');let pid;try{pid=JSON.parse(old).pid;}catch{throw Error('Invalid observer.lock; inspect it before removing');}
  let dead=false;try{process.kill(pid,0);}catch(e){dead=e.code==='ESRCH';}
  if(!dead)throw Error('This state directory already has a running observer');
  if(fs.readFileSync(file,'utf8')===old)fs.unlinkSync(file);
 }
 const token=JSON.stringify({pid:process.pid,token:randomUUID()});
 fs.writeFileSync(file,token,{flag:'wx'});
 return ()=>{try{if(fs.readFileSync(file,'utf8')===token)fs.unlinkSync(file);}catch{}};
}
export function loadJournal(file) {
 if(!fs.existsSync(file))return [];
 const bytes=fs.readFileSync(file);const end=bytes.lastIndexOf(10)+1;
 // Only our incomplete last record may be removed after an interrupted append.
 if(end!==bytes.length)fs.truncateSync(file,end);
 return bytes.subarray(0,end).toString('utf8').split('\n').filter(Boolean).map(s=>JSON.parse(s));
}
export class LogReader {
 constructor(state,offset='+05:00'){this.state=state;this.offset=offset;this.cursors={};this.errors=[];this.file=path.join(state,'cursors.json');if(fs.existsSync(this.file))this.cursors=JSON.parse(fs.readFileSync(this.file,'utf8'));}
 read(file,kind) {
  let stat;try{stat=fs.statSync(file);}catch{return [];}
  let c=this.cursors[file];
  if(!c||stat.size<c.pos||stat.birthtimeMs!==c.birth)c={pos:0,line:0,birth:stat.birthtimeMs,clock:newClock(path.basename(file),this.offset)};
  const fd=fs.openSync(file,'r'), events=[];
  try {
   // Bounded per poll. Incomplete trailing UTF-8 and partial lines are reread.
   const buf=Buffer.alloc(Math.min(stat.size-c.pos,2*1024*1024));fs.readSync(fd,buf,0,buf.length,c.pos);
   const end=buf.lastIndexOf(10)+1;
   for(const line of buf.subarray(0,end).toString('utf8').split('\n').slice(0,-1)) {
    c.line++;const event=parseLine(line.replace(/\r$/,''),kind,file,c.line,c.clock);if(event)events.push(event);
   }
   c.pos+=end;this.cursors[file]=c;return events;
  } finally{fs.closeSync(fd);}
 }
 save(){atomic(this.file,JSON.stringify(this.cursors));}
}
export function ingest(reader,logFiles,eventFile,events,seen,append=fs.appendFileSync) {
 const checkpoint=structuredClone(reader.cursors),size=fs.existsSync(eventFile)?fs.statSync(eventFile).size:0;
 let appended=false;
 try {
  const incoming=logFiles.flatMap(([p,k])=>reader.read(p,k)).filter(e=>!seen.has(e.id));
  if(incoming.length)append(eventFile,incoming.map(e=>JSON.stringify(e)+'\n').join(''));
  appended=true;
  for(const e of incoming){events.push(e);seen.add(e.id);}
  reader.save();return incoming.length>0;
 } catch(e) {
  reader.cursors=checkpoint;
  // An unsuccessful append is rolled back to a known complete boundary.
  // A failed cursor save after a completed append retains the durable journal.
  if(!appended&&fs.existsSync(eventFile))fs.truncateSync(eventFile,size);
  throw e;
 }
}
