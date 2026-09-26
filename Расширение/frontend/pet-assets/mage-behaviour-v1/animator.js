(function(global){
'use strict';
const clips={
 idle:{frames:[0,1],times:[1300,1300]},
 start:{frames:[2,3],times:[160,140]},
 walk:{frames:[0,1,2,3,4,5,6,7],times:[110,90,100,100,110,90,100,100]},
 stop:{frames:[4,5],times:[140,220]},
 yawn:{frames:[6],times:[700]},
 sit:{frames:[7],times:[350]},
 sleep:{frames:[8,9],times:[1500,1500]},
 wake:{frames:[10],times:[500]},
 rise:{frames:[11],times:[350]}
};
class MageAnimator{
 constructor(){this.state='idle';this.elapsed=0;this.intent='idle'}
 request(intent){if(!['idle','walk','sleep'].includes(intent))throw Error('Unknown intent');this.intent=intent}
 enter(state){this.state=state;this.elapsed=0}
 update(ms){
  if(!Number.isFinite(ms)||ms<0)throw Error('Invalid delta');
  let remaining=ms;
  for(let guard=0;guard<1000;guard++){
   if(this.state==='idle'&&this.intent!=='idle'){this.enter(this.intent==='walk'?'start':'yawn');continue}
   if(this.state==='sleep'&&this.intent!=='sleep'){this.enter('wake');continue}
   const clip=clips[this.state],duration=clip.times.reduce((a,b)=>a+b,0);
   if(this.state==='idle'||this.state==='sleep'){this.elapsed=(this.elapsed+remaining)%duration;break}
   const take=Math.min(remaining,duration-this.elapsed);this.elapsed+=take;remaining-=take;
   if(this.elapsed<duration)break;
   const next={start:this.intent==='walk'?'walk':'stop',walk:this.intent==='walk'?'walk':'stop',stop:'idle',yawn:this.intent==='sleep'?'sit':'idle',sit:'sleep',wake:'rise',rise:'idle'}[this.state];
   this.enter(next);
   if(remaining===0&&this.state!=='idle'&&this.state!=='sleep')break;
  }
 }
 pose(){const c=clips[this.state];let t=this.elapsed,index=0;while(index<c.times.length-1&&t>=c.times[index]){t-=c.times[index];index++}return {sheet:this.state==='walk'?'walk':'behaviour',frame:c.frames[index],state:this.state}}
 speed(){
  if(this.state==='walk')return 52;
  if(this.state==='start')return 52*Math.max(0,(this.elapsed-160)/140);
  if(this.state==='stop')return 52*Math.max(0,1-this.elapsed/140);
  return 0;
 }
}
if(typeof module!=='undefined'&&module.exports)module.exports={MageAnimator};
else global.MageAnimator=MageAnimator;
})(typeof window!=='undefined'?window:globalThis);
