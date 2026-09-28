namespace RimLink
{
    internal static class RimLinkConstants
    {
        // ── Сеть ──────────────────────────────────────────────────────────────
        public const string DefaultServerUrl        = "https://shedoy23.ru";
        public const int    DefaultSyncInterval     = 60;

        // ── Фоновый поток синхронизации ────────────────────────────────────────
        public const int CommandPollIntervalMs      = 15000;
        public const int MaxBackoffMs               = 60000;

        // ── Очередь команд ────────────────────────────────────────────────────
        public const int MaxCommandQueueSize        = 1000;
    }
}
