using System;
using BannerlordLink.Util;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Settlements;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// Sprint 5.33 (BLT-parity FIEF) — Daily fief tribute REPORT.
    ///
    /// 2026-06-01 — модель дохода переписана на РЕАЛЬНЫЙ налог владельца
    /// (BLT-parity ClanManagement.cs:826 / CampaignInfo.cs:414):
    ///   town/castle → SettlementTaxModel.CalculateTownTax(town, false).ResultNumber
    ///   village     → ClanFinanceModel.CalculateVillageIncome(clan, village, false)
    /// Раньше брали diff Town.Gold — но казна города ≠ доход владельца и скачет
    /// ≤0, поэтому города/замки НИКОГДА не появлялись в «Моих владениях»
    /// (только деревни по Village.Hearth×10 — слабый прокси). Теперь — прямой
    /// дневной доход, без снапшотов/diff.
    ///
    /// Деньги владелец получает движком (native tax/tariff → Hero.Gold). Это
    /// событие — ТОЛЬКО отчёт для UI ("Заработано"); крустики НЕ начисляются
    /// (credit_fief_tribute → 0, DECOUPLE-1).
    ///
    /// OnDailyTick: для каждого fief, owned by adopted [BLink] hero
    /// (Settlement.OwnerClan.Leader), пушим дневной доход hero.fief_tribute_sync.
    /// </summary>
    public class FiefTributeSyncBehavior : CampaignBehaviorBase
    {
        public override void RegisterEvents()
        {
            CampaignEvents.DailyTickEvent.AddNonSerializedListener(this, OnDailyTick);
        }

        public override void SyncData(IDataStore dataStore)
        {
            // Stateless — доход считается напрямую по модели налогов каждый день.
        }

        private void OnDailyTick()
        {
            try
            {
                int synced = 0;
                foreach (var s in Settlement.All)
                {
                    if (s == null) continue;
                    if (!IsOwnedByBLink(s, out var ownerLogin)) continue;
                    int income = ComputeDailyIncome(s, out var fiefType);
                    if (income <= 0) continue;   // backend и так скипает net_dinars<=0
                    PushSync(s, ownerLogin, fiefType, income);
                    synced++;
                }
                if (synced > 0)
                    BannerlordLinkModule.Log(
                        $"[fief-sync] OnDailyTick pushed {synced} fief tributes (tax-model)");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[fief-sync] OnDailyTick crash: {ex.Message}");
            }
        }

        // ── Helpers ────────────────────────────────────────────────────────────

        /// <summary>Реальный дневной доход владельца фьефа (BLT-parity).
        /// town/castle → налог города; village → village income клана.</summary>
        private static int ComputeDailyIncome(Settlement s, out string fiefType)
        {
            fiefType = "fief";
            try
            {
                if (s.IsVillage && s.Village != null)
                {
                    fiefType = "village";
                    var clan = s.OwnerClan;
                    if (clan == null) return 0;
                    return (int)Campaign.Current.Models.ClanFinanceModel
                        .CalculateVillageIncome(clan, s.Village, false);
                }
                if (s.Town != null)
                {
                    fiefType = s.IsCastle ? "castle" : "town";
                    return (int)Campaign.Current.Models.SettlementTaxModel
                        .CalculateTownTax(s.Town, false).ResultNumber;
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[fief-sync] income calc warn {s?.StringId}: {ex.Message}");
            }
            return 0;
        }

        private static bool IsOwnedByBLink(Settlement s, out string ownerLogin)
        {
            ownerLogin = null;
            try
            {
                Hero owner = s.OwnerClan?.Leader;
                if (owner?.Name == null) return false;
                string nm = owner.Name.ToString();
                if (!HeroNaming.IsAdopted(nm)) return false;
                ownerLogin = HeroNaming.ExtractUsername(nm)?.ToLowerInvariant();
                return !string.IsNullOrEmpty(ownerLogin);
            }
            catch { return false; }
        }

        private static void PushSync(Settlement s, string ownerLogin, string fiefType, int netDinars)
        {
            try
            {
                string evtData = Newtonsoft.Json.JsonConvert.SerializeObject(new
                {
                    owner        = ownerLogin,
                    fief_id      = s.StringId,
                    fief_name    = s.Name?.ToString() ?? s.StringId,
                    fief_type    = fiefType,
                    net_dinars   = netDinars,
                });
                System.Threading.Tasks.Task.Run(async () =>
                    await BannerlordLinkModule.Backend.PostEventAsync(
                        "bannerlord", "hero.fief_tribute_sync", evtData));
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[fief-sync] push crash: {ex.Message}");
            }
        }
    }
}
