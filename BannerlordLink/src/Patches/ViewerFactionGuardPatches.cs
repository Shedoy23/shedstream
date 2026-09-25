using System.Collections;
using System.Linq;
using System.Reflection;
using BannerlordLink.Behaviors;
using BannerlordLink.Util;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.CampaignBehaviors;
using TaleWorlds.CampaignSystem.GameComponents;
using TaleWorlds.CampaignSystem.Party;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// Скрытые правила игры против героев зрителей (разбор 25.09.2026, владелец:
    /// «делай все три»). Каждое — только для героев и кланов зрителей; остальной
    /// мир живёт по ванили, смерть в бою и от старости остаётся настоящей.
    /// Клан зрителя: лидер или любой живой герой — зритель, либо это вассальный
    /// клан зрителя (VassalAutoFollowBehavior).
    /// </summary>
    internal static class ViewerClanGuard
    {
        internal static bool IsViewerClan(Clan clan)
        {
            if (clan == null) return false;
            if (HeroNaming.IsAdopted(clan.Leader)) return true;
            if (clan.Heroes != null && clan.Heroes.Any(h => h != null && h.IsAlive && HeroNaming.IsAdopted(h))) return true;
            return VassalAutoFollowBehavior.Current?.IsVassal(clan) == true;
        }

        internal static bool IsViewerSide(Hero hero)
            => hero != null && (HeroNaming.IsAdopted(hero) || IsViewerClan(hero.Clan));
    }

    /// <summary>
    /// 1. Клан без королевства и без владений игра распускает через 28 игровых
    /// дней (FactionDiscontinuationCampaignBehavior: таймер при выходе из
    /// королевства, его распаде или потере последнего владения) → DestroyClanAction
    /// → ApplyByRemove всех героев. С автопилотом это 10–15 минут; вероятно, так
    /// погиб fikoos418 24.09. Клан зрителя не распускаем и снимаем его с таймера.
    /// </summary>
    [HarmonyPatch(typeof(FactionDiscontinuationCampaignBehavior), "DiscontinueClan")]
    internal static class ViewerClanDiscontinuationPatch
    {
        [HarmonyPrefix]
        public static bool Prefix(object __instance, Clan clan)
        {
            if (!ViewerClanGuard.IsViewerClan(clan)) return true;
            try
            {
                var timers = __instance?.GetType()
                    .GetField("_independentClans", BindingFlags.Instance | BindingFlags.NonPublic)
                    ?.GetValue(__instance) as IDictionary;
                timers?.Remove(clan);
            }
            catch { }
            BannerlordLinkModule.Log($"[ViewerGuard] BLOCKED: роспуск клана зрителя '{clan.Name}' (28 дней без королевства и владений)");
            return false;
        }
    }

    /// <summary>
    /// 2. Игра сама женит лордов (RomanceCampaignBehavior.CheckNpcMarriages) и
    /// переводит не-лидера в клан супруга. 25.09 dssardg так ушёл из клана, за
    /// вступление в который заплатил 50 000💰. Свадьба по заказу зрителя
    /// (MarryHandler) идёт мимо этой модели и не затрагивается.
    /// </summary>
    [HarmonyPatch(typeof(DefaultMarriageModel), nameof(DefaultMarriageModel.NpcCoupleMarriageChance))]
    internal static class ViewerNpcMarriagePatch
    {
        [HarmonyPostfix]
        public static void Postfix(Hero firstHero, Hero secondHero, ref float __result)
        {
            if (__result > 0f && (ViewerClanGuard.IsViewerSide(firstHero) || ViewerClanGuard.IsViewerSide(secondHero)))
                __result = 0f;
        }
    }

    /// <summary>
    /// 3. При смене правителя игра переодевает старого и нового правителя по
    /// шаблону (NPCEquipmentsCampaignBehavior.OnRulingClanChanged) — перековка и
    /// купленное пропадают. Если правитель (новый или старый) — зритель, не трогаем.
    /// </summary>
    [HarmonyPatch(typeof(NPCEquipmentsCampaignBehavior), "OnRulingClanChanged")]
    internal static class ViewerRulerEquipmentPatch
    {
        [HarmonyPrefix]
        public static bool Prefix(Kingdom kingdom, Clan oldRulingClan)
        {
            if (!HeroNaming.IsAdopted(kingdom?.Leader) && !HeroNaming.IsAdopted(oldRulingClan?.Leader)) return true;
            BannerlordLinkModule.Log($"[ViewerGuard] BLOCKED: переодевание правителя при смене власти в '{kingdom?.Name}'");
            return false;
        }
    }

    /// <summary>
    /// 4. Отряд лорда, заходя в город, распродаёт весь свой инвентарь, кроме еды
    /// (PartiesSellLootCampaignBehavior.OnSettlementEntered) по цене скупки. У
    /// зрителя со своим отрядом туда ложатся покупки магазина (цена ×10) и
    /// снятое снаряжение, в том числе перекованное: 25.09 igotpaws купил арбалет
    /// за 46 190💰 — вещь пропала, пришла копеечная выручка. Отряд, которым
    /// командует зритель, в городах не распродаём.
    /// </summary>
    [HarmonyPatch(typeof(PartiesSellLootCampaignBehavior), nameof(PartiesSellLootCampaignBehavior.OnSettlementEntered))]
    internal static class ViewerPartyLootSalePatch
    {
        [HarmonyPrefix]
        public static bool Prefix(MobileParty mobileParty)
            => !HeroNaming.IsAdopted(mobileParty?.LeaderHero);
    }
}
