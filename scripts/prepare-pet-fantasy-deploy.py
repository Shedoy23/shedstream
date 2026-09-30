"""Second pet collection: new assets and exact patches over the first release."""
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXT=ROOT/'Расширение'
walk_fix='--walk-fix' in sys.argv
scenes='--scenes' in sys.argv or walk_fix
OUT=ROOT/('dist/pet-scenes-20260926/walk-bundle' if walk_fix else 'dist/pet-scenes-20260926/bundle' if scenes else 'dist/pets-fantasy-20260926/bundle')
OUT.mkdir(parents=True,exist_ok=True)
payload=OUT/'payload'
variants=[x[0] for x in json.loads((ROOT/'scripts/pet-fantasy-spec.json').read_text(encoding='utf-8'))['items']]
paths=['backend/migrations/m130_pet_fantasy.py','backend/tests/test_pet_fantasy_purchase.py']
for variant in variants:
    paths += [p.relative_to(EXT).as_posix() for p in (EXT/'frontend/pet-assets/v2'/variant).glob('*.png')]
paths += [p.relative_to(EXT).as_posix() for p in (EXT/'frontend/pet-assets/fantasy-v1').iterdir() if p.is_file()]
preview_patches=[]
if scenes:
    paths.remove('frontend/pet-assets/fantasy-v1/preview.html')
    scene_spec=json.loads((ROOT/'scripts/pet-scenes-spec.json').read_text(encoding='utf-8'))
    paths += [f"frontend/pet-assets/v2/{item['id']}/scene-v1.png" for item in scene_spec]
    paths += ['frontend/pet-assets/scenes-v1/manifest.json']
    if walk_fix:
        walk_spec=json.loads((ROOT/'scripts/pet-walk-fix-spec.json').read_text(encoding='utf-8'))
        paths += [f"frontend/pet-assets/v2/{item['id']}/{file}.png" for item in walk_spec for file in ('animation-v2','walk-opposite-v2')]
    paths=list(dict.fromkeys(paths))
    preview_patches=['frontend/pet-assets/'+collection+'/preview.html' for collection in ('companions-v1','fantasy-v1')]
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
patches['frontend/overlay.html']=[['overlay-pets.js?v=20260926a','overlay-pets.js?v=20260926c' if scenes else 'overlay-pets.js?v=20260926b']]
for rel in preview_patches:
    if walk_fix:
        previous=json.loads((ROOT/'dist/pet-scenes-20260926/bundle/manifest.json').read_text(encoding='utf-8'))
        old=previous['patches'][rel][0][1]
    else:
        old=subprocess.check_output(['git','show','284c7da:Расширение/'+rel],cwd=ROOT).decode('utf-8')
    patches[rel]=[[old,(EXT/rel).read_text(encoding='utf-8')]]
candidate=ROOT/'dist/releases/shedlink-0.0.5-review-candidate-20260923-6f8e07f5.zip'
with zipfile.ZipFile(candidate) as z:frozen=['frontend/'+p for p in z.namelist()]
manifest={'patches':patches,'files':paths,'frozen':frozen,'variants':variants,'migration':'m130_pet_fantasy','preview_patches':preview_patches,
 'stage_support':['backend/database.py','backend/routes/pets.py','backend/migrations/m129_pet_companions.py'],
 'extra_tests':['backend/tests/test_pet_fantasy_purchase.py'],
 'candidate_sha256':hashlib.sha256(candidate.read_bytes()).hexdigest(),
 'hashes':{p:hashlib.sha256((payload/p).read_bytes()).hexdigest() for p in paths}}
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
shutil.copyfile(ROOT/'scripts/install-pet-companions.py',OUT/'install.py')
shutil.copyfile(ROOT/'scripts/check-pet-deploy-stream.py',OUT/'check-stream.py')
with tarfile.open(OUT.parent/('walk-bundle.tar.gz' if walk_fix else 'bundle.tar.gz'),'w:gz') as t:
    for p in sorted(OUT.rglob('*')):
        if p.is_file():t.add(p,arcname=p.relative_to(OUT).as_posix())
print('Bundle:',len(paths),'new files;',len(patches),'guarded patches; frozen frontend excluded')
