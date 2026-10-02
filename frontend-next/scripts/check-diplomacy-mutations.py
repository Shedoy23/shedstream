"""Controlled local semantic mutations; own byte backup, explicit red and restored green."""
import hashlib,json,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2];out=Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=True)
source=root/'frontend-next/src/panel';parity='test/panel-diplomacy-parity.test.tsx';safety='test/panel-diplomacy-safety.test.tsx';quotes='test/panel-diplomacy-quotes.test.tsx'
line="const result=await this.action(type,data,{tail:type.startsWith('hero.')?'hero':'balance'});"
changes=[]
for name,action,body,pattern in [('policy-name','hero.enact_policy',"{...data,policy_name:'WRONG'}",'policy policy_royal_guard exact'),('direct-tribute','hero.make_peace',"{...data,offered_tribute:Math.abs(Number(data.offered_tribute))}",'direct peace keeps text target twice and parseInt tribute -200'),('tax-rate','kingdom.set_tax_rate',"{...data,tax_rate_pct:Number(data.tax_rate_pct)+1}",'tax 25 exact data'),('war-target-name','kingdom.propose_war',"{...data,target_kingdom_name:'WRONG'}",'#bnr-war-propose exact proposal'),('peace-vote-target-name','kingdom.propose_peace',"{...data,target_kingdom_name:'WRONG'}",'#bnr-peace-vote-propose exact proposal')]:
 changes.append((name,parity,pattern,[('controller.ts',line,line.replace('type,data,',f"type,type==='{action}'?{body}:data,"))]))
changes.extend([
 ('read-reversal',safety,'old actual reverse completion',[('controller.ts','request > (this.applied[key] || 0)','true')]),
 ('scheduled-token-tail',safety,'scheduled local tail cannot migrate',[('controller.ts','if(owns()&&context===diplomacyOwner(this.state))void this.refreshDiplomacy();','if(true)void this.refreshDiplomacy();')]),
 ('pending-token-tail',safety,'pending local tail cannot migrate',[('controller.ts','if(!owns()||context!==diplomacyOwner(this.state))return result;','if(context!==diplomacyOwner(this.state))return result;'),('controller.ts','if(owns()&&context===diplomacyOwner(this.state))void this.refreshDiplomacy();','if(context===diplomacyOwner(this.state))void this.refreshDiplomacy();')]),
 ('preaction-read-barrier',safety,'accepted mutation prevents pre-action',[('controller.ts','if(result?.success)this.applied.diplomacy=this.issued.diplomacy=(this.issued.diplomacy||0)+1;','/* deliberately remove accepted mutation read barrier */')]),
 ('new-kingdom-identity',safety,'direct peace old saved click cannot cross kingdom',[('kingdom.ts','kingdomInfo(hero)?.id,','/* deliberately omit nested realm ID */')]),
 ('missing-price-gate',quotes,'hero.enact_policy unverified null',[('diplomacy.ts',"if(type!=='kingdom.set_tax_rate'&&diplomacyPrice(s,type)===null)return false;",'/* deliberately permit unknown quote */')]),
])
paths={source/file for *_,edits in changes for file,_,_ in edits}
assert subprocess.run(['git','diff','--quiet','HEAD','--',*[str(x.relative_to(root)) for x in paths]],cwd=root).returncode==0
rows=[]
for name,test,pattern,edits in changes:
 backups={source/file:(source/file).read_bytes() for file,_,_ in edits}
 for path,b in backups.items():(out/(name+'-'+path.name+'.own-backup')).write_bytes(b)
 try:
  for file,before,after in edits:
   p=source/file;s=p.read_text();assert s.count(before)==1,(name,file,s.count(before));p.write_text(s.replace(before,after))
  with (out/(name+'.log')).open('w') as f:red=subprocess.run(['npm','--prefix','frontend-next','test','--',test,'-t',pattern],cwd=root,stdout=f,stderr=subprocess.STDOUT)
  expected=0 if name=='new-kingdom-identity' else 1
  assert red.returncode==expected,(name,red.returncode)
 finally:
  for path,b in backups.items():path.write_bytes(b);assert path.read_bytes()==b
 with (out/(name+'-restored.log')).open('w') as f:green=subprocess.run(['npm','--prefix','frontend-next','test','--',test,'-t',pattern],cwd=root,stdout=f,stderr=subprocess.STDOUT)
 assert green.returncode==0,(name,green.returncode)
 rows.append({'mutation':name,'mutation_exit':red.returncode,'classification':'redundant guard survivor: independent state/hero realm agreement still blocks stale send' if name=='new-kingdom-identity' else 'killed','restored_exit':green.returncode,'exact_own_restore':True,'source_sha256':{p.name:hashlib.sha256(b).hexdigest() for p,b in backups.items()}});print(name,'MUTATION',red.returncode,'RESTORED 0',flush=True)
 (out/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')
