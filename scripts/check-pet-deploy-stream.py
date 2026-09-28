import json,sqlite3,urllib.request,urllib.parse,sys
from dotenv import dotenv_values
cfg=dotenv_values('/root/twitch-extension/backend/.env')
c=sqlite3.connect('file:/root/twitch-extension/backend/viewers.db?mode=ro',uri=True)
channels=c.execute('SELECT channel_id,login FROM channels').fetchall()
try:
    data=urllib.parse.urlencode({'client_id':cfg['TWITCH_CLIENT_ID'],'client_secret':cfg['TWITCH_CLIENT_SECRET'],'grant_type':'client_credentials'}).encode()
    with urllib.request.urlopen(urllib.request.Request('https://id.twitch.tv/oauth2/token',data=data),timeout=15) as r: token=json.load(r)['access_token']
    query=urllib.parse.urlencode([('user_id',str(cid)) for cid,_ in channels])
    req=urllib.request.Request('https://api.twitch.tv/helix/streams?'+query,headers={'Client-ID':cfg['TWITCH_CLIENT_ID'],'Authorization':'Bearer '+token})
    with urllib.request.urlopen(req,timeout=15) as r: streams=json.load(r)['data']
    print(json.dumps({'checked_channels':channels,'live':[{'user_id':s['user_id'],'user_login':s['user_login']} for s in streams]},ensure_ascii=False))
    sys.exit(2 if streams else 0)
except Exception as e:
    print('Stream status unavailable:',type(e).__name__)
    sys.exit(3)
