using System;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using BannerlordLink.Util;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.27a — смена пола героя.
    ///
    /// API: Hero.IsFemale (set). Auto-flip супруги если есть — Bannerlord не
    /// допускает same-sex marriage, ломает брак если оба одного пола. Если
    /// hero мужчина и беременный (теоретически невозможно, но safety) —
    /// блокируем.
    ///
    /// Clean-room re-impl BLT'шного HeroFeatures.cs "gender" case.
    /// Различия:
    ///   - Цену в динарах объявляет бэкенд в `hero_gold_cost`, а СПИСЫВАЕТ
    ///     ЕЁ ЭТОТ ОБРАБОТЧИК (`HeroGoldCharge.TryCharge`). До 2026-07-31
    ///     здесь было написано «backend gold-check уже выполнен, здесь только
    ///     применение» — и это было неправдой: бэкенд лишь ПРОВЕРЯЛ баланс, а
    ///     не списывал, и смена пола была бесплатной. Комментарий и прятал
    ///     дыру: он звучал как объяснение, почему списания тут нет.
    ///   - Нет restrict «только created heroes» (наши всех создаём через
    ///     hero.create, native adoption не используется)
    ///
    /// Body: {"target": username, "gender": "male"|"female"}
    /// </summary>
    public class SetGenderHandler : IActionHandler
    {
        public string ActionType => "hero.set_gender";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string gender = (data["gender"]?.ToString() ?? "").Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));
            if (gender != "male" && gender != "female")
                return Task.FromResult<(bool, string)>((false, "gender must be male|female"));

            string actionId = ActionFeedback.GetActionId(data);

            MainThreadDispatcher.Enqueue(() =>
            {
                Hero chargedHero = null;
                Hero spouse = null;
                bool oldHeroFemale = false;
                bool oldSpouseFemale = false;
                int chargedAmount = 0;
                bool committed = false;
                try
                {
                    var hero = HeroLookup.FindByUsername(username);
                    if (hero == null)
                    {
                        BannerlordLinkModule.Log($"[hero.set_gender] @{username}: hero не найден");
                        ActionFeedback.PostFailed(actionId, "hero_not_found");
                        return;
                    }
                    if (!hero.IsAlive)
                    {
                        BannerlordLinkModule.Log($"[hero.set_gender] @{username}: hero мёртв");
                        ActionFeedback.PostFailed(actionId, "hero_dead");
                        return;
                    }

                    bool wantFemale = gender == "female";
                    if (hero.IsFemale == wantFemale)
                    {
                        BannerlordLinkModule.Log($"[hero.set_gender] @{username}: уже {gender}");
                        ActionFeedback.PostFailed(actionId, "already_gender");
                        return;
                    }

                    // Беременная → male не разрешён (engine breaks)
                    if (hero.IsPregnant && !wantFemale)
                    {
                        BannerlordLinkModule.Log(
                            $"[hero.set_gender] @{username}: cannot become male while pregnant");
                        ActionFeedback.PostFailed(actionId, "pregnant_cannot_become_male");
                        return;
                    }

                    // 2026-07-31: списываем объявленную бэкендом цену В ДИНАРАХ.
                    // До этого поле `hero_gold_cost` не читал никто, и действие
                    // выполнялось бесплатно (подтверждено прогоном в игре).
                    if (!HeroGoldCharge.TryCharge(
                        hero, data, actionId, "hero.set_gender", out chargedAmount))
                        return;

                    chargedHero = hero;
                    spouse = hero.Spouse;
                    oldHeroFemale = hero.IsFemale;
                    oldSpouseFemale = spouse?.IsFemale ?? false;
                    hero.IsFemale = wantFemale;

                    // Auto-flip супруги чтобы избежать same-sex marriage
                    // (engine может ломаться). BLT pattern.
                    if (hero.Spouse != null && hero.Spouse.IsFemale == wantFemale)
                    {
                        hero.Spouse.IsFemale = !wantFemale;
                        BannerlordLinkModule.Log(
                            $"[hero.set_gender] @{username}: auto-flipped spouse "
                            + $"{hero.Spouse.Name} → {(!wantFemale ? "female" : "male")}");
                    }

                    if (hero.IsFemale != wantFemale)
                        throw new InvalidOperationException("gender postcondition failed");
                    committed = true;

                    BannerlordLinkModule.Log(
                        $"[hero.set_gender] @{username}: → {gender}");
                }
                catch (Exception ex)
                {
                    if (!committed && chargedHero != null)
                    {
                        try { chargedHero.IsFemale = oldHeroFemale; } catch { }
                        try { if (spouse != null) spouse.IsFemale = oldSpouseFemale; } catch { }
                        HeroGoldCharge.Refund(chargedHero, chargedAmount, "hero.set_gender");
                    }
                    BannerlordLinkModule.Log($"[hero.set_gender] @{username} CRASHED: {ex.Message}");
                    if (!committed)
                        ActionFeedback.PostFailed(actionId, "crashed:" + ex.GetType().Name);
                }
            });

            return Task.FromResult<(bool, string)>((true, null));
        }
    }
}
