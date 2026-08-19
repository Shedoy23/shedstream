using System.Threading.Tasks;
using Newtonsoft.Json.Linq;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// End-to-end Manager readiness probe. It deliberately does not inspect or
    /// mutate game state: receiving, dispatching and ACKing it proves that the
    /// installed mod and the authenticated backend action channel both work.
    /// </summary>
    public sealed class DiagnosticPingHandler : IActionHandler
    {
        public string ActionType => "diagnostic_ping";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            BannerlordLinkModule.Log("  ↳ Manager diagnostic ping OK");
            return Task.FromResult<(bool, string)>((true, null));
        }
    }
}
