using System;
using System.Linq;
using System.Reflection;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Map;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

internal static partial class Program
{
    static object StabilityCall(AutopilotBehavior b, string name, params object[] args)
        => typeof(AutopilotBehavior).GetMethod(name, BindingFlags.Instance | BindingFlags.NonPublic).Invoke(b, args);

    static void StabilityOrder(AutopilotBehavior b, IMapPoint target, AiBehavior behavior)
        => StabilityCall(b, "ApplyDecision", MobileParty.MainParty,
            new AIBehaviorData(target, behavior, MobileParty.NavigationType.Default, false, false, false), 1f);

    static void CampaignStabilityTests()
    {
        foreach (string scenario in new[] { "strong", "weak", "raided", "neutral", "danger", "other-bound", "trade-only" })
        Try("набег на снабжение крепости: " + scenario, () => {
            var b = Fresh(); var castle = ConquestWorld(); castle.Name = "Шарас";
            castle.Position = new CampaignVec2 { X = 30 }; castle.Militia = scenario == "weak" ? 1 : 100;
            Settlement.All.Add(castle);
            var village = new Settlement { Name = "Деревня Шараса", IsVillage = true,
                Position = new CampaignVec2 { X = 20 }, MapFaction = castle.MapFaction, Militia = 1 };
            village.Village.Bound = castle; village.Village.TradeBound = castle;
            if (scenario == "raided") village.IsRaided = true;
            if (scenario == "neutral") village.MapFaction = new TestFaction();
            if (scenario == "other-bound") { village.Village.Bound = new Settlement(); village.Village.TradeBound = new Settlement(); }
            if (scenario == "trade-only") village.Village.Bound = new Settlement();
            if (scenario == "danger") HuntTarget("подмога", 100, 20, castle.MapFaction);
            Settlement.All.Add(village); Enable(b); HourlyTick(b);
            bool raids = MobileParty.MainParty.DefaultBehavior == AiBehavior.RaidSettlement
                && MobileParty.MainParty.TargetSettlement == village;
            Check(raids == (scenario == "strong"), "сильная крепость → безопасная связанная деревня; граница " + scenario);
            if (scenario == "weak") Check(SiegeTarget(b) == castle, "доступная осада важнее экономического набега");
            if (scenario == "strong") {
                village.IsRaided = true; HourlyTick(b);
                Check(MobileParty.MainParty.DefaultBehavior != AiBehavior.RaidSettlement,
                    "деревню успели разграбить — старый приказ отменён, даже если других целей нет");
            }
        });
        foreach (string change in new[] { "danger", "defense", "commander" })
        Try("поход к деревне пересматривается: " + change, () => {
            var b = Fresh(); var castle = ConquestWorld(); castle.Militia = 100;
            castle.Position = new CampaignVec2 { X = 30 }; Settlement.All.Add(castle);
            var village = new Settlement { IsVillage = true, MapFaction = castle.MapFaction,
                Position = new CampaignVec2 { X = 20 }, Militia = 1 };
            village.Village.Bound = castle; Settlement.All.Add(village);
            Enable(b); HourlyTick(b); var p = MobileParty.MainParty;
            Check(p.TargetSettlement == village && p.DefaultBehavior == AiBehavior.RaidSettlement, "набег начат");
            if (change == "danger") {
                HuntTarget("пришедшая подмога", 100, 20, castle.MapFaction);
                StabilityCall(b, "RecheckPressureRaid", p);
                Check(p.DefaultBehavior == AiBehavior.Hold, "опасный подход отменён при повторной проверке");
            } else if (change == "defense") {
                var own = OwnSiege(); HourlyTick(b);
                Check(p.TargetSettlement == own && p.DefaultBehavior == AiBehavior.GoToSettlement, "срочная оборона своего феода важнее набега");
            } else {
                p.Army = new Army { LeaderParty = new MobileParty() };
                village.IsRaided = true; StabilityCall(b, "RecheckPressureRaid", p);
                Check(p.DefaultBehavior == AiBehavior.RaidSettlement, "пересмотр не выдаёт Hold за чужого командующего");
            }
        });
        foreach (var order in new[] { AiBehavior.BesiegeSettlement, AiBehavior.DefendSettlement })
        Try("армия сохраняется на настоящем маршруте " + order, () => {
            var b = Fresh(); var castle = ConquestWorld(); Enable(b);
            var p = MobileParty.MainParty;
            if (order == AiBehavior.DefendSettlement) {
                castle.MapFaction = p.MapFaction; castle.IsUnderSiege = true;
                castle.SiegeEvent = new TaleWorlds.CampaignSystem.Siege.SiegeEvent { BesiegedSettlement = castle };
            }
            p.Army = new Army { LeaderParty = p, Cohesion = 40 };
            StabilityOrder(b, castle, order);
            Check(p.DefaultBehavior == AiBehavior.GoToSettlement, "стенд воспроизводит реальный приказ движения");
            for (int h = 0; h <= 24; h++) {
                CampaignTime.TestHours = h;
                StabilityCall(b, "DisbandIdleArmy", p);
            }
            Check(p.Army != null, "24 часа на осаду/оборону — армию не распускаем");
            p.SetMoveModeHold();
            CampaignTime.TestHours = 25; StabilityCall(b, "DisbandIdleArmy", p);
            Check(p.Army != null, "отмена похода начинает новый отсчёт простоя");
            CampaignTime.TestHours = 37; StabilityCall(b, "DisbandIdleArmy", p);
            Check(p.Army == null, "после отмены маршрута настоящий простой приводит к роспуску");
        });
        Try("новая армия не наследует простой предыдущей", () => {
            var b = Fresh(); ConquestWorld(); Enable(b); var p = MobileParty.MainParty;
            p.DefaultBehavior = AiBehavior.Hold; p.Army = new Army { LeaderParty = p };
            StabilityCall(b, "DisbandIdleArmy", p);
            CampaignTime.TestHours = 20;
            p.Army = new Army { LeaderParty = p };
            StabilityCall(b, "DisbandIdleArmy", p);
            Check(p.Army != null, "новой армии не присвоены 20 часов чужого простоя");
        });
        Try("повторные отказы на подходе увеличивают паузу", () => {
            var b = Fresh(); var castle = ConquestWorld(); castle.Militia = 8;
            Enable(b);
            StabilityCall(b, "NoteSiegeRejection", castle, "защитники 8");
            CampaignTime.TestHours = 13;
            Check(!(bool)StabilityCall(b, "SiegeRecentlyRejected", castle), "первый отказ даёт прежние 12 часов");
            StabilityCall(b, "NoteSiegeRejection", castle, "защитники 8");
            CampaignTime.TestHours = 26;
            Check((bool)StabilityCall(b, "SiegeRecentlyRejected", castle), "после второго отказа 13 часов недостаточно");
            CampaignTime.TestHours = 38;
            Check(!(bool)StabilityCall(b, "SiegeRecentlyRejected", castle), "второй отказ истекает через 24 часа");
            StabilityCall(b, "NoteSiegeRejection", castle, "защитники 8");
            CampaignTime.TestHours = 63;
            Check((bool)StabilityCall(b, "SiegeRecentlyRejected", castle), "третий отказ удерживает 48 часов");
            CampaignTime.TestHours = 87; StabilityCall(b, "NoteSiegeRejection", castle, "защитники 8");
            CampaignTime.TestHours = 136;
            Check((bool)StabilityCall(b, "SiegeRecentlyRejected", castle), "четвёртый отказ держится дольше 48 часов");
            CampaignTime.TestHours = 160;
            Check(!(bool)StabilityCall(b, "SiegeRecentlyRejected", castle), "предел паузы — 72 часа");
        });
        foreach (bool reinforcement in new[] { false, true })
        Try("заметное улучшение сил снимает запрет раньше таймера " + reinforcement, () => {
            var b = Fresh(); var castle = ConquestWorld(); castle.Militia = 8; Enable(b);
            StabilityCall(b, "NoteSiegeRejection", castle, "защитники 8");
            CampaignTime.TestHours = 1;
            if (reinforcement) MobileParty.MainParty.MemberRoster.AddToCounts(Veteran(), 3);
            else castle.Militia = 6;
            Check(!(bool)StabilityCall(b, "SiegeRecentlyRejected", castle), "есть существенный перевес — повтор разрешён");
            string reason = reinforcement ? "наша сила выросла" : "защита ослабла";
            Check(AutopilotLog.Lines.Any(l => l.Contains("снова доступна") && l.Contains(reason)
                && l.Contains("сила с лагерем") && l.Contains("защита") && l.Contains("до конца паузы")),
                "досрочный возврат объясняет конкретное изменение сил " + reinforcement);
            StabilityCall(b, "SiegeRecentlyRejected", castle);
            Check(AutopilotLog.Lines.Count(l => l.Contains("снова доступна")) == 1,
                "объяснение снятия паузы записывается один раз " + reinforcement);
        });
        Try("небольшое колебание сил не снимает запрет", () => {
            var b = Fresh(); var castle = ConquestWorld(); castle.Militia = 7; Enable(b);
            StabilityCall(b, "NoteSiegeRejection", castle, "защитники 7");
            castle.Militia = 6.6f; CampaignTime.TestHours = 1;
            Check((bool)StabilityCall(b, "SiegeRecentlyRejected", castle), "одно пересечение x1.5 не начинает новый круг");
        });
        foreach (bool ownArmy in new[] { false, true })
        Try("ближняя атака удерживается даже без очередного решения ИИ " + ownArmy, () => {
            var (b, enemy) = HuntWorld(100); var p = MobileParty.MainParty;
            if (ownArmy) p.Army = new Army { LeaderParty = p };
            var target = HuntTarget("Мертеон", 40, 4, enemy);
            var model = Campaign.Current.Models.MobilePartyAIModel;
            model.NextBehavior = AiBehavior.EngageParty; model.NextTarget = target; model.NextScore = 3;
            StabilityCall(b, "TryApplyNearbyAttack", p);
            CampaignTime.TestHours = 1;
            Check(b.HoldsChase(p, 30), "начатая ближняя атака получила удержание");
            target.MemberRoster.AddToCounts(Veteran(), 200);
            Check(!b.HoldsChase(p, 30), "опасно усилившегося врага не преследуем по старому разрешению");
        });
        Try("новый соседний враг не перебивает безопасную погоню", () => {
            var (b, enemy) = HuntWorld(100); var p = MobileParty.MainParty;
            var first = HuntTarget("Мертеон", 40, 4, enemy);
            HourlyTick(b);
            var second = HuntTarget("Джальфар", 70, 3, enemy);
            CampaignTime.TestHours = 1; HourlyTick(b);
            Check(p.TargetParty == first, "более привлекательный сосед не перетягивает приказ");
            first.CurrentSettlement = new Settlement();
            CampaignTime.TestHours = 2; HourlyTick(b);
            Check(p.TargetParty == second, "после исчезновения прежней цели можно выбрать новую");
        });
        Try("армия не подчиняет преследование рядовому участнику", () => {
            var (b, enemy) = HuntWorld(100); var p = MobileParty.MainParty;
            p.Army = new Army { LeaderParty = new MobileParty() };
            var target = HuntTarget("Мертеон", 10, 3, enemy);
            var model = Campaign.Current.Models.MobilePartyAIModel;
            model.NextBehavior = AiBehavior.EngageParty; model.NextTarget = target; model.NextScore = 3;
            Check(!(bool)StabilityCall(b, "TryApplyNearbyAttack", p), "приказы чужому командующему не выдаём");
        });
    }
}
