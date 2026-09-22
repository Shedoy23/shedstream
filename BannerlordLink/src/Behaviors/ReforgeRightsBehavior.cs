using System;
using System.Diagnostics;
using System.Threading.Tasks;
using BannerlordLink.Actions;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.MountAndBlade;
namespace BannerlordLink.Behaviors
{
    // No SyncData: rights come from the paid backend ledger, not a rolled-back save.
    public sealed class ReforgeRightsBehavior : CampaignBehaviorBase
    {
        private static ReforgeRightsBehavior _current;
        private readonly Stopwatch _clock = Stopwatch.StartNew();
        private volatile bool _fetching;
        private bool _started;
        public override void RegisterEvents() { _current=this; CampaignEvents.TickEvent.AddNonSerializedListener(this, Tick); }
        public override void SyncData(IDataStore store) { }
        private void Tick(float dt)
        {
            if (_current != this || Campaign.Current == null || BannerlordLinkModule.Backend == null
                || Mission.Current != null || _fetching || (_started && _clock.Elapsed.TotalSeconds < 30)) return;
            _started=true; _clock.Restart(); _fetching=true;
            var campaign=Campaign.Current;
            string saveId=campaign.UniqueGameId;
            var backend=BannerlordLinkModule.Backend;
            Task.Run(async () => {
                try {
                    string json=await backend.GetAsync("/api/bannerlord/reforge-rights?save_id="+Uri.EscapeDataString(saveId));
                    if (json==null) return;
                    var result=JObject.Parse(json);
                    if ((bool?)result["success"]!=true || (string)result["save_id"]!=saveId || !(result["rights"] is JArray rows)) return;
                    MainThreadDispatcher.Enqueue(() => {
                        if (_current!=this || Campaign.Current!=campaign || Mission.Current!=null) return;
                        foreach (JObject right in rows) {
                            string username=(string)right["username"];
                            var hero=HeroLookup.FindByUsername(username);
                            if (!ReforgeQuality.Restore(hero,right,saveId,username)) continue;
                            BannerlordLinkModule.Log("[reforge_restore] @"+username+" "+right["slot"]+" -> "+right["modifier_id"]+"; no charge");
                            EquipmentSync.PushAll(hero);
                            var inventory=EquipmentShopBehavior.Instance;
                            if (inventory!=null) inventory.Push(hero,inventory.Read(hero));
                        }
                    });
                } catch (Exception ex) { BannerlordLinkModule.Log("[reforge_restore] retry: "+ex.Message); }
                finally { _fetching=false; }
            });
        }
    }
}
