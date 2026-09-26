'use strict';
const $=id=>document.getElementById(id);
const stateNames={idle:'Отдыхает',start:'Собирается в путь',walk:'Гуляет',stop:'Заканчивает шаг',yawn:'Зевает',sit:'Устраивается поудобнее',sleep:'Спит',wake:'Просыпается',rise:'Поднимается'};
const poseNames=['Выдох','Вдох','Перед шагом','Первый шаг','Остановка','Расслабился','Зевок','Устраивается','Спит · выдох','Спит · вдох','Просыпается','Поднимается'];
const schedule=[[0,'idle'],[1800,'walk'],[6500,'idle'],[8200,'sleep'],[15000,'idle'],[18500,'walk'],[23000,'idle']];
let entries=[],selected=null,ready=false,auto=!matchMedia('(prefers-reduced-motion: reduce)').matches,paused=!auto,slow=false,size=180,last=0,inspection=null,lastMainKey='';
function controls(){
 $('auto').setAttribute('aria-pressed',String(auto));$('pause').setAttribute('aria-pressed',String(paused));$('pause').textContent=paused?'Продолжить':'Пауза';
 document.querySelectorAll('[data-intent]').forEach(b=>b.setAttribute('aria-pressed',String(!auto&&selected&&b.dataset.intent===selected.desired)));
}
function command(intent){auto=false;paused=false;inspection=null;for(const e of entries){e.desired=intent;e.turnPending=false;e.model.request(intent)}controls()}
document.querySelectorAll('[data-intent]').forEach(b=>b.onclick=()=>command(b.dataset.intent));
$('wake').onclick=()=>command('idle');
$('auto').onclick=()=>{auto=!auto;paused=false;inspection=null;entries.forEach((e,i)=>{e.autoTime=i*1700;e.lastAuto=-1});controls()};
$('pause').onclick=()=>{paused=!paused;if(!paused)inspection=null;controls()};
$('slow').onclick=()=>{slow=!slow;$('slow').setAttribute('aria-pressed',String(slow))};
$('turn').onclick=()=>{if(!selected)return;auto=false;paused=false;inspection=null;selected.turnPending=!selected.turnPending;selected.model.request(selected.turnPending?'idle':selected.desired);controls()};
$('background').onclick=()=>{const on=document.body.classList.toggle('light');$('background').setAttribute('aria-pressed',String(on))};
$('size').onchange=e=>{size=Number(e.target.value);$('hero').style.width=$('hero').style.height=size+'px';entries.forEach(e=>e.x=clamp(e.x));render()};
$('pet').onchange=e=>selectPet(e.target.value,true);
function limit(){return Math.max(0,($('world').clientWidth-size-60)/2)}
function clamp(x){return Math.max(-limit(),Math.min(limit(),x))}
function paint(canvas,entry,pose){const ctx=canvas.getContext('2d');ctx.clearRect(0,0,256,256);ctx.imageSmoothingEnabled=false;ctx.drawImage(entry.images[pose.sheet],pose.frame*256,0,256,256,0,0,256,256)}
function selectPet(id,updateUrl=false){
 const e=entries.find(e=>e.profile.id===id);if(!e)return;
 selected=e;inspection=null;lastMainKey='';$('pet').value=id;$('petname').textContent=e.profile.name;$('story').textContent=e.profile.story;$('hero').setAttribute('aria-label',e.profile.name);$('hero').dataset.pet=id;
 document.querySelectorAll('.pet-choice').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.pet===id)));
 if(updateUrl){const url=new URL(location.href);url.searchParams.set('pet',id);history.replaceState(null,'',url)}
 if(ready)buildFrames();controls();render();
}
function buildFrames(){
 $('frames').replaceChildren();
 for(const sheet of ['walk','behaviour'])for(let frame=0;frame<(sheet==='walk'?8:12);frame++){
  const pose={sheet,frame},b=document.createElement('button');b.className='frame';b.dataset.sheet=sheet;b.dataset.frame=frame;
  const label=sheet==='walk'?(selected.profile.hover?'Парение ':'Шаг ')+(frame+1):poseNames[frame];
  b.setAttribute('aria-label',label);b.innerHTML='<canvas width="256" height="256"></canvas><span></span>';b.querySelector('span').textContent=label;paint(b.querySelector('canvas'),selected,pose);
  b.onclick=()=>{inspection=pose;auto=false;paused=true;document.querySelectorAll('.frame').forEach(q=>q.setAttribute('aria-pressed',String(q===b)));controls();render()};
  $('frames').append(b);
 }
}
function render(){
 if(!ready||!selected)return;
 for(const e of entries){
  const p=e.model.pose(),key=p.sheet+':'+p.frame;
  if(key!==e.lastKey){paint(e.canvas,e,p);e.lastKey=key}
  e.canvas.dataset.state=e.model.state;e.canvas.dataset.frame=p.frame;e.canvas.dataset.sheet=p.sheet;
  e.caption.textContent=e.profile.hover&&e.model.state==='walk'?'Парит':stateNames[e.model.state];
 }
 const e=selected,p=inspection||e.model.pose(),key=e.profile.id+':'+p.sheet+':'+p.frame;
 if(key!==lastMainKey){paint($('hero'),e,p);lastMainKey=key}
 $('hero').style.transform='translateX(calc(-50% + '+e.x+'px)) translateY('+(-e.bob)+'px) scaleX('+e.direction+')';
 $('hero').dataset.state=inspection?'inspect':e.model.state;$('hero').dataset.frame=p.frame;$('hero').dataset.sheet=p.sheet;
 $('state').textContent=inspection?'Рассматриваем кадр':e.profile.hover&&e.model.state==='walk'?'Парит':stateNames[e.model.state];
 $('frameLabel').textContent=(p.sheet==='walk'?(e.profile.hover?'Парение':'Ходьба'):'Поведение')+' · '+(p.frame+1)+' / '+(p.sheet==='walk'?8:12);
 $('next').textContent=inspection?'Продолжи или выбери действие':e.turnPending?'Остановится и развернётся':auto?'Каждый занят своим делом':e.desired==='sleep'?'После переходов — сон':e.desired==='walk'?'После переходов — прогулка':'После переходов — отдых';
}
function load(image,url){return new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(Error(url));image.src=url})}
fetch('profiles.json').then(r=>{if(!r.ok)throw Error('profiles');return r.json()}).then(async profiles=>{
 entries=profiles.map((profile,i)=>({profile,model:new PetAnimator(profile),images:{walk:new Image(),behaviour:new Image()},desired:'idle',direction:1,x:clamp(-100+i*12),autoTime:i*1700,lastAuto:-1,turnPending:false,bob:0,clock:0,lastKey:''}));
 for(const e of entries){const option=document.createElement('option');option.value=e.profile.id;option.textContent=e.profile.name;$('pet').append(option)}
 await Promise.all(entries.flatMap(e=>[load(e.images.walk,'assets/'+e.profile.id+'/walk-8.png'),load(e.images.behaviour,'assets/'+e.profile.id+'/behaviour-12.png')]));
 for(const e of entries){
  const b=document.createElement('button');b.className='pet-choice';b.dataset.pet=e.profile.id;b.setAttribute('aria-label',e.profile.name);
  b.innerHTML='<canvas width="256" height="256"></canvas><span></span><small></small>';b.querySelector('span').textContent=e.profile.name;e.canvas=b.querySelector('canvas');e.caption=b.querySelector('small');
  b.onclick=()=>selectPet(e.profile.id,true);$('gallery').append(b);
 }
 ready=true;const requested=new URL(location.href).searchParams.get('pet');selectPet(entries.some(e=>e.profile.id===requested)?requested:'wayfarer');
}).catch(error=>{$('state').textContent='Не удалось загрузить все картинки. Обнови страницу.';$('state').className='error';console.error(error)});
function tick(now){
 const dt=last?Math.min(50,now-last)*(slow?.25:1):0;last=now;
 if(ready&&!paused)for(const e of entries){
  e.clock+=dt;
  if(auto){e.autoTime=(e.autoTime+dt)%26000;let index=0;for(let i=0;i<schedule.length;i++)if(e.autoTime>=schedule[i][0])index=i;if(index!==e.lastAuto){e.lastAuto=index;e.desired=schedule[index][1];e.turnPending=false;e.model.request(e.desired)}}
  if(e.model.state==='walk'&&!e.turnPending&&((e.direction>0&&e.x>limit()-48)||(e.direction<0&&e.x<-limit()+48))){e.turnPending=true;e.model.request('idle')}
  const before=e.model.speed();e.model.update(dt);
  if(e.turnPending&&e.model.state==='idle'){e.direction*=-1;e.turnPending=false;e.model.request(e.desired);e.model.update(0)}
  e.x=clamp(e.x+e.direction*(before+e.model.speed())/2*dt/1000*(size/180));
  const hovering=e.profile.hover&&['idle','start','walk','stop','yawn'].includes(e.model.state),target=hovering?7+Math.sin(e.clock/650)*3:0;e.bob+=(target-e.bob)*Math.min(1,dt/180);
 }
 render();requestAnimationFrame(tick);
}
window.addEventListener('resize',()=>{entries.forEach(e=>e.x=clamp(e.x));render()});
controls();requestAnimationFrame(tick);
