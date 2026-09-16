using System;
using System.Threading;
using System.Threading.Tasks;

namespace BannerlordLink.Util
{
    // Retry the original epoch, never assign retries a newer timestamp that
    // could supersede a subsequently loaded campaign on the backend.
    internal sealed class EquipmentSessionHandshake
    {
        private readonly string _payload;
        private readonly long _timestamp;
        private readonly SemaphoreSlim _gate = new SemaphoreSlim(1, 1);
        private bool _acked;
        internal EquipmentSessionHandshake(string payload, long timestamp)
        { _payload = payload; _timestamp = timestamp; }

        internal async Task<bool> EnsureAsync(Func<string, long, Task<bool>> send)
        {
            await _gate.WaitAsync().ConfigureAwait(false);
            try
            {
                if (!_acked) _acked = await send(_payload, _timestamp).ConfigureAwait(false);
                return _acked;
            }
            finally { _gate.Release(); }
        }
    }
}
