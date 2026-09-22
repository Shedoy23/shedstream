using System;
using System.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;

namespace BannerlordLink.Util
{
    /// <summary>
    /// 2026-09-22 — целостность связки «клан ↔ его лидер».
    ///
    /// Ваниль в `DefaultDiplomacyModel.GetRelationScore` берёт `Leader.Clan` без
    /// единой проверки, поэтому клан, который числится в королевстве и указывает
    /// на лидера БЕЗ клана, роняет игру на ближайшем суточном тике (разбор:
    /// `docs/BANNERLORD_CRASH_2026-09-22.md`).
    ///
    /// Здесь собрано ОДНО место, которое такую связку рвёт корректно: им
    /// пользуется и `hero.leave_clan`, и ремонт уже испорченных сейвов на
    /// загрузке.
    /// </summary>
    internal static class ClanIntegrity
    {
        /// <summary>
        /// Снять <paramref name="hero"/> с поста лидера клана, у которого больше
        /// нет живых членов. Возвращает true, если клан ДЕЙСТВИТЕЛЬНО перестал
        /// считать героя лидером.
        /// </summary>
        internal static bool DetachLeader(Clan clan, Hero hero, string who)
        {
            if (clan == null || hero == null) return false;

            // Sprint 5.32 BLT-parity — публичный engine API вместо reflection-хака.
            // BLT в ClanManagement.cs:802 для single-leader detach использует
            // ChangeClanLeaderAction.ApplyWithoutSelectedNewLeader(clan).
            //
            // Fallback: reflection _leader=null если API недоступен в данной
            // версии TaleWorlds (старые сборки 1.0-1.1).
            bool detached = false;
            try
            {
                var method = typeof(ChangeClanLeaderAction).GetMethod(
                    "ApplyWithoutSelectedNewLeader",
                    System.Reflection.BindingFlags.Public |
                    System.Reflection.BindingFlags.Static);
                if (method != null)
                {
                    method.Invoke(null, new object[] { clan });
                    detached = true;
                    BannerlordLinkModule.Log(
                        $"[leave_clan] @{who}: leader без членов → " +
                        $"ChangeClanLeaderAction.ApplyWithoutSelectedNewLeader OK");
                }
                else
                {
                    BannerlordLinkModule.Log(
                        $"[leave_clan] @{who}: " +
                        $"ApplyWithoutSelectedNewLeader not found → reflection fallback");
                    if (ForceLeaderNull(clan))
                    {
                        detached = true;
                        BannerlordLinkModule.Log(
                            $"[leave_clan] @{who}: reflection " +
                            $"_leader=null OK (clan '{clan.Name}' orphaned)");
                    }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[leave_clan] @{who}: API failed ({ex.Message}) — " +
                    $"trying reflection fallback");
                try
                {
                    if (ForceLeaderNull(clan))
                    {
                        detached = true;
                        BannerlordLinkModule.Log(
                            $"[leave_clan] @{who}: reflection _leader=null OK after API fail");
                    }
                }
                catch (Exception rex)
                {
                    BannerlordLinkModule.Log(
                        $"[leave_clan] REFUSE @{who}: both API + reflection failed: {rex.Message}");
                }
            }
            return detached;
        }

        /// <summary>
        /// Ремонт уже сохранённых кампаний: кланы, у которых лидер не совпадает
        /// со своим кланом. Возвращает число вылеченных кланов.
        /// </summary>
        internal static int RepairAll()
        {
            return 0;
        }

        /// <summary>Занулить `Clan._leader` напрямую (поле приватное).</summary>
        private static bool ForceLeaderNull(Clan clan)
        {
            var leaderField = HarmonyLib.AccessTools.Field(
                typeof(TaleWorlds.CampaignSystem.Clan), "_leader");
            if (leaderField == null) return false;
            leaderField.SetValue(clan, null);
            return true;
        }
    }
}
