"""Actual TCP/HTTP integration; uses no fixture transport and no hidden board.

Starts the explicit disposable local runner. Requires built frontend-next and
backend dependencies. Minesweeper is solved only from public numeric clues.
This is not browser/CSS/Twitch-hosted validation.
"""
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    with tempfile.TemporaryFile(mode='w+') as log:
        process=subprocess.Popen([sys.executable,str(ROOT/'scripts/run-skillgames-local.py'),
                                  '--allow-local-demo','--port',str(port)],stdout=log,stderr=log,cwd=ROOT)
        try:
            def call(path, body=None, token=None, expected=200, extra_headers=None):
                headers={'Content-Type':'application/json', **(extra_headers or {})}
                if token: headers['X-Twitch-JWT']=token
                req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
                try:
                    response=urllib.request.urlopen(req,timeout=10)
                except urllib.error.HTTPError as error:
                    response=error
                raw=response.read()
                assert response.status==expected,(path,response.status,raw[:500])
                return json.loads(raw) if 'application/json' in response.headers.get('Content-Type','') else raw.decode()
            deadline=time.monotonic()+15
            while True:
                try:
                    home=call('/')
                    break
                except urllib.error.URLError:
                    if time.monotonic()>deadline or process.poll() is not None:
                        log.seek(0); raise AssertionError(log.read())
                    time.sleep(.1)
            tokens={p:call('/local-identity?player='+p)['token'] for p in ('alice','bobby')}
            html=call('/mobile.html?player=bobby')
            assert '/local-twitch-helper.js' in html and 'assets/' in html
            call('/api/skillgames/state',expected=401)
            call('/local-identity',expected=403,extra_headers={'Origin':'https://evil.example'})
            print('PASS TCP server, built mobile entrypoint, JWT rejection, origin safety',flush=True)
            def state(player):return call('/api/skillgames/state',token=tokens[player])
            def command(player, endpoint, body, expected=200):
                return call('/api/skillgames/'+endpoint,{**body,'request_id':uuid.uuid4().hex},tokens[player],expected)
            def action(player, session, move, **values):
                return command(player,'action',dict(session_id=session['id'],version=session['version'],action=move,**values))['session']
            def no_secrets(value):
                encoded=json.dumps(value)
                for name in ('"mines"','"fleets"','"seed"','"certification"','"opponent_ships"'):
                    assert name not in encoded,name
            # Solve both puzzle tiers using ONLY public opened counts and total.
            for tier in ('beginner','advanced'):
                session=command('alice','start',dict(game_type='minesweeper',mode='ranked',difficulty=tier))['session']
                original=session['id']
                session=action('alice',session,'open',cell=0)
                assert session['status']=='active','Initial click must not win'
                assert state('alice')['active_session']['id']==original,'Reload must resume'
                known=set(); moves=0
                while session['status']=='active':
                    no_secrets(session)
                    board=session['state']; rows,cols=board['rows'],board['cols']; allcells=set(range(rows*cols))
                    opened={int(k):v for k,v in board['opened'].items()}
                    def neighbors(cell):
                        r,c=divmod(cell,cols)
                        return {rr*cols+cc for rr in range(max(0,r-1),min(rows,r+2)) for cc in range(max(0,c-1),min(cols,c+2))}-{cell}
                    constraints=[]
                    for cell,count in opened.items():
                        n=neighbors(cell); unknown=n-set(opened)-known
                        if unknown: constraints.append((unknown,count-len(n&known)))
                    constraints.append((allcells-set(opened)-known,board['mine_count']-len(known)))
                    safe=set(); marked=set()
                    for cells,count in constraints:
                        if cells and count==0:safe|=cells
                        elif cells and len(cells)==count:marked|=cells
                    if not safe and not marked:
                        for small,a in constraints:
                            for big,b in constraints:
                                if small < big:
                                    diff=big-small
                                    if b-a==0:safe|=diff
                                    elif b-a==len(diff):marked|=diff
                    known |= marked
                    if not safe:
                        assert marked,'Public solver stalled: no forced safe move or mine'
                        continue
                    session=action('alice',session,'open',cell=min(safe)); moves+=1
                    assert moves<=36
                assert session['result']['outcome']=='win',session['result']
                assert session['result']['points']==0
                assert session['result']['rating']['delta']>0
                no_secrets(session)
                print(f'PASS TCP Minesweeper {tier}: no-guess win in {moves} poststart API opens, resume, rating, no points',flush=True)
            # Separate real participants, manual fleet validation and full battle.
            command('alice','queue',{})
            command('bobby','queue',{})
            fleet_a=[[0,1,2],[12,13],[16,17],[30]]
            fleet_b=[[0,6,12],[3,9],[24,25],[29]]
            fleets={'alice':fleet_a,'bobby':fleet_b}
            for player in ('alice','bobby'):
                session=state(player)['active_session']; no_secrets(session)
                action(player,session,'place',ships=fleets[player])
                action(player,state(player)['active_session'],'ready')
            a,b=state('alice')['active_session'],state('bobby')['active_session']
            assert a['id']==b['id'] and a['state']['phase']=='active'
            attacker='alice' if a['state']['your_turn'] else 'bobby'
            defender='bobby' if attacker=='alice' else 'alice'
            targets=[c for ship in fleets[defender] for c in ship]
            water=[c for c in range(36) if all(c not in ship for ship in fleets[attacker])]
            for index,cell in enumerate(targets):
                session=state(attacker)['active_session']; no_secrets(session)
                session=action(attacker,session,'fire',cell=cell)
                if index < len(targets)-1:
                    action(defender,state(defender)['active_session'],'fire',cell=water[index])
            win,loss=state(attacker)['active_session'],state(defender)['active_session']
            assert win['result']['outcome']=='win' and loss['result']['outcome']=='loss'
            assert win['result']['rating']['delta']==-loss['result']['rating']['delta']
            for snapshot in (win,loss):no_secrets(snapshot)
            print('PASS TCP Battleship: two-player matching, manual placement, alternating hits/misses, verified win/loss, separate ratings',flush=True)
            replay=dict(session_id=win['id'],version=win['version'],action='fire',cell=35,request_id=uuid.uuid4().hex)
            call('/api/skillgames/action',replay,tokens[attacker],expected=409)
            assert state(attacker)['active_session']['result']['rating']==win['result']['rating']
            print('PASS TCP completed-session replay cannot change result/rating',flush=True)
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()

if __name__=='__main__':run()
