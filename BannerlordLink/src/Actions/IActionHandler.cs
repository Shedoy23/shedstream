using System.Threading.Tasks;
using Newtonsoft.Json.Linq;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Интерфейс handler'а для одного action_type из manifest.yaml.
    ///
    /// Регистрируется в ActionRegistry. Action poller достаёт queued
    /// actions с backend, dispatch'ит к handler'у по type, ACK'ает успех.
    ///
    /// Sprint 2.4: только EchoHandler (test stub).
    /// Sprint 3+: реальные handlers (SummonHeroHandler, GiveItemHandler, и т.д.)
    /// </summary>
    public interface IActionHandler
    {
        /// <summary>Action type из manifest, e.g. "player.heal".</summary>
        string ActionType { get; }

        /// <summary>Выполнить action. Возвращает (success, optional error).</summary>
        /// <param name="data">JSON data из envelope (payload action'а)</param>
        Task<(bool success, string error)> ExecuteAsync(JObject data);
    }
}
