import {act,cleanup,render} from '@testing-library/preact';
import {afterEach,expect,it,vi} from 'vitest';
import {pair,flush,disposePairs} from './panel-shell-pair';
import {CasesView} from '../src/common/CasesView';
import {PetsView} from '../src/common/PetsView';
import {ViewerShell} from '../src/common/ViewerShell';
import {PanelController} from '../src/panel/controller';
import {HttpPanelTransport} from '../src/panel/transport';
afterEach(()=>{cleanup();disposePairs();vi.useRealTimers();});
it('shell collapse and restore retain exact minute activity without remounting services',async()=>{
  const p=await pair(),controller=new PanelController(new HttpPanelTransport('',p.auth,p.fetcher),p.auth,p.identity);
  const ui=render(<ViewerShell auth={p.auth} identity={p.identity} controller={controller} runtime={p.runtime}/>);await act(async()=>{await vi.dynamicImportSettled();await flush();});
  Object.defineProperty(p.old.document.getElementById('overlay-panel'),'offsetWidth',{value:420});
  await p.old.click('#panel-hide-tab');await act(async()=>{ui.getByRole('button',{name:'Свернуть панель',exact:true}).click();await flush();});
  expect(ui.queryByRole('navigation',{name:'Панель зрителя'})).toBeNull();await act(async()=>{await p.advance(16000);});
  await p.old.click('#panel-restore-tab');await act(async()=>{ui.getByRole('button',{name:'Развернуть панель',exact:true}).click();await flush();await p.advance(45000);});p.check();expect(ui.getByRole('navigation',{name:'Панель зрителя'})).toBeTruthy();
});
it.each([false,true])('cases whole shell open all=%s preserves complete minute traffic',async all=>{
  const p=await pair({'GET /api/viewer/cases':{success:true,cases:[{id:71,tier:'rare',source:'quest',opened_at:null}],unopened_counts:{rare:2,total:2},lifetime_count:5},'GET /api/case/preview':{success:true,tiers:[{tier:'rare',label:'Редкий',color:'#3b82f6',reward_points:1234}]},'POST /api/viewer/case/open':{success:true,tier:'rare',reward_points:1234,new_balance:8888,message:'Открыт'},'POST /api/viewer/cases/open-all':{success:true,opened:2,total_reward:2468,left:1,message:'Остался 1'}});
  await p.old.click('[data-action="cases"]');document.dispatchEvent(new Event('click'));const ui=render(<CasesView client={p.runtime.snapshot().client!}/>);await act(flush);p.check();await p.old.click(all?'#cases-open-all-btn':'[data-open-case-id="71"]');await act(async()=>{ui.getByRole('button',{name:all?'Открыть все (2)':'Открыть кейс 71',exact:true}).click();await flush();await p.advance(60000);});p.check();
});
it('pets whole shell paid confirmation has one extra click and complete minute traffic',async()=>{
  const gem={item_id:'fixture_gem',name:'Огонёк',slot:'aura',rarity:'epic',price_crustics:12345,owned:false};
  const p=await pair({'GET /api/pet/my':{success:true,username:'alice',pet:{pet_type:'egg',name:'Друг'},inventory:[],equipped:{}},'GET /api/pet/catalog':{success:true,items:[gem]},'POST /api/pet/purchase':{success:true,price:12345,hatched:true,message:'Питомец вылупился'}});
  await p.old.click('[data-action="pets"]');document.dispatchEvent(new Event('click'));const ui=render(<PetsView client={p.runtime.snapshot().client!}/>);await act(flush);p.check();await p.old.click('#pets-tab-catalog');await act(async()=>{ui.getByRole('button',{name:'Магазин питомцев',exact:true}).click();});await p.old.click('[data-pet-action="buy"][data-item-id="fixture_gem"]');await act(async()=>{ui.getByRole('button',{name:'Купить Огонёк',exact:true}).click();});await act(async()=>{ui.getByRole('button',{name:'Подтвердить',exact:true}).click();await flush();await p.advance(60000);});p.check({extraConfirmationClicks:1});
});
