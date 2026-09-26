"""Server-side stage/apply. Exact source guards preserve unrelated deployments."""
import asyncio,hashlib,importlib,json,os,py_compile,shutil,sqlite3,subprocess,sys,time,urllib.request
from pathlib import Path

BUNDLE=Path(__file__).resolve().parent
ROOT=Path('/root/twitch-extension')
BACKUP=BUNDLE/'backup'
STAGE=BUNDLE/'stage'
manifest=json.loads((BUNDLE/'manifest.json').read_text())
variants=manifest.get('variants',['wayfarer','crimson_knight','colony_engineer','lantern_mage','shadow_rogue','rain_fisher'])

def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def atomic_copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_name(target.name+'.companions-new')
    shutil.copyfile(source,temp);os.replace(temp,target)
def frozen_hashes():return {r:digest(ROOT/r) for r in manifest['frozen'] if (ROOT/r).is_file()}
def check_bundle():
    assert not (set(manifest['files'])|set(manifest['patches'])) & set(manifest['frozen'])
    for rel,h in manifest['hashes'].items():assert digest(BUNDLE/'payload'/rel)==h,rel

def check_new_target(rel):
    # Preview assets may be published in advance while the stream is live.
    target=ROOT/rel
    if target.exists():
        assert rel.startswith('frontend/pet-assets/'),('new backend target appeared',rel)
        assert digest(target)==manifest['hashes'][rel],('new static target differs',rel)

def publish_preview():
    check_bundle();state=json.loads((BUNDLE/'prepared.json').read_text())
    assert frozen_hashes()==state['frozen']
    assets=[r for r in manifest['files'] if r.startswith('frontend/pet-assets/')]
    for rel in assets:
        check_new_target(rel)
        assert digest(STAGE/rel)==manifest['hashes'][rel],rel
    for rel in assets:atomic_copy(STAGE/rel,ROOT/rel)
    assert frozen_hashes()==state['frozen']
    print('Published',len(assets),'new static preview assets; no backend/catalog/restart changes')
async def stage_migration(db):
    import aiosqlite
    sys.path.insert(0,str(STAGE/'backend'))
    migration=importlib.import_module('migrations.'+manifest.get('migration','m129_pet_companions'))
    async with aiosqlite.connect(db) as conn:await migration.apply(conn)

def prepare():
    check_bundle()
    assert not (BUNDLE/'prepared.json').exists(),'Already prepared; use a new release directory'
    BACKUP.mkdir();STAGE.mkdir()
    before={}
    for rel,replacements in manifest['patches'].items():
        original=ROOT/rel;before[rel]=digest(original)
        saved=BACKUP/rel;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,saved)
        text=original.read_text()
        for old,new in replacements:
            assert text.count(old)==1,('patch context drift',rel,old[:90])
            text=text.replace(old,new,1)
        target=STAGE/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
    for rel in manifest['files']:
        assert not (ROOT/rel).exists(),('target already exists',rel)
        target=STAGE/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(BUNDLE/'payload'/rel,target)
    shutil.copyfile(ROOT/'backend/config.py',STAGE/'backend/config.py')
    for rel in manifest.get('stage_support',[]):
        target=STAGE/rel;target.parent.mkdir(parents=True,exist_ok=True)
        assert not target.exists(),('stage support overlaps release',rel)
        shutil.copyfile(ROOT/rel,target)
    for p in (STAGE/'backend').rglob('*.py'):py_compile.compile(str(p),doraise=True)
    subprocess.run([sys.executable,str(STAGE/'backend/tests/test_pet_collection_purchase.py')],check=True)
    for rel in manifest.get('extra_tests',[]):
        subprocess.run([sys.executable,str(STAGE/rel)],check=True)
    with sqlite3.connect('file:'+str(ROOT/'backend/viewers.db')+'?mode=ro',uri=True) as src, sqlite3.connect(BACKUP/'viewers.db') as dst:src.backup(dst)
    shutil.copyfile(BACKUP/'viewers.db',STAGE/'viewers.db')
    with sqlite3.connect(STAGE/'viewers.db') as c:
        schema=c.execute('PRAGMA table_info(pet_catalog)').fetchall();assert {'item_id','png_path','rarity'} <= {r[1] for r in schema}
        original_catalog=c.execute('SELECT * FROM pet_catalog ORDER BY item_id').fetchall()
        owned=c.execute('SELECT count(*) FROM pet_inventory').fetchone()[0]
    asyncio.run(stage_migration(STAGE/'viewers.db'))
    with sqlite3.connect(STAGE/'viewers.db') as c:
        assert c.execute('SELECT count(*) FROM pet_catalog').fetchone()[0]==len(original_catalog)+len(variants)
        for row in original_catalog:assert c.execute('SELECT * FROM pet_catalog WHERE item_id=?',(row[0],)).fetchone()==row
        assert c.execute('SELECT count(*) FROM pet_inventory').fetchone()[0]==owned
    state={'before':before,'frozen':frozen_hashes(),'staged':{r:digest(STAGE/r) for r in manifest['patches']}}
    (BUNDLE/'prepared.json').write_text(json.dumps(state,indent=2))
    print('PREPARED: real-schema migration + purchase tests passed; production unchanged')

def apply():
    check_bundle();state=json.loads((BUNDLE/'prepared.json').read_text())
    assert frozen_hashes()==state['frozen'],'frozen frontend changed since prepare'
    for rel,h in state['before'].items():assert digest(ROOT/rel)==h,('production changed since prepare',rel)
    subprocess.run([sys.executable,str(BUNDLE/'check-stream.py')],check=True)
    # Publish complete image directories first. No catalog item exists yet.
    for rel in manifest['files']:check_new_target(rel)
    try:
        for rel in manifest['files']:atomic_copy(STAGE/rel,ROOT/rel)
        for rel in manifest['patches']:atomic_copy(STAGE/rel,ROOT/rel)
        subprocess.run(['supervisorctl','restart','twitchbot'],check=True,timeout=60)
        for attempt in range(15):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3) as r: health=json.load(r)
                if health.get('status')=='ok':break
            except Exception:pass
            time.sleep(2)
        else:raise RuntimeError('health failed')
        with urllib.request.urlopen('http://127.0.0.1:8000/api/pet/catalog',timeout=10) as r:catalog=json.load(r)
        for variant in variants:
            item=next(x for x in catalog['items'] if x['item_id']=='skin_'+variant)
            assert item['rarity']=='rare' and item['price_crustics']==500000,item
        assert frozen_hashes()==state['frozen'],'frozen files changed'
        for rel,h in state['staged'].items():assert digest(ROOT/rel)==h,rel
        for rel,h in manifest['hashes'].items():assert digest(ROOT/rel)==h,rel
        result={'health':health,'catalog':[{k:x[k] for k in ('item_id','rarity','price_crustics')} for x in catalog['items']], 'frozen_unchanged':True,'backup':str(BACKUP)}
        (BUNDLE/'deployed.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps(result,ensure_ascii=False))
    except Exception:
        for rel in manifest['patches']:atomic_copy(BACKUP/rel,ROOT/rel)
        # Never restore the whole live DB: preserve viewer purchases and unrelated writes.
        with sqlite3.connect(ROOT/'backend/viewers.db') as c:
            for variant in variants:
                c.execute('UPDATE pet_catalog SET deprecated=1 WHERE item_id=?',('skin_'+variant,))
        subprocess.run(['supervisorctl','restart','twitchbot'],check=True,timeout=60)
        raise

if __name__=='__main__':
    {'prepare':prepare,'publish-preview':publish_preview,'apply':apply}[sys.argv[1]]()
