"""Challenge each adjacent realm gate, restoring this run's exact own bytes."""
import hashlib,json,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2];out=Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=True)
p=root/'frontend-next/src/panel/party.ts';original=p.read_bytes();(out/'party.ts.own-backup').write_bytes(original)
assert subprocess.run(['git','diff','--quiet','HEAD','--',str(p.relative_to(root))],cwd=root).returncode==0
before="['hero.army_create','hero.army_disband','hero.party_order_set'].includes(type)&&kingdomConflicted(s)"
rows=[]
for name,after,pattern in [('army-create',"['hero.army_disband','hero.party_order_set'].includes(type)&&kingdomConflicted(s)",'army create saved button'),('army-disband',"['hero.army_create','hero.party_order_set'].includes(type)&&kingdomConflicted(s)",'army affirmative cannot use observed'),('party-order',"['hero.army_create','hero.army_disband'].includes(type)&&kingdomConflicted(s)",'already-open order editor')]:
 try:
  text=original.decode();assert text.count(before)==1;p.write_text(text.replace(before,after))
  with (out/(name+'-red.log')).open('w') as f:red=subprocess.run(['npm','--prefix','frontend-next','test','--','test/panel-army-kingdom-safety.test.tsx','-t',pattern],cwd=root,stdout=f,stderr=subprocess.STDOUT)
  assert red.returncode==1,(name,red.returncode)
 finally:p.write_bytes(original);assert p.read_bytes()==original
 with (out/(name+'-restored.log')).open('w') as f:green=subprocess.run(['npm','--prefix','frontend-next','test','--','test/panel-army-kingdom-safety.test.tsx','-t',pattern],cwd=root,stdout=f,stderr=subprocess.STDOUT)
 assert green.returncode==0,(name,green.returncode)
 rows.append({'mutation':name,'mutation_exit':red.returncode,'restored_exit':green.returncode,'exact_own_restore':True,'source_sha256':hashlib.sha256(original).hexdigest()});print(name,'RED1 RESTORED0',flush=True)
(out/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')
