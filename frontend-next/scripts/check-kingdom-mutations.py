"""Local semantic mutations, each restored from this run's exact own bytes."""
import hashlib,json,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]; out=Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=True)
p=root/'frontend-next/src/panel/KingdomView.tsx';original=p.read_bytes();(out/'KingdomView.tsx.own-backup').write_bytes(original)
changes=[('create-name','create button/Enter',"perform(type,{kingdom_name});","perform(type,creating?{clan_name:kingdom_name}:{kingdom_name});"),('join-name','join button/Enter',"perform(type,{kingdom_name});","perform(type,creating?{kingdom_name}:{clan_name:kingdom_name});"),('leave-empty-body','leave ruler true',"if(c&&ok)perform(c.type);","if(c&&ok)perform(c.type,c.type==='hero.leave_kingdom'?{price:0}:{});"),('hire-empty-body','NPC hire quote confirmation true',"if(c&&ok)perform(c.type);","if(c&&ok)perform(c.type,c.type==='hero.recruit_vassal_clan'?{price:0}:{});")]
rows=[]
for name,pattern,before,after in changes:
    try:
        s=original.decode();assert s.count(before)==1;p.write_text(s.replace(before,after))
        with (out/(name+'.log')).open('w') as f:run=subprocess.run(['npm','--prefix','frontend-next','test','--','test/panel-kingdom-parity.test.tsx','-t',pattern],cwd=root,stdout=f,stderr=subprocess.STDOUT)
        assert run.returncode==1,(name,run.returncode)
    finally:p.write_bytes(original);assert p.read_bytes()==original
    with (out/(name+'-restored.log')).open('w') as f:green=subprocess.run(['npm','--prefix','frontend-next','test','--','test/panel-kingdom-parity.test.tsx','-t',pattern],cwd=root,stdout=f,stderr=subprocess.STDOUT)
    assert green.returncode==0
    rows.append({'mutation':name,'red_exit':run.returncode,'restored_exit':green.returncode,'exact_own_restore':True,'sha256':hashlib.sha256(original).hexdigest()});print(name,'RED 1 RESTORED 0',flush=True)
(out/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')
