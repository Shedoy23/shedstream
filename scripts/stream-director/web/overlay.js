const $=id=>document.getElementById(id);let last='';
export function render(state){
 const t=state.thoughts;$('card').hidden=!t?.visible;if(!t?.visible)return;
 $('thought').textContent=t.thought;$('previous').textContent=t.previous?.[0]?'До этого: '+t.previous[0]:'';
 $('thought').classList.toggle('long',t.thought.length>130);
 $('age').textContent=t.age<10?'только что':`${Math.floor(t.age)} с назад`;
 const b=state.battle;$('metrics').hidden=!b;
 $('phase').textContent=b?(b.finished?'ИТОГ БОЯ':b.siege?'ШТУРМ':'БОЙ'):'ПОХОД';
 if(b){$('heroes').textContent=b.participants;$('heroesLabel').textContent=b.finished?'героев участвовало':'героев замечено';$('enemyMetric').hidden=b.enemyStart===null;$('enemies').textContent=b.enemyStart??'—';$('outcome').textContent=b.finished?({victory:'ПОБЕДА',defeat:'ПОРАЖЕНИЕ',unknown:'ЗАВЕРШЁН'}[b.outcome]):b.siege?'ОСАДА':'БИТВА';$('outcomeLabel').textContent=b.finished?'результат':'событие';}
 if(last!==t.thought){last=t.thought;$('card').classList.remove('changed');void $('card').offsetWidth;$('card').classList.add('changed');}
}
const demo=new URLSearchParams(location.search).has('demo');
if(demo){
 document.body.classList.add('demo');$('demo').hidden=false;
 const scenes={siege:['Хватит ждать — лезем на стены. Кто первый наверху, тот герой.',{siege:true,participants:18,enemyStart:null,outcome:'unknown',finished:false}],field:['Подкрепление подошло. Теперь можно прижать их с двух сторон.',{siege:false,participants:24,enemyStart:null,outcome:'unknown',finished:false}],victory:['Крепость наша. Теперь бойцам нужен отдых.',{siege:true,participants:18,enemyStart:740,outcome:'victory',finished:true}],long:['К нам идёт вражеская армия. Сворачиваем осаду, собираем отряды вместе и отходим к своим владениям — здесь принимать бой слишком опасно.',null],off:['',null]};
 const show=name=>{const [thought,battle]=scenes[name];render({thoughts:{visible:name!=='off',thought,previous:['Встали лагерем у крепости. Готовимся к штурму.'],age:3},battle});};
 for(const b of document.querySelectorAll('button[data-scene]'))b.addEventListener('click',()=>show(b.dataset.scene));show('siege');
}else{
 let failures=0;
 async function poll(){try{const r=await fetch('/api/state',{cache:'no-store',signal:AbortSignal.timeout(2500)});if(!r.ok)throw Error();render(await r.json());failures=0;}catch{if(++failures>=2)$('card').hidden=true;}setTimeout(poll,1000);}poll();
}
