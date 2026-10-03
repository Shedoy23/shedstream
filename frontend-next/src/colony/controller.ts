import type {ViewerClient} from '../common/client';
import type {ViewerRuntime} from '../common/runtime';
import type {ColonyConfig,Colonist,Capacity} from './contracts';
interface ActionState {busy:boolean;uncertain:boolean;actionMessage:string}
const idleAction=():ActionState=>({busy:false,uncertain:false,actionMessage:''});
const ownerOf=(client:ViewerClient)=>JSON.stringify(['shedcolony',client.identity.channelId,client.identity.login]);
interface State extends ActionState {config:ColonyConfig|null;citizen:Colonist|null;cap:Capacity|null;message:string}
export class ColonyController {
  private state:State={config:null,citizen:null,cap:null,message:'Загрузка колонии…',...idleAction()};
  // Kept for this controller's lifetime, independently of component remounts,
  // JWT rotations and active_module changes. A page reload is not reconciliation.
  private actions=new Map<string,ActionState>();
  private listeners=new Set<()=>void>();private client:ViewerClient|null=null;private owner='';private sequence=0;private appliedSequence=0;private configSequence=0;private timer?:ReturnType<typeof setInterval>;
  constructor(private readonly runtime?:ViewerRuntime){runtime?.bindModule((client,module)=>{if(client&&module==='shedcolony')this.start(client);else this.stop();});}
  snapshot=()=>this.state;
  subscribe=(fn:()=>void)=>{this.listeners.add(fn);return()=>{this.listeners.delete(fn);};};
  private publish(patch:Partial<State>){this.state={...this.state,...patch};this.listeners.forEach(fn=>fn());}
  attach(client:ViewerClient){this.start(client);const off=client.onStats(stats=>{if(stats.active_module==='shedcolony')this.start(client);});return()=>{off();this.stop();};}
  private start(client:ViewerClient){
    const owner=ownerOf(client);if(this.owner&&this.owner!==owner)this.stop();this.owner=owner;this.client=client;this.publish(this.actions.get(owner)||idleAction());
    const issued=++this.configSequence,owns=()=>this.client===client&&issued===this.configSequence;
    void client.read<ColonyConfig>('/api/shedcolony/config').then(config=>{if(owns())this.publish({config});}).catch(()=>{if(owns())this.publish({config:null,message:'Цены и каталог не загружены — покупки недоступны'});}).then(()=>{if(owns())void this.refresh();});
    void this.refresh();if(this.timer===undefined)this.timer=setInterval(()=>{void this.refresh();},5000);
  }
  refresh=async()=>{
    const client=this.client;if(!client)return;const issued=++this.sequence;
    const [citizen,cap]=await Promise.all([client.read<Colonist>('/api/shedcolony/my-colonist').catch(()=>null),client.read<Capacity>('/api/shedcolony/capacity').catch(()=>null)]);
    if(this.client!==client||issued<=this.appliedSequence)return;
    this.appliedSequence=issued;
    this.publish({citizen:citizen?.success?citizen:null,cap:cap?.success?cap:null,message:!citizen?.success||!cap?.success?citizen?.message||cap?.message||'Состояние колонии недоступно. Действия заблокированы.':this.state.message==='Загрузка колонии…'?'':this.state.message});
  };
  private actionState(owner:string,state:ActionState){
    this.actions.set(owner,state);
    if(this.owner===owner)this.publish(state);
  }
  async action(client:ViewerClient,type:string,data:Record<string,unknown>,label:string){
    const owner=ownerOf(client),previous=this.actions.get(owner);
    if(this.client!==client||this.owner!==owner||previous?.busy||previous?.uncertain)return;
    if(this.runtime&&(this.runtime.snapshot().client!==client||this.runtime.snapshot().stats?.active_module!=='shedcolony'))return;
    this.actionState(owner,{busy:true,uncertain:false,actionMessage:'Заявка отправлена. Ждём ответ сервера.'});
    try{
      const result=await client.moduleAction<{success:boolean;message?:string}>('shedcolony',type,data);
      if(!result||typeof result.success!=='boolean')throw new Error('Некорректный ответ сервера');
      this.actionState(owner,{busy:false,uncertain:false,actionMessage:result.success?`Заявка принята: ${label}. Исход будет известен после выполнения в игре; повторно нажимать не нужно.`:result.message||'Сервер отказал в действии'});
      const current=this.client;
      if(result.success&&this.owner===owner&&current&&(!this.runtime||this.runtime.snapshot().client===current)){
        void current.refreshUser().catch(()=>{});void this.refresh();
      }
    }catch(error){
      this.actionState(owner,{busy:false,uncertain:true,actionMessage:(error instanceof Error?error.message:'Ошибка сети')+'. Исход заявки неизвестен; повторная покупка заблокирована в этой открытой панели.'});
    }
  }
  stop(){clearInterval(this.timer);this.timer=undefined;this.client=null;this.owner='';this.appliedSequence=++this.sequence;this.configSequence++;this.publish({config:null,citizen:null,cap:null,message:'Загрузка колонии…',...idleAction()});}
}
