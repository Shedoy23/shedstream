using System;
using System.Collections.Generic;
using System.Linq;
using BannerlordLink.Util;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// 2026-05-29 Stage 7 (BLT-RC22 pattern) — auto-following vassal clans.
    /// Pattern из BLT VassalBehavior.cs (Section C.20 audit).
    ///
    /// Concept:
    ///   Когда viewer создаёт vassal sub-clan (через hero.create_vassal_clan
    ///   action → CreateVassalClanHandler), мы регистрируем связь
    ///   "vassal_clan.StringId → masterUsername". Master = viewer login кто
    ///   sponsor'ил vassal creation.
    ///
    ///   Если master clan меняет kingdom (joins/leaves/declares war) → ВСЕ его
    ///   vassal clans автоматически делают то же самое. Без этого vassal'ы
    ///   накапливают divergence (AI moves их independently → они в чужом
    ///   kingdom, war'ят против master'а и т.п.).
    ///
    /// Events handled:
    ///   - OnClanChangedKingdom — master moves → vassals follow
    ///   - WarDeclared — master at war → vassals join war
    ///   - MakePeace — master peace → vassals peace
    ///   - OnClanDestroyed — cleanup map
    ///
    /// Resolution:
    ///   Master clan resolved DYNAMICALLY каждый event'ом (не stored как
    ///   StringId). Lookup: vassalToMaster[vassalStringId] → masterUsername →
    ///   find Hero с "[BLink] masterUsername" name → return their Clan.
    ///
    ///   Reasoning: master clan'а StringId может changeить (clan rebrands,
    ///   succession, etc.). Username — stable identity from backend perspective.
    ///
    /// Persistence:
    ///   _vassalToMaster persisted в save через standard SyncData. После save
    ///   load — мапа доступна сразу, нет нужды в HTTP bootstrap.
    ///
    /// Limitations:
    ///   - Если master clan'а leader умер (без heir activation) → ResolveMaster
    ///     возвращает null → no auto-follow (как BLT — graceful no-op).
    ///   - AI kingdom shuffles между ticks: возможен race condition если
    ///     OnClanChangedKingdom fires до нашего follow → vassal в обоих
    ///     kingdom'ах temporary. Engine eventually consistent.
    /// </summary>
    public class VassalAutoFollowBehavior : CampaignBehaviorBase
    {
        public static VassalAutoFollowBehavior Current { get; private set; }

        // vassal_clan_StringId → master viewer login (lowercase)
        private Dictionary<string, string> _vassalToMaster = new Dictionary<string, string>();

        // 2026-05-29 (VAS income share) — vassal_clan_StringId → last observed
        // leader gold. Дневной delta (net profit) × INCOME_SHARE_PCT транзитом
        // master'у. Persisted чтобы baseline переживал save/load.
        private Dictionary<string, int> _vassalLastGold = new Dictionary<string, int>();

        // 25% дневной ЧИСТОЙ прибыли вассала (gold delta day-over-day) → master
        // hero gold. Совпадает с backend default income_share_pct (таблица
        // bannerlord_vassals). Берём net gold-delta, а не gross income —
        // справедливее: skim'им только реальную прибыль, и если вассал
        // потратился (delta ≤ 0) — ничего не уводим.
        private const float INCOME_SHARE_PCT = 25f;
        // Буфер: всегда оставляем вассалу минимум, чтобы не банкротить.
        private const int MIN_VASSAL_BUFFER = 500;

        public VassalAutoFollowBehavior()
        {
            Current = this;
        }

        public override void RegisterEvents()
        {
            CampaignEvents.OnClanChangedKingdomEvent.AddNonSerializedListener(
                this, OnClanChangedKingdom);
            CampaignEvents.WarDeclared.AddNonSerializedListener(
                this, OnWarDeclared);
            CampaignEvents.MakePeace.AddNonSerializedListener(
                this, OnMakePeace);
            CampaignEvents.OnClanDestroyedEvent.AddNonSerializedListener(
                this, OnClanDestroyed);
            // 2026-05-29 (VAS income share) — daily 25% net-profit skim.
            CampaignEvents.DailyTickClanEvent.AddNonSerializedListener(
                this, OnDailyTickClan);
        }

        public override void SyncData(IDataStore dataStore)
        {
            // AUDIT 2026-05-29 (fix #3): каждый SyncData обёрнут в try/catch.
            // Если движок не сможет (де)сериализовать Dictionary — мы НЕ роняем
            // save/load pipeline (теряем persistence этой мапы, но кампания не
            // корраптится). Pattern из HeroIdentityBehavior.
            try
            {
                dataStore.SyncData("BLink_VassalToMaster", ref _vassalToMaster);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[VassalAutoFollow] SyncData VassalToMaster failed: {ex.Message}");
            }
            if (_vassalToMaster == null) _vassalToMaster = new Dictionary<string, string>();

            try
            {
                dataStore.SyncData("BLink_VassalLastGold", ref _vassalLastGold);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[VassalAutoFollow] SyncData VassalLastGold failed: {ex.Message}");
            }
            if (_vassalLastGold == null) _vassalLastGold = new Dictionary<string, int>();
        }

        // ─── Public registration API ──────────────────────────────────────────────

        /// <summary>Called from CreateVassalClanHandler после успешного
        /// CreateClan + ChangeClanLeader. Persists в save через next SyncData.</summary>
        public void RegisterVassal(Clan vassalClan, string masterUsername)
        {
            if (vassalClan == null || string.IsNullOrEmpty(masterUsername)) return;
            string mu = masterUsername.Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(mu)) return;

            _vassalToMaster[vassalClan.StringId] = mu;
            BannerlordLinkModule.Log(
                $"[VassalAutoFollow] Registered: vassal={vassalClan.Name} ({vassalClan.StringId}) " +
                $"→ master=@{mu}");
        }

        /// <summary>True если clan зарегистрирован как vassal любого master'а.</summary>
        public bool IsVassal(Clan clan)
        {
            return clan != null && _vassalToMaster.ContainsKey(clan.StringId);
        }

        // ─── Resolution helpers ───────────────────────────────────────────────────

        /// <summary>Find Clan с leader'ом имеющим "[BLink] masterUsername" name.
        /// Returns null если master hero не найден / умер / не имеет clan'а.</summary>
        private static Clan ResolveMasterClan(string masterUsername)
        {
            if (string.IsNullOrEmpty(masterUsername)) return null;

            try
            {
                foreach (var hero in Hero.AllAliveHeroes)
                {
                    if (hero?.Name == null) continue;
                    string extracted = HeroNaming.ExtractUsername(hero.Name.ToString());
                    if (string.IsNullOrEmpty(extracted)) continue;
                    if (extracted.Equals(masterUsername, StringComparison.OrdinalIgnoreCase))
                    {
                        return hero.Clan;
                    }
                }
            }
            catch { /* defensive */ }
            return null;
        }

        /// <summary>Find все vassal clans которые принадлежат данному master clan.
        /// Если masterClan == null → empty list.</summary>
        private List<Clan> GetVassalsOfMaster(Clan masterClan)
        {
            var result = new List<Clan>();
            if (masterClan == null) return result;

            // Resolve master username from leader's name.
            string masterUser = HeroNaming.ExtractUsername(masterClan.Leader?.Name?.ToString());
            if (string.IsNullOrEmpty(masterUser)) return result;
            masterUser = masterUser.ToLowerInvariant();

            foreach (var kvp in _vassalToMaster)
            {
                if (!string.Equals(kvp.Value, masterUser, StringComparison.OrdinalIgnoreCase))
                    continue;
                var c = Clan.All.FirstOrDefault(x => x.StringId == kvp.Key);
                if (c != null && !c.IsEliminated) result.Add(c);
            }
            return result;
        }

        // ─── Event handlers ───────────────────────────────────────────────────────

        private void OnClanChangedKingdom(
            Clan clan, Kingdom oldKingdom, Kingdom newKingdom,
            ChangeKingdomAction.ChangeKingdomActionDetail detail, bool showNotification)
        {
            try
            {
                if (clan == null) return;

                // Branch 1: this clan IS a master with vassals → vassals follow.
                var vassals = GetVassalsOfMaster(clan);
                foreach (var vassal in vassals)
                {
                    try
                    {
                        if (vassal.Kingdom == newKingdom)
                        {
                            // Already correct — nothing to do.
                            continue;
                        }

                        // Force vassal to follow master kingdom.
                        if (vassal.Kingdom != null)
                        {
                            try { vassal.ClanLeaveKingdom(true); }
                            catch (Exception lex)
                            {
                                BannerlordLinkModule.Log(
                                    $"[VassalAutoFollow] {vassal.Name} leave warn: {lex.Message}");
                            }
                        }
                        if (newKingdom != null)
                        {
                            try
                            {
                                ChangeKingdomAction.ApplyByJoinToKingdom(
                                    vassal, newKingdom, default, false);
                                BannerlordLinkModule.Log(
                                    $"[VassalAutoFollow] {vassal.Name} → joined {newKingdom.Name} " +
                                    $"(following master {clan.Name})");
                            }
                            catch (Exception jex)
                            {
                                BannerlordLinkModule.Log(
                                    $"[VassalAutoFollow] {vassal.Name} join warn: {jex.Message}");
                            }
                        }
                        else
                        {
                            // Master became independent — vassal also independent.
                            BannerlordLinkModule.Log(
                                $"[VassalAutoFollow] {vassal.Name} → independent " +
                                $"(master {clan.Name} also independent)");
                        }
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[VassalAutoFollow] vassal {vassal.Name} follow error: {ex.Message}");
                    }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[VassalAutoFollow] OnClanChangedKingdom error: {ex.Message}");
            }
        }

        private void OnWarDeclared(
            IFaction faction1, IFaction faction2,
            DeclareWarAction.DeclareWarDetail detail)
        {
            try
            {
                // If either faction is a clan with vassals → vassals also at war.
                TryFollowWar(faction1, faction2);
                TryFollowWar(faction2, faction1);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[VassalAutoFollow] OnWarDeclared error: {ex.Message}");
            }
        }

        private void TryFollowWar(IFaction source, IFaction target)
        {
            if (!(source is Clan clan)) return;
            var vassals = GetVassalsOfMaster(clan);
            foreach (var vassal in vassals)
            {
                try
                {
                    if (vassal.IsAtWarWith(target)) continue;
                    DeclareWarAction.ApplyByDefault(vassal, target);
                    BannerlordLinkModule.Log(
                        $"[VassalAutoFollow] {vassal.Name} joined war against {target.Name}");
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[VassalAutoFollow] {vassal.Name} war follow warn: {ex.Message}");
                }
            }
        }

        private void OnMakePeace(
            IFaction faction1, IFaction faction2,
            MakePeaceAction.MakePeaceDetail detail)
        {
            try
            {
                TryFollowPeace(faction1, faction2);
                TryFollowPeace(faction2, faction1);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[VassalAutoFollow] OnMakePeace error: {ex.Message}");
            }
        }

        private void TryFollowPeace(IFaction source, IFaction target)
        {
            if (!(source is Clan clan)) return;
            var vassals = GetVassalsOfMaster(clan);
            foreach (var vassal in vassals)
            {
                try
                {
                    if (!vassal.IsAtWarWith(target)) continue;
                    MakePeaceAction.Apply(vassal, target);
                    BannerlordLinkModule.Log(
                        $"[VassalAutoFollow] {vassal.Name} made peace with {target.Name}");
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[VassalAutoFollow] {vassal.Name} peace follow warn: {ex.Message}");
                }
            }
        }

        // ─── Income share (daily 25% net-profit skim) ──────────────────────────────

        /// <summary>2026-05-29 (VAS income share) — раз в день: 25% дневной
        /// ЧИСТОЙ прибыли вассала (прирост Leader.Gold за сутки) → gold героя-
        /// мастера. Backend column income_share_pct наконец реализован in-game.
        ///
        /// Net-profit (а не gross income): если вассал потратился (delta ≤ 0) →
        /// skip. Буфер MIN_VASSAL_BUFFER чтобы не увести вассала в минус.
        /// Master мёртв/исчез → no-op (baseline всё равно обновляем, чтобы не
        /// копить «долг» за период когда master отсутствовал).</summary>
        private void OnDailyTickClan(Clan clan)
        {
            try
            {
                if (clan == null || clan.IsEliminated) return;
                if (!_vassalToMaster.TryGetValue(clan.StringId, out var masterUser)) return;

                Hero vassalLeader = clan.Leader;
                if (vassalLeader == null || !vassalLeader.IsAlive) return;

                int cur = vassalLeader.Gold;

                // First observation — establish baseline, no skim yet.
                if (!_vassalLastGold.TryGetValue(clan.StringId, out int prev))
                {
                    _vassalLastGold[clan.StringId] = cur;
                    return;
                }

                int delta = cur - prev;
                // Update baseline upfront — covers spend-down + no-master cases.
                _vassalLastGold[clan.StringId] = cur;
                if (delta <= 0) return;  // нет прибыли → нечего делить

                Clan masterClan = ResolveMasterClan(masterUser);
                Hero masterHero = masterClan?.Leader;
                if (masterHero == null || !masterHero.IsAlive) return;  // master gone
                if (masterHero == vassalLeader) return;                 // safety (self)

                int share = (int)(delta * INCOME_SHARE_PCT / 100f);
                if (share <= 0) return;

                // Cap: keep MIN_VASSAL_BUFFER в кармане вассала.
                int affordable = Math.Max(0, cur - MIN_VASSAL_BUFFER);
                share = Math.Min(share, affordable);
                if (share <= 0) return;

                GiveGoldAction.ApplyBetweenCharacters(vassalLeader, masterHero, share, true);
                // Re-sync baseline после трансфера (Gold изменился).
                _vassalLastGold[clan.StringId] = vassalLeader.Gold;

                BannerlordLinkModule.Log(
                    $"[VassalIncome] {clan.Name} → master @{masterUser}: {share} denars " +
                    $"(25% от дневной прибыли {delta})");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[VassalIncome] OnDailyTickClan error: {ex.Message}");
            }
        }

        private void OnClanDestroyed(Clan destroyedClan)
        {
            try
            {
                if (destroyedClan == null) return;

                // If destroyed clan IS a vassal — remove from map.
                if (_vassalToMaster.ContainsKey(destroyedClan.StringId))
                {
                    _vassalToMaster.Remove(destroyedClan.StringId);
                    _vassalLastGold.Remove(destroyedClan.StringId);
                    BannerlordLinkModule.Log(
                        $"[VassalAutoFollow] Removed destroyed vassal {destroyedClan.Name}");
                }

                // If destroyed clan WAS a master — remove all its vassal entries
                // (they become orphans, but mapping entry stale).
                string destroyedUser = HeroNaming.ExtractUsername(
                    destroyedClan.Leader?.Name?.ToString());
                if (!string.IsNullOrEmpty(destroyedUser))
                {
                    destroyedUser = destroyedUser.ToLowerInvariant();
                    var toRemove = _vassalToMaster
                        .Where(kv => string.Equals(kv.Value, destroyedUser,
                            StringComparison.OrdinalIgnoreCase))
                        .Select(kv => kv.Key)
                        .ToList();
                    foreach (var key in toRemove)
                    {
                        _vassalToMaster.Remove(key);
                        _vassalLastGold.Remove(key);
                    }
                    if (toRemove.Count > 0)
                    {
                        BannerlordLinkModule.Log(
                            $"[VassalAutoFollow] Orphaned {toRemove.Count} vassals " +
                            $"(master @{destroyedUser} destroyed)");
                    }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[VassalAutoFollow] OnClanDestroyed error: {ex.Message}");
            }
        }
    }
}
