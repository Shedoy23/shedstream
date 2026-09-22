from pathlib import Path
root=Path(__file__).parent
s=(root/'../../src/Util/ClanIntegrity.cs').read_text(encoding='utf-8')
marker='internal static class ClanIntegrity'
a=s.index(marker); start=s.index('{',a); n=1; b=start+1
while n:
    n += (s[b]=='{')-(s[b]=='}'); b+=1
body=s[a:b]
(root/'Generated.cs').write_text(
 'using System; using System.Linq; using BannerlordLink; '
 'using TaleWorlds.CampaignSystem; using TaleWorlds.CampaignSystem.Actions; '
 'namespace BannerlordLink.Util {'+body+'}', encoding='utf-8')
