using System;
using System.Collections.Generic;
using System.Linq;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.GameMenus;
using TaleWorlds.CampaignSystem.GameState;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Core;

internal static partial class Program
{
    static (AutopilotBehavior Pilot, MapEvent Battle, TestFaction Bandits) GatheringWorld(float enemy = 40)
    {
        var b = Fresh(); Enable(b);
        var ours = new TestFaction(); var bandits = new TestFaction();
        ours.Enemies.Add(bandits); bandits.Enemies.Add(ours);
        var main = MobileParty.MainParty; main.MapFaction = ours; main.Party.MapFaction = ours;
        main.Party.TestStrength = 100;
        var battle = new MapEvent { PlayerSide = BattleSideEnum.Attacker };
        main.Party.MapEventSide = battle.AttackerSide;
        var target = GatherCandidate("target", enemy, 0, bandits);
        target.Party.MapEventSide = battle.DefenderSide;
        PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.Battle = battle;
        PlayerEncounter.EncounteredMobileParty = target;
        Show(new GameMenu { StringId = "encounter", Options = { new GameMenuOption { IdString = "attack" } } });
        return (b, battle, bandits);
    }

    static MobileParty GatherCandidate(string name, float strength, float distance, TestFaction faction)
    {
        var p = new MobileParty { Name = name, IsBandit = true, MapFaction = faction, Position = new CampaignVec2 { X = distance } };
        p.Party.MapFaction = faction; p.Party.TestStrength = strength;
        MobileParty.AllBanditParties.Add(p);
        return p;
    }

    static void BanditGatheringTests()
    {
        foreach (float addition in new[] { 60f, 80f, 81f, 10f })
        Try("реплика общего боя до ультиматума: добавочная сила " + addition, () => {
            var pilot = Fresh(); Enable(pilot);
            var ours = new TestFaction(); var bandits = new TestFaction(); ours.Enemies.Add(bandits); bandits.Enemies.Add(ours);
            var main = MobileParty.MainParty; main.MapFaction = ours; main.Party.TestStrength = 100;
            var target = GatherCandidate("target", 40, 0, bandits);
            var extra = GatherCandidate("extra", addition, 1, bandits);
            main.TargetParty = target; main.DefaultBehavior = AiBehavior.EngageParty;
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounteredMobileParty = target;
            var conversation = Campaign.Current.ConversationManager;
            conversation.IsConversationInProgress = true; conversation.ConversationParty = target;
            CampaignEvents.OnSessionLaunchedEvent = new SessionEvent();
            pilot.RegisterEvents(); var starter = new CampaignGameStarter(); CampaignEvents.OnSessionLaunchedEvent.Raise(starter);
            var line = starter.Lines.FirstOrDefault(x => x.Id == "autopilot_bandit_gather");
            Check(line != null && line.Input == "bandit_attacker" && line.Output == "bandit_start_fight", "зарегистрирована своя реплика со штатным выходом в бой");
            bool offered = line?.Condition?.Invoke() == true;
            Check(offered == (addition >= 60 && addition <= 80), "вызов предлагается только для достижимых 100–120% силы");
            conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id = "common_encounter_ultimatum", IsClickable = true });
            if (offered) conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id = line.Id, IsClickable = true });
            pilot.PollDialogs();
            Check(conversation.Selected.Single() == (offered ? "autopilot_bandit_gather" : "common_encounter_ultimatum"), "вызов выбирается раньше ультиматума, иначе сохранён ультиматум");
            Check(extra.MapEvent == null && extra.Position.X == 1, "оценка реплики и её выбор не телепортируют партии до появления боя");
        });
        Try("добор ближайших: пропуск слишком сильного, ровно 120%, один раз", () => {
            var w = GatheringWorld();
            var huge = GatherCandidate("too big", 81, 1, w.Bandits);
            var a = GatherCandidate("a", 30, 2, w.Bandits);
            var b = GatherCandidate("b", 50, 3, w.Bandits);
            var extra = GatherCandidate("extra", 1, 4, w.Bandits);
            w.Pilot.PollState(); w.Pilot.PollState();
            Check(a.MapEvent == w.Battle && b.MapEvent == w.Battle, "два ближайших подходящих отряда включены в тот же бой");
            Check(huge.MapEvent == null && extra.MapEvent == null, "лимит 120% и остановка добора после достижения нашей силы");
            Check(a.Position.X == 0 && b.Position.X == 0 && huge.Position.X == 1, "перемещены только принятые отряды");
            Check(a.Party.TestJoinCalls == 1 && b.Party.TestJoinCalls == 1, "повторный опрос не добавляет и не учитывает отряд дважды");
            Check(MenuContext.Invoked.Contains("attack"), "после добора нажата штатная атака");
        });
        Try("вражеские подкрепления уже в бою тоже расходуют предел", () => {
            var w = GatheringWorld(60);
            var existing = GatherCandidate("already", 40, 0, w.Bandits); existing.Party.MapEventSide = w.Battle.DefenderSide;
            var extra = GatherCandidate("extra", 10, 1, w.Bandits);
            w.Pilot.PollState();
            Check(extra.MapEvent == null, "враг уже равен нам с учётом подкреплений — добора нет");
        });
        Try("политика отбрасывания и радиус", () => {
            var w = GatheringWorld();
            var bad = new List<MobileParty>();
            Action<Action<MobileParty>> reject = set => { var p = GatherCandidate("rejected", 1, 1, w.Bandits); set(p); bad.Add(p); };
            reject(p => p.IsBandit = false); reject(p => p.IsActive = false);
            reject(p => p.IsCurrentlyAtSea = true); reject(p => p.IsEngaging = true);
            reject(p => p.Army = new object()); reject(p => p.SiegeEvent = new object());
            reject(p => p.CurrentSettlement = new Settlement { IsHideout = true });
            reject(p => p.BesiegedSettlement = new Settlement()); reject(p => p.IsDisbanding = true);
            reject(p => p.IsTransitionInProgress = true); reject(p => p.AttachedTo = new MobileParty());
            reject(p => p.AttachedParties.Add(new MobileParty()));
            reject(p => p.MapEvent = new MapEvent()); reject(p => p.Party.NumberOfHealthyMembers = 0);
            reject(p => p.Party.TestStrength = float.NaN); reject(p => p.Party.TestStrength = float.PositiveInfinity);
            reject(p => p.Party.TestStrength = -1); reject(p => p.Position = new CampaignVec2 { X = 31 });
            reject(p => { p.MapFaction = new TestFaction(); p.Party.MapFaction = p.MapFaction; });
            reject(p => w.Battle.TestDisallowed.Add(p.Party));
            var good = GatherCandidate("eligible", 70, 30, w.Bandits);
            w.Pilot.PollState();
            Check(bad.All(p => p.MapEvent != w.Battle && p.Party.TestJoinCalls == 0), "занятые, нейтральные, далёкие, небоеспособные и запрещённые движком отряды не тронуты");
            Check(good.MapEvent == w.Battle, "доступный отряд на границе радиуса собран, итог 110%");
        });
        foreach (string block in new[] { "observe", "inquiry", "attack-disabled", "lord", "sea", "settlement", "our-strength-nan", "enemy-strength-nan", "already-stronger", "defending" })
        Try("нет сбора: " + block, () => {
            var w = GatheringWorld(block == "already-stronger" ? 130 : 40);
            var p = GatherCandidate("candidate", 60, 1, w.Bandits);
            if (block == "observe") w.Pilot.TryEnable(AutopilotBehavior.Mode.Observe, out _);
            if (block == "inquiry") TaleWorlds.Library.InformationManager.TestInquiryActive = true;
            if (block == "attack-disabled") Campaign.Current.CurrentMenuContext.GameMenu.Options[0].IsEnabled = false;
            if (block == "lord") w.Battle.DefenderSide.LeaderParty.MobileParty.IsBandit = false;
            if (block == "sea") w.Battle.IsNavalMapEvent = true;
            if (block == "settlement") w.Battle.MapEventSettlement = new Settlement();
            if (block == "our-strength-nan") MobileParty.MainParty.Party.TestStrength = float.NaN;
            if (block == "enemy-strength-nan") w.Battle.DefenderSide.LeaderParty.TestStrength = float.NaN;
            if (block == "defending") w.Battle.PlayerSide = BattleSideEnum.Defender;
            w.Pilot.PollState();
            Check(p.MapEvent == null && p.Position.X == 1, "состояние " + block + " не перемещает бандитов");
        });
        Try("перечитываем силу после обработчиков присоединения", () => {
            var w = GatheringWorld(); var a = GatherCandidate("a", 20, 1, w.Bandits); var b = GatherCandidate("b", 50, 2, w.Bandits);
            a.Party.TestAfterJoin = () => w.Battle.DefenderSide.LeaderParty.TestStrength = 75;
            w.Pilot.PollState();
            Check(a.MapEvent == w.Battle && b.MapEvent == null, "изменение силы после первого присоединения не позволяет превысить предел вторым");
        });
        Try("тихий отказ присоединения возвращает позицию и останавливает", () => {
            var w = GatheringWorld(); var p = GatherCandidate("noop", 60, 1, w.Bandits); p.Party.TestIgnoreJoin = true;
            w.Pilot.PollState();
            Check(p.Position.X == 1 && p.MapEvent == null, "no-op присоединения не оставил телепортированный отряд");
            Check(w.Pilot.CurrentMode == AutopilotBehavior.Mode.Off && !MenuContext.Invoked.Contains("attack"), "сомнительный сбор останавливает автопилот до атаки");
        });
        Try("изменение силы сторон во время callback: превышение не запускает атаку", () => {
            var w = GatheringWorld(); var p = GatherCandidate("callback", 60, 1, w.Bandits);
            p.Party.TestAfterJoin = () => MobileParty.MainParty.Party.TestStrength = 50;
            w.Pilot.PollState();
            Check(w.Pilot.CurrentMode == AutopilotBehavior.Mode.Off && !MenuContext.Invoked.Contains("attack"), "после callback итоговые 200% замечены до атаки");
            Check(p.MapEvent == w.Battle, "подтверждённое присоединение не откатывается поверх действий движка");
        });
        Try("исключение после присоединения: нет повтора или ложного отката", () => {
            var w = GatheringWorld(); var p = GatherCandidate("throw", 60, 1, w.Bandits);
            p.Party.TestAfterJoin = () => throw new Exception("subscriber failed after joining");
            w.Pilot.PollState(); w.Pilot.PollState();
            Check(p.MapEvent == w.Battle && p.Position.X == 0 && p.Party.TestJoinCalls == 1, "эффект до исключения сохранён и не повторён");
            Check(w.Pilot.CurrentMode == AutopilotBehavior.Mode.Off && !MenuContext.Invoked.Contains("attack"), "исключение callback останавливает сбор до атаки");
        });
        Try("отдельный лорд среди противников запрещает сбор", () => {
            var w = GatheringWorld(); var lord = GatherCandidate("lord", 1, 0, w.Bandits); lord.IsBandit = false;
            lord.Party.MapEventSide = w.Battle.DefenderSide;
            var p = GatherCandidate("candidate", 60, 1, w.Bandits);
            w.Pilot.PollState();
            Check(p.MapEvent == null, "проверяется весь состав противников, а не один лидер");
        });
        Try("хватило равной силы — не заполняем остаток до 120%", () => {
            var w = GatheringWorld(); var near = GatherCandidate("near", 60, 1, w.Bandits);
            var far = GatherCandidate("far", 10, 2, w.Bandits);
            w.Pilot.PollState();
            Check(near.MapEvent == w.Battle && far.MapEvent == null, "добор прекращается на 100%, хотя ещё один отряд влезает в потолок");
        });
    }
}

namespace TaleWorlds.CampaignSystem
{
    public class SessionEvent
    {
        private Action<CampaignGameStarter> _handler;
        public void AddNonSerializedListener(object owner, Action<CampaignGameStarter> handler) { _handler = handler; }
        public void Raise(CampaignGameStarter starter) => _handler?.Invoke(starter);
    }
    public class CampaignGameStarter
    {
        public class Line { public string Id, Input, Output; public Func<bool> Condition; }
        public List<Line> Lines = new();
        public void AddPlayerLine(string id, string input, string output, string text, Func<bool> condition, Action consequence, int priority = 100)
            => Lines.Add(new Line { Id = id, Input = input, Output = output, Condition = condition });
    }
    public class MapEventParty { public PartyBase Party { get; set; } }
    public partial class MapEventSide
    {
        public MapEvent MapEvent;
        public List<MapEventParty> Parties { get; } = new();
    }
    public partial class MapEvent
    {
        public enum PowerCalculationContext { PlainBattle }
        public PowerCalculationContext SimulationContext { get; set; }
        public bool IsFieldBattle { get; set; } = true;
        public HashSet<PartyBase> TestDisallowed = new();
        public MapEvent() { AttackerSide.MapEvent = DefenderSide.MapEvent = this; }
        public bool CanPartyJoinBattle(PartyBase party, BattleSideEnum side)
        {
            var friends = side == BattleSideEnum.Attacker ? AttackerSide : DefenderSide;
            var enemies = side == BattleSideEnum.Attacker ? DefenderSide : AttackerSide;
            return !TestDisallowed.Contains(party) && friends.Parties.All(p => !p.Party.MapFaction.IsAtWarWith(party.MapFaction))
                && enemies.Parties.All(p => p.Party.MapFaction.IsAtWarWith(party.MapFaction));
        }
    }
}
namespace TaleWorlds.CampaignSystem.Party
{
    public partial class MobileParty
    {
        public static List<MobileParty> AllBanditParties { get; } = new();
        public bool IsEngaging { get; set; }
        public bool IsDisbanding { get; set; }
        public bool IsTransitionInProgress { get; set; }
        public MobileParty AttachedTo { get; set; }
        public List<MobileParty> AttachedParties { get; } = new();
    }
    public partial class PartyBase
    {
        public float TestStrength = 1;
        public int NumberOfHealthyMembers { get; set; } = 1;
        public int TestJoinCalls;
        public bool TestIgnoreJoin;
        public Action TestAfterJoin;
        public float GetCustomStrength(BattleSideEnum side, MapEvent.PowerCalculationContext context) => TestStrength;
        private MapEventSide _testSide;
        public MapEventSide MapEventSide
        {
            get => _testSide;
            set {
                if (TestIgnoreJoin || _testSide == value) return;
                _testSide = value;
                MobileParty.MapEvent = value.MapEvent;
                value.Parties.Add(new MapEventParty { Party = this });
                value.LeaderParty ??= this;
                TestJoinCalls++;
                TestAfterJoin?.Invoke();
            }
        }
    }
}
