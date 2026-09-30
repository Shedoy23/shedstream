using System;
using BannerlordLink.Util;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;

namespace BannerlordLink.Behaviors
{
    /// <summary>Герой зрителя не сидит в плену вечно без войны (30.09.2026, багрепорт #81).
    ///
    /// laitru: «уже несколько игровых лет в плену Баттании, хотя войны с ней нет» — и в
    /// плену нельзя менять снаряжение. Ваниль освобождает лордов при мире между
    /// сторонами и при смене клана, а побег (шанс в день) требует тюремщика
    /// (PartyBelongedToAsPrisoner). Герой, чей тюремщик исчез, или тюремщик которого
    /// больше не воюет с его стороной (зритель сменил королевство, мир заключили до
    /// пленения), из плена не выходит никогда. Раз в игровой день такого отпускаем
    /// штатно — EndCaptivityAction.ApplyByPeace (null-тюремщика она переносит).
    /// Пленник воюющей стороны и пленник бандитов не трогаются: это обычный плен.</summary>
    public class StuckPrisonerReleaseBehavior : CampaignBehaviorBase
    {
        public override void RegisterEvents()
        {
            CampaignEvents.DailyTickEvent.AddNonSerializedListener(this, OnDailyTick);
        }

        public override void SyncData(IDataStore dataStore) { }

        /// <summary>Чистое решение: отпустить ли пленника.</summary>
        internal static bool ShouldRelease(bool adopted, bool isPrisoner, bool hasCaptor, bool captorAtWar) =>
            adopted && isPrisoner && (!hasCaptor || !captorAtWar);

        private void OnDailyTick()
        {
            try
            {
                // Сначала собираем: освобождение меняет состояние героя, а список общий.
                var prisoners = new System.Collections.Generic.List<Hero>();
                foreach (var h in Hero.AllAliveHeroes)
                    if (h != null && h.IsPrisoner && HeroNaming.IsAdopted(h)) prisoners.Add(h);
                foreach (var hero in prisoners)
                {
                    var captor = hero.PartyBelongedToAsPrisoner;
                    IFaction captorFaction = captor?.MapFaction;
                    bool atWar = captorFaction != null && hero.MapFaction != null
                        && captorFaction.IsAtWarWith(hero.MapFaction);
                    if (!ShouldRelease(true, true, captor != null, atWar)) continue;
                    string where = captor == null ? "тюремщика нет"
                        : $"держит «{captor.Name}» ({captorFaction?.Name?.ToString() ?? "без стороны"}), войны с «{hero.MapFaction?.Name}» нет";
                    EndCaptivityAction.ApplyByPeace(hero);
                    BannerlordLinkModule.Log($"[StuckPrisoner] RELEASED '{hero.Name}': {where}; свободен={!hero.IsPrisoner}");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[StuckPrisoner] daily tick error: {ex.GetType().Name}: {ex.Message}");
            }
        }
    }
}
