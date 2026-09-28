using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Util
{
    // All registry reads and TextObject localization happen on the game thread.
    // Only the resulting strings may cross into the background publisher.
    internal static class RuntimeGameCatalogs
    {
        internal static List<CharacterObject> CreationTemplates(string requestedCulture, out string reason)
        {
            var cultures = MBObjectManager.Instance.GetObjectTypeList<CultureObject>();
            var templates = MBObjectManager.Instance.GetObjectTypeList<CharacterObject>()
                .Where(c => c != null && c.Occupation == Occupation.Wanderer).ToList();
            reason = null;
            if (!string.IsNullOrEmpty(requestedCulture))
            {
                var culture = cultures.FirstOrDefault(c => c != null &&
                    string.Equals(c.StringId, requestedCulture, StringComparison.Ordinal));
                if (culture == null)
                {
                    reason = "culture_not_found";
                    return new List<CharacterObject>();
                }
                templates = templates.Where(c => c.Culture == culture).ToList();
                if (templates.Count == 0) reason = "culture_no_wanderer_templates";
            }
            else if (templates.Count == 0) reason = "no_wanderer_templates";
            return templates;
        }

        internal static string ValidateSession(string requestedSave, string requestedSession,
            string currentSave, string currentSession)
        {
            if (requestedSave != null && requestedSave != currentSave) return "stale_hero_session";
            if (requestedSession != null && requestedSession != currentSession) return "stale_equipment_session";
            return null;
        }

        private static JObject Entry(string id, string name, string description)
            => new JObject { ["id"] = id, ["name"] = string.IsNullOrEmpty(name) ? id : name,
                ["description"] = description ?? "" };

        internal static List<string> Build(string saveId, string sessionId, long sequence)
        {
            if (sequence <= 0) throw new ArgumentOutOfRangeException(nameof(sequence));
            var cultures = new JArray();
            foreach (var culture in MBObjectManager.Instance.GetObjectTypeList<CultureObject>())
            {
                if (culture == null || string.IsNullOrEmpty(culture.StringId)) continue;
                var row = Entry(culture.StringId, culture.Name?.ToString(), culture.EncyclopediaText?.ToString());
                CreationTemplates(culture.StringId, out var reason);
                row["available"] = reason == null;
                if (reason != null) row["unavailable_reason"] = reason;
                cultures.Add(row);
            }
            var policies = new JArray();
            foreach (var policy in PolicyObject.All)
            {
                if (policy == null || string.IsNullOrEmpty(policy.StringId)) continue;
                var description = string.Join("\n", new[] { policy.Description?.ToString(), policy.SecondaryEffects?.ToString() }
                    .Where(s => !string.IsNullOrWhiteSpace(s)).Distinct());
                policies.Add(Entry(policy.StringId, policy.Name?.ToString(), description));
            }
            var skills = new JArray(MBObjectManager.Instance.GetObjectTypeList<SkillObject>()
                .Where(s => s != null && !string.IsNullOrEmpty(s.StringId))
                .Select(s => Entry(s.StringId, s.Name?.ToString(), s.Description?.ToString())));
            var attributes = new JArray(MBObjectManager.Instance.GetObjectTypeList<CharacterAttribute>()
                .Where(a => a != null && !string.IsNullOrEmpty(a.StringId))
                .Select(a => Entry(a.StringId, a.Name?.ToString(), a.Description?.ToString())));
            var result = new List<string>();
            foreach (var catalog in new[] { ("cultures", cultures), ("policies", policies), ("skills", skills), ("attributes", attributes) })
                result.Add(new JObject { ["catalog"] = catalog.Item1, ["save_id"] = saveId,
                    ["equipment_session_id"] = sessionId, ["catalog_seq"] = sequence,
                    ["entries"] = catalog.Item2 }.ToString(Formatting.None));
            return result;
        }
    }

    // One publisher owns a batch. A refusal/exception preserves the failed
    // payload and revision; retries never rebuild snapshots on the worker.
    internal sealed class CatalogSnapshotBatch
    {
        private readonly string[] _payloads;
        private int _next;
        internal CatalogSnapshotBatch(IEnumerable<string> payloads) { _payloads = payloads.ToArray(); }
        internal async Task<bool> PublishAsync(Func<string, Task<bool>> send)
        {
            while (_next < _payloads.Length)
            {
                if (!await send(_payloads[_next])) return false;
                _next++;
            }
            return true;
        }
    }
}
