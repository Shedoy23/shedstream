// Read-only adapters for the installed log formats. No game decisions or mutations.
import {createHash} from 'node:crypto';

export const hash=s=>createHash('sha256').update(s).digest('hex').slice(0,24);
export function newClock(filename,offset='+05:00') {
 const m=filename.replaceAll('\\','/').split('/').at(-1).match(/(20\d{2})(\d{2})(\d{2})/);
 if(!m)throw Error('Log filename must contain YYYYMMDD');
 return {day:`${m[1]}-${m[2]}-${m[3]}`,last:null,offset};
}
export function parseLine(line,kind,source,lineNo,clock) {
 const m=line.replace(/^\uFEFF/,'').match(/^\[?(\d{2}:\d{2}:\d{2}(?:\.\d{3})?)\]?\s+(.*)$/);
 if(!m)return null;
 const [,tod,body]=m, sec=tod.split(':').reduce((n,v)=>n*60+Number(v),0);
 if(+tod.slice(0,2)>23||+tod.slice(3,5)>59||+tod.slice(6)>59.999)return null;
 const explicit=body.match(/^СЕАНС (\d{4}-\d{2}-\d{2})/);
 if(explicit)clock.day=explicit[1];
 else if(clock.last!==null&&clock.last-sec>43200)clock.day=new Date(Date.parse(clock.day+'T00:00:00Z')+86400000).toISOString().slice(0,10);
 clock.last=sec;
 const at=new Date(`${clock.day}T${tod}${clock.offset}`).toISOString();
 let data=null,q;
 if(kind==='link') {
  if(body.startsWith('MissionBehaviors registered:'))data={type:'mission'};
  else if((q=body.match(/^\[KillReward\] @(\S+) entered Mission \(side=(player|enemy), tracking\)/)))data={type:'fighter',user:q[1],side:q[2]};
  else if((q=body.match(/^\[KillReward\] @(\S+) сторона уточнена → (player|enemy)/)))data={type:'side',user:q[1],side:q[2]};
  else if((q=body.match(/^\[Participation\] @(\S+) side=(ally|enemy) result=/)))data={type:'side',user:q[1],side:q[2]==='ally'?'player':'enemy'};
  else if((q=body.match(/^\[BattlePayout v2\] battle=(\w+) @(\S+) enemies=(\d+) siege=(True|False) won=(True|False)/)))data={type:'payout',battle:q[1],user:q[2],enemies:+q[3],siege:q[4]==='True'};
  else if((q=body.match(/^\[BattlePayout v2\] battle=(\w+) @(\S+) SKIP: герой погиб/)))data={type:'death',battle:q[1],user:q[2]};
  else if((q=body.match(/^\[Participation\] applied to (\d+)\/(\d+) participants \(playerVictory=(True|False)\)/)))data={type:'outcome',participants:+q[2],won:q[3]==='True'};
 } else {
  if(body==='БОЙ: штатная расстановка готова; начинаем бой')data={type:'battle_start'};
  else if(body==='БОЙ: результат определён игрой; штатный выход из завершённой миссии')data={type:'battle_end'};
  else if(body==='ОСАДА: штатное авторазмещение и назначение расчётов выполнены')data={type:'siege'};
 }
 return data?{id:hash(`${source}|${lineNo}|${line}`),at,source,line:lineNo,...data}:null;
}
export function parseLog(text,kind,source,offset='+05:00') {
 const clock=newClock(source,offset);
 return text.split(/\r?\n/).map((s,i)=>parseLine(s,kind,source,i+1,clock)).filter(Boolean);
}

export function buildEpisodes(events) {
 const all=[],seen=new Set();let current=null;
 const make=e=>{const b={id:e.id,start:null,end:null,observed:e.at,last:e.at,missionAt:null,confirmed:false,resolved:false,siege:false,users:{},payouts:[],deaths:[],evidence:[],outcome:'unknown',enemyStart:null,participants:0};all.push(b);return b;};
 for(const e of [...events].sort((a,b)=>a.at.localeCompare(b.at)||a.source.localeCompare(b.source)||a.line-b.line)) {
  if(seen.has(e.id))continue;seen.add(e.id);
  if(e.type==='mission') {
   // A rounded autopilot timestamp can precede the Link timestamp by <1s.
   if(current&&!current.missionAt&&!current.end&&Math.abs(Date.parse(e.at)-Date.parse(current.observed))<5000)current.missionAt=e.at;
   else {current=make(e);current.missionAt=e.at;}
  }
  else if(e.type==='battle_start'||e.type==='siege') {
   if(!current||current.end||Date.parse(e.at)-Date.parse(current.last)>1800000)current=make(e);
   current.start??=e.at;current.confirmed=true;if(e.type==='siege')current.siege=true;
  }
  else if(e.type==='payout'||e.type==='death') {
   const existing=all.findLast(b=>b.battle===e.battle);
   if(existing)current=existing;
   else if(!current||current.battle||(Date.parse(e.at)-Date.parse(current.last)>7200000))current=make(e);
   current.battle=e.battle;
   if(e.type==='payout'){current.confirmed=true;current.resolved=true;current.siege ||= e.siege;current.payouts.push(e);}
   else if(!current.deaths.includes(e.user))current.deaths.push(e.user);
   // First appearance is evidence of participation, not proof of deployment time.
   current.users[e.user]??={};
  }
  else if(e.type==='battle_end') {
   if(!current)current=make(e);
   current.end=e.at;current.resolved=true;current.confirmed=true;
  }
  else if(e.type==='fighter'||e.type==='side') {
   if(!current||current.end&&Date.parse(e.at)-Date.parse(current.end)>5000)continue;
   current.users[e.user]={side:e.side};
  }
  else if(e.type==='outcome') {
   if(!current||Date.parse(e.at)-Date.parse(current.last)>30000)continue;
   current.end=e.at;current.result=e.won;current.reportedParticipants=e.participants;
  }
  if(current){current.last=e.at;current.evidence.push({source:e.source,line:e.line,type:e.type,at:e.at});}
 }
 return all.filter(b=>b.confirmed).map(b=>{
  b.participants=Math.max(Object.keys(b.users).length,b.reportedParticipants??0);
  b.start??=b.missionAt;
  b.outcome=b.resolved&&b.result!==undefined?(b.result?'victory':'defeat'):'unknown';
  const enemy=new Set(b.payouts.filter(p=>b.users[p.user]?.side==='player').map(p=>p.enemies));
  b.enemyStart=enemy.size===1?[...enemy][0]:null;
  return b;
 });
}

// Only interpolate inside a continuous observed recording interval. Never bridge
// a pause/restart/disconnect/file split or substitute stream time for recording time.
export function locate(at,samples) {
 const t=typeof at==='string'?Date.parse(at):at;
 let i=samples.findIndex(s=>s.at>=t);
 if(i<0)return null;
 let a=samples[Math.max(0,i-1)],b=samples[i];
 if(!a.active||!b.active||a.paused||b.paused||a.session!==b.session||b.at-a.at>3000||t<a.at||t>b.at)return null;
 const wall=b.at-a.at,media=b.ms-a.ms;
 if(media<0||wall&&Math.abs(media-wall)>750)return null;
 return {session:a.session,file:a.file??b.file??null,seconds:(a.ms+(wall?(t-a.at)*media/wall:0))/1000,accuracySeconds:1.5};
}
export function timecode(seconds) {
 if(seconds===null||seconds===undefined)return 'нет привязки';
 const n=Math.max(0,Math.floor(seconds));return [Math.floor(n/3600),Math.floor(n/60)%60,n%60].map(x=>String(x).padStart(2,'0')).join(':');
}
export function recordingSegments(samples) {
 const segments=[];
 for(const s of samples) {
  if(!s.active||s.paused){segments.push({first:s,last:s,invalid:true});continue;}
  const prev=segments.at(-1),a=prev?.last,delta=a?s.at-a.at:0;
  if(prev&&!prev.invalid&&a.session===s.session&&delta<=3000&&delta>=0&&s.ms>=a.ms&&Math.abs(s.ms-a.ms-delta)<=750)prev.last=s;
  else segments.push({first:s,last:s});
 }
 return segments.filter(s=>!s.invalid);
}
export function report(episodes,samples) {
 const segments=recordingSegments(samples);
 return episodes.map(b=>{
  const reasons=[];let score=10;
  if(b.siege){reasons.push('Осада');score+=30;}
  if(b.enemyStart>=300){reasons.push(`${b.enemyStart} противников на старте`);score+=Math.min(30,Math.floor(b.enemyStart/100));}
  if(b.participants>=10){reasons.push(`${b.participants} участников-зрителей`);score+=20;}
  if(b.deaths.length){reasons.push(`Погибли герои: ${b.deaths.map(u=>'@'+u).join(', ')}`);score+=20;}
  if(!reasons.length)reasons.push('Бой');
  const video=b.start?locate(b.start,samples):null,finish=b.end?locate(b.end,samples):null;
  const span=b.start&&b.end?segments.find(s=>s.first.at<=Date.parse(b.start)&&s.last.at>=Date.parse(b.end)):null;
  const clip=video&&finish&&span?{session:video.session,file:video.file,start:Math.max(span.first.ms/1000,video.seconds-20),end:Math.min(span.last.ms/1000,finish.seconds+15)}:null;
  return {id:b.id,title:b.siege?'Штурм / осадный бой':'Бой',start:b.start,end:b.end,observed:b.observed,outcome:b.outcome,participants:b.participants,enemyStart:b.enemyStart,score,reasons,video,clip,recordingGap:!!(video&&b.end&&!span),evidence:b.evidence};
 }).sort((a,b)=>b.score-a.score||a.observed.localeCompare(b.observed));
}
export function thoughtState(text,mtime,now=Date.now()) {
 const lines=text.replace(/^\uFEFF/,'').trim().split(/\r?\n/);
 const age=Math.max(0,(now-mtime)/1000);
 const visible=lines[0]?.startsWith('ИГРАЕТ ИИ')&&age<180;
 return {visible:!!visible,thought:visible?(lines[1]??'Наблюдаю за обстановкой').replace(/^•\s*/, ''):'',previous:visible?lines.slice(2,4).map(s=>s.replace(/^•\s*/,'')):[],age};
}
