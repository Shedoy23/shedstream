"""Second pet collection: new assets and exact patches over the first release."""
import hashlib
import json
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXT=ROOT/'Расширение'
OUT=ROOT/'dist/pets-fantasy-20260926/bundle'
OUT.mkdir(parents=True,exist_ok=True)
payload=OUT/'payload'
variants=[x[0] for x in json.loads((ROOT/'scripts/pet-fantasy-spec.json').read_text(encoding='utf-8'))['items']]
paths=['backend/migrations/m130_pet_fantasy.py','backend/tests/test_pet_fantasy_purchase.py']
for variant in variants:
    paths += [p.relative_to(EXT).as_posix() for p in (EXT/'frontend/pet-assets/v2'/variant).glob('*.png')]
paths += [p.relative_to(EXT).as_posix() for p in (EXT/'frontend/pet-assets/fantasy-v1').iterdir() if p.is_file()]
for rel in paths:
    dest=payload/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(EXT/rel,dest)

patches={}
for rel in ['backend/pet_collection.py','backend/tests/test_pet_collection_purchase.py','frontend/pet-assets/companions-v1/overlay-pets.js']:
    old=subprocess.check_output(['git','show','73634eb:Расширение/'+rel],cwd=ROOT).decode('utf-8')
    new=(EXT/rel).read_text(encoding='utf-8')
    assert old!=new
    patches[rel]=[[old,new]]
anchor='        await m129_pet_companions.apply(conn)'
patches['backend/main.py']=[[anchor,anchor+'\n\n        from migrations import m130_pet_fantasy\n        await m130_pet_fantasy.apply(conn)']]
patches['frontend/overlay.html']=[['overlay-pets.js?v=20260926a','overlay-pets.js?v=20260926b']]
candidate=ROOT/'dist/releases/shedlink-0.0.5-review-candidate-20260923-6f8e07f5.zip'
with zipfile.ZipFile(candidate) as z:frozen=['frontend/'+p for p in z.namelist()]
manifest={'patches':patches,'files':paths,'frozen':frozen,'variants':variants,'migration':'m130_pet_fantasy',
 'stage_support':['backend/database.py','backend/routes/pets.py','backend/migrations/m129_pet_companions.py'],
 'extra_tests':['backend/tests/test_pet_fantasy_purchase.py'],
 'candidate_sha256':hashlib.sha256(candidate.read_bytes()).hexdigest(),
 'hashes':{p:hashlib.sha256((payload/p).read_bytes()).hexdigest() for p in paths}}
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
shutil.copyfile(ROOT/'scripts/install-pet-companions.py',OUT/'install.py')
shutil.copyfile(ROOT/'scripts/check-pet-deploy-stream.py',OUT/'check-stream.py')
with tarfile.open(OUT.parent/'bundle.tar.gz','w:gz') as t:
    for p in sorted(OUT.rglob('*')):
        if p.is_file():t.add(p,arcname=p.relative_to(OUT).as_posix())
print('Bundle:',len(paths),'new files;',len(patches),'guarded patches; frozen frontend excluded')
