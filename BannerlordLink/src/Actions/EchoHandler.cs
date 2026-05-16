using System.Threading.Tasks;
using Newtonsoft.Json.Linq;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Test stub handler — просто log + success.
    ///
    /// Зарегистрирован для всех «non-implemented» action types в Sprint 2.4.
    /// Когда придут real handlers (Sprint 3) — будут регистрироваться по type
    /// и Echo останется только как default fallback.
    /// </summary>
    public class EchoHandler : IActionHandler
    {
        private readonly string _type;
        public string ActionType => _type;
        public EchoHandler(string type) { _type = type; }

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string preview = data?.ToString(Newtonsoft.Json.Formatting.None) ?? "{}";
            if (preview.Length > 200) preview = preview.Substring(0, 200) + "...";
            BannerlordLinkModule.Log($"  ↳ Echo[{_type}] data={preview}");
            return Task.FromResult<(bool, string)>((true, null));
        }
    }
}
