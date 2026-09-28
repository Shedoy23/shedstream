using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace BannerlordLink.Net
{
    /// <summary>
    /// Durable terminal outcomes for mod actions. The journal closes the common
    /// crash/restart window where a gameplay effect was committed but its ACK was
    /// lost. Re-delivery then repeats the recorded result, not the effect.
    /// </summary>
    internal sealed class ActionOutcomeStore
    {
        internal sealed class Outcome
        {
            public string ActionId;
            public bool Success;
            public string Error;
            public DateTime CompletedAtUtc;
        }

        private readonly object _gate = new object();
        private readonly Dictionary<string, Outcome> _outcomes =
            new Dictionary<string, Outcome>(StringComparer.Ordinal);
        private readonly string _path;
        private readonly Action<string> _log;
        private readonly TimeSpan _ttl;
        private readonly int _maxCount;
        private int _recordsSinceCompact;

        public ActionOutcomeStore(
            string path,
            Action<string> log,
            TimeSpan ttl,
            int maxCount)
        {
            _path = path;
            _log = log ?? (_ => { });
            _ttl = ttl;
            _maxCount = Math.Max(100, maxCount);
            Load();
        }

        public bool TryGet(string actionId, out Outcome outcome)
        {
            lock (_gate)
            {
                outcome = null;
                if (string.IsNullOrEmpty(actionId)
                    || !_outcomes.TryGetValue(actionId, out var found))
                    return false;
                if (found.CompletedAtUtc < DateTime.UtcNow.Subtract(_ttl))
                {
                    _outcomes.Remove(actionId);
                    return false;
                }
                outcome = found;
                return true;
            }
        }

        public bool Record(string actionId, bool success, string error)
        {
            if (string.IsNullOrEmpty(actionId)) return false;
            var outcome = new Outcome
            {
                ActionId = actionId,
                Success = success,
                Error = error,
                CompletedAtUtc = DateTime.UtcNow,
            };

            lock (_gate)
            {
                // Keep the in-memory guard even if persistence is temporarily
                // unavailable. This still prevents duplicate Apply in the
                // current game process.
                _outcomes[actionId] = outcome;
                try
                {
                    string directory = Path.GetDirectoryName(_path);
                    if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
                    File.AppendAllText(
                        _path,
                        JsonConvert.SerializeObject(outcome, Formatting.None)
                        + Environment.NewLine);
                    _recordsSinceCompact++;
                    PruneLocked();
                    if (_recordsSinceCompact >= 1000) CompactLocked();
                    return true;
                }
                catch (Exception ex)
                {
                    _log($"[action-outcomes] persist FAILED action[{actionId}]: {ex.Message}");
                    return false;
                }
            }
        }

        private void Load()
        {
            lock (_gate)
            {
                try
                {
                    if (!File.Exists(_path)) return;
                    foreach (string line in File.ReadLines(_path))
                    {
                        if (string.IsNullOrWhiteSpace(line)) continue;
                        try
                        {
                            var outcome = JObject.Parse(line).ToObject<Outcome>();
                            if (outcome != null && !string.IsNullOrEmpty(outcome.ActionId))
                                _outcomes[outcome.ActionId] = outcome;
                        }
                        catch { /* tolerate a partial final record after a crash */ }
                    }
                    PruneLocked();
                    if (_outcomes.Count > 0)
                        _log($"[action-outcomes] restored {_outcomes.Count} terminal outcome(s)");
                }
                catch (Exception ex)
                {
                    _log($"[action-outcomes] load FAILED: {ex.Message}");
                }
            }
        }

        private void PruneLocked()
        {
            DateTime cutoff = DateTime.UtcNow.Subtract(_ttl);
            foreach (string id in _outcomes
                .Where(x => x.Value.CompletedAtUtc < cutoff)
                .Select(x => x.Key)
                .ToList())
            {
                _outcomes.Remove(id);
            }

            int overflow = _outcomes.Count - _maxCount;
            if (overflow > 0)
            {
                foreach (string id in _outcomes
                    .OrderBy(x => x.Value.CompletedAtUtc)
                    .Take(overflow)
                    .Select(x => x.Key)
                    .ToList())
                {
                    _outcomes.Remove(id);
                }
            }
        }

        private void CompactLocked()
        {
            try
            {
                string temp = _path + ".tmp";
                using (var writer = new StreamWriter(temp, false))
                {
                    foreach (var outcome in _outcomes.Values
                        .OrderBy(x => x.CompletedAtUtc))
                    {
                        writer.WriteLine(JsonConvert.SerializeObject(
                            outcome, Formatting.None));
                    }
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
                _log($"[action-outcomes] compact warning: {ex.Message}");
            }
        }
    }
}
