"""Controlled semantic red tests. Run only on committed, clean panel sources.
Every mutation is restored from this process's own byte backup, never checkout.
Usage: python frontend-next/scripts/check-combat-mutations.py OUTPUT_DIRECTORY
"""
import hashlib, json, subprocess, sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
out=Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=True)
source=root/'frontend-next/src/panel'
parity='test/panel-combat-parity.test.tsx';safety='test/panel-combat-safety.test.tsx'
# name, test, exact semantic replacement(s). These deliberately change behavior,
# never assertions or fixtures. A selector mismatch is drift, not a passed probe.
mutations=[
 ('restored-startup-order',parity,'restored inventory initial selected-host',[('controller.ts','this.initialEquipment = false; this.primeEquipment();','this.initialEquipment = false;')]),
 ('restored-read-consumption',parity,'restored inventory initial selected-host',[('controller.ts','return preload.promise as Promise<T>;','return this.transport.read<T>(path, signal);')]),
 ('restored-initial-readiness',safety,'restored inventory preloads first',[('PanelApp.tsx',"state.canAct && (!combat || state.hero !== null)","state.canAct")]),
 ('order-price',parity,'old rendered hero.detach_hold', [('CombatView.tsx','const price=s.config?.action_prices?.[type],data={price}', 'const price=s.config?.action_prices?.[type],data={price:999999}')]),
 ('stance-key',parity,'old rendered stance aggressive',[('CombatView.tsx',"onClick={()=>act('hero.set_combat_stance',{stance:key})}","onClick={()=>act('hero.set_combat_stance',{stance:'defensive'})}")]),
 ('summon-side',parity,'old rendered enemy summon',[('CombatView.tsx','data={price,side},cd=',"data={price,side:'player'},cd=")]),
 ('summon-price',parity,'old rendered enemy summon',[('CombatView.tsx','data={price,side},cd=',"data={price:0,side},cd=")]),
 ('legacy-price',parity,'legacy ability rage',[('CombatView.tsx','data={price:p.price,power_key:p.power_key}', 'data={power_key:p.power_key}')]),
 ('legacy-power-key',parity,'legacy ability rage',[('CombatView.tsx','data={price:p.price,power_key:p.power_key}', "data={price:p.price,power_key:'wrong_key'}")]),
 ('new-price-field',parity,'actual selected one_handed ability',[('CombatView.tsx','const data={power_key:power.power_key},cd=', 'const data={power_key:power.power_key,price:power.price},cd=')]),
 ('thrown-weapon-key',parity,'actual weapon choice thrown',[('CombatView.tsx','const data={weapon_type:p.weapon_type};', "const data={weapon_type:p.weapon_type==='thrown'?'throwing':p.weapon_type};")]),
 ('choice-power-not-weapon',parity,'actual weapon choice crossbow',[('CombatView.tsx','const data={weapon_type:p.weapon_type};', 'const data={weapon_type:p.power_key};')]),
 ('shared-weapon-cooldown',safety,'shared weapon cooldown disables',[('combat.ts','return remaining(weapon ? Math.max(state.cooldowns.weapon_power || 0, state.buildCooldownUntil) : state.cooldowns[power.power_key], now);','return 0;')]),
 ('participant-alive',safety,'new build participant gate',[('combat.ts','!!(state.battle?.in_battle && state.battle.my_stats?.alive)','true')]),
 ('malformed-price',safety,'malformed price -1',[('contracts.ts',"typeof value === 'number' && Number.isFinite(value) && value >= 0", "typeof value === 'number' && Number.isFinite(value)")]),
 ('shared-build-busy',safety,'weapon selection blocks development',[('combat.ts','!state.buildPending && !state.buildBusy &&','!state.buildPending &&'),('controller.ts','this.state.buildPending || this.state.buildBusy ||','this.state.buildPending ||')]),
 ('battle-transition-buffs',parity,'actual host has combat startup',[('controller.ts','if (battle.in_battle && !this.state.battle?.in_battle) void this.refreshBuffs();','if (false) void this.refreshBuffs();')]),
 ('client-action-id',parity,'old rendered hero.detach_hold',[('transport.ts','data: { ...data, client_action_id: this.newId() }','data: { ...data }')]),
 ('delayed-build-tail',parity,'old rendered hero.detach_hold',[('controller.ts','void this.refreshHero(); void this.refreshBuild(); void this.equipmentRefresh?.(); }, 3500);','void this.refreshHero(); void this.equipmentRefresh?.(); }, 3500);')]),
 ('cooldown-revision',safety,'pre-action buffs reply',[('controller.ts','cooldowns: revision === this.cooldownRevision ?', 'cooldowns: true ?')]),
 ('build-pending-revision',safety,'pre-action build response',[('controller.ts','() => revision === this.buildRevision);','() => true);')]),
 ('balance-interval',safety,'60-second balance phase',[('PanelApp.tsx','void controller.refreshBalance(); }, 60000);','void controller.refreshBalance(); }, 120000);')]),
 ('late-stance-ownership',safety,'older refunded stance',[('controller.ts',"r.action_id === this.pendingStance?.actionId && r.type === 'hero.set_combat_stance'", "r.type === 'hero.set_combat_stance'")]),
 ('battle-response-ownership',safety,'old viewer balance, battle, build',[('controller.ts','this.active && generation === this.generation && request >', 'this.active && request >'),('controller.ts','this.aborts.forEach(abort => abort.abort());','/* deliberately removed abort ownership fence */')]),
 ('combat-telemetry-feature',parity,'actual collector counts combat family player.spawn',[('controller.ts',"this.usage?.trackAction('bannerlord:' + type)", "this.usage?.trackAction('bannerlord:wrong.' + type)")]),
 ('combat-ui-order',parity,'server UI permutation',[('combat.ts',"order:order.filter(id=>id!=='tournament')", "order:combatSections.filter(id=>id!=='tournament')")]),
 ('new-balance-gate',safety,'new weapon balance boundary 299',[('combat.ts','state.points !== null && state.points >= power.price &&','true &&')]),
]
paths={source/file for *_,edits in mutations for file,_,_ in edits}
if subprocess.run(['git','diff','--quiet','HEAD','--',*[str(p.relative_to(root)) for p in paths]],cwd=root).returncode:
    raise SystemExit('Commit source changes before running controlled mutations')
results=[]
for name,test,pattern,edits in mutations:
    backups={source/file:(source/file).read_bytes() for file,_,_ in edits}
    try:
        for file,before,after in edits:
            path=source/file;text=path.read_text()
            if text.count(before)!=1:raise RuntimeError(f'{name}: exact mutation selector drift ({text.count(before)})')
            path.write_text(text.replace(before,after))
        log=out/(name+'.log')
        command=['npm','--prefix','frontend-next','test','--',test,'-t',pattern]
        with log.open('w') as stream:result=subprocess.run(command,cwd=root,stdout=stream,stderr=subprocess.STDOUT,timeout=120)
        if result.returncode != 1:raise RuntimeError(f'{name}: expected semantic red exit 1, received {result.returncode}; see {log}')
        results.append({'mutation':name,'command':command,'exit':result.returncode,'log':log.name})
        print(name,'RED_EXIT=1',flush=True)
    finally:
        for path,backup in backups.items():
            path.write_bytes(backup)
            if hashlib.sha256(path.read_bytes()).digest()!=hashlib.sha256(backup).digest():raise RuntimeError('Restore failed: '+str(path))
if subprocess.run(['git','diff','--quiet','HEAD','--',*[str(p.relative_to(root)) for p in paths]],cwd=root).returncode:
    raise SystemExit('Mutation restore left a source diff')
(out/'summary.json').write_text(json.dumps({'mutations':results,'exact_restore':True},ensure_ascii=False,indent=2)+'\n')
print('ALL_MUTATIONS_RESTORED',len(results))
