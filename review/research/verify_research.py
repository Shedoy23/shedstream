"""Read-only evidence checks for the BLT research deliverable."""
from pathlib import Path
from urllib.parse import unquote
import hashlib
import json
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REPOS = {
    'billw2012/Bannerlord-Twitch': Path('D:/shedlink-build/billw2012'),
    'Randomchair22/Bannerlord-Twitch': Path('D:/shedlink-build/blt-research-randomchair22'),
    'MesmerTurn/BLT-5.4.x-Warsails-Reforged': Path('D:/shedlink-build/blt-research-mesmerturn'),
    'MesmerTurn/MakeBltGreatAgain': Path('D:/shedlink-build/blt-research-mbga'),
}


def main():
    baseline = json.loads((HERE / 'shedlink-baseline.json').read_text(encoding='utf-8'))
    source = Path(baseline['root'])
    modified = [entry['path'] for entry in baseline['files']
                if not (source / entry['path']).is_file()
                or hashlib.sha256((source / entry['path']).read_bytes()).hexdigest() != entry['sha256']]
    assert not modified, modified
    documents = [*HERE.glob('*.md'), ROOT / 'review/BLT_MECHANICS_GAP_ANALYSIS.md']
    url_pattern = re.compile(r'https://github\.com/([^/]+/[^/]+)/blob/([0-9a-f]{7,40})/([^\s)#]+)(?:#L(\d+)(?:-L(\d+))?)?')
    checked = {}
    errors = []
    local_links = set()
    for doc in documents:
        text = doc.read_text(encoding='utf-8-sig')
        for match in url_pattern.finditer(text):
            repo, rev, path, first, last = match.groups()
            path = unquote(path)
            key = (repo, rev, path)
            if key not in checked:
                cp = subprocess.run(['git', '-C', str(REPOS[repo]), 'show', f'{rev}:{path}'],
                                    capture_output=True)
                if cp.returncode:
                    errors.append({'document': doc.name, 'reference': match.group(),
                                   'error': cp.stderr.decode('utf-8', errors='replace')[:300]})
                    continue
                checked[key] = len(cp.stdout.decode('utf-8-sig', errors='replace').splitlines())
            if first and not (1 <= int(first) <= int(last or first) <= checked[key]):
                errors.append({'document': doc.name, 'reference': match.group(), 'error': 'line out of range'})
        for link in re.findall(r'\]\(([^)]+)\)', text):
            if link.startswith(('http:', 'https:', '#')):
                continue
            target = link.strip('<>').split('#')[0]
            target = re.sub(r':\d+$', '', target)
            if not target:
                continue
            p = Path(target) if re.match(r'^[A-Za-z]:[/\\]', target) else doc.parent / unquote(target)
            local_links.add(str(p))
            if not p.is_file():
                errors.append({'document': doc.name, 'reference': link, 'error': 'local file absent'})
    result = {'source_commit': baseline['commit'], 'source_files_hashed': len(baseline['files']),
              'source_changes_since_baseline': modified, 'pinned_source_files_verified': len(checked),
              'local_file_links_verified': len(local_links), 'errors': errors,
              'limits': ['Reference existence and line bounds are not semantic proof',
                         'No game execution, BLT build or production deployment',
                         'Historical and guide-only findings are explicitly labeled']}
    (HERE / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True, indent=2))
    assert not errors, 'Research references need correction'


if __name__ == '__main__':
    main()
