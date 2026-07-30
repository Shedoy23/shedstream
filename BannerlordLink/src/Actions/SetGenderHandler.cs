using System;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
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
                try
                {
                    var hero = HeroLookup.FindByUsername(username);
                    if (hero == null)
                    {
                        BannerlordLinkModule.Log($"[hero.set_gender] @{username}: hero не найден");
                        return;
                    }
                    if (!hero.IsAlive)
                    {
                        BannerlordLinkModule.Log($"[hero.set_gender] @{username}: hero мёртв");
                        return;
                    }

                    bool wantFemale = gender == "female";
                    if (hero.IsFemale == wantFemale)
                    {
                        BannerlordLinkModule.Log($"[hero.set_gender] @{username}: уже {gender}");
                        return;
                    }

                    // Беременная → male не разрешён (engine breaks)
                    if (hero.IsPregnant && !wantFemale)
                    {
                        BannerlordLinkModule.Log(
                            $"[hero.set_gender] @{username}: cannot become male while pregnant");
                        return;
                    }

                    // 2026-07-31: списываем объявленную бэкендом цену В ДИНАРАХ.
                    // До этого поле `hero_gold_cost` не читал никто, и действие
                    // выполнялось бесплатно (подтверждено прогоном в игре).
                    if (!HeroGoldCharge.TryCharge(hero, data, actionId, "hero.set_gender"))
                        return;

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

                    BannerlordLinkModule.Log(
                        $"[hero.set_gender] @{username}: → {gender}");
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log($"[hero.set_gender] @{username} CRASHED: {ex.Message}");
                }
            });

            return Task.FromResult<(bool, string)>((true, null));
        }
    }
}
