using System;
using System.Collections.Generic;
using BannerlordLink.Util;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// Backlog #1 (BLT-RC22 parity, C.5 KingdomTaxBehavior) — kingdom tax.
    ///
    /// Концепт (адаптация BLT KingdomTaxBehavior + GoldIncomeBehavior collection):
    ///   Король (RulingClan.Leader) — если это adopted viewer — может задать
    ///   налоговую ставку 0-100% для своего королевства. Раз в день каждый
    ///   вассальный клан королевства (кроме самого ruling clan) платит rate% от
    ///   дневной прибыли в казну короля.
    ///
    /// BLT rules сохранены:
    ///   - rate clamp 0..1
    ///   - НЕ облагаем ruling clan
    ///   - collect только если король = adopted viewer (иначе налог уходит в
    ///     никуда — engine AI king не наш игрок)
    ///
    /// Отличие от BLT: BLT таксит fiefIncome (внутри GoldIncomeBehavior). У нас
    /// нет перехвата fief-income distribution, поэтому базой берём дневной
    /// gold-delta лидера клана (net profit) — тот же робастный приём, что в
    /// VassalAutoFollowBehavior.OnDailyTickClan (без зависимости от
    /// ClanFinanceModel API, который дрейфует по версиям).
    ///
    /// Storage authority: ставки живут ЗДЕСЬ (SyncData), мод — источник истины
    /// (см. ARCH_DATA_OWNERSHIP.md). Backend кэширует для отображения.
    ///
    /// Overlap note: вассальные sub-кланы (VassalAutoFollowBehavior) обычно
    /// Kingdom=null (independent) → не попадают под kingdom tax. Если клан всё
    /// же и vassal-sponsored, и в taxed kingdom — обе системы скимят свой
    /// gold-delta независимо (rare double-dip, приемлемо для MVP).
    /// </summary>
    public class KingdomTaxBehavior : CampaignBehaviorBase
    {
        public static KingdomTaxBehavior Current { get; private set; }

        // kingdom_StringId → tax rate (0.0–1.0)
        private Dictionary<string, float> _kingdomTaxRates = new Dictionary<string, float>();
        // taxed_clan_StringId → last observed leader gold (для дневного delta)
        private Dictionary<string, int> _clanLastGold = new Dictionary<string, int>();

        // Оставляем вассалу буфер — не банкротим налогом.
        private const int MIN_CLAN_BUFFER = 500;

        public KingdomTaxBehavior()
        {
            Current = this;
        }

        public override void RegisterEvents()
        {
            CampaignEvents.DailyTickClanEvent.AddNonSerializedListener(this, OnDailyTickClan);
            CampaignEvents.OnClanDestroyedEvent.AddNonSerializedListener(this, OnClanDestroyed);
        }

        public override void SyncData(IDataStore dataStore)
        {
            // AUDIT fix #3 pattern — обёрнуто в try/catch: сбой (де)сериализации
            // не должен ронять save/load pipeline.
            try { dataStore.SyncData("BLink_KingdomTaxRates", ref _kingdomTaxRates); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[KingdomTax] SyncData rates failed: {ex.Message}");
            }
            if (_kingdomTaxRates == null) _kingdomTaxRates = new Dictionary<string, float>();

            try { dataStore.SyncData("BLink_KingdomTaxLastGold", ref _clanLastGold); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[KingdomTax] SyncData lastGold failed: {ex.Message}");
            }
            if (_clanLastGold == null) _clanLastGold = new Dictionary<string, int>();
        }

        // ─── Public API (mirror BLT) ───────────────────────────────────────────────

        /// <summary>Set tax rate 0.0–1.0 для королевства. Clamp как в BLT.</summary>
        public void SetKingdomTaxRate(Kingdom kingdom, float taxRate)
        {
            if (kingdom == null) return;
            taxRate = Math.Max(0f, Math.Min(1f, taxRate));
            _kingdomTaxRates[kingdom.StringId] = taxRate;
            BannerlordLinkModule.Log(
                $"[KingdomTax] {kingdom.Name} rate set → {taxRate * 100f:F0}%");
        }

        /// <summary>Get tax rate (0.0 если не задано).</summary>
        public float GetKingdomTaxRate(Kingdom kingdom)
        {
            if (kingdom == null) return 0f;
            return _kingdomTaxRates.TryGetValue(kingdom.StringId, out float r) ? r : 0f;
        }

        // ─── Daily collection ───────────────────────────────────────────────────────

        private void OnDailyTickClan(Clan clan)
        {
            try
            {
                if (clan == null || clan.IsEliminated) return;
                Kingdom kingdom = clan.Kingdom;
                if (kingdom == null) return;

                Hero clanLeader = clan.Leader;
                if (clanLeader == null || !clanLeader.IsAlive) return;

                int cur = clanLeader.Gold;

                // First observation — baseline only.
                if (!_clanLastGold.TryGetValue(clan.StringId, out int prev))
                {
                    _clanLastGold[clan.StringId] = cur;
                    return;
                }
                int delta = cur - prev;
                _clanLastGold[clan.StringId] = cur;  // update baseline upfront

                float rate = GetKingdomTaxRate(kingdom);
                if (rate <= 0f) return;                       // no tax set
                if (clan == kingdom.RulingClan) return;       // BLT: don't tax ruler
                if (delta <= 0) return;                       // no profit → no tax

                // King must be an adopted viewer — иначе налог некому платить.
                Hero king = kingdom.RulingClan?.Leader;
                if (king == null || !king.IsAlive) return;
                if (king == clanLeader) return;               // safety
                string kingUser = HeroNaming.ExtractUsername(king.Name?.ToString());
                if (string.IsNullOrEmpty(kingUser)) return;   // AI king → skip

                int tax = (int)(delta * rate);
                if (tax <= 0) return;

                // Cap: keep MIN_CLAN_BUFFER в кармане вассала.
                int affordable = Math.Max(0, cur - MIN_CLAN_BUFFER);
                tax = Math.Min(tax, affordable);
                if (tax <= 0) return;

                GiveGoldAction.ApplyBetweenCharacters(clanLeader, king, tax, true);
                _clanLastGold[clan.StringId] = clanLeader.Gold;  // re-sync after transfer

                BannerlordLinkModule.Log(
                    $"[KingdomTax] {clan.Name} → king @{kingUser} ({kingdom.Name}): " +
                    $"{tax} denars ({rate * 100f:F0}% от дневной прибыли {delta})");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[KingdomTax] OnDailyTickClan error: {ex.Message}");
            }
        }

        private void OnClanDestroyed(Clan destroyedClan)
        {
            if (destroyedClan == null) return;
            try { _clanLastGold.Remove(destroyedClan.StringId); }
            catch { /* defensive */ }
        }
    }
}
