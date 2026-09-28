"""Verify public preview assets while backend rollout is intentionally pending."""
import concurrent.futures
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'dist/pets-fantasy-20260926'
manifest=json.loads((OUT/'bundle/manifest.json').read_text(encoding='utf-8'))

def get(path):
    with urllib.request.urlopen('https://shedoy23.ru'+path,timeout=20) as r:return r.read()

def verify(rel):
    assert hashlib.sha256(get('/'+rel.removeprefix('frontend/'))).hexdigest()==manifest['hashes'][rel],rel
    return rel

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    checked=list(pool.map(verify,[p for p in manifest['files'] if p.startswith('frontend/')]))
catalog=json.loads(get('/api/pet/catalog'))
assert not {x['item_id'] for x in catalog['items']} & {'skin_'+v for v in manifest['variants']},'Unexpected catalogue activation'
report={'health':json.loads(get('/health')),'public_assets_verified':len(checked),'catalogue_activation_pending':True,'catalogue_count':len(catalog['items'])}
(OUT/'preview-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
