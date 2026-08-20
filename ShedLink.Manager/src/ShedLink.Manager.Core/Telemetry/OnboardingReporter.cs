using System.Text.Json;
using ShedLink.Manager.Core.Api;

namespace ShedLink.Manager.Core.Telemetry;

/// <summary>
/// Пишет шаги воронки онбординга и отправляет их пачками.
///
/// ROADMAP §R4 требует видеть путь незнакомого стримера от запуска Manager до
/// первого действия его зрителя. Самое ценное в этом пути — места, где человек
/// уходит, и они по определению случаются там, где ничего не работает: сети
/// нет, бэкенд лежит, вход не пройден. Поэтому события сначала ложатся на диск
/// и только потом уезжают.
///
/// ДВА ПРАВИЛА, которые здесь важнее аккуратности кода:
///
/// 1. Телеметрия НИКОГДА не ломает продукт. Любая ошибка внутри проглатывается.
///    Установка не имеет права упасть из-за того, что не записалась метрика.
/// 2. Телеметрия НИКОГДА не задерживает продукт. Запись — это дозапись в файл,
///    отправка — отдельный вызов, который никто не ждёт.
///
/// Буфер ограничен: долгая работа без сети не должна раздувать файл. При
/// переполнении выбрасываются САМЫЕ СТАРЫЕ события, потому что свежий отрезок
/// пути важнее давнего.
/// </summary>
public sealed class OnboardingReporter
{
    private const int MaxBuffered = 200;

    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    private readonly ManagerApiClient _api;
    private readonly string _bufferPath;
    private readonly string _installationId;
    private readonly string _managerVersion;
    private readonly object _gate = new();

    public OnboardingReporter(
        ManagerApiClient api,
        string installationId,
        string managerVersion,
        string? bufferPath = null)
    {
        _api = api;
        _installationId = installationId;
        _managerVersion = managerVersion;
        _bufferPath = bufferPath ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "ShedLink", "Manager", "onboarding-queue.json");
    }

    /// <summary>
    /// Записать шаг. Возвращает управление сразу; ничего не бросает.
    /// `result` — КОД, а не сообщение: сообщение может содержать путь на диске.
    /// </summary>
    public void Record(
        string eventName,
        string? integrationId = null,
        string? integrationVersion = null,
        long? elapsedMs = null,
        string? result = null,
        string? sourceStep = null)
    {
        try
        {
            var item = new OnboardingEvent(
                eventName,
                _installationId,
                integrationId,
                integrationVersion,
                _managerVersion,
                elapsedMs,
                result,
                sourceStep,
                Guid.NewGuid().ToString("N"));
            lock (_gate)
            {
                var queue = ReadUnlocked();
                queue.Add(item);
                if (queue.Count > MaxBuffered)
                {
                    queue.RemoveRange(0, queue.Count - MaxBuffered);
                }
                WriteUnlocked(queue);
            }
        }
        catch
        {
            // Метрика не стоит того, чтобы из-за неё что-то сломалось.
        }
    }

    /// <summary>
    /// Отправить накопленное. Успех — очередь очищается; неудача — остаётся до
    /// следующего раза. Ничего не бросает и не сообщает пользователю: он не
    /// просил телеметрию и не должен видеть её проблемы.
    /// </summary>
    public async Task FlushAsync(
        string? accessToken = null,
        CancellationToken cancellationToken = default)
    {
        List<OnboardingEvent> batch;
        try
        {
            lock (_gate)
            {
                batch = ReadUnlocked();
            }
            if (batch.Count == 0)
            {
                return;
            }
            // Бэкенд принимает до 50 событий за раз.
            var chunk = batch.Count > 50 ? batch.GetRange(0, 50) : batch;
            await _api.PostOnboardingAsync(chunk, accessToken, cancellationToken);
            lock (_gate)
            {
                var current = ReadUnlocked();
                var sentIds = new HashSet<string>(
                    chunk.Select(e => e.ClientEventId ?? string.Empty),
                    StringComparer.Ordinal);
                current.RemoveAll(e => sentIds.Contains(e.ClientEventId ?? string.Empty));
                WriteUnlocked(current);
            }
        }
        catch
        {
            // Нет сети или бэкенд молчит — события остаются в очереди.
        }
    }

    public int PendingCount()
    {
        try
        {
            lock (_gate)
            {
                return ReadUnlocked().Count;
            }
        }
        catch
        {
            return 0;
        }
    }

    private List<OnboardingEvent> ReadUnlocked()
    {
        if (!File.Exists(_bufferPath))
        {
            return new List<OnboardingEvent>();
        }
        try
        {
            var text = File.ReadAllText(_bufferPath);
            return JsonSerializer.Deserialize<List<OnboardingEvent>>(text, Json)
                   ?? new List<OnboardingEvent>();
        }
        catch (JsonException)
        {
            // Битый буфер не должен блокировать запись новых событий.
            return new List<OnboardingEvent>();
        }
    }

    private void WriteUnlocked(List<OnboardingEvent> queue)
    {
        var directory = Path.GetDirectoryName(_bufferPath);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }
        var temporary = _bufferPath + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(queue, Json));
        File.Move(temporary, _bufferPath, overwrite: true);
    }
}
