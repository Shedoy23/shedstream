using System;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;

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
    ///   - Backend gold-check уже выполнен до action'а (extension списывает
    ///     50k💰 через action-buy flow), здесь только применение
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
