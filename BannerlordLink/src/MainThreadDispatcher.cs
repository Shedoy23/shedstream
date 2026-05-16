using System;
using System.Collections.Concurrent;

namespace BannerlordLink
{
    /// <summary>
    /// Главный thread-safety helper мода.
    ///
    /// Bannerlord API (Hero creation, Mission, Campaign mutations) НЕ
    /// thread-safe. Все calls к TaleWorlds.* должны идти из главного
    /// game thread'а. ActionPoller / HttpClient работают в background —
    /// они enqueue работу сюда, главный thread drain'ит queue через
    /// MBSubModuleBase.OnApplicationTick.
    ///
    /// Использование:
    ///   // В background:
    ///   MainThreadDispatcher.Enqueue(() => { Hero h = HeroCreator.CreateSpecialHero(...); });
    ///   // На main thread (auto-called каждый tick):
    ///   MainThreadDispatcher.DrainQueue();
    /// </summary>
    public static class MainThreadDispatcher
    {
        private static readonly ConcurrentQueue<Action> _queue = new ConcurrentQueue<Action>();

        /// <summary>Enqueue action для выполнения на следующем main-thread tick.
        /// Thread-safe.</summary>
        public static void Enqueue(Action action)
        {
            if (action == null) return;
            _queue.Enqueue(action);
        }

        /// <summary>Выполнить все pending actions. Вызывать ТОЛЬКО с main thread.
        /// Exceptions из actions поглощаются и логируются — не сваливают drain.</summary>
        public static void DrainQueue()
        {
            int drained = 0;
            while (_queue.TryDequeue(out var action))
            {
                try { action(); }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"MainThreadDispatcher: action crashed: {ex.GetType().Name}: {ex.Message}");
                }
                drained++;
                // Safety cap: не блокируем frame на тысячах queued actions.
                if (drained >= 32) break;
            }
        }
    }
}
