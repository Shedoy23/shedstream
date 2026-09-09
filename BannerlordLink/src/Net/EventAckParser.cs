using System;

namespace BannerlordLink.Net
{
    /// <summary>
    /// Разбор ответа `POST /v1/module/{id}/events`: подтверждён ли конверт.
    ///
    /// ЗАЧЕМ ОТДЕЛЬНЫМ ФАЙЛОМ. Бэкенд (`routes/module_api.py`) отвечает
    /// `{"status": "ok", "acks": [...]}` ВСЕГДА — даже когда конверт отклонён.
    /// Судьба каждого события лежит внутри `acks`:
    ///   {"id": "...", "success": false, "error": "event_not_in_manifest"}
    /// либо `"error": "&lt;Исключение&gt;: ..."`, если упал обработчик.
    /// `BackendClient.PostEventAsync` до 2026-09-09 проверял только наличие
    /// `"status":"ok"` в теле — и объявлял доставленным то, что сервер
    /// отклонил. Для зеркала состояния героя это означало «замёрзло навсегда».
    ///
    /// Класс намеренно без зависимостей от игры и от HTTP: тестовый harness
    /// подключает ЭТОТ ЖЕ файл и проверяет настоящий разбор, а не его копию.
    /// </summary>
    public static class EventAckParser
    {
        /// <summary>true — сервер подтвердил КАЖДЫЙ конверт в ответе.
        ///
        /// Отсутствие `acks` подтверждением НЕ считается: повторить снимок
        /// дешевле, чем счесть доставленным то, о чём сервер промолчал.
        /// `duplicate: true` при `success: true` — это подтверждение: событие
        /// уже обработано ранее.</summary>
        public static bool IsAcked(string response, out string error)
        {
            error = null;
            if (string.IsNullOrEmpty(response))
            {
                error = "пустой ответ";
                return false;
            }
            try
            {
                var parsed = Newtonsoft.Json.Linq.JObject.Parse(response);
                if (parsed["status"]?.ToString() != "ok")
                {
                    error = "status != ok";
                    return false;
                }
                var acks = parsed["acks"] as Newtonsoft.Json.Linq.JArray;
                if (acks == null || acks.Count == 0)
                {
                    error = "нет acks";
                    return false;
                }
                foreach (var ack in acks)
                {
                    bool success = false;
                    try { success = ack?["success"]?.ToObject<bool>() ?? false; }
                    catch { success = false; }
                    if (success) continue;
                    error = ack?["error"]?.ToString() ?? "success=false";
                    return false;
                }
                return true;
            }
            catch (Exception ex)
            {
                error = $"ответ не разобран: {ex.GetType().Name}";
                return false;
            }
        }
    }
}
