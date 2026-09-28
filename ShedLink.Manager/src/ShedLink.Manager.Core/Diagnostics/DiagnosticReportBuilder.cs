using System.Text.Json;
using System.Text.Encodings.Web;
using System.Text.RegularExpressions;

namespace ShedLink.Manager.Core.Diagnostics;

public sealed record DiagnosticReportInput(
    string ManagerVersion,
    string ApiVersion,
    string BackendOrigin,
    string? GameVersion,
    string GameCompatibility,
    string? IntegrationVersion,
    string InstallationCondition,
    string InstallationReason,
    IReadOnlyList<string> FailedHealthProbes,
    bool? ModuleOnline,
    int? HeartbeatAgeSeconds,
    IReadOnlyList<string> RecentMessages);

public static class DiagnosticReportBuilder
{
    private static readonly JsonSerializerOptions Json = new()
    {
        WriteIndented = true,
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    public static string Build(DiagnosticReportInput input)
    {
        var report = new
        {
            schema_version = 2,
            generated_at_utc = DateTimeOffset.UtcNow,
            versions = new
            {
                manager = Redact(input.ManagerVersion),
                api = Redact(input.ApiVersion),
                game = DisplayValue(input.GameVersion),
                integration = DisplayValue(input.IntegrationVersion),
            },
            backend_origin = SafeOrigin(input.BackendOrigin),
            installation = new
            {
                condition = Redact(input.InstallationCondition),
                reason = Redact(input.InstallationReason),
                game_compatibility = Redact(input.GameCompatibility),
                failed_health_probes = input.FailedHealthProbes.Select(Redact).ToArray(),
            },
            runtime = new
            {
                module_online = input.ModuleOnline,
                heartbeat_age_seconds = input.HeartbeatAgeSeconds,
            },
            recent_messages = input.RecentMessages.Select(Redact).ToArray(),
            privacy = "Secrets, cookies, usernames and user-profile paths are excluded or redacted.",
        };
        return JsonSerializer.Serialize(report, Json);
    }

    private static string DisplayValue(string? value) =>
        string.IsNullOrWhiteSpace(value) ? "unknown/unmanaged" : Redact(value);

    public static string Redact(string? value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return value ?? string.Empty;
        }
        var redacted = Regex.Replace(
            value, @"(?i)slmod_v1\.[A-Za-z0-9._-]+", "<redacted-token>");
        redacted = Regex.Replace(
            redacted, @"(?i)(bearer\s+)[^\s,;\""']+", "$1<redacted-token>");
        redacted = Regex.Replace(
            redacted,
            @"(?i)((?:token|cookie|authorization|password|secret)\s*[:=]\s*)[^\s,;\""']+",
            "$1<redacted>");
        return Regex.Replace(
            redacted, @"(?i)\b[A-Z]:\\Users\\[^\\/\s\""']+", @"C:\Users\<redacted>");
    }

    private static string SafeOrigin(string raw)
    {
        if (Uri.TryCreate(raw, UriKind.Absolute, out var uri))
        {
            return uri.GetLeftPart(UriPartial.Authority);
        }
        return Redact(raw);
    }
}
