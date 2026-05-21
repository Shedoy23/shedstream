using System.Collections.Generic;
using BannerlordLink.Behaviors;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.ComponentInterfaces;
using TaleWorlds.CampaignSystem.Naval;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Roster;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Library;
using TaleWorlds.Localization;

namespace BannerlordLink.Models
{
    /// <summary>
    /// Sprint 5.26d — BLT-style model replacement для статических clan-upgrade
    /// эффектов. Каждый model subclass-it оригинал, делегирует _previous
    /// и добавляет bonus сверху из ClanUpgradesBehavior.Current.
    ///
    /// Pattern: BLT-v5.2.4 BLTUpgradeModels.cs. Clean-room re-impl.
    ///
    /// Покрываются эффекты:
    ///   - party_size_bonus  → BLPartySizeLimitModel
    ///   - party_speed_bonus → BLPartySpeedModel (когда party НЕ в армии)
    ///   - army_speed_bonus  → BLPartySpeedModel (когда party В армии — sum по членам)
    ///   - party_amount_bonus → BLClanTierModel.GetPartyLimitForTier
    ///
    /// НЕ покрываются (требуют отдельных реализаций):
    ///   - retinue_size_bonus → backend-side (см. routes/bannerlord.py MAX_RETINUE)
    ///   - max_vassals_bonus → vassal limit нативно не controllable per-clan
    /// </summary>

    public class BLPartySpeedModel : PartySpeedModel
    {
        private readonly PartySpeedModel _previous;
        private static readonly TextObject Text =
            new TextObject("{=BL_UpgradePartySpeed}Апгрейды клана");

        public BLPartySpeedModel(PartySpeedModel previous) { _previous = previous; }

        public override float BaseSpeed    => _previous.BaseSpeed;
        public override float MinimumSpeed => _previous.MinimumSpeed;

        public override ExplainedNumber CalculateBaseSpeed(
            MobileParty party, bool includeDescriptions = false,
            int additionalTroopOnFootCount = 0, int additionalTroopOnHorseCount = 0)
        {
            return _previous.CalculateBaseSpeed(party, includeDescriptions,
                additionalTroopOnFootCount, additionalTroopOnHorseCount);
        }

        public override ExplainedNumber CalculateFinalSpeed(MobileParty party, ExplainedNumber finalSpeed)
        {
            var result = _previous.CalculateFinalSpeed(party, finalSpeed);
            if (ClanUpgradesBehavior.Current == null || party?.LeaderHero == null)
                return result;

            // В армии — army_speed_bonus (суммируем по всем party leader'ам в армии)
            if (party.Army != null)
            {
                float armyBonus = 0f;
                if (party.Army.Parties != null)
                {
                    foreach (var p in party.Army.Parties)
                    {
                        if (p?.LeaderHero == null) continue;
                        armyBonus += (float)ClanUpgradesBehavior.Current
                            .GetBonusFor(p.LeaderHero, "army_speed_bonus");
                    }
                }
                if (armyBonus != 0f) result.Add(armyBonus, Text);
            }
            else
            {
                // Solo party — party_speed_bonus
                float partyBonus = (float)ClanUpgradesBehavior.Current
                    .GetBonusFor(party.LeaderHero, "party_speed_bonus");
                if (partyBonus != 0f) result.Add(partyBonus, Text);
            }
            return result;
        }
    }


    public class BLPartySizeLimitModel : PartySizeLimitModel
    {
        private readonly PartySizeLimitModel _previous;
        private static readonly TextObject Text =
            new TextObject("{=BL_UpgradePartySize}Апгрейды клана");

        public BLPartySizeLimitModel(PartySizeLimitModel previous) { _previous = previous; }

        public override int MinimumNumberOfVillagersAtVillagerParty
            => _previous.MinimumNumberOfVillagersAtVillagerParty;

        public override ExplainedNumber GetPartyMemberSizeLimit(
            PartyBase party, bool includeDescriptions = true)
        {
            var result = _previous.GetPartyMemberSizeLimit(party, includeDescriptions);
            if (ClanUpgradesBehavior.Current == null || party?.LeaderHero == null)
                return result;
            int bonus = (int)ClanUpgradesBehavior.Current
                .GetBonusFor(party.LeaderHero, "party_size_bonus");
            if (bonus != 0) result.Add(bonus, Text);
            return result;
        }

        public override ExplainedNumber CalculateGarrisonPartySizeLimit(
            Settlement settlement, bool includeDescriptions = true)
            => _previous.CalculateGarrisonPartySizeLimit(settlement, includeDescriptions);

        public override ExplainedNumber GetPartyPrisonerSizeLimit(
            PartyBase party, bool includeDescriptions = false)
            => _previous.GetPartyPrisonerSizeLimit(party, includeDescriptions);

        public override int GetClanTierPartySizeEffectForHero(Hero hero)
            => _previous.GetClanTierPartySizeEffectForHero(hero);

        public override int GetNextClanTierPartySizeEffectChangeForHero(Hero hero)
            => _previous.GetNextClanTierPartySizeEffectChangeForHero(hero);

        public override int GetAssumedPartySizeForLordParty(
            Hero leaderHero, IFaction partyMapFaction, Clan actualClan)
            => _previous.GetAssumedPartySizeForLordParty(leaderHero, partyMapFaction, actualClan);

        public override int GetIdealVillagerPartySize(Village village)
            => _previous.GetIdealVillagerPartySize(village);

        public override TroopRoster FindAppropriateInitialRosterForMobileParty(
            MobileParty party, PartyTemplateObject partyTemplate)
            => _previous.FindAppropriateInitialRosterForMobileParty(party, partyTemplate);

        public override List<Ship> FindAppropriateInitialShipsForMobileParty(
            MobileParty party, PartyTemplateObject partyTemplate)
            => _previous.FindAppropriateInitialShipsForMobileParty(party, partyTemplate);
    }


    public class BLClanTierModel : ClanTierModel
    {
        private readonly ClanTierModel _previous;

        public BLClanTierModel(ClanTierModel previous) { _previous = previous; }

        // ── единственный override с логикой апгрейда ──
        public override int GetPartyLimitForTier(Clan clan, int clanTier)
        {
            int baseLimit = _previous.GetPartyLimitForTier(clan, clanTier);
            if (ClanUpgradesBehavior.Current == null || clan?.Leader == null) return baseLimit;
            int bonus = (int)ClanUpgradesBehavior.Current
                .GetBonusForClan(clan, "party_amount_bonus");
            return baseLimit + bonus;
        }

        // ── всё остальное — pure delegation к _previous ──
        public override int GetCompanionLimit(Clan clan) => _previous.GetCompanionLimit(clan);
        public override int GetRequiredRenownForTier(int tier) => _previous.GetRequiredRenownForTier(tier);
        public override int CalculateTier(Clan clan) => _previous.CalculateTier(clan);
        public override int CalculateInitialRenown(Clan clan) => _previous.CalculateInitialRenown(clan);
        public override int CalculateInitialInfluence(Clan clan) => _previous.CalculateInitialInfluence(clan);
        public override (ExplainedNumber, bool) HasUpcomingTier(Clan clan, out TextObject explanation, bool includeExplanation = false)
            => _previous.HasUpcomingTier(clan, out explanation, includeExplanation);
        public override int MinClanTier => _previous.MinClanTier;
        public override int MaxClanTier => _previous.MaxClanTier;
        public override int BannerEligibleTier => _previous.BannerEligibleTier;
        public override int MercenaryEligibleTier => _previous.MercenaryEligibleTier;
        public override int VassalEligibleTier => _previous.VassalEligibleTier;
        public override int RebelClanStartingTier => _previous.RebelClanStartingTier;
        public override int CompanionToLordClanStartingTier => _previous.CompanionToLordClanStartingTier;
    }
}
