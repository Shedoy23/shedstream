from pathlib import Path
root = Path(__file__).parent
s = (root / '../../src/Behaviors/StuckPrisonerReleaseBehavior.cs').read_text(encoding='utf-8')
a = s.index('internal static bool ShouldRelease(')
b = s.index(';', s.index('=>', a)) + 1
(root / 'Generated.cs').write_text('static class Stuck { ' + s[a:b] + ' }', encoding='utf-8')
