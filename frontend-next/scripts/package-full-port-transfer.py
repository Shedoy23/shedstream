"""Create a small review ZIP and transport parts from a completed local export.

The full binary patch reconstructs the entire Git tree, including the authorized
merge. The ZIP also contains immediately reviewable Preact sources and evidence.
No upload or publication is performed by this script.
"""
import hashlib
import json
import math
import os
import subprocess
import sys
import zipfile
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
out = Path(sys.argv[1]).resolve()
assert out.parent == repo.parent and out != repo
delivery = json.loads((out/'DELIVERY.json').read_text(encoding='utf8'))
head, base = delivery['head'], delivery['base']
git_command = ['git', '-c', 'safe.directory='+repo.as_posix()]
assert subprocess.check_output(git_command+['rev-parse','HEAD'],cwd=repo).decode().strip() == head
assert not subprocess.check_output(git_command+['status','--porcelain'],cwd=repo)
env = dict(os.environ, GIT_INDEX_FILE=str(out/'patch-check.index'))
def git(*args):
    return subprocess.check_output(git_command+list(args),cwd=repo,env=env)
git('read-tree',base)
git('apply','--cached','--check',str(out/'panel-preact-full.patch'))
git('apply','--cached','--whitespace=nowarn',str(out/'panel-preact-full.patch'))
tree=git('write-tree').decode().strip()
assert tree == git('rev-parse',head+'^{tree}').decode().strip()
proof={'base':base,'head':head,'tree':tree,'exact_tree_match':True,'isolated_index':True}
(out/'PATCH-VERIFY.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf8')

def selected(name):
    return (name.startswith(('frontend-next/','docs/evidence/full-port/','docs/PANEL_FULL_PORT_'))
            or name in {'AGENTS.md','CLAUDE.md','STATUS.md','DEFERRED.md','LESSONS.md',
                        'Расширение/docs/CONTEXT.md','docs/CLAUDE_FULL_PORT_HANDOFF_2026-10-03.md',
                        'docs/TASK_ASTRA_PREACT_FULL_PORT_2026-10-03.md'})
target=out/f'shedstream-panel-preact-full-{head[:12]}-transfer.zip'
manifest={**proof,'branch':delivery['branch'],'production_or_publish_performed':False,
          'contents':'Complete tracked frontend-next sources; full-port reports/evidence; readable local build; full binary patch from base.',
          'omitted':'Full-repository source.zip and history bundle remain in the local full export. Apply the included binary patch to reconstruct the exact entire tree.',
          'credentials':'No local environment, DB, node_modules, .git configuration or real credentials; test identities are synthetic.'}
with zipfile.ZipFile(out/'source.zip') as source, zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for info in source.infolist():
        if not info.is_dir() and selected(info.filename): z.writestr('sources/'+info.filename,source.read(info))
    z.write(out/'panel-preact-full.patch','panel-preact-full.patch')
    z.write(out/'PATCH-VERIFY.json','PATCH-VERIFY.json')
    z.writestr('DELIVERY.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    for p in sorted((repo/'frontend-next/dist').rglob('*')):
        if p.is_file(): z.write(p,'build/'+p.relative_to(repo/'frontend-next/dist').as_posix())
    z.writestr('README.txt','Read sources/docs/CLAUDE_FULL_PORT_HANDOFF_2026-10-03.md and PANEL_FULL_PORT_RESULT_2026-10-03.md.\nApply panel-preact-full.patch only in a separate checkout at base '+base+'.\nUse git apply --check, then git apply --index. Exact expected tree: '+tree+'.\nNo push, deploy, PR or Twitch submission is authorized.\n')
with zipfile.ZipFile(target) as z:
    assert z.testzip() is None
    source_files=len(z.namelist())
blob=target.read_bytes()
transfer={'file':str(target),'head':head,'bytes':len(blob),'sha256':hashlib.sha256(blob).hexdigest(),'files':source_files,'zip_crc_ok':True}
(out/'TRANSFER.json').write_text(json.dumps(transfer,indent=2)+'\n',encoding='utf8')
parts_dir=out/'transfer-parts';parts_dir.mkdir(exist_ok=True)
size=768*1024;count=math.ceil(len(blob)/size)
parts=[]
for i in range(count):
    payload=blob[i*size:(i+1)*size];name=f'panel-full-{head[:7]}-part{i+1:02}-of-{count:02}.zip';part=parts_dir/name
    with zipfile.ZipFile(part,'w',compression=zipfile.ZIP_STORED) as z:z.writestr('payload.bin',payload)
    parts.append({'number':i+1,'file':name,'payload_bytes':len(payload),'payload_sha256':hashlib.sha256(payload).hexdigest(),'zip_sha256':hashlib.sha256(part.read_bytes()).hexdigest(),'path':str(part)})
transport={**proof,'target_name':target.name,'target_bytes':len(blob),'target_sha256':transfer['sha256'],'parts':parts}
(out/'PARTS.json').write_text(json.dumps(transport,indent=2)+'\n',encoding='utf8')
print(json.dumps({**transfer,'parts':count,'patch_tree_verified':True}))
