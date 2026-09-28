"""Read-only source inventory for the 0.0.6 game-data ownership audit.

Candidate regex matches are leads, not findings or proof of completeness.
Run from any directory. Writes only beside this script.
"""
from pathlib import Path
import collections
import hashlib
import json
import re
import subprocess

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
EXTENSIONS = {'.cs', '.py', '.js', '.mjs', '.cjs', '.html', '.css', '.json',
              '.yaml', '.yml', '.xml', '.xaml', '.csproj'}
PATTERNS = {
    'explicit_hardcode': r'hard.?cod|хардкод|захард|vanilla|ваниль|curated',
    'catalog_identity': r'cultures?|polic(?:y|ies)|skills?|attributes?|traits?|genes?|xenotype|hediff|def_name|StringId|item_id|troop_id',
    'closed_sets': r'ALLOWED_|VALID_|SUPPORTED_|DEFAULT_|const\s+\w+\s*=|static\s+readonly|HashSet|new\[\]|switch\s*\(',
    'limits_rules': r'Max[A-Z]|Min[A-Z]|MAX_|MIN_|COST|PRICE|COOLDOWN|Math\.(Min|Max|Clamp)|Mathf\.Clamp|\.clamp|\bmin\(|\bmax\(',
    'fallback': r'fallback|запасн|по умолчанию|\.get\([^\n]+,|\?\?',
    'dynamic_discovery': r'GetObjectTypeList|AllDefs|DefDatabase|\.All\b|module.catalog_update|catalog_update|available_actions',
}


def group(path):
    if '/tests/' in path or '/test/' in path or '/tools/' in path:
        return None
    if path.startswith('Расширение/frontend/'):
        return 'frontend'
    if path.startswith('Расширение/admin/'):
        return 'admin'
    if path.startswith('Расширение/backend/migrations/'):
        return 'migrations'
    if path.startswith('Расширение/backend/'):
        return 'backend'
    if path.startswith('BannerlordLink/src/'):
        return 'bannerlord_connector'
    if path.startswith('RimLink/Source/'):
        return 'rimworld_connector'
    if path.startswith('BannerlordAutopilot/src/'):
        return 'autopilot'
    if path.startswith('ShedLink.Manager/src/'):
        return 'manager'
    if path.startswith('manifests/installation/'):
        return 'installation_manifests'
    return None


def main():
    paths = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z']).decode('utf-8').split('\0')
    patterns = {key: re.compile(value, re.I) for key, value in PATTERNS.items()}
    files = []
    candidates = []
    baseline = []
    for name in sorted(filter(None, paths)):
        path = ROOT / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        if not name.startswith('version-0.0.6/'):
            baseline.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest()})
        layer = group(name)
        if layer is None or path.suffix.lower() not in EXTENSIONS:
            continue
        content = data.decode('utf-8-sig', errors='replace').splitlines()
        counts = collections.Counter()
        for line, text in enumerate(content, 1):
            hits = [key for key, pattern in patterns.items() if pattern.search(text)]
            counts.update(hits)
            if hits:
                candidates.append({'path': name, 'line': line, 'tags': hits, 'text': text.strip()[:400]})
        files.append({'path': name, 'layer': layer, 'lines': len(content),
                      'sha256': hashlib.sha256(data).hexdigest(), 'candidate_counts': dict(counts),
                      'coverage': 'automated lexical scan; not semantic review'})
    for name, payload in [('inventory.json', files), ('candidates.json', candidates), ('baseline-hashes.json', baseline)]:
        (OUT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    summary = {'source_commit': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']).decode().strip(),
               'files_scanned': len(files), 'lines_scanned': sum(f['lines'] for f in files),
               'candidate_lines': len(candidates), 'by_layer': dict(collections.Counter(f['layer'] for f in files)),
               'note': 'Lexical matches are not findings. Review evidence and active paths separately.'}
    (OUT / 'inventory-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
