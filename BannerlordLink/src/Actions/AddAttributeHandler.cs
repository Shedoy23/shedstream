using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
namespace BannerlordLink.Actions
{
    public class AddAttributeHandler : IActionHandler
    {
        public string ActionType => "hero.add_attribute";
        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "").Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username)) return Task.FromResult<(bool,string)>((false,"no username"));
            var request = (JObject)data.DeepClone();
            MainThreadDispatcher.Enqueue(() => ProgressionPurchase.Apply(username, request, false));
            return Task.FromResult<(bool,string)>((true,null));
        }
    }
}
