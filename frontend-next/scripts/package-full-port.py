"""Local review export only: committed sources, base diff, bundle and readable build."""
import argparse
import hashlib
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
base = 'b2064f4b045025d33d05aaf166ca1694ae0f5475'
branch = 'feature/panel-preact-full'
parser = argparse.ArgumentParser()
parser.add_argument('output', type=Path)
args = parser.parse_args()
out = args.output.resolve()
if out == repo or repo in out.parents:
    raise SystemExit('Export outside the repository into the authorized workspace')
if out.parent != repo.parent:
    raise SystemExit('Output must be a sibling directory within the task workspace')
out.mkdir(exist_ok=True)

def git(*command):
    return subprocess.check_output(['git', '-c', 'safe.directory=' + repo.as_posix(), *command], cwd=repo)

head = git('rev-parse', 'HEAD').decode().strip()
if git('branch', '--show-current').decode().strip() != branch:
    raise SystemExit('Unexpected branch')
if git('status', '--porcelain'):
    raise SystemExit('Commit the delivery evidence before export')
source = out / 'source.zip'
bundle = out / 'panel-preact-full.bundle'
patch = out / 'panel-preact-full.patch'
git('archive', '--format=zip', '--output=' + str(source), head)
git('bundle', 'create', str(bundle), branch, '^' + base)
verification = subprocess.run(['git', '-c', 'safe.directory=' + repo.as_posix(), 'bundle', 'verify', str(bundle)], cwd=repo, capture_output=True, text=True)
(out / 'bundle-verify.txt').write_text(verification.stdout + verification.stderr, encoding='utf8')
if verification.returncode:
    raise SystemExit('Bundle verification failed')
git('diff', '--binary', '--full-index', '--output=' + str(patch), base, head)

def forbidden(name):
    parts = Path(name).parts
    leaf = Path(name).name.lower()
    return ('node_modules' in parts or '.git' in parts or
            Path(name).suffix.lower() in {'.db', '.sqlite', '.sqlite3', '.pfx', '.key'} or
            leaf == '.env' or leaf.startswith('.env.') and leaf not in {'.env.example', '.env.sample'})

with zipfile.ZipFile(source) as archive:
    bad = [name for name in archive.namelist() if forbidden(name)]
    if bad:
        raise SystemExit('Prohibited export file names: ' + repr(bad))
    if archive.testzip():
        raise SystemExit('Source ZIP CRC failure')
    source_files = len([info for info in archive.infolist() if not info.is_dir()])

reports = ['PANEL_FULL_PORT_RESULT_2026-10-03.md', 'PANEL_FULL_PORT_COVERAGE_2026-10-03.md',
           'PANEL_FULL_PORT_REVIEW_FIXES_2026-10-03.md',
           'PANEL_FULL_PORT_RECONCILIATION_2026-10-03.md', 'CLAUDE_FULL_PORT_HANDOFF_2026-10-03.md',
           'PANEL_FULL_PORT_MERGE_2026-10-03.md', 'TASK_ASTRA_PREACT_FULL_PORT_2026-10-03.md']
files = [(source, source.name), (bundle, bundle.name), (patch, patch.name), (out / 'bundle-verify.txt', 'bundle-verify.txt')]
files += [(repo / 'docs' / name, 'docs/' + name) for name in reports]
files += [(path, 'build/' + path.relative_to(repo / 'frontend-next/dist').as_posix()) for path in sorted((repo / 'frontend-next/dist').rglob('*')) if path.is_file()]
records = [{'path': name, 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path, name in files]
manifest = {'branch': branch, 'head': head, 'base': base,
            'authorized_progression_merge': 'e66e82098f894bc8f6e0dbe9598ddf2516088636',
            'created_utc': datetime.now(timezone.utc).isoformat(),
            'source_files': source_files, 'bundle_verify_exit': verification.returncode,
            'source_zip_crc_ok': True, 'prohibited_file_names': [],
            'production_or_publish_performed': False,
            'credentials': 'Only committed synthetic test fixtures; no local environment, DB, tokens, node_modules or .git config.',
            'files': records}
manifest_path = out / 'DELIVERY.json'
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
target = out / ('shedstream-panel-preact-full-' + head[:12] + '.zip')
with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path, name in files:
        archive.write(path, name)
    archive.write(manifest_path, 'DELIVERY.json')
with zipfile.ZipFile(target) as archive:
    if archive.testzip():
        raise SystemExit('Delivery ZIP CRC failure')
result = {'file': str(target), 'head': head, 'bytes': target.stat().st_size,
          'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'zip_crc_ok': True,
          'source_files': source_files, 'bundle_verify_exit': verification.returncode}
(out / 'PACKAGE.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
print(json.dumps(result, ensure_ascii=False))
