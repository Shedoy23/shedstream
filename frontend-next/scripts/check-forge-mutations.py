"""Challenge forge wire and safety gates; every mutation restores own exact bytes."""
import hashlib, json, subprocess, sys
from pathlib import Path
root = Path(__file__).resolve().parents[2]
out = Path(sys.argv[1]).resolve(); out.mkdir(parents=True, exist_ok=True)
changes = [
    ('slot', 'controller.ts', "this.action('hero.reforge_quality', { slot },", "this.action('hero.reforge_quality', { slot: 'body' },", 'parity', 'forge head real control'),
    ('action-type', 'controller.ts', "this.action('hero.reforge_quality', { slot },", "this.action('hero.smith_item', { slot },", 'parity', 'forge head real control'),
    ('client-action-id', 'transport.ts', 'data: { ...data, client_action_id: this.newId() }', "data: { ...data, ...(type === 'hero.reforge_quality' ? {} : { client_action_id: this.newId() }) }", 'parity', 'forge head real control'),
    ('local-hero-tail', 'controller.ts', 'if (owns()) void this.refreshHero();', 'if (false) void this.refreshHero();', 'parity', 'forge head real control'),
    ('item-quote-context', 'forge.ts', 'context === forgeContext(state, slot)', 'true', 'safety', 'stale pre-render item control|quote replacement invalidates'),
    ('numeric-quote', 'forge.ts', 'validPrice(state.config?.reforge_price)', 'true', 'safety', 'malformed/missing quote'),
    ('alive-hero', 'forge.ts', '!!state.hero.hero?.is_alive', 'true', 'safety', 'dead hero removes controls'),
    ('hero-read-quarantine', 'forge.ts', '!state.errors.hero', 'true', 'safety', 'failed hero read quarantines'),
    ('active-inventory', 'controller.ts', '!this.forgeActive || ', '', 'safety', 'same-task navigation fences'),
    ('local-tail-owner', 'controller.ts', 'const owns = this.captureRequestOwner();', 'const owns = () => true;', 'safety', 'successful local and generic delayed tails are fenced after token|pending POST completion after token'),
    ('forge-usage', 'ForgeView.tsx', "'bannerlord:details.inv-forge'", "'bannerlord:details.forge'", 'parity', 'initially closed'),
    ('observed-slot-gate', 'forge.ts', '!forgeDisagreement(state, slot)', 'true', 'observation', 'newer equipped item disagreement'),
    ('observed-item-id', 'forge.ts', 'heroItem.item_id !== shopItem.item', 'false', 'observation', 'newer equipped item disagreement'),
    ('observed-quality', 'forge.ts', 'observedQuality(heroItem.quality) !== shopItem.quality', 'false', 'observation', 'newer equipped quality disagreement'),
    ('observation-admission', 'EquipmentView.tsx', 'controller.observeForgeEquipment(result, identity, hero);', '', 'observation', 'newer equipped item disagreement'),
    ('observation-retention', 'controller.ts', 'heroContext(hero) === heroContext(this.state.hero) ? this.state.forgeEquipment : null', 'null', 'observation', 'newer equipped item disagreement'),
]
rows = []
for name, file, before, after, suite, pattern in changes:
    path = root / 'frontend-next/src/panel' / file
    assert subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', str(path.relative_to(root))], cwd=root).returncode == 0
    original = path.read_bytes(); (out / (name + '.own-backup')).write_bytes(original)
    command = ['npm', '--prefix', 'frontend-next', 'test', '--', 'test/panel-forge-' + suite + '.test.tsx', '-t', pattern, '--maxWorkers=2']
    try:
        source = original.decode(); assert source.count(before) == 1, (name, source.count(before))
        path.write_text(source.replace(before, after))
        with (out / (name + '-red.log')).open('w') as log:
            red = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
        assert red.returncode == 1, (name, red.returncode)
    finally:
        path.write_bytes(original); assert path.read_bytes() == original
    with (out / (name + '-restored.log')).open('w') as log:
        green = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
    assert green.returncode == 0, (name, green.returncode)
    rows.append({'mutation': name, 'mutation_exit': red.returncode, 'restored_exit': green.returncode, 'exact_own_restore': True, 'source_sha256': hashlib.sha256(original).hexdigest()})
    print(name, 'RED1 RESTORED0', flush=True)
(out / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
