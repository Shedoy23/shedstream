using HarmonyLib;
using TaleWorlds.MountAndBlade;
using BannerlordLink.Behaviors;

namespace BannerlordLink.Patches
{
    /// <summary>30.09, багрепорт #84: герой зрителя с приказом движения («в атаку», к
    /// стенам, к воротам, набег, перестрелка) не тормозится до темпа своего строя.
    /// Ваниль (1.4.8) в HumanAIComponent.ParallelUpdateFormationMovement считает
    /// ограничение скорости по строю и передаёт его сюда; отделённому от строя бойцу
    /// она сама передаёт -1 (без ограничения) — делаем так же для наших героев.
    /// Вызывается из параллельного тика ИИ: только чтение потокобезопасного набора.</summary>
    [HarmonyPatch(typeof(HumanAIComponent), nameof(HumanAIComponent.AdjustSpeedLimit))]
    internal static class DetachedHeroSpeedPatch
    {
        [HarmonyPrefix]
        public static void Prefix(Agent agent, ref float desiredSpeed, ref bool limitIsMultiplier)
        {
            if (agent != null && HeroDetachmentBehavior.FullSpeedAgents.ContainsKey(agent.Index))
            {
                desiredSpeed = -1f;
                limitIsMultiplier = false;
            }
        }
    }
}
