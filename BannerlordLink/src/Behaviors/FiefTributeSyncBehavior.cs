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
    /// (канонический owner-income движка через ClanFinanceModel/SettlementTaxModel):
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
                var fin = Campaign.Current.Models.ClanFinanceModel;
                if (s.IsVillage && s.Village != null)
                {
                    fiefType = "village";
                    var vclan = s.OwnerClan;
                    if (vclan == null) return 0;
                    return (int)fin.CalculateVillageIncome(vclan, s.Village, false);
                }
                if (s.Town != null)
                {
                    fiefType = s.IsCastle ? "castle" : "town";
                    var town = s.Town;
                    double tax = Campaign.Current.Models.SettlementTaxModel
                        .CalculateTownTax(town, false).ResultNumber;
                    var clan = s.OwnerClan;
                    if (clan == null) return (int)tax;   // тарифы/проекты требуют clan
                    // 2026-06-01 — нетто-доход владельца (канонический engine-расчёт):
                    // налог + тарифы + проекты − жалование гарнизона. Bound-villages НЕ
                    // добавляем — они отдельные фьефы и отчитываются сами (иначе двойной счёт).
                    double income = tax
                        + fin.CalculateTownIncomeFromTariffs(clan, town, false).ResultNumber
                        + fin.CalculateTownIncomeFromProjects(town)
                        - (town.GarrisonParty?.TotalWage ?? 0);
                    return (int)income;
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

        /// <summary>2026-06-02 (PROPERTIES-MIRROR) — полный список фьефов,
        /// которыми [BLink]-герои владеют СЕЙЧАС (для snapshot-зеркала на backend).
        /// В отличие от OnDailyTick — БЕЗ income-фильтра: владение есть = строка
        /// есть, даже при нулевом/отриц. дневном доходе.</summary>
        public static System.Collections.Generic.List<object> BuildFiefSnapshot()
        {
            var items = new System.Collections.Generic.List<object>();
            try
            {
                if (Campaign.Current == null) return items;
                foreach (var s in Settlement.All)
                {
                    if (s == null) continue;
                    if (!IsOwnedByBLink(s, out var ownerLogin)) continue;
                    string fiefType = s.IsVillage ? "village"
                                    : s.IsCastle ? "castle"
                                    : s.Town != null ? "town"
                                    : "fief";
                    items.Add(new
                    {
                        owner     = ownerLogin,
                        fief_id   = s.StringId,
                        fief_name = s.Name?.ToString() ?? s.StringId,
                        fief_type = fiefType,
                    });
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[fief-sync] BuildFiefSnapshot crash: {ex.Message}");
            }
            return items;
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
