using System.Threading.Tasks;
using Newtonsoft.Json.Linq;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Test stub handler — log + success for action types still on the TODO list.
    ///
    /// Зарегистрирован для всех «non-implemented» action types в Sprint 2.4.
    /// Когда придут real handlers (Sprint 3) — будут регистрироваться по type
    /// и Echo останется только как default fallback.
    ///
    /// Sprint 5.31 #45g (codegraph audit HIGH-1) — раньше Echo возвращал
    /// `(true, null)` → backend ACK'ал action как applied, viewer'у списывались
    /// крустики (особенно `world.trigger_event` за 1000⦷), а в игре НИЧЕГО
    /// не происходило. Теперь возвращаем `(false, "not_implemented")` +
    /// PostFailed для refund. Viewer получает обратно крустики, в логах
    /// streamer'а виден "REFUSE: not implemented yet" — становится понятно
    /// что фича в TODO. ACTION_PRICES для этих action_type должны быть 0
    /// (бесплатные стабы) пока handler реальный не появился.
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
            BannerlordLinkModule.Log(
                $"  ↳ Echo[{_type}] REFUSE: not implemented yet. data={preview}");
            // Refund крустиков через action.failed event, если backend назначил
            // цену action_type (иначе PostFailed нop'нет на actionId="").
            string actionId = BannerlordLink.Util.ActionFeedback.GetActionId(data);
            BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "not_implemented:" + _type);
            return Task.FromResult<(bool, string)>((false, "not_implemented"));
        }
    }
}
