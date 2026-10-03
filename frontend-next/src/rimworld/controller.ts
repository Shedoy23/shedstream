import type {ViewerClient} from '../common/client';
import type {ViewerRuntime} from '../common/runtime';
export interface RimItem {def_name:string;label?:string;name?:string;description?:string;desc?:string;tooltip?:string;category?:string;price?:number;degree?:number;trait_def?:string;is_paired?:boolean;has_archite?:boolean;source_mod?:string;genes?:({def_name?:string;label?:string}|string)[];[key:string]:unknown}
export interface RimSkill {def_name:string;name?:string;label?:string;level:number;passion:number;xp?:number;is_disabled?:boolean;disabled?:boolean;upgrade_price?:number|null;reset_price?:number|null}
export interface RimPawn {exists:boolean;auth_required?:boolean;error?:string;pawn_name?:string;is_alive?:boolean;health?:number;world_id?:string;world_name?:string;equipment?:(RimItem&{slot?:string;item_def?:string;hp?:number;max_hp?:number})[];skills?:RimSkill[];traits?:RimItem[];genes?:(RimItem&{is_active?:boolean;xenogene?:boolean;gene_class?:string})[];hediffs?:{def_name?:string;part?:string;part_def?:string;label?:string;severity?:number;is_paired?:boolean;is_left?:boolean|null}[]}
export type PawnAction='create'|'heal'|'resurrect'|'remove-trait'|'remove-gene';
export type RimAction=PawnAction|'item'|'implant'|'trait'|'gene'|'neuro'|'xeno'|'passion'|'reset'|'event';
export interface RimConfirmation {kind:RimAction;id:string;degree?:number;label:string;price:number;context:string;body:Record<string,unknown>;endpoint:string}
export interface RimState {pawn:RimPawn|null;config:Record<string,unknown>|null;online:boolean|null;colonists:{username:string;pawn_name:string;health:number;is_alive:boolean}[];catalog:RimItem[];events:{id:string|number;name:string;cost:number;category?:string}[];skills:RimSkill[];modal:'passion'|'xenotype'|'neurotrainer'|null;modalItems:RimItem[];side:{item:RimItem;context:string}|null;message:string;busy:boolean;confirmation:RimConfirmation|null;cooldownUntil:number;healPending:boolean;now:number}
const empty=():RimState=>({pawn:null,config:null,online:null,colonists:[],catalog:[],events:[],skills:[],modal:null,modalItems:[],side:null,message:'',busy:false,confirmation:null,cooldownUntil:0,healPending:false,now:Date.now()});
export const actualPrice=(p:unknown):p is number=>typeof p==='number'&&Number.isFinite(p)&&p>=0;
export class RimworldController {
  private actionSession=0;private state=empty();private listeners=new Set<()=>void>();private client:ViewerClient|null=null;private owner='';private statusTimer:ReturnType<typeof setInterval>|undefined;private pawnTimer:ReturnType<typeof setInterval>|undefined;private tick:ReturnType<typeof setInterval>|undefined;private tails=new Set<ReturnType<typeof setTimeout>>();private pawnRevision=0;private catalogFlight:Promise<void>|null=null;
  constructor(readonly runtime:ViewerRuntime){runtime.bindModule((client,module)=>this.sync(module==='rimworld'?client:null));runtime.bindTab(tab=>{if(tab==='integration'&&this.client){this.run(this.refreshPawn());if(!this.state.catalog.some(x=>!['neurotrainer','xenotype'].includes(x.category||'')))this.run(this.loadCatalog());}});}
  snapshot=()=>this.state;subscribe=(fn:()=>void)=>{this.listeners.add(fn);return()=>{this.listeners.delete(fn);};};
  private publish(patch:Partial<RimState>){this.state={...this.state,...patch};this.listeners.forEach(fn=>fn());}
  private current(c:ViewerClient){return c===this.client&&c===this.runtime.snapshot().client;}
  private run(p:Promise<unknown>){void p.catch(e=>{if(this.client)this.publish({message:e instanceof Error?e.message:'Сервер недоступен'});});}
  private sync(client:ViewerClient|null){const owner=client?JSON.stringify([client.identity.channelId,client.identity.login]):'';if(owner===this.owner){this.client=client;return;}this.stop();this.owner=owner;this.client=client;this.publish(empty());if(!client)return;
    this.run(this.loadStatus());this.run(this.loadConfig());this.run(this.loadColonists());this.run(this.refreshPawn());this.run(this.loadCatalog());this.run(this.loadEvents());
    this.statusTimer=setInterval(()=>this.run(this.loadStatus()),30000);this.tick=setInterval(()=>this.publish({now:Date.now()}),1000);
  }
  stop(){this.actionSession++;clearInterval(this.statusTimer);clearInterval(this.pawnTimer);clearInterval(this.tick);this.tails.forEach(clearTimeout);this.tails.clear();this.client=null;this.owner='';this.pawnRevision++;this.catalogFlight=null;}
  private later(fn:()=>void,ms:number){const id=setTimeout(()=>{this.tails.delete(id);if(this.client)fn();},ms);this.tails.add(id);}
  private async loadStatus(){const c=this.client;if(!c)return;const d=await c.read<{online:boolean}>('/api/rimworld/status');if(this.current(c))this.publish({online:d.online});}
  private async loadConfig(){const c=this.client;if(!c)return;const d=await c.read<Record<string,unknown>>('/api/rimworld/config',false);if(this.current(c)){this.publish({config:d});this.run(this.refreshPawn());}}
  private async loadColonists(){const c=this.client;if(!c)return;const d=await c.read<{colonists:RimState['colonists']}>('/api/rimworld/colonists');if(this.current(c))this.publish({colonists:d.colonists||[]});}
  async refreshPawn(){const c=this.client;if(!c)return;const seq=++this.pawnRevision,d=await c.read<RimPawn>('/api/rimworld/my-pawn/'+c.identity.login);if(!this.current(c))return;if(seq===this.pawnRevision){this.publish({pawn:d});this.invalidate();}if(d.exists)this.run(this.loadCooldown(c));}
  private async loadCooldown(c:ViewerClient){const d=await c.read<{cooldown_left:number}>('/api/rimworld/heal-cooldown/'+encodeURIComponent(c.identity.login));if(this.current(c))this.publish({cooldownUntil:d.cooldown_left>0?Date.now()+d.cooldown_left*1000:0,healPending:false});return d.cooldown_left;}
  async loadCatalog(){if(this.catalogFlight)return this.catalogFlight;const c=this.client;if(!c)return;const flight=(async()=>{const d=await c.read<{items:RimItem[]}>('/api/rimworld/catalog?username='+encodeURIComponent(c.identity.login));if(this.current(c)){this.publish({catalog:d.items||[]});this.invalidate();}})();this.catalogFlight=flight;try{await flight;}finally{if(this.catalogFlight===flight)this.catalogFlight=null;}}
  private async loadEvents(){const c=this.client;if(!c)return;const d=await c.read<{events:RimState['events']}>('/api/rimworld/events');if(this.current(c))this.publish({events:d.events||[]});}
  async openModal(modal:NonNullable<RimState['modal']>){const c=this.client;if(!c)return;this.publish({modal,skills:[],modalItems:[]});try{if(modal==='passion'){const d=await c.read<{skills:RimSkill[]}>('/api/rimworld/pawn-skills/'+encodeURIComponent(c.identity.login));if(this.current(c)&&this.state.modal===modal)this.publish({skills:d.skills||[]});}else{const d=await c.read<{items:RimItem[]}>('/api/rimworld/catalog?category='+modal+'&username='+encodeURIComponent(c.identity.login));if(this.current(c)&&this.state.modal===modal)this.publish({modalItems:d.items||[]});}}catch(e){if(this.current(c))this.publish({message:e instanceof Error?e.message:'Каталог недоступен'});}}
  closeModal(){this.publish({modal:null,confirmation:null});}
  private context(kind:RimAction,id:string,degree?:number){const s=this.state,p=s.pawn;const source=kind==='remove-trait'?p?.traits?.find(t=>t.def_name===id&&t.degree===degree):kind==='remove-gene'?p?.genes?.find(g=>g.def_name===id):['item','implant','trait','gene'].includes(kind)?s.catalog.find(x=>x.def_name===id):kind==='neuro'||kind==='xeno'?s.modalItems.find(x=>x.def_name===id):kind==='passion'||kind==='reset'?s.skills.find(x=>x.def_name===id):kind==='event'?s.events.find(x=>String(x.id)===id):null;return JSON.stringify([this.owner,p?.exists,p?.pawn_name,p?.world_id,p?.is_alive,s.config,source,kind==='implant'?p?.hediffs:null]);}
  private invalidate(){const q=this.state.confirmation,side=this.state.side;if(q&&q.context!==this.context(q.kind,q.id,q.degree))this.publish({confirmation:null,message:'Данные изменились. Выбери действие заново.'});if(side&&side.context!==this.context('implant',side.item.def_name))this.publish({side:null,message:'Пешка или имплант изменились. Выбери заново.'});}
  async choose(kind:PawnAction,item?:RimItem){const c=this.client,p=this.state.pawn;if(!c||!p||this.state.busy)return;const keys={create:'spawn_cost',heal:'heal_cost',resurrect:'resurrect_cost','remove-trait':'trait_remove_cost','remove-gene':'gene_remove_cost'};const price=this.state.config?.[keys[kind]];if(!actualPrice(price))return;
    if(kind==='create'?(p.exists||p.auth_required):!p.exists)return;if(kind==='heal'&&!p.is_alive||kind==='resurrect'&&p.is_alive)return;
    if(kind==='remove-trait'&&!p.traits?.some(t=>t.def_name===item?.def_name&&t.degree===item?.degree)||kind==='remove-gene'&&!p.genes?.some(g=>g.def_name===item?.def_name))return;
    if(kind==='heal'){const observed=this.context(kind,'');try{if(await this.loadCooldown(c)>0)return;}catch(e){if(this.current(c))this.publish({message:e instanceof Error?e.message:'Не удалось проверить лечение'});return;}if(!this.current(c))return;if(observed!==this.context(kind,'')){this.publish({message:'Пешка изменилась во время проверки. Выбери лечение заново.'});return;}}
    const id=item?.def_name||'',degree=item?.degree;const body:Record<string,unknown>={username:c.identity.login};if(kind==='create')body.pawn_name=c.identity.login;if(kind==='remove-trait'){body.trait_def=id;body.degree=degree??0;}if(kind==='remove-gene'){body.def_name=id;body.label=item?.label||id;}
    this.publish({confirmation:{kind,id,degree,label:item?.label||p.pawn_name||c.identity.login,price,context:this.context(kind,id,degree),body,endpoint:kind==='create'?'create-pawn':kind==='heal'?'heal-pawn':kind==='resurrect'?'resurrect-pawn':kind}});
  }
  cancel(){this.publish({confirmation:null,side:null});}
  async chooseItem(shown:RimItem,source:'shop'|'xenotype'|'neurotrainer'='shop',part?:'left'|'right'){
    const c=this.client;if(!c||!this.current(c)||this.state.busy||!actualPrice(shown.price))return;const item=(source==='shop'?this.state.catalog:this.state.modalItems).find(x=>x.def_name===shown.def_name);if(!item||JSON.stringify(item)!==JSON.stringify(shown))return;
    const kind:RimAction=source==='xenotype'?'xeno':source==='neurotrainer'?'neuro':item.category==='trait'?'trait':item.category==='gene'?'gene':item.category==='implant'?'implant':'item';
    if(kind==='implant'&&item.is_paired&&!part){const context=this.context(kind,item.def_name);try{const pawn=await c.read<RimPawn>('/api/rimworld/my-pawn/'+c.identity.login);if(!this.current(c)||context!==this.context(kind,item.def_name))return;this.pawnRevision++;this.publish({pawn,side:{item,context:''},confirmation:null});this.publish({side:{item,context:this.context(kind,item.def_name)}});}catch(e){if(this.current(c))this.publish({message:e instanceof Error?e.message:'Стороны импланта не определены'});}return;}
    if(part&&(!this.state.side||this.state.side.context!==this.context(kind,item.def_name)))return;
    const body:Record<string,unknown>={username:c.identity.login};let endpoint='buy-item';
    if(kind==='trait'){endpoint='buy-trait';body.trait_def=item.trait_def||item.def_name;body.degree=item.degree||0;body.expected_price=item.price;}
    else if(kind==='gene'){endpoint='buy-gene';body.def_name=item.def_name;body.expected_price=item.price;}
    else{body.item_def=item.def_name;if(kind==='xeno')body.def_name=item.def_name;if(kind==='implant'){endpoint='buy-implant';if(part)body.part_hint=part;}if(kind==='neuro')endpoint='train-skill';}
    this.publish({side:null,confirmation:{kind,id:item.def_name,label:(item.label||item.name||item.def_name)+(part?(part==='left'?' · левая сторона':' · правая сторона'):''),price:item.price!,body,endpoint,context:this.context(kind,item.def_name)}});
  }
  chooseSide(part:'left'|'right'){const side=this.state.side;if(side)this.run(this.chooseItem(side.item,'shop',part));}
  occupied(part:'left'|'right'){const side=this.state.side;if(!side)return false;const id=side.item.def_name.toLowerCase();return this.state.pawn?.hediffs?.some(x=>x.is_paired&&(x.def_name?.toLowerCase()===id||x.part_def?.toLowerCase()===id)&&x.is_left===(part==='left'))||false;}
  chooseSkill(shown:RimSkill,reset=false){const c=this.client,skill=this.state.skills.find(x=>x.def_name===shown.def_name);if(!c||!this.current(c)||this.state.busy||!skill||JSON.stringify(skill)!==JSON.stringify(shown)||skill.is_disabled)return;const price=reset?skill.reset_price:skill.upgrade_price;if(!actualPrice(price))return;const kind=reset?'reset':'passion',body:Record<string,unknown>={username:c.identity.login,skill_def:skill.def_name};if(!reset)body.passion=skill.passion+1;this.publish({confirmation:{kind,id:skill.def_name,label:skill.label||skill.def_name,price,body,endpoint:reset?'reset-passion':'buy-passion',context:this.context(kind,skill.def_name)}});}
  chooseEvent(shown:RimState['events'][number]){const c=this.client,event=this.state.events.find(x=>String(x.id)===String(shown.id));if(!c||!this.current(c)||this.state.busy||!event||JSON.stringify(event)!==JSON.stringify(shown)||!actualPrice(event.cost))return;const id=String(event.id);this.publish({confirmation:{kind:'event',id,label:event.name,price:event.cost,body:{username:c.identity.login,event_id:id},endpoint:'trigger-event',context:this.context('event',id)}});}
  async confirm(){
    const c=this.client,q=this.state.confirmation;
    if(!c||!this.current(c)||!q||this.state.busy)return;
    if(q.context!==this.context(q.kind,q.id,q.degree)){this.invalidate();return;}
    // An admitted action belongs to the viewer session, not its rotating JWT.
    // stop() invalidates this session even if the same viewer later returns.
    const session=this.actionSession,owns=()=>session===this.actionSession&&this.owner!=='';
    this.publish({confirmation:null,busy:true});
    try{
      const d=await c.post<{success:boolean;message?:string;cooldown_left?:number}>('/api/rimworld/'+q.endpoint,q.body);
      if(!owns())return;
      if(!d||typeof d.success!=='boolean')throw new Error('Некорректный ответ сервера');
      this.publish({busy:false,message:(d.success?'Заявка принята. Ждём игру. ':'')+(d.message||(!d.success?'Сервер отказал в действии':''))});
      if(d.success){
        if(q.kind==='xeno')this.publish({modal:null});
        const current=this.client;if(current&&this.current(current))this.run(current.refreshUser());
        if(q.kind==='heal')this.publish({healPending:true});
        if(['remove-trait','passion','reset'].includes(q.kind))this.later(()=>this.run(this.openModal('passion')),2000);
        if(!['item','implant','neuro','event'].includes(q.kind))this.startPawnRefresh(q.kind==='create'?25000:15000,q.kind==='create'?5000:3000);
        if(q.kind==='trait'||q.kind==='gene')this.run(this.loadCatalog());
      }else if(typeof d.cooldown_left==='number')this.publish({cooldownUntil:Date.now()+d.cooldown_left*1000,healPending:false});
    }catch{
      if(owns())this.publish({message:'Исход заявки неизвестен. Проверь состояние пешки. Повторная покупка заблокирована до нового входа.'});
    }
  }
  private startPawnRefresh(duration:number,interval:number){clearInterval(this.pawnTimer);let elapsed=0;this.pawnTimer=setInterval(()=>{elapsed+=interval;if(elapsed>=duration){clearInterval(this.pawnTimer);return;}this.run(this.refreshPawn());},interval);}
}
