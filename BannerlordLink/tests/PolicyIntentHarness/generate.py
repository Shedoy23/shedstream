from pathlib import Path
root = Path(__file__).parent
s = (root / '../../src/Actions/DiplomacyHandlers.cs').read_text(encoding='utf-8')
a = s.index('internal static (bool WantEnact, string Refusal) ResolvePolicyIntent(')
start = s.index('{', a); n = 1; b = start + 1
while n:
    n += (s[b] == '{') - (s[b] == '}'); b += 1
(root / 'Generated.cs').write_text('static class PolicyIntent { ' + s[a:b] + ' }', encoding='utf-8')
