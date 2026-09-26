'use strict';
const $=id=>document.getElementById(id),mage=new MageAnimator(),images={walk:new Image(),behaviour:new Image()};
const names={idle:'Отдыхает',start:'Собирается в путь',walk:'Гуляет',stop:'Заканчивает шаг',yawn:'Зевает',sit:'Устраивается поудобнее',sleep:'Спит',wake:'Просыпается и потягивается',rise:'Встаёт с фонарём'};
const poseNames=['Выдох','Вдох','Перед шагом','Первый шаг','Остановка','Расслабился','Зевок','Садится','Спит · выдох','Спит · вдох','Потягивается','Встаёт'];
const schedule=[[0,'idle'],[1800,'walk'],[6500,'idle'],[8200,'sleep'],[15000,'idle'],[18500,'walk'],[23000,'idle']];
let auto=!matchMedia('(prefers-reduced-motion: reduce)').matches,paused=!auto,slow=false,desired='idle',direction=1,x=-120,size=180,autoTime=0,lastAuto=-1,last=0,ready=false,turnPending=false,inspection=null,lastKey='';
function controls(){$('auto').setAttribute('aria-pressed',String(auto));$('pause').setAttribute('aria-pressed',String(paused));$('pause').textContent=paused?'Продолжить':'Пауза';document.querySelectorAll('[data-intent]').forEach(b=>b.setAttribute('aria-pressed',String(!auto&&b.dataset.intent===desired)))}
function command(intent){auto=false;paused=false;inspection=null;desired=intent;turnPending=false;mage.request(intent);controls()}
document.querySelectorAll('[data-intent]').forEach(b=>b.onclick=()=>command(b.dataset.intent));
$('wake').onclick=()=>command('idle');
$('auto').onclick=()=>{auto=!auto;inspection=null;paused=false;autoTime=0;lastAuto=-1;if(!auto){desired= mage.intent;mage.request(desired)}controls()};
$('pause').onclick=()=>{paused=!paused;if(!paused)inspection=null;controls()};
$('slow').onclick=()=>{slow=!slow;$('slow').setAttribute('aria-pressed',String(slow))};
$('turn').onclick=()=>{auto=false;paused=false;inspection=null;turnPending=!turnPending;if(turnPending)mage.request('idle');else mage.request(desired);controls()};
$('background').onclick=()=>{const on=document.body.classList.toggle('light');$('background').setAttribute('aria-pressed',String(on))};
$('size').onchange=e=>{size=Number(e.target.value);$('hero').style.width=$('hero').style.height=size+'px';x=Math.max(-limit(),Math.min(limit(),x));render()};
function limit(){return Math.max(0,($('world').clientWidth-size-60)/2)}
function paint(canvas,pose){const ctx=canvas.getContext('2d');ctx.clearRect(0,0,256,256);ctx.imageSmoothingEnabled=false;ctx.drawImage(images[pose.sheet],pose.frame*256,0,256,256,0,0,256,256)}
function render(){
 if(!ready)return;
 const pose=inspection||mage.pose(),key=pose.sheet+':'+pose.frame;
 if(key!==lastKey){paint($('hero'),pose);lastKey=key}
 $('hero').style.transform='translateX(calc(-50% + '+x+'px)) scaleX('+direction+')';
 $('hero').dataset.state=inspection?'inspect':mage.state;$('hero').dataset.frame=pose.frame;$('hero').dataset.sheet=pose.sheet;
 $('state').textContent=inspection?'Рассматриваем кадр':names[mage.state];
 $('frameLabel').textContent=(pose.sheet==='walk'?'Ходьба':'Поведение')+' · '+(pose.frame+1)+' / '+(pose.sheet==='walk'?8:12);
 $('next').textContent=inspection?'Нажми «Продолжить» или выбери действие':turnPending?'Остановится и развернётся':auto?'Сам выбирает занятие':desired==='sleep'?'После переходов — сон':desired==='walk'?'После переходов — прогулка':'После переходов — отдых';
}
function load(image,url){return new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=reject;image.src=url})}
Promise.all([load(images.walk,'walk-8.png'),load(images.behaviour,'behaviour-12.png')]).then(()=>{
 ready=true;for(const sheet of ['walk','behaviour'])for(let frame=0;frame<(sheet==='walk'?8:12);frame++){
  const pose={sheet,frame},b=document.createElement('button');b.className='frame';b.setAttribute('aria-label',sheet==='walk'?'Шаг '+(frame+1):poseNames[frame]);
  b.innerHTML='<canvas width="256" height="256"></canvas><span>'+(sheet==='walk'?'Шаг '+(frame+1):poseNames[frame])+'</span>';paint(b.querySelector('canvas'),pose);
  b.onclick=()=>{inspection=pose;auto=false;paused=true;controls();document.querySelectorAll('.frame').forEach(q=>q.setAttribute('aria-pressed',String(q===b)));render()};
  $('frames').append(b);
 }x=Math.max(-limit(),Math.min(limit(),x));render();
}).catch(()=>{$('state').textContent='Картинки не загрузились. Обнови страницу.';$('state').className='error'});
function tick(now){
 const dt=last?Math.min(50,now-last)*(slow?.25:1):0;last=now;
 if(ready&&!paused){
  if(auto){autoTime=(autoTime+dt)%26000;let index=0;for(let i=0;i<schedule.length;i++)if(autoTime>=schedule[i][0])index=i;if(index!==lastAuto){lastAuto=index;desired=schedule[index][1];turnPending=false;mage.request(desired)}}
  if(mage.state==='walk'&&!turnPending&&((direction>0&&x>limit()-48)||(direction<0&&x<-limit()+48))){turnPending=true;mage.request('idle')}
  const before=mage.speed();mage.update(dt);
  if(turnPending&&mage.state==='idle'){direction*=-1;turnPending=false;mage.request(desired);mage.update(0)}
  x=Math.max(-limit(),Math.min(limit(),x+direction*(before+mage.speed())/2*dt/1000*(size/180)));
 }
 render();requestAnimationFrame(tick);
}
window.addEventListener('resize',()=>{x=Math.max(-limit(),Math.min(limit(),x));render()});
controls();requestAnimationFrame(tick);

