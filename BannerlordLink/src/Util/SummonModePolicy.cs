namespace BannerlordLink.Util
{
    /// <summary>В каких режимах сцены можно призывать героя зрителя.
    ///
    /// 26.09.2026 (владелец: «можно разрешить спавн во время расстановки?
    /// новые BLT как-то смогли»): расстановка (Deployment) больше не запрет.
    /// Новый BLT (reference/BLT_lait, SummonHero.cs) убрал её из своего списка
    /// и призывает на расстановке «не по тревоге» (isAlarmed=false) и не как
    /// подкрепление; старый комментарий «SpawnAgent падает на Deployment»
    /// относился к прежнему способу призыва. В живой игре у нас не проверено.</summary>
    internal static class SummonModePolicy
    {
        internal static bool Blocks(string mode) =>
            mode == "CutScene" || mode == "Conversation" || mode == "Replay"
            || mode == "Barter" || mode == "Duel" || mode == "Tournament";

        internal static bool IsDeployment(string mode) => mode == "Deployment";

        /// <summary>Свита выходит в бою, на старте сцены и на расстановке.</summary>
        internal static bool RetinueAllowed(string mode) =>
            mode == "Battle" || mode == "StartUp" || mode == "Deployment";
    }
}
