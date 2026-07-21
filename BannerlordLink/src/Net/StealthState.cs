using System.Collections.Concurrent;

namespace BannerlordLink.Net
{
    /// <summary>
    /// 2026-07-21 — «Невидимость» ассасина (см. docs/SPEC_ASSASSIN_INVIS.md).
    /// Хранит момент последнего УДАРА невидимки: пока не истекло окно раскрытия,
    /// тик перестаёт срывать врагам захват цели — то есть ассасина снова видно.
    /// «Ударил и растворился»: рубить не отрываясь в свалке становится опасно.
    ///
    /// Пишется из DamageHookPatch (поток обработки blow'ов), читается из
    /// PowersMissionBehavior — отсюда ConcurrentDictionary.
    /// </summary>
    public static class StealthState
    {
        private static readonly ConcurrentDictionary<string, float> _lastHitAt =
            new ConcurrentDictionary<string, float>();

        public static void NoteHit(string username, float missionTime)
        {
            if (string.IsNullOrEmpty(username)) return;
            _lastHitAt[username] = missionTime;
        }

        /// <summary>true — герой только что бил, окно раскрытия ещё идёт.</summary>
        public static bool IsRevealed(string username, float missionTime, float revealWindowSec)
        {
            if (revealWindowSec <= 0f || string.IsNullOrEmpty(username)) return false;
            float last;
            if (!_lastHitAt.TryGetValue(username, out last)) return false;
            return missionTime - last < revealWindowSec;
        }

        public static void Clear() => _lastHitAt.Clear();
    }
}
