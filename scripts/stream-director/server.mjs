import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {parseLog,buildEpisodes,report,thoughtState,timecode} from './director.mjs';
import {atomic,loadJournal,LogReader,ingest,acquireLock} from './storage.mjs';
import {ObsClock} from './obs.mjs';
const root=path.dirname(fileURLToPath(import.meta.url));
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function exportReport(dir,moments) {
 atomic(path.join(dir,'moments.json'),JSON.stringify(moments,null,2));
 const rows=moments.map(m=>[m.video?timecode(m.video.seconds):'НЕТ ПРИВЯЗКИ',m.start??m.observed,m.title,m.participants,m.enemyStart??'',m.outcome,m.score,m.reasons.join('; '),m.video?.file??'']);
 const csv=v=>'"'+String(v).replace(/^[=+@-]/,"'$&").replaceAll('"','""')+'"';
 atomic(path.join(dir,'moments.csv'),'\uFEFF'+[['Видео','Время UTC','Событие','Герои зрителей','Враги на старте','Исход','Приоритет','Причины','Файл'],...rows].map(r=>r.map(csv).join(',')).join('\r\n'));
 const blocks=moments.map(m=>`<article><b>${esc(m.title)}</b> · приоритет ${m.score}<p>${esc(m.reasons.join(' · '))}</p><p>Видео: ${esc(m.video?timecode(m.video.seconds):'нет привязки OBS')} · время компьютера: ${esc(new Date(m.start??m.observed).toLocaleString('ru-RU',{timeZone:'Asia/Yekaterinburg'}))} (Екатеринбург)</p><small>Герои: ${m.participants} · исход: ${esc(({victory:'победа',defeat:'поражение',unknown:'не подтверждён'})[m.outcome])}</small></article>`).join('');
 atomic(path.join(dir,'moments.html'),`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Моменты стрима</title><style>body{background:#111720;color:#edf2fa;font:16px system-ui;max-width:950px;margin:30px auto;padding:18px}article{background:#1b2533;border-left:3px solid #dfbe82;padding:18px;margin:14px 0}small{color:#a9b7c8}h1{color:#dfbe82}</style><h1>Моменты стрима · ${moments.length}</h1><p>Кандидаты для просмотра. Приоритет — правила отбора, а не оценка качества кадра. Без OBS-привязки указаны только часы компьютера.</p>${blocks}`);
}
function options(args) {const a={mode:args[0]??'serve'};for(let i=1;i<args.length;i++){if(!args[i].startsWith('--'))throw Error('Expected --option');a[args[i].slice(2)]=args[i+1]&&!args[i+1].startsWith('--')?args[++i]:true;}return a;}
export function start(a) {
 const state=path.resolve(a.state??path.join(root,'state'));fs.mkdirSync(state,{recursive:true});
 if(a.mode==='replay') {
  let events=[];for(const kind of ['autopilot','link'])if(a[kind])events.push(...parseLog(fs.readFileSync(a[kind],'utf8'),kind,path.resolve(a[kind]),a.offset??'+05:00'));
  const samples=a.clock?loadJournal(a.clock).sort((x,y)=>x.at-y.at):[];
  const moments=report(buildEpisodes(events),samples);exportReport(state,moments);
  console.log(JSON.stringify({events:events.length,moments:moments.length,withVideo: moments.filter(m=>m.video).length,report:path.join(state,'moments.html')}));return;
 }
 if(a.mode!=='serve')throw Error('Use serve or replay');
 const releaseLock=acquireLock(state);process.on('exit',releaseLock);
 const eventFile=path.join(state,'events.jsonl'),clockFile=path.join(state,'clock.jsonl'),filesFile=path.join(state,'recordings.json');
 const events=loadJournal(eventFile),samples=loadJournal(clockFile),seen=new Set(events.map(e=>e.id));
 let files=fs.existsSync(filesFile)?JSON.parse(fs.readFileSync(filesFile,'utf8')):{};
 const reader=new LogReader(state,a.offset??'+05:00');let episodes=[],moments=[],lastExport=0,lastScan=0,logFiles=[],ioError=null;
 const game=path.resolve(a.game??path.join(os.homedir(),'Documents','Mount and Blade II Bannerlord'));
 const thoughtFile=path.join(game,'Logs','autopilot_stream.txt');
 const obsConfig=a['obs-config']?JSON.parse(fs.readFileSync(a['obs-config'],'utf8')):{};
 const clock=new ObsClock({url:a.obs??'ws://127.0.0.1:4455',password:process.env.OBS_WEBSOCKET_PASSWORD??obsConfig.server_password??'',onSample:s=>{
  try{fs.appendFileSync(clockFile,JSON.stringify(s)+'\n');samples.push(s);}catch{ioError='Не удалось сохранить таймкод';}
 },onFile:f=>{try{files[f.session]=f.file;atomic(filesFile,JSON.stringify(files));}catch{ioError='Не удалось сохранить имя записи';}}});
 if(!a['no-obs'])clock.connect();else clock.status='синхронизация отключена';
 function poll() {
  try {
   const now=Date.now();let dirty=false;
   if(now-lastScan>10000) {
    lastScan=now;logFiles=[];
    for(const [kind,dir,prefix] of [['autopilot',path.join(game,'Logs'),'autopilot_'],['link',path.join(game,'Configs','ModLogs'),'bannerlordlink_']]) {
     try{for(const n of fs.readdirSync(dir).filter(n=>new RegExp('^'+prefix+'\\d{8}\\.txt$').test(n))) {
      // Include yesterday: the game keeps the original filename after midnight.
      const p=path.join(dir,n);if(now-fs.statSync(p).mtimeMs<2*86400000)logFiles.push([p,kind]);
     }}catch{ioError='Журнал игры недоступен';}
    }
   }
   dirty=ingest(reader,logFiles,eventFile,events,seen);
   if(dirty||!lastExport||now-lastExport>10000) {
    episodes=buildEpisodes(events);const mapped=samples.map(s=>({...s,file:files[s.session]??null})).sort((x,y)=>x.at-y.at);
    moments=report(episodes,mapped);exportReport(state,moments);lastExport=now;
   }
  } catch(e){ioError='Ошибка чтения или сохранения; проверь пути и диск';console.error(ioError,e.code??e.name);}
 }
 poll();const timer=setInterval(poll,2000);
 const port=Number(a.port??17863);if(!Number.isInteger(port)||port<1024||port>65535)throw Error('Invalid port');
 const server=http.createServer((req,res)=>{
  if(![`127.0.0.1:${port}`,`localhost:${port}`].includes(req.headers.host)){res.writeHead(403).end();return;}
  if(req.method!=='GET'){res.writeHead(405).end();return;}
  const route=new URL(req.url,'http://localhost').pathname;
  res.setHeader('Cache-Control','no-store');res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'");
  if(route==='/api/state') {
   let thoughts=thoughtState('',0);try{thoughts=thoughtState(fs.readFileSync(thoughtFile,'utf8'),fs.statSync(thoughtFile).mtimeMs);}catch{}
   const recent=episodes.filter(b=>Date.now()-Date.parse(b.last)<180000).at(-1);
   res.setHeader('Content-Type','application/json; charset=utf-8');res.end(JSON.stringify({thoughts,battle:recent?{siege:recent.siege,participants:recent.participants,enemyStart:recent.enemyStart,outcome:recent.outcome,finished:!!recent.end}:null,clock:clock.status,moments:moments.slice(0,100),error:ioError,updated:Date.now()}));return;
  }
  const map={'/':'overlay.html','/overlay.html':'overlay.html','/overlay.css':'overlay.css','/overlay.js':'overlay.js','/moments.html':'moments.html','/moments.json':'moments.json','/moments.csv':'moments.csv'};
  if(!map[route]){res.writeHead(404).end();return;}
  const file=path.join(route.startsWith('/moments.')?state:path.join(root,'web'),map[route]);
  try{res.setHeader('Content-Type',({'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json; charset=utf-8','.csv':'text/csv; charset=utf-8'})[path.extname(file)]);res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}
 });
 server.listen(port,'127.0.0.1',()=>console.log(`Overlay http://127.0.0.1:${port}/ | Demo /?demo=1 | Report /moments.html`));
 const close=()=>{clearInterval(timer);clock.close();server.close();releaseLock();};process.on('SIGINT',close);process.on('SIGTERM',close);return {server,close};
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))start(options(process.argv.slice(2)));
