using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;
using BannerlordLink.Net;
using Newtonsoft.Json;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// MissionLogic: kill reward + battle participation для adopted heroes.
    /// BLT-aligned (Sprint 5.27g): all constants × 0.5 от BLT defaults.
    ///
    /// Personal kill (OnAgentRemoved, affector == наш hero):
    ///   gold = GOLD_PER_KILL × horseFactor × max(levelBoost, MinGold)
    ///   xp   = XP_PER_KILL   × horseFactor × levelBoost     → AddSkillXp(weaponSkill)
    ///   heal = HEAL_PER_KILL × horseFactor × levelBoost     → affector.Health
    ///
    /// Retinue kill (affector == свита нашего hero):
    ///   gold = RETINUE_GOLD_PER_KILL × horseFactor × max(levelBoost, MinGold)
    ///         → owner.Hero
    ///   heal = RETINUE_HEAL_PER_KILL × horseFactor × levelBoost
    ///         → САМ retinue agent (не owner)
    ///   xp   = 0                                          (BLT: свита XP не даёт)
    ///
    /// Killed (наш hero был убит — consolation):
    ///   xp = XP_PER_KILLED × levelBoost(killerLevel)
    ///
    /// Level scaling (BLT formula):
    ///   factor = (1 - (killedLvl - killerLvl) / 30) ^ (-10 × n)
    ///   gold-only clamp: max(factor, MinGold) для human kills
    ///
    /// Kill streaks: 5/10/15 — extra gold+XP bonus. Reset на смерть.
    ///
    /// Overlay stats push каждые 1.5с (snapshot участников).
    /// </summary>
    public class KillRewardBehavior : MissionLogic
    {
        // ── Combat economy (наши значения; крустики 1:5 динары) ─────────────

        // Personal kill (trooper)
        private const int   GOLD_PER_KILL = 2400;
        private const int   XP_PER_KILL   = 2400;
        private const float HEAL_PER_KILL = 12f;
        private const float HORSE_FACTOR  = 0.30f;  // mount kill multiplier

        // Killed (consolation XP за смерть нашего hero)
        private const int   XP_PER_KILLED = 900;

        // Retinue kill — gold owner'у, heal retinue agent'у самому.
        private const int   RETINUE_GOLD_PER_KILL = 1200;
        private const float RETINUE_HEAL_PER_KILL = 30f;

        // Level-gap reward factor (наш дизайн — линейный, клампится):
        // factor = clamp(1 + perLevel × (killedLvl − killerLvl), floor, cap).
        // perLevel = 0.18 → +18% за уровень разницы; cap ×4; floor 0.4.
        // MinGold = 0.4 — отдельный gold-клампинг (только human kills).
        private const int   MAX_LEVEL_GAP         = 28;
        private const float LEVEL_GAP_PER_LEVEL   = 0.18f;
        private const float LEVEL_GAP_CAP         = 4f;
        private const float LEVEL_GAP_FLOOR       = 0.4f;
        private const float MINIMUM_GOLD_PER_KILL = 0.4f;

        // Kill streak milestones: kills → +gold/+xp награда. Начисляется
        // КУМУЛЯТИВНО: проходя каждую веху (KillStreak == kills), зритель получает
        // её бонус один раз → дойдя до 150, накапливает все пройденные.
        // 2026-06-17 — золото вех 5-50 срезано ×0.5 (стрики = ~90% дохода и давили
        // перекос в пользу мили-фарма в толпе); хвост расширен до 150 каждые 10
        // плоско (+10k/шаг от 285k) — аспирационный потолок ~4M за 150-килл-бой,
        // не jackpot. XP не трогали (это прокачка, не заработок).
        private static readonly (int kills, int gold, int xp)[] KILL_STREAKS =
        {
            (  5,   5000,   2500),
            ( 10,  10000,   5000),
            ( 15,  20000,  10000),
            ( 20,  37500,  15000),
            ( 25,  62500,  20000),
            ( 30, 100000,  30000),
            ( 40, 175000,  45000),
            ( 50, 275000,  60000),
            ( 60, 285000,  75000),
            ( 70, 295000,  90000),
            ( 80, 305000, 105000),
            ( 90, 315000, 120000),
            (100, 325000, 135000),
            (110, 335000, 150000),
            (120, 345000, 165000),
            (130, 355000, 180000),
            (140, 365000, 195000),
            (150, 375000, 210000),
        };

        // 2026-07-21 — ВЕХИ ТЕПЕРЬ ЗА ВКЛАД, А НЕ ТОЛЬКО ЗА ДОБИВАНИЕ.
        // Замер владельца: берсерк за бой ~4М💰, остальные ~100К. Разбор формулы
        // подтвердил: 150 киллов = 360К базы + 3 985К вех, т.е. ВЕХИ дают 92%
        // дохода — и начислялись исключительно за добивающий удар. Разница в
        // киллах 7.5× превращалась в разницу в деньгах 36×. Лучник, выбивший
        // врага на 80%, и латник, державший на себе толпу, получали НОЛЬ.
        //
        // Теперь по той же лестнице двигают три вклада (порог = kills × LADDER_SCALE):
        //   убийство         +KILL_POINTS
        //   нанесённый урон  +1 очко за DAMAGE_PER_POINT единиц
        //   поглощённый урон +1 очко за ABSORB_PER_POINT единиц — ТОЛЬКО ВЫЖИВШИМ
        //     (иначе эксплойт «подставься под лучников ради денег»; умер — сгорело)
        //
        // Рядовой пехотинец ≈ 100 HP → убить его самому ≈ 10 + 100/12 ≈ 18 очков,
        // отсюда LADDER_SCALE = 18: убийца доходит до вершины примерно как раньше.
        // Деньги НЕ печатаются — они перераспределяются к тем, кто получал ноль.
        // Берсерка сознательно не ослабляем (11 зрителей из 18 сидят на нём).
        //
        // ЧИСЛА СТАРТОВЫЕ: счётчик киллов был сломан (844e6ae), замеров не было.
        // Строка [CONTRIB] в конце боя логирует урон/поглощение/очки по каждому —
        // по ней калибруем после первого же стрима. См. docs/SPEC_BATTLE_PAYOUT.md.
        private const int KILL_POINTS      = 10;
        private const int DAMAGE_PER_POINT = 12;
        private const int ABSORB_PER_POINT = 8;
        private const int LADDER_SCALE     = 18;

        // Participation reward (fires в OnEndMission). Применяется к каждому
        // BLink-участнику независимо от kill'ов — награда за факт участия.
        // Newbie-friendly: lose-штраф убран.
        private const int WIN_GOLD  = 4800;
        private const int WIN_XP    = 4800;
        private const int LOSE_GOLD = 0;      // мы не штрафуем за поражение
        private const int LOSE_XP   = 2400;   // consolation

        // Static registry: retinue agent → owner username. Populated
        // SummonHeroHandler'ом при spawn'е retinue. Cleared OnEndMission.
        //
        // Sprint 5.31 #45d (audit HIGH-3) — переход с ConcurrentDictionary
        // на ConditionalWeakTable<Agent, string>. ConcurrentDictionary
        // держит strong reference на Agent → если OnEndMission не fire'ит
        // (state transition без EndMission), Agent-объекты из мёртвой
        // миссии висят до process restart, блокируя GC и портя attribution
        // следующей миссии. CWT даёт weak-key — мёртвые Agent'ы auto-evict.
        // Thread-safety гарантирует сам CWT (lock-free reads, locked writes).
        //
        // Sprint 5.28 (history): был ConcurrentDictionary — Bannerlord
        // в основном single-threaded на main thread, но native engine
        // может callback'ать с других threads (AI, physics, animation).
        // Iteration mid-write бросал Collection modified exception на
        // background thread без catch → process die.
        private static readonly ConditionalWeakTable<Agent, string> _retinueOwners =
            new ConditionalWeakTable<Agent, string>();

        /// <summary>Called от SummonHeroHandler после spawn'a retinue agent'a.
        /// Регистрирует attribution: kill этого agent'a кредитится owner'у.</summary>
        public static void RegisterRetinue(Agent agent, string ownerUsername)
        {
            if (agent == null || string.IsNullOrEmpty(ownerUsername)) return;
            // CWT.Add throws on duplicate key. Remove+Add для idempotency.
            _retinueOwners.Remove(agent);
            _retinueOwners.Add(agent, ownerUsername.ToLowerInvariant());
        }

        // Sprint 5.7: registry для restore hero обратно в original party
        // после Mission end. BLT pattern (SummonHero.cs onMissionOver).
        //
        // Sprint 5.31 #45d (audit HIGH-2) — entries теперь keyed by Mission.
        // Если auto-resolve → следующая миссия запускается до того как
        // OnEndMission предыдущей пробежал по restore — записи от mission N
        // утекали в restore N+1 (hero восстанавливался в stale OriginalParty).
        // Теперь RestorePartyMembership фильтрует ТОЛЬКО записи которые были
        // зарегистрированы для текущей `Mission.Current` (захваченной при
        // регистрации).
        private class PartyRestoreEntry
        {
            public Mission Mission;   // sprint 5.31 #45d — для фильтра по миссии
            public Hero Hero;
            public TaleWorlds.CampaignSystem.Party.PartyBase OriginalParty;
            public bool WasLeader;
            public int OldHP;
        }
        private static readonly List<PartyRestoreEntry> _partyRestores =
            new List<PartyRestoreEntry>();

        /// <summary>Called от SummonHeroHandler перед spawn'ом hero.
        /// На OnEndMission hero возвращается в OriginalParty с восстановлением HP.</summary>
        public static void RegisterPartyRestore(
            Hero hero,
            TaleWorlds.CampaignSystem.Party.PartyBase originalParty,
            bool heroWasLeader,
            int hpBefore)
        {
            if (hero == null) return;
            _partyRestores.Add(new PartyRestoreEntry
            {
                Mission       = Mission.Current,   // snapshot текущей миссии
                Hero          = hero,
                OriginalParty = originalParty,
                WasLeader     = heroWasLeader,
                OldHP         = hpBefore,
            });
        }

        /// <summary>Восстановить hero в его original party. Вызывается из OnEndMission.
        ///
        /// Sprint 5.27e fix: раньше restore требовал OriginalParty != null —
        /// но у адоптированных viewer'ов чаще НЕТ своей party (PartyBelongedTo
        /// == null). SpawnHero всё равно делал AddMember(MainParty), и без
        /// restore эти герои оставались в streamer'овском party навсегда.
        /// Теперь removal делается ВСЕГДА (если current != original),
        /// а add-back в original — только если он был.</summary>
        private static void RestorePartyMembership()
        {
            // Sprint 5.31 #45d — обрабатываем ТОЛЬКО записи для текущей миссии.
            // Записи без mission'a (старые до фикса) обрабатываем тоже —
            // backward compat. Записи для других миссий — оставляем в списке,
            // их обработает ИХ OnEndMission.
            var currentMission = Mission.Current;
            var toProcess = _partyRestores
                .Where(e => e == null || e.Mission == null || e.Mission == currentMission)
                .ToList();
            foreach (var entry in toProcess)
            {
                if (entry?.Hero == null) continue;
                try
                {
                    var currentParty = entry.Hero.PartyBelongedTo?.Party;

                    // Skip если hero уже в нужном месте (либо в original,
                    // либо без party — тогда мы ничего не меняли).
                    if (currentParty == entry.OriginalParty) continue;

                    // 1) Remove from current party (обычно MainParty стримера).
                    //
                    // Sprint 5.28 fix (negative-roster bug):
                    // Раньше делали безусловный AddMember(-1). Если engine уже
                    // remove'нул героя (death mid-battle → auto-clear из roster'а,
                    // или MapEventEnded handler уже evict'нул его), наш -1 уводил
                    // count в негатив. У юзера накопилось -36/101 «Войны готовые
                    // к битве». Теперь проверяем GetTroopCount > 0 до удаления.
                    if (currentParty?.MemberRoster != null)
                    {
                        int curCount = 0;
                        try { curCount = currentParty.MemberRoster.GetTroopCount(entry.Hero.CharacterObject); }
                        catch { }
                        if (curCount > 0)
                        {
                            try { currentParty.MemberRoster.AddToCounts(entry.Hero.CharacterObject, -1); }
                            catch (Exception ex)
                            {
                                BannerlordLinkModule.Log(
                                    $"[PartyRestore] {entry.Hero.Name} remove from " +
                                    $"{currentParty.Name} failed: {ex.Message}");
                            }
                        }
                        else
                        {
                            BannerlordLinkModule.Log(
                                $"[PartyRestore] {entry.Hero.Name} skip remove from " +
                                $"{currentParty.Name?.ToString() ?? "?"} — count={curCount} " +
                                "(engine already cleared or never was в roster)");
                        }
                    }

                    // 2) Skip остальное если hero мёртв — не реанимируем призраков
                    //    в original party (ещё один путь корраптить roster: dead hero
                    //    + AddToCounts(+1) → ghost member). HP restore тоже не имеет
                    //    смысла для трупа.
                    if (!entry.Hero.IsAlive)
                    {
                        BannerlordLinkModule.Log(
                            $"[PartyRestore] {entry.Hero.Name} мёртв — skip HP/re-add (BLT pattern)");
                        continue;
                    }

                    // 3) Restore HP (alive hero only).
                    try { entry.Hero.HitPoints = entry.OldHP; } catch { }

                    // 4) Re-add в original party ТОЛЬКО если он был и ещё жив.
                    if (entry.OriginalParty != null
                        && entry.OriginalParty.MemberRoster != null
                        && entry.OriginalParty.MemberRoster.TotalHealthyCount > 0)
                    {
                        try
                        {
                            entry.OriginalParty.MemberRoster.AddToCounts(
                                entry.Hero.CharacterObject, 1, insertAtFront: entry.WasLeader);
                        }
                        catch (Exception ex)
                        {
                            BannerlordLinkModule.Log(
                                $"[PartyRestore] add to {entry.OriginalParty.Name} failed: {ex.Message}");
                        }
                        if (entry.WasLeader)
                        {
                            try
                            {
                                entry.OriginalParty.MobileParty?.PartyComponent?.ChangePartyLeader(entry.Hero);
                            }
                            catch { }
                        }
                        BannerlordLinkModule.Log(
                            $"[PartyRestore] {entry.Hero.Name} → {entry.OriginalParty.Name} " +
                            $"(was_leader={entry.WasLeader}, hp={entry.OldHP})");
                    }
                    else
                    {
                        // Sprint 5.27j: BLT pattern — viewer без original party
                        // отправляется в HomeSettlement через
                        // EnterSettlementAction.ApplyForCharacterOnly. Без этого
                        // PartyBelongedTo может застрять в phantom-state
                        // (count=0 в roster но hero числится "in party"),
                        // что ломает MainParty инварианты (negative members,
                        // broken passive heal). См. BLT AdoptAHero.cs:435.
                        var home = entry.Hero.HomeSettlement;
                        if (home == null)
                        {
                            // Fallback: любой town в map.
                            try
                            {
                                home = TaleWorlds.CampaignSystem.Settlements.Settlement.All
                                    ?.Where(s => s != null && s.IsTown)
                                    .FirstOrDefault();
                            }
                            catch { }
                        }
                        if (home != null)
                        {
                            try
                            {
                                EnterSettlementAction.ApplyForCharacterOnly(entry.Hero, home);
                                BannerlordLinkModule.Log(
                                    $"[PartyRestore] {entry.Hero.Name} → sent home " +
                                    $"({home.Name?.ToString() ?? "?"}) [no original party, BLT pattern]");
                            }
                            catch (Exception ex)
                            {
                                BannerlordLinkModule.Log(
                                    $"[PartyRestore] EnterSettlementAction failed for " +
                                    $"{entry.Hero.Name}: {ex.Message}");
                            }
                        }
                        else
                        {
                            BannerlordLinkModule.Log(
                                $"[PartyRestore] {entry.Hero.Name} → detached from " +
                                $"{currentParty?.Name?.ToString() ?? "?"} (no home settlement either!)");
                        }
                    }
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[PartyRestore] entry failed: {ex.Message}");
                }
            }
            // Sprint 5.31 #45d — удаляем только обработанные. Записи для
            // других миссий остаются ждать своего OnEndMission.
            _partyRestores.RemoveAll(e => toProcess.Contains(e));
        }

        // Overlay state push interval (sec)
        private const float STATS_PUSH_INTERVAL = 1.5f;

        // username → BattleStats (per-Mission tracker).
        // Sprint 5.28: ConcurrentDictionary (см. _retinueOwners выше).
        private readonly ConcurrentDictionary<string, BattleStats> _participants =
            new ConcurrentDictionary<string, BattleStats>();
        private float _nextStatsPushAt = 0f;

        private class BattleStats
        {
            public string Username;
            public Hero Hero;
            public Agent Agent;          // последний known agent (для HP read)
            public bool IsPlayerSide;    // sticky — сохраняется даже после смерти
            public int Kills;
            public int RetinueKills;     // киллы свиты, кредитятся owner'у
            public int GoldEarned;
            public int XpEarned;
            public int KillStreak;       // 2026-06-06: per-БОЙ (НЕ reset на смерть; только OnEndMission)
            // 2026-07-21 — вклад в бой (см. блок констант KILL_POINTS/…).
            public int DamageDealt;      // суммарный урон по врагам
            public int DamageAbsorbed;   // суммарный принятый на себя урон
            public int ContribPoints;    // пересчитанные очки (для лога/оверлея)
            public int MilestoneIdx;     // сколько вех уже выдано — каждая ровно один раз
            public bool Died;            // умирал ли за бой → поглощение не засчитываем
        }

        /// <summary>Множитель награды за разницу уровней (наш дизайн — линейный).
        /// killerLvl &lt; killedLvl → factor &gt; 1 (boost за сильную цель);
        /// killerLvl &gt; killedLvl → factor &lt; 1 (меньше за слабую). Разница
        /// клампится ±MAX_LEVEL_GAP, результат — в [floor..cap].</summary>
        private static float LevelGapRewardFactor(int killerLevel, int killedLevel,
            float perLevel, float cap)
        {
            int diff = killedLevel - killerLevel;
            if (diff >  MAX_LEVEL_GAP) diff =  MAX_LEVEL_GAP;
            if (diff < -MAX_LEVEL_GAP) diff = -MAX_LEVEL_GAP;
            float factor = 1f + perLevel * diff;
            if (factor < LEVEL_GAP_FLOOR) factor = LEVEL_GAP_FLOOR;
            if (factor > cap)             factor = cap;
            return factor;
        }

        /// <summary>
        /// Сторона агента: true — команда стримера (союз тоже считается).
        ///
        /// Возвращает false ЕСЛИ СЕЙЧАС ОПРЕДЕЛИТЬ НЕЛЬЗЯ (агента удалили,
        /// команда ещё не назначена, миссия кончилась) — вызывающий обязан в
        /// этом случае оставить прежнее значение, а не записывать «свой».
        ///
        /// 2026-07-31, пост-стрим-триаж. Раньше метод отдавал bool и на любой
        /// неопределённости возвращал false — то есть «чужой» и «не знаю» были
        /// неразличимы. Вместе с защёлкой `if (!s.IsPlayerSide)` это давало
        /// переворот стороны у всех призванных врагами (разбор — в шапке
        /// RefreshSide).
        /// </summary>
        private static bool TryComputeIsPlayerSide(Agent agent, out bool isPlayerSide)
        {
            isPlayerSide = false;
            try
            {
                if (agent == null || agent.Team == null) return false;
                var playerTeam = Mission.Current?.PlayerTeam;
                if (playerTeam == null) return false;
                isPlayerSide = agent.Team.Side == playerTeam.Side;
                return true;
            }
            catch { return false; }
        }

        /// <summary>
        /// Пересчитать сторону зрителя по ЖИВОМУ агенту.
        ///
        /// ЗАЧЕМ (пост-стрим-триаж 31.07, 43 неверные выплаты за вечер).
        /// Призыв «врагом» ставит команду вручную ПОСЛЕ рождения агента
        /// (`SummonHeroHandler`: forced SetTeam → PlayerEnemyTeam — так же
        /// делает BLT, движок иначе берёт сторону из партии-источника). А
        /// сторона фиксировалась в `OnAgentBuild`, то есть ДО этого момента,
        /// и пересчитывалась только «пока флаг ложный»:
        ///
        ///     if (!s.IsPlayerSide) s.IsPlayerSide = Compute(agent);
        ///
        /// Условие выполнимо лишь в одну сторону: как только флаг встал в
        /// «свой», он замерзал навсегда. По логу — 120 случаев из 120, где
        /// SetTeam шёл ПОСЛЕ фиксации стороны.
        ///
        /// Цена: награда за бой считается как `IsPlayerSide == playerVictory`.
        /// У призванного врагом она переворачивалась — он получал деньги
        /// победителя, проиграв, и штраф, победив. За вечер 31.07: 43 выплаты
        /// из 209, ~192 000💰 не в ту сторону.
        ///
        /// Липкость нужна и остаётся: после смерти агента команду уже не
        /// спросить, а награда начисляется в конце боя. Поэтому значение
        /// обновляется только когда его реально удалось определить.
        /// </summary>
        public static void RefreshSide(string username)
        {
            var inst = _instance;
            if (inst == null || string.IsNullOrEmpty(username)) return;
            if (!inst._participants.TryGetValue(username, out var s) || s == null) return;
            if (!TryComputeIsPlayerSide(s.Agent, out bool side)) return;
            if (s.IsPlayerSide == side) return;
            s.IsPlayerSide = side;
            BannerlordLinkModule.Log(
                $"[KillReward] @{username} сторона уточнена → {(side ? "player" : "enemy")}");
        }

        /// <summary>Возвращает state string для overlay: active/routed/unconscious/killed.</summary>
        private static string ComputeAgentState(Agent agent)
        {
            try
            {
                if (agent == null) return "killed";
                switch (agent.State)
                {
                    case AgentState.Active: return "active";
                    case AgentState.Routed: return "routed";
                    case AgentState.Unconscious: return "unconscious";
                    case AgentState.Killed: return "killed";
                    case AgentState.Deleted: return "killed";
                    default: return "active";
                }
            }
            catch { return "killed"; }
        }

        public override void OnAgentBuild(Agent agent, Banner banner)
        {
            base.OnAgentBuild(agent, banner);
            // 2026-07-24 — привязываем static _instance к ЖИВОЙ копии поведения
            // здесь: OnAgentBuild гарантированно выполняется на инстансе, который
            // держит реальный _participants. Раньше _instance ставился только в
            // OnBehaviorInitialize — и по факту оставался null/на чужой копии, из-за
            // чего NoteDamageDealt/NoteDamageAbsorbed тихо ничего не писали (весь
            // урон/поглощение = 0, оплата за вклад считала только киллы). Киллы
            // работали, т.к. идут через OnAgentRemoved (прямой вызов, без _instance).
            _instance = this;
            // Для overlay tracking используем STRICT [BLink] prefix check —
            // НЕ filter'ем по PowerCache (viewer мог адоптнуться, но не
            // выбрать класс — он всё равно должен показаться в overlay).
            string username = GetBLinkUsername(agent);
            if (username == null) return;

            if (!_participants.TryGetValue(username, out var s))
            {
                s = new BattleStats
                {
                    Username = username,
                    Hero     = (agent.Character as CharacterObject)?.HeroObject,
                };
                _participants[username] = s;
            }
            s.Agent = agent;
            // Сторона: пишем только если её удалось определить. Значение здесь
            // ПРЕДВАРИТЕЛЬНОЕ — призыв врагом переставляет команду сразу после
            // рождения агента, поэтому дальше её уточняют RefreshSide и
            // периодический snapshot. Прежняя защёлка `if (!s.IsPlayerSide)`
            // это уточнение и блокировала.
            if (TryComputeIsPlayerSide(agent, out bool builtSide))
            {
                s.IsPlayerSide = builtSide;
            }
            BannerlordLinkModule.Log(
                $"[KillReward] @{username} entered Mission " +
                $"(side={(s.IsPlayerSide ? "player" : "enemy")}, tracking)");
        }

        /// <summary>STRICT check: agent имеет [BLink] prefix в имени.
        /// Используется для overlay tracking — НЕ требует PowerCache class.</summary>
        private static string GetBLinkUsername(Agent agent)
        {
            if (agent == null || !agent.IsHuman) return null;
            var hero = (agent.Character as CharacterObject)?.HeroObject;
            if (hero?.Name == null) return null;
            string name = hero.Name.ToString();
            if (!BannerlordLink.Util.HeroNaming.IsAdopted(name)) return null;
            string username = BannerlordLink.Util.HeroNaming.ExtractUsername(name);
            return string.IsNullOrEmpty(username) ? null : username;
        }

        /// <summary>Sprint 5.27k — BLT WinGold/WinXP/LoseXP × 0.5.
        /// Fires в OnEndMission для каждого участника battle (BLink prefix):
        ///   • Если их сторона ПОБЕДИЛА:  +WIN_GOLD +WIN_XP
        ///   • Если их сторона ПРОИГРАЛА: +LOSE_XP (без штрафа gold)
        /// Skip если BattleState == DefenderPullBack (siege retreat).</summary>
        private void ApplyParticipationRewards()
        {
            if (_participants.Count == 0) return;

            // MissionResult может быть null на abort/retreat — skip полностью.
            var result = Mission?.MissionResult;
            if (result == null) return;
            // BLT pattern: skip когда defender отступил в keep (siege).
            try
            {
                if (result.BattleState == BattleState.DefenderPullBack) return;
            }
            catch { /* enum may not exist in старых TaleWorlds */ }

            bool playerVictory = false;
            try { playerVictory = result.PlayerVictory; }
            catch { return; }

            int rewarded = 0;
            List<BattleStats> snapshot;
            try { snapshot = _participants.Values.ToList(); }
            catch { return; }

            foreach (var s in snapshot)
            {
                if (s?.Hero == null) continue;
                try
                {
                    // Их side выиграл = (они на player side) == (player победил).
                    bool theirSideWon = s.IsPlayerSide == playerVictory;

                    // Sprint 5.30 #42 — apply sub reward_boost к participation reward.
                    int baseGold = theirSideWon ? WIN_GOLD : -LOSE_GOLD;
                    int baseXp   = theirSideWon ? WIN_XP   : LOSE_XP;
                    int goldDelta = baseGold >= 0
                        ? BannerlordLink.Net.RewardBoostCache.ApplyToInt(s.Username, baseGold)
                        : baseGold;   // losses не boost'им (penalty уже nerf'ed)
                    int xpDelta = baseXp >= 0
                        ? BannerlordLink.Net.RewardBoostCache.ApplyToInt(s.Username, baseXp)
                        : baseXp;

                    if (goldDelta != 0)
                    {
                        try
                        {
                            // ApplyBetweenCharacters(null, hero, delta>0)
                            // или (hero, null, delta>0) для удаления.
                            if (goldDelta > 0)
                                GiveGoldAction.ApplyBetweenCharacters(null, s.Hero, goldDelta, true);
                            else
                                GiveGoldAction.ApplyBetweenCharacters(s.Hero, null, -goldDelta, true);
                            s.GoldEarned += goldDelta;
                        }
                        catch (Exception ex)
                        { BannerlordLinkModule.Log($"[Participation] @{s.Username} gold failed: {ex.Message}"); }
                    }

                    if (xpDelta > 0)
                    {
                        // BLT: SkillXP.ImproveSkill(hero, xp, SkillsEnum.All).
                        // У нас нет helper'a — distribute по нескольким skills.
                        try { DistributeXpAcrossSkills(s.Hero, xpDelta); }
                        catch (Exception ex)
                        { BannerlordLinkModule.Log($"[Participation] @{s.Username} xp failed: {ex.Message}"); }
                        s.XpEarned += xpDelta;
                    }

                    rewarded++;
                    // Sprint 5.31 #45c — добавлен sub-boost в participation-лог.
                    double subBoost = BannerlordLink.Net.RewardBoostCache.Get(s.Username);
                    BannerlordLinkModule.Log(
                        $"[Participation] @{s.Username} side={(s.IsPlayerSide ? "ally" : "enemy")} " +
                        $"result={(theirSideWon ? "🏆WIN" : "💀LOSS")}: " +
                        $"{(goldDelta >= 0 ? "+" : "")}{goldDelta}💰 +{xpDelta} XP " +
                        $"[sub ×{subBoost:F2}]");

                    HeroStateSyncSafe(s.Hero);
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[Participation] @{s?.Username} CRASHED: {ex.Message}");
                }
            }
            BannerlordLinkModule.Log(
                $"[Participation] applied to {rewarded}/{_participants.Count} participants " +
                $"(playerVictory={playerVictory})");
        }

        /// <summary>BLT SkillXP.ImproveSkill(hero, xp, SkillsEnum.All) аналог:
        /// raspaivает xp по 4 ключевым combat skills + Athletics + Riding.</summary>
        private static void DistributeXpAcrossSkills(Hero hero, int totalXp)
        {
            if (hero == null || totalXp <= 0) return;
            var pool = new[] {
                DefaultSkills.OneHanded,
                DefaultSkills.TwoHanded,
                DefaultSkills.Polearm,
                DefaultSkills.Bow,
                DefaultSkills.Crossbow,
                DefaultSkills.Athletics,
                DefaultSkills.Riding,
            };
            int per = totalXp / pool.Length;
            if (per <= 0) per = 1;
            foreach (var skill in pool)
            {
                try { hero.HeroDeveloper.AddSkillXp(skill, per); } catch { }
            }
        }

        public override void OnAgentRemoved(Agent affectedAgent, Agent affectorAgent,
            AgentState agentState, KillingBlow blow)
        {
            base.OnAgentRemoved(affectedAgent, affectorAgent, agentState, blow);
            if (affectedAgent == null) return;

            // ── Retinue casualty (BLT RetinueDeathChance) — призванное войско
            //    свиты при killing blow с шансом теряется НАВСЕГДА. ──
            try
            {
                HandleRetinueCasualty(affectedAgent, agentState);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] retinue casualty CRASHED: {ex.GetType().Name}: {ex.Message}");
            }

            // ── Killed leg: наш hero был убит → consolation XP (BLT XPPerKilled) ─
            try
            {
                HandleAffectedKilled(affectedAgent, affectorAgent, agentState, blow);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] HandleAffectedKilled CRASHED: {ex.GetType().Name}: {ex.Message}");
            }

            // ── Killer leg: наш hero / его retinue убил кого-то → award reward ──
            if (affectorAgent == null || affectorAgent == affectedAgent) return;

            try
            {
                HandleAffectorKill(affectedAgent, affectorAgent, agentState, blow);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] HandleAffectorKill CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }

        // 2026-05-29 (BLT-parity BLTSummonBehavior) — шанс безвозвратной гибели
        // войска свиты — наш шанс безвозвратной гибели за бой (3%).
        private const float RETINUE_DEATH_CHANCE = 0.03f;

        /// <summary>Если убитый агент — наше призванное войско свиты (есть в
        /// RetinueRegistry) и это реальная смерть (Killed), бросаем шанс гибели.
        /// Выпал → пушим hero.retinue_casualty (backend убирает 1 слот навсегда).
        /// Не выпал → войско просто «погибло на этот бой», вернётся следующим
        /// призывом. Reg-запись снимаем в любом случае (агент удалён из миссии).</summary>
        private void HandleRetinueCasualty(Agent affectedAgent, AgentState state)
        {
            if (state != AgentState.Killed) return;   // unconscious не считается
            var tag = BannerlordLink.Net.RetinueRegistry.Get(affectedAgent);
            if (tag == null) return;                  // не наше войско свиты
            BannerlordLink.Net.RetinueRegistry.Remove(affectedAgent);

            if (TaleWorlds.Core.MBRandom.RandomFloat >= RETINUE_DEATH_CHANCE)
                return;                               // выжил (вернётся след. бой)

            string troopName =
                (affectedAgent.Character as CharacterObject)?.Name?.ToString() ?? tag.TroopId;
            var payload = new
            {
                username = tag.User,
                troop_id = tag.TroopId,
                troop_name = troopName,
            };
            string json = Newtonsoft.Json.JsonConvert.SerializeObject(payload);
            System.Threading.Tasks.Task.Run(async () => await BannerlordLinkModule.Backend
                .PostEventAsync("bannerlord", "hero.retinue_casualty", json));
            BannerlordLinkModule.Log(
                $"[KillReward] @{tag.User} RETINUE CASUALTY — {tag.TroopId} погиб " +
                $"навсегда ({RETINUE_DEATH_CHANCE * 100f:F1}% roll)");
        }

        /// <summary>Если affected это наш hero и его прибили — даём consolation XP
        /// (BLT XPPerKilled) с level-scaling. 2026-06-06 — KillStreak больше НЕ
        /// сбрасывается на смерть (per-бой стрик).</summary>
        private void HandleAffectedKilled(Agent affectedAgent, Agent affectorAgent,
            AgentState state, KillingBlow blow)
        {
            if (affectedAgent == null || !affectedAgent.IsHuman) return;
            if (state != AgentState.Unconscious && state != AgentState.Killed) return;

            string victimUsername = GetBLinkUsername(affectedAgent);
            if (victimUsername == null) return;

            Hero victim = (affectedAgent.Character as CharacterObject)?.HeroObject;
            if (victim == null) return;

            // 2026-06-06 — KillStreak НЕ сбрасываем на смерть (per-БОЙ стрик, по
            // просьбе стримера): убран `vstats.KillStreak = 0`. Стрик переживает
            // смерти/ре-вызовы, обнуляется только при очистке _participants в
            // OnEndMission → вехи 20-50 реально достижимы за бой. vstats всё ещё
            // объявляем — он нужен ниже (XpEarned += xp), но streak НЕ трогаем.
            _participants.TryGetValue(victimUsername, out var vstats);
            // 2026-07-21 — умер за бой → поглощённый урон в очки НЕ пойдёт
            // (защита от «подставься под лучников ради вех»).
            if (vstats != null) vstats.Died = true;

            // Consolation XP. Level scaling: убит higher-level → больше xp.
            int killerLevel = victim.Level;
            try
            {
                var killerChar = affectorAgent?.Character as CharacterObject;
                if (killerChar != null) killerLevel = killerChar.Level;
            }
            catch { }

            float levelBoost = LevelGapRewardFactor(
                victim.Level, killerLevel,
                LEVEL_GAP_PER_LEVEL, LEVEL_GAP_CAP);
            int xp = (int)(XP_PER_KILLED * levelBoost);
            if (xp <= 0) return;

            SkillObject skill = ResolveSkillFromBlow(blow) ?? DefaultSkills.Athletics;
            try { victim.HeroDeveloper.AddSkillXp(skill, xp); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] @{victimUsername} XPPerKilled failed: {ex.Message}");
                return;
            }

            if (vstats != null) vstats.XpEarned += xp;

            BannerlordLinkModule.Log(
                $"[KillReward] @{victimUsername} killed by {affectorAgent?.Name?.ToString() ?? "?"} → " +
                $"consolation +{xp} XP ({skill.StringId}, levelBoost={levelBoost:F2})");

            HeroStateSyncSafe(victim);
        }

        /// <summary>Affector — наш hero или его retinue → выдать gold/xp/heal.
        /// BLT pattern: личный kill даёт всё, retinue kill даёт gold owner'у +
        /// heal САМОМУ retinue agent'у (не owner'у), XP не даёт.</summary>
        private void HandleAffectorKill(Agent affectedAgent, Agent affectorAgent,
            AgentState state, KillingBlow blow)
        {
            // Identify killer как personal hero / retinue owner.
            string killerName = GetBLinkUsername(affectorAgent);
            bool isRetinueKill = false;
            Hero killer = null;

            if (killerName != null)
            {
                killer = (affectorAgent.Character as CharacterObject)?.HeroObject;
                if (killer == null || !killer.IsAlive) return;
            }
            else if (_retinueOwners.TryGetValue(affectorAgent, out var ownerUsername))
            {
                killerName = ownerUsername;
                isRetinueKill = true;
                if (_participants.TryGetValue(ownerUsername, out var ownerStats))
                    killer = ownerStats.Hero;
                if (killer == null || !killer.IsAlive) return;
            }
            else
            {
                return;  // не наш killer
            }

            bool isHumanTarget = affectedAgent.IsHuman;
            bool isHeroTarget = isHumanTarget
                && (affectedAgent.Character as CharacterObject)?.HeroObject != null;

            // Base reward по типу kill'a
            int baseGold;
            int baseXp;
            float baseHeal;
            if (isRetinueKill)
            {
                baseGold = RETINUE_GOLD_PER_KILL;
                baseXp   = 0;                       // BLT: свита XP не даёт
                baseHeal = RETINUE_HEAL_PER_KILL;   // heal — самому retinue agent'у
            }
            else
            {
                baseGold = GOLD_PER_KILL;
                baseXp   = XP_PER_KILL;
                baseHeal = HEAL_PER_KILL;
            }

            // Horse factor (×0.25 если убил mount)
            float horseFactor = isHumanTarget ? 1f : HORSE_FACTOR;
            baseGold = (int)(baseGold * horseFactor);
            baseXp   = (int)(baseXp   * horseFactor);
            baseHeal = baseHeal * horseFactor;

            // Level scaling (BLT): killer-level vs killed-level
            int killerLevel = killer.Level;
            int killedLevel = killerLevel;
            try
            {
                var killedChar = affectedAgent.Character as CharacterObject;
                if (killedChar != null) killedLevel = killedChar.Level;
            }
            catch { }

            float levelBoost = LevelGapRewardFactor(
                killerLevel, killedLevel,
                LEVEL_GAP_PER_LEVEL, LEVEL_GAP_CAP);

            // Gold factor: max(levelBoost, MinGold) для human, для mount без clamp.
            float goldBoost = isHumanTarget
                ? Math.Max(levelBoost, MINIMUM_GOLD_PER_KILL)
                : levelBoost;

            // Sprint 5.30 #42 — sub-tier reward_boost из RewardBoostCache.
            // Backend пушит boost при login/action (через _user_role + Helix
            // sub detection). Per-user multiplier к gold + XP (heal не трогаем —
            // tactical advantage и без того сильный).
            double rewardBoost = BannerlordLink.Net.RewardBoostCache.Get(killerName);

            int gold = (int)(baseGold * goldBoost * rewardBoost);
            int xp   = (int)(baseXp   * levelBoost * rewardBoost);
            float heal = baseHeal * levelBoost;

            // Apply gold (owner)
            if (gold > 0)
            {
                try { GiveGoldAction.ApplyBetweenCharacters(null, killer, gold, true); }
                catch (Exception ex)
                { BannerlordLinkModule.Log($"[KillReward] gold give failed: {ex.Message}"); }
            }

            // Apply XP (personal only — свита XP не даёт)
            SkillObject skill = ResolveSkillFromBlow(blow) ?? DefaultSkills.Athletics;
            if (xp > 0 && !isRetinueKill)
            {
                try { killer.HeroDeveloper.AddSkillXp(skill, xp); }
                catch (Exception ex)
                { BannerlordLinkModule.Log($"[KillReward] xp add failed: {ex.Message}"); }
            }

            // Apply heal:
            //   personal kill → affector это hero, heal hero agent
            //   retinue kill  → affector это retinue agent, heal САМ retinue
            if (heal > 0f && affectorAgent.IsActive())
            {
                try
                {
                    affectorAgent.Health = Math.Min(
                        affectorAgent.HealthLimit,
                        affectorAgent.Health + heal);
                }
                catch { }
            }

            // Update stats + kill streak (BLT pattern: streak только за personal)
            if (_participants.TryGetValue(killerName, out var s))
            {
                if (isRetinueKill)
                {
                    s.RetinueKills++;
                }
                else
                {
                    s.Kills++;
                    // 2026-07-21 — KillStreak остаётся ДЛЯ ОВЕРЛЕЯ (показать «×N
                    // подряд»), но деньги за вехи он больше НЕ выдаёт: лестница
                    // переехала на очки вклада (AwardContribMilestones, тик 1.5с),
                    // иначе добивание оплачивалось бы дважды.
                    if (isHumanTarget) s.KillStreak++;
                }
                s.GoldEarned += gold;
                s.XpEarned += xp;
                if (!isRetinueKill) s.Agent = affectorAgent;
            }

            // 2026-07-21 — блок выдачи веха-бонуса ЗДЕСЬ удалён: вехи переехали на
            // очки вклада (AwardContribMilestones, тик 1.5с + добор в конце боя),
            // иначе добивание оплачивалось бы дважды. Осиротел из-за этой же правки.

            string targetLabel = isHeroTarget ? "HERO"
                : (isHumanTarget ? "human" : "mount");
            if (isRetinueKill) targetLabel += "/retinue";

            string victimName = affectedAgent.Name?.ToString() ?? "?";
            // Sprint 5.31 #45c — добавлен sub-boost в kill-лог.
            // Раньше rewardBoost применялся (L675) но в логе не показывался —
            // нельзя было понять "subscriber не получил x1.5" cache miss это
            // или реально применилось.
            BannerlordLinkModule.Log(
                $"[KillReward] @{killerName} {(isRetinueKill ? "retinue" : "personal")} " +
                $"killed {victimName} ({targetLabel}): " +
                $"+{gold}💰 +{xp} XP ({skill.StringId}) +{heal:F0} HP " +
                $"[lvl K{killerLevel}/T{killedLevel} → boost ×{levelBoost:F2}, " +
                $"sub ×{rewardBoost:F2}]");

            HeroStateSyncSafe(killer);
        }

        // Sprint 5.32 (BLT-parity M1) — per-tick HP regen для viewer-hero'ев.
        // BLT pattern (BLTAdoptAHeroCustomMissionBehavior.AddListeners onSlowTick)
        // — даёт viewer'ам passive HP throughout battle. Без этого они умирают
        // в долгих сиегах гораздо быстрее обычных troops. Per-class rate чтобы
        // tank регенерил быстрее archer'а (компенсирует melee-exposure):
        //   tank/knight        → 5.0 HP/s  (heavy armor + shield-front-line)
        //   infantry/berserk/psycho/assassin → 3.0 HP/s
        //   cavalry/camel_cavalry → 4.0 HP/s (mobility = ranged exposure)
        //   horse_archer/camel_archer → 3.5 HP/s
        //   archer/heavy_archer/crossbow/heavy_crossbow → 2.0 HP/s
        //   unknown class      → 2.5 HP/s default
        private const float REGEN_INTERVAL = 1.0f;
        private float _nextRegenAt = 0f;
        private static readonly Dictionary<string, float> _classRegenPerSec =
            new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase)
            {
                ["tank"]            = 5.0f,
                ["knight"]          = 5.0f,
                ["infantry"]        = 3.0f,
                ["berserk"]         = 3.0f,
                ["psycho"]          = 3.0f,
                ["assassin"]        = 3.0f,
                ["cavalry"]         = 4.0f,
                ["camel_cavalry"]   = 4.0f,
                ["horse_archer"]    = 3.5f,
                ["camel_archer"]    = 3.5f,
                ["archer"]          = 2.0f,
                ["heavy_archer"]    = 2.0f,
                ["crossbow"]        = 2.0f,
                ["heavy_crossbow"]  = 2.0f,
            };
        private const float DEFAULT_REGEN_PER_SEC = 2.5f;

        // Sprint 5.32 (LOG-2) — periodic regen stats. Каждые 10 секунд dump'аем
        // одну строку чтобы streamer мог понять — heal'ает ли реально regen,
        // или агенты на cap'е (no-op), или поведение сломано. Counters reset
        // после каждого dump'а.
        private const float REGEN_STATS_LOG_INTERVAL = 10.0f;
        private float _nextRegenStatsAt = 0f;
        private int _regenHealedCount = 0;
        private float _regenHpTotal = 0f;

        // 2026-07-21 — инстанс для DamageHookPatch (hot path: дёргается на каждый
        // удар, GetMissionBehavior там был бы дорог). Чистится в OnEndMission.
        private static KillRewardBehavior _instance;

        public override void OnBehaviorInitialize()
        {
            base.OnBehaviorInitialize();
            _instance = this;
        }

        /// <summary>Учёт вклада: урон, нанесённый нашим героем врагу.</summary>
        public static void NoteDamageDealt(string username, int damage)
        {
            if (damage <= 0 || string.IsNullOrEmpty(username)) return;
            var inst = _instance;
            if (inst == null) return;
            if (inst._participants.TryGetValue(username, out var s)) s.DamageDealt += damage;
        }

        /// <summary>Учёт вклада: урон, принятый нашим героем НА СЕБЯ. В очки
        /// конвертируется только если он пережил бой (см. SettleAbsorbedContrib) —
        /// иначе появился бы фарм «подставься под лучников».</summary>
        public static void NoteDamageAbsorbed(string username, int damage)
        {
            if (damage <= 0 || string.IsNullOrEmpty(username)) return;
            var inst = _instance;
            if (inst == null) return;
            if (inst._participants.TryGetValue(username, out var s)) s.DamageAbsorbed += damage;
        }

        /// <summary>2026-07-21 — выдать все ПРОЙДЕННЫЕ вехи по очкам вклада.
        /// Именно «все», а не одну: очки могут прыгнуть сразу через несколько
        /// порогов (удар по площади, зачёт поглощения в конце боя). MilestoneIdx
        /// гарантирует, что каждая веха выдаётся ровно один раз.</summary>
        private void AwardContribMilestones(BattleStats s, bool includeAbsorb)
        {
            if (s?.Hero == null) return;
            int pts = s.Kills * KILL_POINTS
                    + s.DamageDealt / DAMAGE_PER_POINT
                    + (includeAbsorb ? s.DamageAbsorbed / ABSORB_PER_POINT : 0);
            s.ContribPoints = pts;

            while (s.MilestoneIdx < KILL_STREAKS.Length
                   && pts >= KILL_STREAKS[s.MilestoneIdx].kills * LADDER_SCALE)
            {
                var ks = KILL_STREAKS[s.MilestoneIdx];
                s.MilestoneIdx++;
                try
                {
                    int gold = BannerlordLink.Net.RewardBoostCache.ApplyToInt(s.Username, ks.gold);
                    int xp   = BannerlordLink.Net.RewardBoostCache.ApplyToInt(s.Username, ks.xp);
                    if (gold > 0)
                    {
                        GiveGoldAction.ApplyBetweenCharacters(null, s.Hero, gold, true);
                        s.GoldEarned += gold;
                    }
                    if (xp > 0)
                    {
                        DistributeXpAcrossSkills(s.Hero, xp);
                        s.XpEarned += xp;
                    }
                    BannerlordLinkModule.Log(
                        $"[CONTRIB] @{s.Username} веха {ks.kills} ({ks.kills * LADDER_SCALE} очк.): " +
                        $"киллы={s.Kills} урон={s.DamageDealt} поглощено={s.DamageAbsorbed} " +
                        $"→ +{gold}💰 +{xp} XP");

                    // In-game popup (как было у стриков): бронза → красный.
                    var col = ks.kills >= 15
                        ? new TaleWorlds.Library.Color(1f, 0.13f, 0.13f)
                        : (ks.kills >= 10
                            ? new TaleWorlds.Library.Color(1f, 0.55f, 0.0f)
                            : new TaleWorlds.Library.Color(1f, 0.84f, 0.18f));
                    TaleWorlds.Library.InformationManager.DisplayMessage(
                        new TaleWorlds.Library.InformationMessage(
                            $"🔥 @{s.Username} вклад ×{ks.kills}! +{gold}💰", col));
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[CONTRIB] @{s.Username} веха {ks.kills} FAILED: {ex.Message}");
                }
            }
        }

        /// <summary>Конец боя: выжившим засчитываем поглощённый урон и добираем
        /// вехи. Умершим поглощение сгорает — это и есть защита от подставы.</summary>
        private void SettleAbsorbedContrib()
        {
            List<BattleStats> snapshot;
            try { snapshot = _participants.Values.ToList(); }
            catch { return; }
            foreach (var s in snapshot)
            {
                if (s?.Hero == null) continue;
                try
                {
                    AwardContribMilestones(s, includeAbsorb: !s.Died);
                    BannerlordLinkModule.Log(
                        $"[CONTRIB итог] @{s.Username}: киллы={s.Kills} урон={s.DamageDealt} " +
                        $"поглощено={s.DamageAbsorbed}{(s.Died ? " (СГОРЕЛО — умирал)" : "")} " +
                        $"очки={s.ContribPoints} вех={s.MilestoneIdx} заработал={s.GoldEarned}💰");
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log($"[CONTRIB итог] @{s?.Username} crashed: {ex.Message}");
                }
            }
        }

        public override void OnMissionTick(float dt)
        {
            base.OnMissionTick(dt);
            try
            {
                if (Mission == null) return;
                float now;
                try { now = Mission.CurrentTime; }
                catch { return; }

                // Stats push (existing).
                if (now >= _nextStatsPushAt && _participants.Count > 0)
                {
                    _nextStatsPushAt = now + STATS_PUSH_INTERVAL;
                    PushStatsSnapshot();
                    // 2026-07-21 — вехи по вкладу проверяем здесь, а не на каждый
                    // удар: очки растут от урона тоже, а хот-пас блоу трогать нельзя.
                    // Поглощение в ход НЕ идёт — оно считается в конце боя выжившим.
                    foreach (var st in _participants.Values)
                    {
                        try { AwardContribMilestones(st, includeAbsorb: false); }
                        catch { }
                    }
                }

                // Sprint 5.32 (BLT-parity M1) — passive HP regen tick.
                if (now >= _nextRegenAt && _participants.Count > 0)
                {
                    _nextRegenAt = now + REGEN_INTERVAL;
                    ApplyPassiveRegen(REGEN_INTERVAL);
                }

                // Sprint 5.32 CRASH FIX — drain pending reflects из DamageHookPatch.
                // Counter-blows откладываются queue'ом из RegisterBlow Prefix'а,
                // applies здесь — отдельный frame, fresh AttackCollisionData, no
                // shared ref → нет engine corruption.
                try
                {
                    BannerlordLink.Patches.DamageHookPatch.DrainPendingReflects();
                }
                catch (Exception drainEx)
                {
                    BannerlordLinkModule.Log(
                        $"[KillReward] DrainPendingReflects warn: {drainEx.Message}");
                }
                // Sprint 5.32 (LOG-2) — periodic regen summary. 10s interval.
                // Если viewer'и активно лечатся — counters > 0. Если нет —
                // counters=0 значит "behavior работает, регенерить некому
                // (все на cap'е или мёртвые)". Это лучше silent log absence.
                if (now >= _nextRegenStatsAt)
                {
                    _nextRegenStatsAt = now + REGEN_STATS_LOG_INTERVAL;
                    if (_regenHealedCount > 0)
                    {
                        BannerlordLinkModule.Log(
                            $"[M1-REGEN] last 10s: heals={_regenHealedCount} ticks " +
                            $"on {_participants.Count} participants, " +
                            $"+{_regenHpTotal:F0} HP total");
                    }
                    _regenHealedCount = 0;
                    _regenHpTotal = 0f;
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] OnMissionTick CRASHED: {ex.Message}");
            }
        }

        private void ApplyPassiveRegen(float seconds)
        {
            try
            {
                // Snapshot для безопасной iteration (collection может меняться mid-frame).
                List<BattleStats> snapshot;
                try { snapshot = _participants.Values.ToList(); }
                catch { return; }

                foreach (var s in snapshot)
                {
                    if (s == null || s.Hero == null) continue;        // retinue → skip
                    if (string.IsNullOrEmpty(s.Username)) continue;
                    var agent = s.Agent;
                    if (agent == null) continue;
                    bool active;
                    try { active = agent.IsActive(); }
                    catch { continue; }
                    if (!active) continue;
                    float hp, hpMax;
                    try { hp = agent.Health; hpMax = agent.HealthLimit; }
                    catch { continue; }
                    if (hp <= 0f || hp >= hpMax) continue;             // dead or at cap

                    // Lookup per-class rate.
                    float rate = DEFAULT_REGEN_PER_SEC;
                    try
                    {
                        var hc = BannerlordLink.Net.PowerCache.GetHeroClass(s.Username);
                        if (hc.HasValue && !string.IsNullOrEmpty(hc.Value.classKey)
                            && _classRegenPerSec.TryGetValue(hc.Value.classKey, out float r))
                        {
                            rate = r;
                        }
                    }
                    catch { }

                    float newHp = Math.Min(hpMax, hp + rate * seconds);
                    try
                    {
                        agent.Health = newHp;
                        // Sprint 5.32 (LOG-2) — counter для periodic dump.
                        _regenHealedCount++;
                        _regenHpTotal += (newHp - hp);
                    }
                    catch { }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward M1] regen pass crashed: {ex.Message}");
            }
        }

        protected override void OnEndMission()
        {
            base.OnEndMission();
            _instance = null;
            // 2026-07-21 — сначала добираем вехи по вкладу: выжившим засчитывается
            // поглощённый урон (умершим сгорает). Должно идти ДО participation,
            // чтобы итоговый лог [CONTRIB итог] показал честный заработок за бой.
            try { SettleAbsorbedContrib(); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] SettleAbsorbedContrib crashed: {ex.Message}");
            }
            // Sprint 5.27k: BLT-style participation reward (WinGold/WinXP /
            // LoseXP × 0.5). Применяется за факт участия независимо от kill'ов.
            try { ApplyParticipationRewards(); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] ApplyParticipationRewards crashed: {ex.Message}");
            }
            try { PushStatsSnapshot(isFinal: true); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] PushStatsSnapshot final crashed: {ex.Message}");
            }
            // Sprint 5.31 #45d — больше не нужен explicit Clear: CWT
            // (weak keys) auto-evict'ит мёртвые Agent'ы через GC. Старый
            // ConcurrentDictionary держал strong refs → нужен был Clear.
            // Restore heroes в их original parties (BLT pattern)
            try { RestorePartyMembership(); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] RestorePartyMembership crashed: {ex.Message}");
            }

            // Sprint 5.32 (BLT-parity H5) — post-mission state push для каждого
            // [BLink]-participants. Backend получит is_wounded=1 для viewer'ов
            // KO'd в Mission'е (engine ставит Hero.IsWounded=true при поражении
            // в бою БЕЗ death). Без этого UI badge "🟡 ранен" появлялся бы только
            // на следующий campaign day (DailyTickHero в MainCampaignBehavior).
            try
            {
                foreach (var s in _participants.Values)
                {
                    if (s == null || string.IsNullOrEmpty(s.Username)) continue;
                    Hero hero;
                    try { hero = BannerlordLink.Actions.HeroLookup.FindByUsername(s.Username); }
                    catch { continue; }
                    if (hero == null) continue;
                    HeroStateSyncSafe(hero);
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] post-mission state push (H5) failed: {ex.Message}");
            }
        }

        /// <summary>Push current participants snapshot для overlay.
        ///
        /// IMPORTANT: snapshot копия dict.Values ДО iteration — защита от
        /// `Collection was modified` (OnAgentBuild может вклиниться mid-frame).
        /// Wrapped в try/catch на каждом уровне чтобы не уронить game.</summary>
        private void PushStatsSnapshot(bool isFinal = false)
        {
            try
            {
                // Snapshot копия — устраняет race с OnAgentBuild.
                List<BattleStats> snapshot;
                try
                {
                    snapshot = _participants.Values.ToList();
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[KillReward] snapshot copy failed: {ex.Message}");
                    return;
                }

                var items = new List<object>();
                foreach (var s in snapshot)
                {
                    if (s == null || string.IsNullOrEmpty(s.Username)) continue;
                    int hp = 0, hpMax = 100;
                    bool alive = false;
                    string state = "killed";
                    bool isPlayerSide = s.IsPlayerSide;
                    try
                    {
                        if (s.Agent != null)
                        {
                            hp = (int)s.Agent.Health;
                            hpMax = (int)s.Agent.HealthLimit;
                            if (hpMax <= 0) hpMax = 100;
                            alive = s.Agent.IsActive() && hp > 0;
                            state = ComputeAgentState(s.Agent);
                            // Уточняем сторону, пока агент жив и её видно.
                            // Раньше здесь стояло `if (!isPlayerSide)` — та же
                            // защёлка, что и в OnAgentBuild: значение могло
                            // меняться только в одну сторону и намертво
                            // застревало на «свой».
                            if (TryComputeIsPlayerSide(s.Agent, out bool liveSide))
                            {
                                isPlayerSide = liveSide;
                                s.IsPlayerSide = liveSide;
                            }
                        }
                    }
                    catch (Exception ex)
                    {
                        // Per-participant errors не должны валить весь snapshot
                        BannerlordLinkModule.Log(
                            $"[KillReward] snapshot @{s.Username} read error: {ex.Message}");
                    }
                    items.Add(new
                    {
                        username = s.Username,
                        hp = hp,
                        hp_max = hpMax,
                        alive = alive,
                        state = state,
                        is_player_side = isPlayerSide,
                        kills = s.Kills,
                        retinue_kills = s.RetinueKills,
                        gold_earned = s.GoldEarned,
                        xp_earned = s.XpEarned,
                    });
                }
                if (items.Count == 0 && !isFinal) return;

                string json;
                try
                {
                    json = JsonConvert.SerializeObject(new
                    {
                        final = isFinal,
                        participants = items,
                    });
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[KillReward] JSON serialize failed: {ex.Message}");
                    return;
                }
                Task.Run(async () =>
                {
                    try
                    {
                        await BannerlordLinkModule.Backend.PostEventAsync(
                            "bannerlord", "battle.stats_snapshot", json);
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[KillReward] HTTP push failed: {ex.Message}");
                    }
                });
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] PushStatsSnapshot CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }

        private static SkillObject ResolveSkillFromBlow(KillingBlow blow)
        {
            try
            {
                int wcInt = blow.WeaponClass;
                WeaponClass wc = (WeaponClass)wcInt;
                switch (wc)
                {
                    case WeaponClass.OneHandedSword:
                    case WeaponClass.OneHandedAxe:
                    case WeaponClass.Mace:
                    case WeaponClass.Dagger:
                        return DefaultSkills.OneHanded;
                    case WeaponClass.TwoHandedSword:
                    case WeaponClass.TwoHandedAxe:
                    case WeaponClass.TwoHandedMace:
                        return DefaultSkills.TwoHanded;
                    case WeaponClass.OneHandedPolearm:
                    case WeaponClass.TwoHandedPolearm:
                    case WeaponClass.LowGripPolearm:
                        return DefaultSkills.Polearm;
                    case WeaponClass.Bow:
                    case WeaponClass.Arrow:
                        return DefaultSkills.Bow;
                    case WeaponClass.Crossbow:
                    case WeaponClass.Bolt:
                        return DefaultSkills.Crossbow;
                    case WeaponClass.Javelin:
                    case WeaponClass.ThrowingAxe:
                    case WeaponClass.ThrowingKnife:
                    case WeaponClass.Stone:
                        return DefaultSkills.Throwing;
                    default:
                        return DefaultSkills.Athletics;
                }
            }
            catch
            {
                return DefaultSkills.Athletics;
            }
        }

        private static void HeroStateSyncSafe(Hero hero)
        {
            try { BannerlordLink.Util.HeroStateSync.Push(hero); }
            catch { }
        }
    }
}
