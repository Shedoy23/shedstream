"""Assemble a single research document; never edit product sources."""
from pathlib import Path
import json
import re

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / 'BLT_MECHANICS_GAP_ANALYSIS.md'
BASELINE = json.loads((HERE / 'shedlink-baseline.json').read_text(encoding='utf-8'))
SOURCE = Path(BASELINE['root'])
FILES = [e['path'] for e in BASELINE['files']]


def link_shedlink(match):
    path, line = match.group(1), match.group(2)
    candidates = [p for p in FILES if p == path or p.endswith('/'+path)]
    if len(candidates) != 1:
        return match.group()
    label = match.group()[1:-1]
    return f'[{label}]({(SOURCE / candidates[0]).as_posix()}:{line})'


def main():
    text = (HERE / 'report-summary.md').read_text(encoding='utf-8').rstrip().replace('](verification.json)', '](research/verification.json)')
    chapters = [
        ('provenance-history.md', 'sources', False),
        ('shedlink-progression.md', 'shedlink-progression', True),
        ('shedlink-combat.md', 'shedlink-combat', True),
        ('shedlink-world.md', 'shedlink-world', True),
        ('blt-progression.md', 'progression-details', False),
        ('blt-combat.md', 'combat-details', False),
        ('blt-world.md', 'world-details', False),
    ]
    for name, anchor, local in chapters:
        body = (HERE / name).read_text(encoding='utf-8-sig').strip()
        body = re.sub(r'^(#{1,5}) ', r'\1# ', body, flags=re.M)
        body = re.sub(r'\]\(([^/():#]+\.md)\)', r'](research/\1)', body)
        if local:
            body = re.sub(r'`([^`\n]+?\.(?:cs|py|js|yaml|html)):(\d+)(?:[–-]\d+)?`', link_shedlink, body)
        text += f'\n\n---\n\n<a id="{anchor}"></a>\n\n{body}'
    text += '\n\n## Независимые проверки спорных выводов\n\n'
    for name in ['cross-review-combat.md', 'cross-review-world.md', 'cross-review-provenance.md']:
        text += f'- [{name}](research/{name})\n'
    text += '\nЭти проверки уточнили выводы; фактические оговорки внесены в основной текст. '
    text += 'Хеши baseline и результаты проверки ссылок лежат в research/.\n'
    OUT.write_text(text, encoding='utf-8', newline='\n')
    print(f'Created {OUT.name}: {len(text.splitlines())} lines, {len(text.encode("utf-8"))} bytes')


if __name__ == '__main__':
    main()
