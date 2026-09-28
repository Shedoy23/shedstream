import {createHash,randomUUID} from 'node:crypto';
const sha=s=>createHash('sha256').update(s).digest('base64');
export const authentication=(password,salt,challenge)=>sha(sha(password+salt)+challenge);
// OBS read-only protocol v5. No Start/Stop/Set/Create requests are sent.
export class ObsClock {
 constructor({url='ws://127.0.0.1:4455',password='',onSample=()=>{},onFile=()=>{},WebSocketClass=WebSocket}={}) {
  const u=new URL(url);if(u.protocol!=='ws:'||!['127.0.0.1','localhost','[::1]'].includes(u.hostname))throw Error('OBS must be on localhost');
  Object.assign(this,{url,password,onSample,onFile,WebSocketClass});this.status='не подключён';this.session=null;this.ready=false;this.stopped=false;this.counter=0;this.epoch=0;
 }
 connect() {
  if(this.stopped)return;
  this.ws=new this.WebSocketClass(this.url);this.ready=false;this.sceneChanging=false;this.session=null;this.pending=false;this.valid=false;this.active=false;this.file=null;this.epoch++;
  this.ws.addEventListener('message',e=>{try{this.message(JSON.parse(e.data));}catch{this.status='ошибка протокола';this.ws.close();}});
  this.ws.addEventListener('error',()=>{this.status='OBS недоступен';});
  this.ws.addEventListener('close',()=>{this.ready=false;this.status='нет связи';clearInterval(this.poller);if(!this.stopped)this.retry=setTimeout(()=>this.connect(),5000);});
  this.timeout=setTimeout(()=>{if(!this.ready)this.ws.close();},6000);
 }
 send(op,d){this.ws.send(JSON.stringify({op,d}));}
 poll(){if(!this.ready||this.sceneChanging)return;if(this.pending){if(Date.now()-this.requestAt>5000)this.ws.close();return;}this.pending=true;this.requestAt=Date.now();this.pendingId=`clock:${this.epoch}:${++this.counter}`;this.send(6,{requestType:'GetRecordStatus',requestId:this.pendingId});}
 invalidate(){this.epoch++;this.pending=false;this.pendingId=null;}
 message({op,d}) {
  if(op===0){const data={rpcVersion:1,eventSubscriptions:66};if(d.authentication)data.authentication=authentication(this.password,d.authentication.salt,d.authentication.challenge);this.send(1,data);}
  else if(op===2){clearTimeout(this.timeout);this.ready=true;this.status='ожидаю запись';this.poll();this.poller=setInterval(()=>this.poll(),1000);}
  else if(op===5) {
   if(d.eventType==='CurrentSceneCollectionChanging'){this.sceneChanging=true;this.valid=false;this.invalidate();}
   if(d.eventType==='CurrentSceneCollectionChanged'){this.sceneChanging=false;this.poll();}
   if(d.eventType==='RecordFileChanged'){this.valid=false;this.invalidate();this.status='файл разделён: нужна новая привязка';}
   if(d.eventType==='RecordStateChanged') {
    const e=d.eventData;
    this.invalidate();
    if(e.outputState==='OBS_WEBSOCKET_OUTPUT_STARTED'){this.session=randomUUID();this.valid=true;this.file=null;this.lastMs=0;this.active=false;}
    if(e.outputState==='OBS_WEBSOCKET_OUTPUT_STOPPED'){
     if(this.session&&this.valid&&e.outputPath)this.onFile({session:this.session,file:e.outputPath});
     this.valid=false;this.active=false;
    }
    // Invalidate interpolation immediately on pause / stop / resume transition.
    if(this.session)this.onSample({at:Date.now(),ms:0,session:this.session,active:false,paused:true});
    this.poll();
   }
  }
  else if(op===7&&this.pending&&d.requestId===this.pendingId) {
   this.pending=false;if(!d.requestStatus?.result){this.status='нет статуса записи';return;}
   const r=d.responseData,now=Date.now();
   if(this.active&&r.outputDuration<this.lastMs-1000)this.valid=false;
   this.lastMs=r.outputDuration;this.active=r.outputActive;
   if(!r.outputActive)this.status='запись не идёт';
   else if(!this.valid)this.status='запись без начальной привязки';
   else this.status=r.outputPaused?'запись на паузе':'таймкоды OBS';
   if(this.session)this.onSample({at:Math.round((this.requestAt+now)/2),ms:r.outputDuration,session:this.session,active:!!r.outputActive&&this.valid&&(now-this.requestAt<1000),paused:!!r.outputPaused});
  }
 }
 close(){this.stopped=true;clearTimeout(this.timeout);clearTimeout(this.retry);clearInterval(this.poller);this.ws?.close();}
}
