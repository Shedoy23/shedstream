namespace BannerlordLink.Util
{
    /// <summary>03.10 22:30:42 — вылет при роспуске королевства (см. VassalAutoFollowBehavior.
    /// ShouldFollowNow). Чистое правило без типов игры, чтобы его держал стенд.</summary>
    public static class VassalFollowPolicy
    {
        /// <summary>false — вассала сейчас не трогать: господин ушёл потому, что их общее
        /// королевство распускается, и игра в том же обходе переведёт вассала сама.</summary>
        public static bool ShouldFollowNow(bool kingdomDestroyed, bool vassalInSameOldKingdom)
            => !(kingdomDestroyed && vassalInSameOldKingdom);
    }
}
