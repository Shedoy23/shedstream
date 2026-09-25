from pathlib import Path
root=Path(__file__).parent
s=(root/'../../src/Actions/DiplomacyHandlers.cs').read_text(encoding='utf-8')
def extract(marker):
    a=s.index(marker); start=s.index('{',a); n=1; b=start+1
    while n:
        n += (s[b]=='{')-(s[b]=='}'); b+=1
    return s[a:b]
parts=[extract('public class ProposeWarHandler'),extract('public class ProposePeaceHandler')]
util=extract('public static Kingdom ResolveKingdom(')+extract('public static bool SubmitDecisionToVote(')
(root/'Generated.cs').write_text('using System; using System.Linq; using System.Threading.Tasks; using Newtonsoft.Json.Linq; using TaleWorlds.CampaignSystem; using TaleWorlds.CampaignSystem.Election; using TaleWorlds.ObjectSystem; using BannerlordLink.Util; namespace BannerlordLink.Actions {'+'\n'.join(parts)+' public static class DiploUtil {'+util+'}}',encoding='utf-8')
