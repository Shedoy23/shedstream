import {act,cleanup,render} from '@testing-library/preact';
import {afterEach,expect,it,vi} from 'vitest';
import {CommunityGamesView,type CommunityGame} from '../src/common/CommunityGamesView';
import {pair,flush,disposePairs,authorization,token} from './panel-shell-pair';
import saved from './panel-fixtures/community-game-responses.json';
import type {LegacyFixture,LegacyJson} from './panel-legacy-harness';
const r=saved.responses;
afterEach(()=>{cleanup();disposePairs();vi.useRealTimers();});
async function setup(game:CommunityGame,active=false,overrides:Record<string,LegacyFixture>={}){
  const q='/api/match/queue/status?game_type='+game;
  const routes:Record<string,LegacyFixture>={
    ['GET '+q]:r[(game+(active?'_matched':'_idle')) as 'rps_idle'],
    'GET /api/duel/list':r.duels,'GET /api/duel/leaderboard':r.rps_leaderboard,'GET /api/tictactoe/leaderboard':r.ttt_leaderboard,
    'GET /api/rps/poll?room_id=fixture-rps':r.rps_active,'GET /api/tictactoe/poll?room_id=fixture-tictactoe':r.tictactoe_active,
    'GET /api/tug/status':active?r.tug_active:r.tug_status_idle,'POST /api/tug/pull':r.tug_pull,
    'POST /api/rps/move':r.rps_move,'POST /api/tictactoe/move':r.tictactoe_move,
    'POST /api/match/queue':r[(game+'_join') as 'rps_join'],'POST /api/match/queue/cancel':r[(game+'_cancel') as 'rps_cancel'],...overrides,
  };
  const p=await pair(routes);await p.old.click(`[data-action="${game==='rps'?'duels':game}"]`);document.dispatchEvent(new Event('click'));
  const ui=render(<CommunityGamesView runtime={p.runtime} game={game}/>);await act(flush);
  const click=async(selector:string)=>{await p.old.click(selector);await act(async()=>{const b=ui.container.querySelector(selector) as HTMLElement;expect(b,'new game control '+selector).toBeTruthy();b.click();await flush();});};
  if(game==='rps')await click('#duel-find-btn');p.check();
  return {...p,ui,click,q,async hint(data:Record<string,LegacyJson>,seq=1){const env={v:1,type:'match_state',seq,ts:Date.now(),data};await p.old.realtimeMessage('broadcast',env);await act(async()=>{p.subscriptions.get('broadcast')?.('broadcast','application/json',JSON.stringify(env));await flush();});}};
}
for(const game of ['rps','tictactoe','tug'] as const)it(`${game} queue entry and cancellation preserve full shell minute traffic`,async()=>{
  const p=await setup(game);p.routes['GET '+p.q]=r[(game+'_queued') as 'rps_queued'];
  // Old tug renderer reads obsolete aliases; expose the same documented alias for this exact-wire scenario.
  if(game==='tug')p.routes['GET '+p.q]={...r.tug_queued,queued:true};
  await p.click(game==='rps'?'#rps-queue-btn':game==='tug'?'#tug-find':'#ttt-find-btn');p.check();
  p.routes['GET '+p.q]=r[(game+'_idle') as 'rps_idle'];await p.click(game==='rps'?'#rps-leave-btn':game==='tug'?'#tug-cancel':'#ttt-cancel-btn');
  await act(async()=>{await p.advance(60000);});p.check();
});
for(const game of ['rps','tictactoe'] as const)it(`${game} move uses displayed room and exact action continuation`,async()=>{
  const p=await setup(game,true);p.routes['GET /api/'+game+'/poll?room_id=fixture-'+game]=r[(game+'_after') as 'rps_after'];
  await p.click(game==='rps'?'[data-rps-move="rock"]':'[data-ttt-cell="5"]');p.check();
  await act(async()=>{await p.advance(6000);});p.check();expect(p.trace.find(q=>q.path==='/api/'+game+'/move')?.body).toEqual(game==='rps'?{room_id:'fixture-rps',move:'rock'}:{room_id:'fixture-tictactoe',cell:5});
});
for(const game of ['rps','tictactoe'] as const)it(`${game} refusal displays unknown reason without successful extra reads`,async()=>{
  const p=await setup(game,true,{['POST /api/'+game+'/move']:{success:false,message:'Новая причина сервера'}});await p.click(game==='rps'?'[data-rps-move="paper"]':'[data-ttt-cell="4"]');p.check();expect(p.ui.getByRole('status').textContent).toContain('Новая причина сервера');
});
it('tictactoe realtime re-reads canonical room only for matching room and game',async()=>{const p=await setup('tictactoe',true);await p.hint({room_id:'other',game:'tictactoe'});p.check();await p.hint({room_id:'fixture-tictactoe',game:'rps'},2);p.check();p.routes['GET /api/tictactoe/poll?room_id=fixture-tictactoe']=r.tictactoe_after;await p.hint({room_id:'fixture-tictactoe',game:'tictactoe'},3);p.check();expect(p.ui.container.querySelector('[data-ttt-cell="5"]')?.textContent).toContain('❌');});
for(const game of ['rps','tictactoe'] as const)it(`${game} finished room stops polls and another game retains its exact refresh tail`,async()=>{
  const p=await setup(game,true);p.routes['GET /api/'+game+'/poll?room_id=fixture-'+game]=r[(game+'_finished') as 'rps_finished'];await act(async()=>{await p.advance(2000);});p.check();expect(p.ui.container.textContent).toContain('Победа');
  await act(async()=>{await p.advance(6000);});p.check();p.routes['GET '+p.q]=r[(game+'_idle') as 'rps_idle'];await p.click(game==='rps'?'#rps-new-game-btn':'#ttt-new-game-btn');await act(async()=>{await p.advance(6000);});p.check();
});
it('tug batches three real clicks into one exact pull and preserves both refresh reads',async()=>{const p=await setup('tug',true);await p.click('#tug-pull');await p.click('#tug-pull');await p.click('#tug-pull');expect(p.trace.some(q=>q.path==='/api/tug/pull')).toBe(false);p.routes['GET /api/tug/status']=r.tug_after;await act(async()=>{await p.advance(1000);});p.check();expect(p.trace.find(q=>q.path==='/api/tug/pull')?.rawBody).toBe('{"taps":3}');});
it('tug recognizes actual queued status instead of copying obsolete legacy aliases',async()=>{const p=await setup('tug',false,{'GET /api/match/queue/status?game_type=tug':r.tug_queued});p.check();expect(p.old.document.querySelector('#tug-cancel')).toBeNull();expect(p.ui.container.querySelector('#tug-cancel')).toBeTruthy();expect(p.ui.container.textContent).toContain(r.tug_status_idle.rules.formula_ru);});
for(const game of ['rps','tictactoe','tug'] as const)it(`${game} explicit close preserves cancellation behavior and stops poll traffic`,async()=>{const p=await setup(game);await p.click(game==='rps'?'#rps-close-btn':game==='tug'?'#tug-close':'#ttt-close-btn');await act(async()=>{await p.advance(6000);});p.check();});
for(const game of ['rps','tictactoe','tug'] as const)it(`${game} queue rejection preserves only its actual refusal refreshes`,async()=>{const p=await setup(game,false,{'POST /api/match/queue':{success:false,message:'Очередь отключена сервером'}});await p.click(game==='rps'?'#rps-queue-btn':game==='tug'?'#tug-find':'#ttt-find-btn');p.check();expect(p.ui.getByRole('status').textContent).toContain('Очередь отключена сервером');});
for(const game of ['rps','tictactoe','tug'] as const)it(`${game} token refresh retains the open room and original polling phase`,async()=>{const p=await setup(game,true);await act(async()=>{await p.advance(1700);});const next={...authorization,token:token.replace(/fixture$/,'refreshed')};await p.old.authorizeShell(next);await act(async()=>{p.callbacks.forEach(cb=>cb(next));await flush();});await act(async()=>{await p.advance(4500);});p.check();expect(p.ui.container.textContent).toContain('bob');});
it('tictactoe winning move keeps optimistic final board leaderboard and delayed balance reads',async()=>{const end=r.tictactoe_finished.room;const p=await setup('tictactoe',true,{'POST /api/tictactoe/move':{...r.tictactoe_move,state:end.state,status:end.status,winner:end.winner,outcome:end.outcome,finished:true,message:'Победа подтверждена'}});await p.click('[data-ttt-cell="5"]');await act(async()=>{await p.advance(6500);});p.check();expect(p.ui.container.textContent).toContain('Победа подтверждена');});
it('tug cancels its unsubmitted tap batch on close instead of applying it to an unseen room',async()=>{const p=await setup('tug',true);await p.click('#tug-pull');await p.click('#tug-close');p.check();const before=p.trace.slice(),oldCount=p.old.trace.length;await act(async()=>{await p.advance(1000);});expect(p.trace).toEqual(before);expect(p.old.trace.slice(oldCount).map(q=>[q.method,q.path,q.query,q.rawBody])).toEqual([['POST','/api/tug/pull','','{"taps":1}'],['GET','/api/tug/status','',null],['GET','/api/match/queue/status','?game_type=tug',null]]);});
