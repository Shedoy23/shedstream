import sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from modules.bannerlord import _adapter as m
ch=991871
try:
    m._battle_stats[ch]={"final":True,"updated_at":time.time(),"participants":[{"username":"Alice","payout_version":2,"payout_status":"paid","gold_earned":154800}]}
    r=m.get_my_battle_stats(ch,"ALICE")
    assert not r["in_battle"] and r["my_stats"] is None
    assert r.get("last_payout",{}).get("gold_earned")==154800,"final payment hidden from owner"
    assert m.get_my_battle_stats(ch,"Bob").get("last_payout") is None
    assert m.get_my_battle_stats(ch+1,"Alice").get("last_payout") is None
    m._battle_stats[ch]["updated_at"]=time.time()-121
    assert m.get_my_battle_stats(ch,"Alice").get("last_payout") is None
    m._battle_stats[ch]["updated_at"]=time.time()
    m._battle_stats[ch]["final"]=False
    assert m.get_my_battle_stats(ch,"Alice").get("last_payout") is None
    print("PASS final payout: owner/channel isolation, TTL, active battle compatibility")
finally:m._battle_stats.pop(ch,None)
