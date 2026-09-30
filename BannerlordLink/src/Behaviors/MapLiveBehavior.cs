using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

namespace BannerlordLink.Behaviors
{
    /// <summary>Живой слой карты на сайте shedoy23.ru/map/&lt;логин&gt; (30.09.2026).
    ///
    /// Раз в IntervalSeconds реального времени — снимок: отряды лордов (и зрителей, и
    /// стримера) с позицией, численностью, армией, осадой, целью; у городов и замков —
    /// гарнизон, ополчение, осада, владелец; у деревень — разорена ли. Только чтение
    /// управляемых объектов кампании, ничего не меняет. Событие не durable: устаревший
    /// снимок никому не нужен, следующий придёт через 15 с. На миссии кампания не тикает —
    /// снимков нет, сайт покажет «обновлено N мин назад».</summary>
    public class MapLiveBehavior : CampaignBehaviorBase
    {
        internal const double IntervalSeconds = 15;
        private readonly Stopwatch _since = Stopwatch.StartNew();
        private int _errors;

        public override void RegisterEvents()
        {
            CampaignEvents.TickEvent.AddNonSerializedListener(this, Tick);
        }

        public override void SyncData(IDataStore dataStore) { }

        private void Tick(float dt)
        {
            if (_since.Elapsed.TotalSeconds < IntervalSeconds) return;
            _since.Restart();
            try
            {
                var clock = Stopwatch.StartNew();
                string json = JsonConvert.SerializeObject(Build());
                long buildMs = clock.ElapsedMilliseconds;
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "map.live_snapshot", json));
                if (_errors > 0 || buildMs > 20)
                    BannerlordLinkModule.Log($"[MapLive] snapshot {json.Length / 1024} KB built in {buildMs} ms");
                _errors = 0;
            }
            catch (Exception ex)
            {
                // Не спамить лог каждые 15 с: первые три ошибки подряд, потом молчим до успеха.
                if (++_errors <= 3)
                    BannerlordLinkModule.Log($"[MapLive] snapshot error: {ex.GetType().Name}: {ex.Message}");
            }
        }

        private static object Build()
        {
            var parties = new List<object>();
            foreach (var p in MobileParty.All)
            {
                if (p == null || !p.IsActive) continue;
                bool main = p.IsMainParty;
                var leader = p.LeaderHero;
                if (!main && (!p.IsLordParty || leader == null)) continue;
                bool viewer = leader != null && HeroNaming.IsAdopted(leader);
                var pos = p.Position.ToVec2();
                var army = p.Army;
                var faction = p.MapFaction;
                parties.Add(new
                {
                    id = p.StringId,
                    x = Math.Round(pos.x, 1), y = Math.Round(pos.y, 1),
                    name = p.Name?.ToString(),
                    hero = leader?.Name?.ToString(),
                    login = viewer ? HeroNaming.ExtractUsername(leader.Name.ToString()) : null,
                    main,
                    clan = p.ActualClan?.Name?.ToString(),
                    f = faction?.StringId,
                    color = faction == null ? null : Hex(faction.Color),
                    men = p.MemberRoster?.TotalManCount ?? 0,
                    wounded = p.MemberRoster?.TotalWounded ?? 0,
                    prisoners = p.PrisonRoster?.TotalManCount ?? 0,
                    // Армия: участники идут за вождём; сайт рисует одного вождя с общей силой.
                    armyLeader = army?.LeaderParty?.StringId,
                    armyName = army?.Name?.ToString(),
                    armyMen = army == null ? 0 : ArmyMen(army),
                    inside = p.CurrentSettlement?.StringId,
                    besieging = p.BesiegedSettlement?.Name?.ToString(),
                    target = p.TargetSettlement?.Name?.ToString(),
                    behavior = p.DefaultBehavior.ToString(),
                });
            }

            var settlements = new List<object>();
            foreach (var s in Settlement.All)
            {
                if (s == null || (!s.IsTown && !s.IsCastle && !s.IsVillage)) continue;
                var faction = s.MapFaction;
                settlements.Add(new
                {
                    id = s.StringId,
                    f = faction?.StringId,
                    factionName = faction?.Name?.ToString(),
                    color = faction == null ? null : Hex(faction.Color),
                    clan = s.OwnerClan?.Name?.ToString(),
                    garrison = s.Town?.GarrisonParty?.MemberRoster?.TotalManCount,
                    militia = s.IsVillage ? (int?)null : (int)s.Militia,
                    siege = s.IsUnderSiege,
                    raided = s.IsVillage && s.Village != null ? s.Village.VillageState.ToString() : null,
                });
            }

            return new
            {
                save_id = Campaign.Current?.UniqueGameId,
                day = Math.Round(CampaignTime.Now.ToDays, 2),
                parties,
                settlements,
            };
        }

        private static int ArmyMen(Army army)
        {
            int total = 0;
            foreach (var member in army.Parties)
                total += member?.MemberRoster?.TotalManCount ?? 0;
            return total;
        }

        private static string Hex(uint argb) { return "#" + (argb & 0xFFFFFF).ToString("X6"); }
    }
}
