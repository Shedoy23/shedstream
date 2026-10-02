import { it, expect, vi } from 'vitest';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { empty, session } from './skillgame-fixtures';
import { authOne, deferred } from './fixtures';
it('preserves an unsaved fleet across same-viewer token re-resolution',async()=>{
  document.body.innerHTML='<div id="skillgame-root"></div>';
  let authorized:any;
  window.Twitch={ext:{onAuthorized:(fn:any)=>{authorized=fn;},actions:{requestIdShare:vi.fn()}}};
  const pending=deferred<Response>(); let resolvers=0;
  const battle={...session,game_type:'battleship',status:'active',difficulty:null,state:{rows:6,cols:6,fleet_sizes:[3,2,2,1],phase:'placement',own_ships:[],ready:false,opponent_ready:false,opponent:'bobby',shots:[],incoming:[],sunk_count:0,your_turn:false,turn_started_at:null,winner:null}};
  vi.stubGlobal('fetch',vi.fn((url:string)=>{
    if(url.endsWith('/api/user/resolve-twitch-token')) return ++resolvers===1 ? Promise.resolve(new Response(JSON.stringify({login:'alice'}))) : pending.promise;
    return Promise.resolve(new Response(JSON.stringify({...empty,active_session:battle})));
  }));
  await act(async()=>{await import('../src/skillgames/main');});
  await act(async()=>{authorized(authOne);});
  await waitFor(()=>expect(screen.getByRole('button',{name:/^A1 —/})).toBeTruthy());
  fireEvent.click(screen.getByRole('button',{name:/^A1 —/}));
  expect(screen.getByRole('button',{name:'A1 — корабль'})).toBeTruthy();
  await act(async()=>{authorized({...authOne,token:'rotated'});});
  await act(async()=>{pending.resolve(new Response(JSON.stringify({login:'alice'})));});
  await waitFor(()=>expect(screen.getByRole('button',{name:/^A1 —/})).toBeTruthy());
  expect(screen.getByRole('button',{name:'A1 — корабль'})).toBeTruthy();
});
