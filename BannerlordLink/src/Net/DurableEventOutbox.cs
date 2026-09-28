using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace BannerlordLink.Net
{
    /// <summary>
    /// Small append-only durable queue for events whose loss changes money or
    /// action state. Each item keeps one envelope id across all retries, allowing
    /// the backend's envelope dedupe to make delivery effectively once-only.
    /// </summary>
    internal sealed class DurableEventOutbox : IDisposable
    {
        internal sealed class Item
        {
            public string Id;
            public string ModuleId;
            public string EventType;
            public string DataJson;
            public long TimestampMs;
            [JsonIgnore] public int Attempts;
            [JsonIgnore] public DateTime NextAttemptUtc;
        }

        private readonly object _gate = new object();
        private readonly List<Item> _pending = new List<Item>();
        private readonly string _path;
        private readonly Func<Item, Task<bool>> _sender;
        private readonly Action<string> _log;
        private readonly CancellationTokenSource _cts = new CancellationTokenSource();
        private readonly Task _retryLoop;
        private int _pumpRunning;
        private int _recordsSinceCompact;

        public DurableEventOutbox(
            string path,
            Func<Item, Task<bool>> sender,
            Action<string> log)
        {
            _path = path ?? throw new ArgumentNullException(nameof(path));
            _sender = sender ?? throw new ArgumentNullException(nameof(sender));
            _log = log ?? (_ => { });
            Load();
            _retryLoop = Task.Run(() => RetryLoopAsync(_cts.Token));
            TriggerPump();
        }

        public int PendingCount
        {
            get { lock (_gate) return _pending.Count; }
        }

        public bool Enqueue(string moduleId, string eventType, string dataJson)
        {
            if (string.IsNullOrEmpty(moduleId) || string.IsNullOrEmpty(eventType))
                return false;

            // Validate before persisting. A malformed event can never become
            // deliverable by retrying it.
            try { JToken.Parse(string.IsNullOrEmpty(dataJson) ? "{}" : dataJson); }
            catch (Exception ex)
            {
                _log($"[outbox] reject {eventType}: invalid data JSON: {ex.Message}");
                return false;
            }

            var item = new Item
            {
                Id = Guid.NewGuid().ToString("N"),
                ModuleId = moduleId,
                EventType = eventType,
                DataJson = string.IsNullOrEmpty(dataJson) ? "{}" : dataJson,
                TimestampMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                NextAttemptUtc = DateTime.UtcNow,
            };

            lock (_gate)
            {
                try
                {
                    AppendRecordLocked(new { op = "put", item });
                    _pending.Add(item);
                }
                catch (Exception ex)
                {
                    _log($"[outbox] persist FAILED {eventType}: {ex.Message}");
                    return false;
                }
            }

            _log($"[outbox] queued {eventType} id={item.Id} pending={PendingCount}");
            TriggerPump();
            return true;
        }

        private async Task RetryLoopAsync(CancellationToken ct)
        {
            while (!ct.IsCancellationRequested)
            {
                try { await Task.Delay(TimeSpan.FromSeconds(5), ct).ConfigureAwait(false); }
                catch (OperationCanceledException) { break; }
                TriggerPump();
            }
        }

        private void TriggerPump()
        {
            if (_cts.IsCancellationRequested) return;
            if (Interlocked.CompareExchange(ref _pumpRunning, 1, 0) != 0) return;
            Task.Run(PumpAsync);
        }

        private async Task PumpAsync()
        {
            try
            {
                while (!_cts.IsCancellationRequested)
                {
                    Item item;
                    lock (_gate)
                    {
                        item = _pending
                            .Where(x => x.NextAttemptUtc <= DateTime.UtcNow)
                            .OrderBy(x => x.TimestampMs)
                            .FirstOrDefault();
                    }
                    if (item == null) break;

                    bool delivered = false;
                    try { delivered = await _sender(item).ConfigureAwait(false); }
                    catch (Exception ex)
                    {
                        _log($"[outbox] sender crashed {item.EventType}: {ex.Message}");
                    }

                    if (delivered)
                    {
                        bool acknowledgedLocally = false;
                        lock (_gate)
                        {
                            if (_pending.Contains(item))
                            {
                                try
                                {
                                    // Journal the ACK before removing from memory.
                                    // If this disk write fails, retrying the same
                                    // envelope id is safe because backend dedupes it.
                                    AppendRecordLocked(new { op = "ack", id = item.Id });
                                    _pending.Remove(item);
                                    MaybeCompactLocked();
                                    acknowledgedLocally = true;
                                }
                                catch (Exception ex)
                                {
                                    item.Attempts++;
                                    item.NextAttemptUtc = DateTime.UtcNow.AddSeconds(10);
                                    _log($"[outbox] ACK journal FAILED {item.EventType}: {ex.Message}");
                                }
                            }
                        }
                        if (!acknowledgedLocally) break;
                        _log($"[outbox] delivered {item.EventType} id={item.Id} pending={PendingCount}");
                        continue;
                    }

                    item.Attempts++;
                    int delaySeconds = Math.Min(60, 2 << Math.Min(item.Attempts, 5));
                    item.NextAttemptUtc = DateTime.UtcNow.AddSeconds(delaySeconds);
                    _log($"[outbox] retry {item.EventType} id={item.Id} " +
                         $"attempt={item.Attempts} in {delaySeconds}s");
                    // Preserve FIFO for state-changing events. Do not allow a
                    // newer item to overtake the failed one.
                    break;
                }
            }
            finally
            {
                Interlocked.Exchange(ref _pumpRunning, 0);
                // Close the race where an item was queued after the last empty
                // check but before _pumpRunning became zero.
                bool ready;
                lock (_gate)
                    ready = _pending.Any(x => x.NextAttemptUtc <= DateTime.UtcNow);
                if (ready) TriggerPump();
            }
        }

        private void Load()
        {
            lock (_gate)
            {
                try
                {
                    if (!File.Exists(_path)) return;
                    var byId = new Dictionary<string, Item>(StringComparer.Ordinal);
                    foreach (string line in File.ReadLines(_path))
                    {
                        if (string.IsNullOrWhiteSpace(line)) continue;
                        try
                        {
                            var record = JObject.Parse(line);
                            string op = (string)record["op"];
                            if (op == "put")
                            {
                                var item = record["item"]?.ToObject<Item>();
                                if (item != null && !string.IsNullOrEmpty(item.Id))
                                {
                                    item.NextAttemptUtc = DateTime.UtcNow;
                                    byId[item.Id] = item;
                                }
                            }
                            else if (op == "ack")
                            {
                                string id = (string)record["id"];
                                if (!string.IsNullOrEmpty(id)) byId.Remove(id);
                            }
                        }
                        catch { /* tolerate a partial final line after a crash */ }
                    }
                    _pending.AddRange(byId.Values.OrderBy(x => x.TimestampMs));
                    if (_pending.Count > 0)
                        _log($"[outbox] restored {_pending.Count} pending event(s)");
                }
                catch (Exception ex)
                {
                    _log($"[outbox] load FAILED: {ex.Message}");
                }
            }
        }

        private void AppendRecordLocked(object record)
        {
            string directory = Path.GetDirectoryName(_path);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
            File.AppendAllText(
                _path,
                JsonConvert.SerializeObject(record, Formatting.None) + Environment.NewLine);
            _recordsSinceCompact++;
        }

        private void MaybeCompactLocked()
        {
            if (_recordsSinceCompact < 1000) return;
            try
            {
                string temp = _path + ".tmp";
                string directory = Path.GetDirectoryName(_path);
                if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
                using (var writer = new StreamWriter(temp, false))
                {
                    foreach (var item in _pending.OrderBy(x => x.TimestampMs))
                        writer.WriteLine(JsonConvert.SerializeObject(
                            new { op = "put", item }, Formatting.None));
                }
                if (File.Exists(_path))
                {
                    try { File.Replace(temp, _path, null); }
                    catch
                    {
                        File.Copy(temp, _path, true);
                        File.Delete(temp);
                    }
                }
                else File.Move(temp, _path);
                _recordsSinceCompact = 0;
            }
            catch (Exception ex)
            {
                _log($"[outbox] compact warning: {ex.Message}");
            }
        }

        public void Dispose()
        {
            try { _cts.Cancel(); } catch { }
            try { _retryLoop?.Wait(TimeSpan.FromSeconds(1)); } catch { }
            _cts.Dispose();
        }
    }
}
