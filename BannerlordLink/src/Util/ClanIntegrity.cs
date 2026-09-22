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
                    // 2026-09-22 — успехом считаем НАБЛЮДАЕМЫЙ эффект, а не факт
                    // вызова. Ваниль 1.4.8 при пустом GetHeirApparents() выходит,
                    // не тронув _leader, и раньше мы писали «OK» именно тогда.
                    detached = !ReferenceEquals(clan.Leader, hero);
                    BannerlordLinkModule.Log(
                        $"[leave_clan] @{who}: leader без членов → " +
                        $"ChangeClanLeaderAction.ApplyWithoutSelectedNewLeader " +
                        (detached ? "OK" : "НИЧЕГО НЕ СДЕЛАЛ (нет наследников) → reflection"));
                    if (!detached && ForceLeaderNull(clan))
                    {
                        detached = !ReferenceEquals(clan.Leader, hero);
                        BannerlordLinkModule.Log(
                            $"[leave_clan] @{who}: reflection _leader=null " +
                            (detached ? "OK" : "НЕ СРАБОТАЛ"));
                    }
                }
                else
                {
                    BannerlordLinkModule.Log(
                        $"[leave_clan] @{who}: " +
                        $"ApplyWithoutSelectedNewLeader not found → reflection fallback");
                    if (ForceLeaderNull(clan) && !ReferenceEquals(clan.Leader, hero))
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
                    if (ForceLeaderNull(clan) && !ReferenceEquals(clan.Leader, hero))
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
            // Клан без лидера не имеет права оставаться в королевстве: ваниль
            // переберёт его на суточном тике и разыменует Leader.Clan.
            if (detached) DropLeaderlessFromKingdom(clan);
            return detached;
        }

        /// <summary>
        /// Ремонт уже сохранённых кампаний: кланы, у которых лидер не совпадает
        /// со своим кланом. Возвращает число вылеченных кланов.
        /// </summary>
        internal static int RepairAll()
        {
            int repaired = 0;
            try
            {
                var all = Clan.All;
                if (all == null) return 0;
                foreach (var clan in all.ToList())
                {
                    if (clan == null) continue;
                    var leader = clan.Leader;
                    // Битая связка: лидер есть, но он уже не в этом клане.
                    // Бандитские фракции (лидера нет И королевства нет) — норма
                    // движка, их не трогаем.
                    bool danglingLeader = leader != null && !ReferenceEquals(leader.Clan, clan);
                    bool leaderlessInKingdom = leader == null && clan.Kingdom != null;
                    if (!danglingLeader && !leaderlessInKingdom) continue;

                    string name = clan.Name?.ToString() ?? "?";
                    if (danglingLeader)
                    {
                        // Сначала пробуем вылечить: если в клане остался живой
                        // наследник, ваниль поднимет его в лидеры.
                        try { ChangeClanLeaderAction.ApplyWithoutSelectedNewLeader(clan); }
                        catch (Exception ex)
                        {
                            BannerlordLinkModule.Log(
                                $"[clan-repair] '{name}': ApplyWithoutSelectedNewLeader failed: {ex.Message}");
                        }
                        if (!ReferenceEquals(clan.Leader, leader)
                            && clan.Leader != null
                            && ReferenceEquals(clan.Leader.Clan, clan))
                        {
                            repaired++;
                            BannerlordLinkModule.Log(
                                $"[clan-repair] '{name}': лидер заменён на своего члена клана");
                            continue;
                        }
                        ForceLeaderNull(clan);
                    }

                    DropLeaderlessFromKingdom(clan);
                    repaired++;
                    BannerlordLinkModule.Log(
                        $"[clan-repair] '{name}': висящий лидер снят, клан выведен из королевства");
                }
                if (repaired > 0)
                    BannerlordLinkModule.Log($"[clan-repair] вылечено кланов: {repaired}");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[clan-repair] crashed: {ex.Message}");
            }
            return repaired;
        }

        /// <summary>Вывести клан без лидера из королевства (ваниль его там не ждёт).</summary>
        private static void DropLeaderlessFromKingdom(Clan clan)
        {
            if (clan == null || clan.Leader != null || clan.Kingdom == null) return;
            try { ChangeKingdomAction.ApplyByLeaveKingdom(clan, false); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[clan-repair] '{clan.Name}': ApplyByLeaveKingdom failed: {ex.Message}");
            }
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
