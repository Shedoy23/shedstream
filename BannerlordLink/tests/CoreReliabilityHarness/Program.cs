using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using BannerlordLink.Net;

namespace BannerlordLink
{
    // Test seam for the linked dispatcher source. The production build resolves
    // the real MBSubModuleBase implementation instead.
    public static class BannerlordLinkModule
    {
        public static readonly ConcurrentQueue<string> Messages =
            new ConcurrentQueue<string>();
        public static void Log(string message) => Messages.Enqueue(message);
    }

    internal static class Program
    {
        private static int _assertions;

        private static void Assert(bool condition, string message)
        {
            _assertions++;
            if (!condition) throw new InvalidOperationException(message);
        }

        private static async Task TestDispatcherWaitsForApplyAsync()
        {
            MainThreadDispatcher.StartSession();
            bool applied = false;
            Task<(bool success, string error)> action =
                MainThreadDispatcher.ExecuteTrackedAsync(
                    "action-success",
                    () =>
                    {
                        MainThreadDispatcher.Enqueue(() =>
                        {
                            applied = true;
                            bool captured = MainThreadDispatcher.TryReportActionApplied(
                                "action-success");
                            Assert(captured, "explicit apply was not captured");
                        });
                        return Task.FromResult<(bool, string)>((true, null));
                    },
                    CancellationToken.None);

            Assert(!action.IsCompleted, "action completed before main-thread apply");
            MainThreadDispatcher.DrainQueue();
            var result = await action;
            Assert(applied, "main-thread callback was not applied");
            Assert(result.success, "successful apply returned failure");
            Assert(!BannerlordLinkModule.Messages.Any(x =>
                    x.Contains("action_id=action-success") &&
                    x.Contains("БЕЗ ЯВНОГО ИСХОДА")),
                "explicit apply was still reported as unstated");
        }

        private static async Task TestDispatcherCapturesFailureAsync()
        {
            MainThreadDispatcher.StartSession();
            Task<(bool success, string error)> action =
                MainThreadDispatcher.ExecuteTrackedAsync(
                    "action-refuse",
                    () =>
                    {
                        MainThreadDispatcher.Enqueue(() =>
                        {
                            bool captured = MainThreadDispatcher.TryReportActionFailure(
                                "action-refuse", "gameplay_refused");
                            Assert(captured, "main-thread refusal was not captured");
                        });
                        return Task.FromResult<(bool, string)>((true, null));
                    },
                    CancellationToken.None);
            MainThreadDispatcher.DrainQueue();
            var result = await action;
            Assert(!result.success, "captured refusal returned success");
            Assert(result.error == "gameplay_refused", "wrong refusal reason");

            Task<(bool success, string error)> crashed =
                MainThreadDispatcher.ExecuteTrackedAsync(
                    "action-crash",
                    () =>
                    {
                        MainThreadDispatcher.Enqueue(() =>
                            throw new IndexOutOfRangeException("synthetic"));
                        return Task.FromResult<(bool, string)>((true, null));
                    },
                    CancellationToken.None);
            MainThreadDispatcher.DrainQueue();
            var crashResult = await crashed;
            Assert(!crashResult.success, "callback exception returned success");
            Assert(crashResult.error.Contains("IndexOutOfRangeException"),
                "callback exception type was lost");
        }

        private static async Task TestDispatcherShutdownCancelsAsync()
        {
            MainThreadDispatcher.StartSession();
            Task<(bool success, string error)> pending =
                MainThreadDispatcher.ExecuteTrackedAsync(
                    "action-shutdown",
                    () =>
                    {
                        MainThreadDispatcher.Enqueue(() => { });
                        return Task.FromResult<(bool, string)>((true, null));
                    },
                    CancellationToken.None);
            MainThreadDispatcher.Shutdown();
            try
            {
                await pending;
                Assert(false, "shutdown did not cancel pending action");
            }
            catch (TaskCanceledException)
            {
                Assert(true, "shutdown cancellation observed");
            }
        }

        private static void TestOutcomeStore(string root)
        {
            string path = Path.Combine(root, "outcomes.jsonl");
            var store = new ActionOutcomeStore(
                path, BannerlordLinkModule.Log, TimeSpan.FromHours(3), 100);
            Assert(store.Record("ok", true, null), "success outcome not persisted");
            Assert(store.Record("failed", false, "no_hero"), "failure outcome not persisted");

            var restored = new ActionOutcomeStore(
                path, BannerlordLinkModule.Log, TimeSpan.FromHours(3), 100);
            Assert(restored.TryGet("failed", out var failure), "failure outcome not restored");
            Assert(!failure.Success && failure.Error == "no_hero",
                "failure outcome changed during restore");

            for (int i = 0; i < 110; i++)
                Assert(restored.Record("cap-" + i, true, null), "cap outcome persist failed");
            Assert(!restored.TryGet("ok", out _), "hard cap did not evict oldest outcome");
            Assert(restored.TryGet("cap-109", out _), "hard cap evicted newest outcome");
        }

        private static async Task TestOutboxRestoresStableEnvelopeAsync(string root)
        {
            string path = Path.Combine(root, "outbox.jsonl");
            var firstIds = new ConcurrentQueue<string>();
            using (var first = new DurableEventOutbox(
                path,
                item =>
                {
                    firstIds.Enqueue(item.Id);
                    return Task.FromResult(false);
                },
                BannerlordLinkModule.Log))
            {
                Assert(first.Enqueue("bannerlord", "action.failed", "{\"action_id\":\"a1\"}"),
                    "durable event was not persisted");
                await WaitUntilAsync(() => firstIds.Count > 0, TimeSpan.FromSeconds(2));
                Assert(first.PendingCount == 1, "failed delivery disappeared from outbox");
            }

            Assert(firstIds.TryPeek(out string originalId), "first envelope id missing");
            var deliveredIds = new ConcurrentQueue<string>();
            using (var second = new DurableEventOutbox(
                path,
                item =>
                {
                    deliveredIds.Enqueue(item.Id);
                    return Task.FromResult(true);
                },
                BannerlordLinkModule.Log))
            {
                await WaitUntilAsync(() => second.PendingCount == 0, TimeSpan.FromSeconds(3));
                Assert(deliveredIds.TryPeek(out string restoredId), "restored event was not delivered");
                Assert(restoredId == originalId, "retry changed the envelope id");
            }

            using (var third = new DurableEventOutbox(
                path,
                item => throw new InvalidOperationException("ACKed item replayed"),
                BannerlordLinkModule.Log))
            {
                Assert(third.PendingCount == 0, "ACKed event reappeared after second restart");
            }
        }

        private static async Task WaitUntilAsync(Func<bool> predicate, TimeSpan timeout)
        {
            DateTime deadline = DateTime.UtcNow + timeout;
            while (!predicate())
            {
                if (DateTime.UtcNow >= deadline)
                    throw new TimeoutException("condition was not reached");
                await Task.Delay(20);
            }
        }

        private static async Task<int> Main()
        {
            string root = Path.Combine(
                Path.GetTempPath(), "bannerlordlink-core-tests-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                await TestDispatcherWaitsForApplyAsync();
                await TestDispatcherCapturesFailureAsync();
                await TestDispatcherShutdownCancelsAsync();
                TestOutcomeStore(root);
                await TestOutboxRestoresStableEnvelopeAsync(root);
                Console.WriteLine($"PASS: {_assertions} reliability assertions");
                return 0;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("FAIL: " + ex);
                return 1;
            }
            finally
            {
                try { Directory.Delete(root, true); } catch { }
            }
        }
    }
}
