using System;
using System.Linq;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using BannerlordLink.Util;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.27c — hero.make_baby. BLT pattern (MakeBaby в FamilyManagement.cs):
    /// если hero — female → MakePregnantAction.Apply(hero), иначе spouse.
    ///
    /// Eligibility:
    ///   - hero alive, age >= 18
    ///   - hero.Spouse != null
    ///   - female-в-паре не должна быть pregnant
    ///
    /// Pregnancy → через ~36 in-game дней появляется child через
    /// vanilla PregnancyCampaignBehavior. Children появятся в hero.Children
    /// автоматически.
    ///
    /// Limit: 5 alive children в клане (BLT MakeKidsLimit default).
    /// </summary>
    public class MakeBabyHandler : IActionHandler
    {
        // Sprint 5.32 (BLT-parity LOW-7) — default limit, может быть override'нут
        // через data["max_alive_children"] из backend (Boosty tier3 sub'ам можно
        // увеличить, premium streamers — настройка). Backend пока всегда не шлёт
        // и используется DEFAULT, но архитектура готова к per-channel/per-tier override.
        private const int DEFAULT_MAX_ALIVE_CHILDREN = 5;

        public string ActionType => "hero.make_baby";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));

            // Sprint 5.32 (BLT-parity LOW-7) — read override из payload.
            int maxAliveChildren = DEFAULT_MAX_ALIVE_CHILDREN;
            try
            {
                int? overrideVal = (int?)data["max_alive_children"];
                if (overrideVal.HasValue && overrideVal.Value > 0 && overrideVal.Value <= 20)
                    maxAliveChildren = overrideVal.Value;
            }
            catch { }

            string actionId = ActionFeedback.GetActionId(data);

            MainThreadDispatcher.Enqueue(() =>
            {
                try
                {
                    var hero = HeroLookup.FindByUsername(username);
                    if (hero == null) return;
                    if (!hero.IsAlive)
                    {
                        BannerlordLinkModule.Log($"[hero.make_baby] @{username}: hero мёртв");
                        return;
                    }
                    if (hero.Age < 18)
                    {
                        BannerlordLinkModule.Log($"[hero.make_baby] @{username}: too young");
                        return;
                    }
                    if (hero.Spouse == null)
                    {
                        BannerlordLinkModule.Log($"[hero.make_baby] @{username}: no spouse");
                        return;
                    }

                    int childCount = hero.Children?
                        .Where(c => c != null && !c.IsDead && c.Clan == hero.Clan)
                        .Count() ?? 0;
                    if (childCount >= maxAliveChildren)
                    {
                        BannerlordLinkModule.Log(
                            $"[hero.make_baby] @{username}: уже {childCount} детей в клане, лимит {maxAliveChildren}");
                        return;
                    }

                    // Если hero female → она pregnant, иначе её супруга
                    var target = hero.IsFemale ? hero : hero.Spouse;
                    if (target.IsPregnant)
                    {
                        BannerlordLinkModule.Log(
                            $"[hero.make_baby] @{username}: {target.Name} уже беременна");
                        return;
                    }

                    // 2026-07-31: списываем объявленную бэкендом цену В ДИНАРАХ.
                    // До этого поле `hero_gold_cost` не читал никто, и действие
                    // выполнялось бесплатно (подтверждено прогоном в игре).
                    if (!HeroGoldCharge.TryCharge(hero, data, actionId, "hero.make_baby"))
                        return;

                    MakePregnantAction.Apply(target);
                    BannerlordLinkModule.Log(
                        $"[hero.make_baby] @{username}: {target.Name} забеременела "
                        + $"(текущих детей: {childCount}/{maxAliveChildren})");
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log($"[hero.make_baby] @{username} CRASHED: {ex.Message}");
                }
            });

            return Task.FromResult<(bool, string)>((true, null));
        }
    }
}
