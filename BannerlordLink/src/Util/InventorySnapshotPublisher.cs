using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
namespace BannerlordLink.Util
{
    // One in-flight request and only the latest waiting snapshot per hero.
    internal sealed class InventorySnapshotPublisher
    {
        private readonly object _gate=new object();
        private readonly Dictionary<string,string> _pending=new Dictionary<string,string>();
        private readonly Dictionary<string,(string content, DateTime sent)> _sent=new Dictionary<string,(string,DateTime)>();
        private bool _running;
        private readonly Func<DateTime> _now;
        internal InventorySnapshotPublisher(Func<DateTime> now = null) { _now = now ?? (() => DateTime.UtcNow); }
        internal void Queue(string json, Func<string,Task<bool>> send)
        {
            var row=JObject.Parse(json);
            string key=(string)row["equipment_session_id"]+"/"+(string)row["hero_id"]+"/"+(string)row["username"];
            lock (_gate) {
                _pending[key]=json;
                if (_running) return;
                _running=true;
            }
            Task.Run(async () => {
                while (true) {
                    string nextKey,next;
                    lock (_gate) {
                        if (_pending.Count==0) { _running=false; return; }
                        var entry=_pending.First(); nextKey=entry.Key; next=entry.Value; _pending.Remove(nextKey);
                    }
                    var payload=JObject.Parse(next); payload.Remove("inventory_seq");
                    string content=payload.ToString(Formatting.None);
                    lock (_gate) {
                        if (_sent.TryGetValue(nextKey,out var old) && old.content==content && (_now()-old.sent).TotalSeconds<120) continue;
                    }
                    bool ok=false;
                    try { ok=await send(next); } catch (Exception ex) { BannerlordLinkModule.Log("[Inventory] retry: "+ex.Message); }
                    lock (_gate) {
                        if (ok) _sent[nextKey]=(content,_now());
                        else {
                            if (!_pending.ContainsKey(nextKey)) _pending[nextKey]=next;
                            _running=false; return; // next publication retries; no tight failure loop
                        }
                    }
                }
            });
        }
    }
}
