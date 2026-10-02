import { it, expect, vi } from 'vitest';
import { act, fireEvent, screen, waitFor } from '@testing-library/preact';
import { empty, session } from './skillgame-fixtures';
import type { TwitchAuthorization } from '../src/auth';
import { authOne, deferred } from './fixtures';
it('preserves an unsaved fleet across same-viewer token re-resolution',async()=>{
  document.body.innerHTML='<div id="skillgame-root"></div>';
  let authorized!: (value: TwitchAuthorization) => void;
  const telemetryTicks: (() => void)[] = [];
  const nativeInterval = globalThis.setInterval;
  vi.spyOn(globalThis, 'setInterval').mockImplementation(((callback: () => void, delay?: number) => {
    if (delay === 15000) { telemetryTicks.push(callback); return 0; }
    return nativeInterval(callback, delay);
  }) as typeof setInterval);
  const startedAt = Date.now();
  window.Twitch={ext:{onAuthorized:(fn:(value: TwitchAuthorization) => void)=>{authorized=fn;},actions:{requestIdShare:vi.fn()}}};
  const pending=deferred<Response>(); let resolvers=0;
  const battle={...session,game_type:'battleship',status:'active',difficulty:null,state:{rows:6,cols:6,fleet_sizes:[3,2,2,1],phase:'placement',own_ships:[],ready:false,opponent_ready:false,opponent:'bobby',shots:[],incoming:[],sunk_count:0,your_turn:false,turn_started_at:null,winner:null}};
  vi.stubGlobal('fetch',vi.fn((url:string)=>{
    if(url.endsWith('/api/user/resolve-twitch-token')) return ++resolvers===2 ? pending.promise : Promise.resolve(new Response(JSON.stringify({login:'alice'})));
    return Promise.resolve(new Response(JSON.stringify({...empty,active_session:battle})));
  }));
  await act(async()=>{await import('../src/skillgames/main');});
  await act(async()=>{authorized(authOne);});
  await waitFor(()=>expect(screen.getByRole('button',{name:/^A1 —/})).toBeTruthy());
  fireEvent.click(screen.getByRole('button',{name:/^A1 —/}));
  expect(screen.getByRole('button',{name:'A1 — корабль'})).toBeTruthy();
  await act(async()=>{authorized({...authOne,token:'rotated'});});
  expect(screen.queryByRole('button',{name:'A1 — корабль'})).toBeNull();
  vi.spyOn(Date, 'now').mockReturnValue(startedAt + 16000);
  await act(async()=>{telemetryTicks.at(-1)?.();});
  expect(vi.mocked(fetch).mock.calls.filter(([url])=>String(url).endsWith('/api/viewer/ui-usage'))).toHaveLength(0);
  await act(async()=>{pending.resolve(new Response(JSON.stringify({login:'alice'})));});
  await waitFor(()=>expect(screen.getByRole('button',{name:/^A1 —/})).toBeTruthy());
  expect(screen.getByRole('button',{name:'A1 — корабль'})).toBeTruthy();
  await act(async()=>{telemetryTicks.at(-1)?.();});
  const usageCalls = vi.mocked(fetch).mock.calls.filter(([url])=>String(url).endsWith('/api/viewer/ui-usage'));
  expect(usageCalls).toHaveLength(1);
  expect((usageCalls[0]![1]?.headers as Record<string,string>)['X-Twitch-JWT']).toBe('rotated');
  await act(async()=>{authorized({...authOne,token:'other-viewer-token',userId:'another-viewer'});});
  await waitFor(()=>expect(screen.getByRole('button',{name:'A1 — неизвестно'})).toBeTruthy());
  expect(screen.queryByRole('button',{name:'A1 — корабль'})).toBeNull();
});
