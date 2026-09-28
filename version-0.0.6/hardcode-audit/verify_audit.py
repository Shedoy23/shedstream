"""Verify audit evidence and unchanged baseline; no runtime writes."""
from pathlib import Path
import hashlib
import json

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]


def read(name):
    return json.loads((OUT / name).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    baseline = read('baseline-hashes.json')
    changed = [e['path'] for e in baseline
               if not (ROOT / e['path']).is_file()
               or sha(ROOT / e['path']) != e['sha256']]
    allowed = {'README_0.0.6.md', 'STATUS.md', 'DEFERRED.md'}
    unexpected = sorted(set(changed) - allowed)
    assert not unexpected, unexpected
    evidence = read('evidence-quotes.json')
    for e in evidence:
        assert sha(ROOT / e['path']) == e['source_sha256'], e['path']
    frozen = ROOT / 'dist/shedlink-0.0.5.zip'
    frozen_sha = sha(frozen)
    assert frozen_sha == '6f8e07f56b7d6a0b4f628a2731d81686a47b77dd8b7cfcc912dd1f8af3f90672'
    frontend = read('frontend-probe-results.json')
    assert all(r['expected_defect_reproduced'] for r in frontend['results'])
    assert 'exit_code=0' in (OUT / 'backend-probe.log').read_text(encoding='utf-8-sig')
    tests = read('checks/results.json')
    latest = {t['command']: t['exit_code'] for t in tests}
    assert len(latest) == 4 and all(code == 0 for code in latest.values()), latest
    lint = (OUT / 'checks/lint.log').read_text(encoding='utf-8-sig')
    assert '[lint] OK (1 warning(s))' in lint
    result = {
        'baseline_files_checked': len(baseline),
        'baseline_documentation_changes': changed,
        'unexpected_baseline_changes': unexpected,
        'runtime_modified': [],
        'evidence_references_hash_verified': len(evidence),
        'finding_schema_and_line_ranges': 'validated by build_report.py',
        'summary': read('audit-summary.json'),
        'frozen_client_sha256': frozen_sha,
        'frozen_client_path': 'dist/shedlink-0.0.5.zip',
        'test_fixture_sha256': sha(ROOT / 'Расширение/backend/tests/fixtures/frozen_client_0.0.5/shedlink-0.0.5.zip'),
        'frontend_probe': 'four expected current limitations reproduced; not fixed',
        'backend_probe': 'expected current overwrite/filter reproduced; not fixed',
        'existing_tests': tests,
        'lint': {'exit_code': 0, 'warning': 'game assembly policy ID check unavailable; skipped'},
        'limits': ['No live game or browser E2E', 'Minecraft Java connector source absent',
                   'CodeGraph database locked; no graph coverage',
                   'Lexical scan is not exhaustive semantic verification'],
    }
    (OUT / 'audit-verification.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ['baseline_files_checked',
        'unexpected_baseline_changes', 'evidence_references_hash_verified']}, indent=2))


if __name__ == '__main__':
    main()
