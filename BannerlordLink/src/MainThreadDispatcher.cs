using System;
using System.Collections.Concurrent;
using System.Threading;
using System.Threading.Tasks;

namespace BannerlordLink
{
    /// <summary>
    /// Serializes all TaleWorlds API mutations onto Bannerlord's application
    /// thread. Work queued while an action handler is running is tracked as one
    /// unit: the handler does not complete until every queued callback has run.
    ///
    /// This is the transaction boundary between the HTTP poller and the game.
    /// An ACK must never be produced merely because a callback was enqueued.
    /// </summary>
    public static class MainThreadDispatcher
    {
        private sealed class TrackedAction
        {
            private readonly object _gate = new object();
            private readonly TaskCompletionSource<(bool success, string error)> _completion =
                new TaskCompletionSource<(bool, string)>(
                    TaskCreationOptions.RunContinuationsAsynchronously);

            private int _pendingWork;
            private bool _handlerFinished;
            private bool _handlerSuccess = true;
            private bool _cancelled;
            private string _error;

            public TrackedAction(string actionId)
            {
                ActionId = actionId ?? "";
            }

            public string ActionId { get; }
            public Task<(bool success, string error)> Completion => _completion.Task;

            public bool TryAddWork()
            {
                lock (_gate)
                {
                    if (_cancelled || _handlerFinished) return false;
                    _pendingWork++;
                    return true;
                }
            }

            public void FinishHandler(bool success, string error)
            {
                lock (_gate)
                {
                    if (_cancelled) return;
                    _handlerFinished = true;
                    if (!success)
                    {
                        _handlerSuccess = false;
                        if (string.IsNullOrEmpty(_error)) _error = error ?? "handler_failed";
                    }
                    TryCompleteLocked();
                }
            }

            public void Fail(string error)
            {
                lock (_gate)
                {
                    if (_cancelled) return;
                    _handlerSuccess = false;
                    if (string.IsNullOrEmpty(_error)) _error = error ?? "apply_failed";
                }
            }

            public void WorkFinished()
            {
                lock (_gate)
                {
                    if (_pendingWork > 0) _pendingWork--;
                    TryCompleteLocked();
                }
            }

            public void Cancel()
            {
                lock (_gate)
                {
                    if (_cancelled || _completion.Task.IsCompleted) return;
                    _cancelled = true;
                    _completion.TrySetCanceled();
                }
            }

            private void TryCompleteLocked()
            {
                if (_cancelled || !_handlerFinished || _pendingWork != 0) return;
                _completion.TrySetResult((_handlerSuccess, _error));
            }
        }

        private sealed class WorkItem
        {
            public Action Callback;
            public TrackedAction Tracked;
            public long Generation;
        }

        private static readonly ConcurrentQueue<WorkItem> _queue =
            new ConcurrentQueue<WorkItem>();
        private static readonly ConcurrentDictionary<TrackedAction, byte> _active =
            new ConcurrentDictionary<TrackedAction, byte>();
        private static readonly AsyncLocal<TrackedAction> _ambient =
            new AsyncLocal<TrackedAction>();

        [ThreadStatic]
        private static TrackedAction _executing;

        private static long _generation;
        private static int _acceptingWork;

        /// <summary>Starts a fresh module lifecycle and discards stale callbacks.</summary>
        public static void StartSession()
        {
            Interlocked.Exchange(ref _acceptingWork, 0);
            Interlocked.Increment(ref _generation);
            CancelActiveAndClearQueue();
            Interlocked.Exchange(ref _acceptingWork, 1);
        }

        /// <summary>Cancels all pending action completions and rejects new work.</summary>
        public static void Shutdown()
        {
            Interlocked.Exchange(ref _acceptingWork, 0);
            Interlocked.Increment(ref _generation);
            CancelActiveAndClearQueue();
        }

        /// <summary>
        /// Runs a handler inside a tracking scope. Every callback enqueued by the
        /// handler is included in its result, including failures reported through
        /// ActionFeedback.PostFailed.
        /// </summary>
        public static async Task<(bool success, string error)> ExecuteTrackedAsync(
            string actionId,
            Func<Task<(bool success, string error)>> handler,
            CancellationToken cancellationToken)
        {
            if (handler == null) return (false, "handler_null");
            if (Volatile.Read(ref _acceptingWork) == 0)
                throw new OperationCanceledException("dispatcher is shutting down");

            var tracked = new TrackedAction(actionId);
            _active.TryAdd(tracked, 0);
            var previous = _ambient.Value;
            _ambient.Value = tracked;

            try
            {
                using (cancellationToken.Register(tracked.Cancel))
                {
                    try
                    {
                        var result = await handler().ConfigureAwait(false);
                        tracked.FinishHandler(result.success, result.error);
                    }
                    catch (OperationCanceledException)
                    {
                        tracked.Cancel();
                        throw;
                    }
                    catch (Exception ex)
                    {
                        tracked.FinishHandler(false,
                            $"{ex.GetType().Name}: {ex.Message}");
                    }

                    return await tracked.Completion.ConfigureAwait(false);
                }
            }
            finally
            {
                _ambient.Value = previous;
                _active.TryRemove(tracked, out _);
            }
        }

        /// <summary>
        /// Called by ActionFeedback on the game thread. Returns true when the
        /// failure belongs to the currently executing tracked action, so no
        /// secondary HTTP compensation event is needed.
        /// </summary>
        public static bool TryReportActionFailure(string actionId, string reason)
        {
            var tracked = _executing ?? _ambient.Value;
            if (tracked == null) return false;
            if (!string.IsNullOrEmpty(actionId)
                && !string.Equals(tracked.ActionId, actionId, StringComparison.Ordinal))
                return false;

            tracked.Fail(reason);
            return true;
        }

        /// <summary>Queues a callback for the next application tick.</summary>
        public static void Enqueue(Action action)
        {
            if (action == null) return;

            var tracked = _ambient.Value;
            if (Volatile.Read(ref _acceptingWork) == 0)
            {
                tracked?.Cancel();
                return;
            }
            if (tracked != null && !tracked.TryAddWork())
                return;

            long generation = Volatile.Read(ref _generation);
            _queue.Enqueue(new WorkItem
            {
                Callback = action,
                Tracked = tracked,
                Generation = generation,
            });

            // Close the enqueue-vs-shutdown race. The active action has already
            // been cancelled by Shutdown; this only prevents stale untracked work
            // from surviving until a later module session.
            if (Volatile.Read(ref _acceptingWork) == 0
                || generation != Volatile.Read(ref _generation))
            {
                tracked?.Cancel();
            }
        }

        /// <summary>Executes up to 32 callbacks on Bannerlord's main thread.</summary>
        public static void DrainQueue()
        {
            int drained = 0;
            long generation = Volatile.Read(ref _generation);
            while (_queue.TryDequeue(out var item))
            {
                if (item.Generation != generation
                    || Volatile.Read(ref _acceptingWork) == 0)
                {
                    item.Tracked?.Cancel();
                    item.Tracked?.WorkFinished();
                }
                else
                {
                    _executing = item.Tracked;
                    try
                    {
                        item.Callback();
                    }
                    catch (Exception ex)
                    {
                        string error = $"{ex.GetType().Name}: {ex.Message}";
                        if (item.Tracked != null) item.Tracked.Fail(error);
                        BannerlordLinkModule.Log(
                            $"MainThreadDispatcher: action crashed: {error}");
                    }
                    finally
                    {
                        _executing = null;
                        item.Tracked?.WorkFinished();
                    }
                }

                drained++;
                if (drained >= 32) break;
            }
        }

        private static void CancelActiveAndClearQueue()
        {
            foreach (var tracked in _active.Keys)
                tracked.Cancel();

            while (_queue.TryDequeue(out var item))
            {
                item.Tracked?.Cancel();
                item.Tracked?.WorkFinished();
            }
        }
    }
}
