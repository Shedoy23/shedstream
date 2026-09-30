"""Build an allowlisted, surgical deployment bundle; never package frozen UI."""
import difflib
import hashlib
import json
import shutil
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / 'Расширение'
OUT = ROOT / 'dist/pets-collection-20260926/bundle'
OUT.mkdir(parents=True, exist_ok=True)
payload = OUT / 'payload'
paths = ['backend/pet_collection.py', 'backend/migrations/m129_pet_companions.py',
         'backend/tests/test_pet_collection_purchase.py']
variants = ['wayfarer','crimson_knight','colony_engineer','lantern_mage','shadow_rogue','rain_fisher']
for variant in variants:
    paths += [str(p.relative_to(EXT)).replace('\\','/') for p in (EXT/'frontend/pet-assets/v2'/variant).glob('*.png')]
paths += [str(p.relative_to(EXT)).replace('\\','/') for p in (EXT/'frontend/pet-assets/companions-v1').iterdir() if p.is_file()]
for rel in paths:
    dest=payload/rel; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(EXT/rel,dest)

# Make exact replacements from this task only. Production has unrelated changes.
patches={
 'backend/database.py': [
  ['        from config import PET_COSMETIC_PRICES, PET_BASE_TYPE', '        from config import PET_BASE_TYPE\n        from pet_collection import get_pet_price'],
  ["                price = PET_COSMETIC_PRICES.get(rarity, PET_COSMETIC_PRICES['common'])", '                price = get_pet_price(item_id, rarity)']],
 'backend/routes/pets.py': [
  ['from config import PET_COSMETIC_PRICES, PET_SLOTS','from config import PET_SLOTS\nfrom pet_collection import get_pet_price'],
  ['        it["price_crustics"] = PET_COSMETIC_PRICES.get(it.get("rarity"), PET_COSMETIC_PRICES["common"])','        it["price_crustics"] = get_pet_price(it.get("item_id"), it.get("rarity"))']],
 'backend/main.py': [[
  '        print("✅ Migrations complete")',
  '        from migrations import m129_pet_companions\n        await m129_pet_companions.apply(conn)\n\n        print("✅ Migrations complete")']],
}
# Derive OBS-only replacements against the initial unchanged checkout blob.
import subprocess
old=subprocess.check_output(['git','show','bc6f5ab:Расширение/frontend/overlay.html'],cwd=ROOT).decode('utf-8').splitlines(keepends=True)
new=(EXT/'frontend/overlay.html').read_text(encoding='utf-8').splitlines(keepends=True)
replacements=[]
for tag,a,b,c,d in difflib.SequenceMatcher(None,old,new,autojunk=False).get_opcodes():
    if tag=='equal':continue
    # Insertions need an anchor, never replace the empty string.
    if a==b:
        start=max(0,a-3)
        anchor=''.join(old[start:a])
        while ''.join(old).count(anchor)!=1 and start>0:
            start-=1;anchor=''.join(old[start:a])
        replacements.append([anchor,anchor+''.join(new[c:d])])
    else:replacements.append([''.join(old[a:b]),''.join(new[c:d])])
replacements.reverse()
patches['frontend/overlay.html']=replacements
check=''.join(old)
for before,after in replacements:
    assert check.count(before)==1,('ambiguous OBS patch',before)
    check=check.replace(before,after,1)
assert check==''.join(new),'OBS patch does not reproduce local renderer'
candidate=ROOT/'dist/releases/shedlink-0.0.5-review-candidate-20260923-6f8e07f5.zip'
with zipfile.ZipFile(candidate) as z: frozen=['frontend/'+p for p in z.namelist()]
manifest={'patches':patches,'files':paths,'frozen':frozen,'candidate_sha256':hashlib.sha256(candidate.read_bytes()).hexdigest(),
 'hashes':{p:hashlib.sha256((payload/p).read_bytes()).hexdigest() for p in paths}}
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
shutil.copyfile(ROOT/'scripts/install-pet-companions.py',OUT/'install.py')
shutil.copyfile(ROOT/'scripts/check-pet-deploy-stream.py',OUT/'check-stream.py')
with tarfile.open(OUT.parent/'bundle.tar.gz','w:gz') as t:
    for p in sorted(OUT.rglob('*')):
        if p.is_file():t.add(p,arcname=str(p.relative_to(OUT)))
print('Bundle:',len(paths),'new files;',len(patches),'surgical patches; frozen files excluded')
