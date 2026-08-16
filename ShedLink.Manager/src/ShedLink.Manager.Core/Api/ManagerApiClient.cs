using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;

namespace ShedLink.Manager.Core.Api;

public sealed class ManagerApiClient
{
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _http;

    public ManagerApiClient(HttpClient http)
    {
        _http = http ?? throw new ArgumentNullException(nameof(http));
        if (_http.BaseAddress is null || !IsSafeBaseAddress(_http.BaseAddress))
        {
            throw new ArgumentException(
                "Manager API requires HTTPS (HTTP is allowed only for loopback tests).",
                nameof(http));
        }
    }

    public Task<PairingCreated> CreatePairingAsync(
        string installationId,
        string moduleId,
        string deviceChallenge,
        CancellationToken cancellationToken = default) =>
        SendAsync<PairingCreated>(
            HttpMethod.Post,
            "/v1/manager/pairings",
            new PairingCreateRequest(installationId, moduleId, deviceChallenge),
            null,
            cancellationToken);

    public Task<ManagerSession> ExchangePairingAsync(
        string pairingId,
        string deviceSecret,
        CancellationToken cancellationToken = default) =>
        SendAsync<ManagerSession>(
            HttpMethod.Post,
            $"/v1/manager/pairings/{Uri.EscapeDataString(pairingId)}/exchange",
            new PairingExchangeRequest(deviceSecret),
            null,
            cancellationToken);

    public Task<ManagerSession> RefreshAsync(
        string refreshToken,
        CancellationToken cancellationToken = default) =>
        SendAsync<ManagerSession>(
            HttpMethod.Post,
            "/v1/manager/session/refresh",
            new RefreshRequest(refreshToken),
            null,
            cancellationToken);

    public Task<ModuleCredential> IssueCredentialAsync(
        string accessToken,
        string moduleId,
        string label,
        CancellationToken cancellationToken = default) =>
        SendAsync<ModuleCredential>(
            HttpMethod.Post,
            "/v1/manager/module-credentials",
            new CredentialRequest(moduleId, label),
            accessToken,
            cancellationToken);

    public Task<ModuleCredential> RotateCredentialAsync(
        string accessToken,
        string credentialId,
        string label,
        CancellationToken cancellationToken = default) =>
        SendAsync<ModuleCredential>(
            HttpMethod.Post,
            $"/v1/manager/module-credentials/{Uri.EscapeDataString(credentialId)}/rotate",
            new CredentialRotateRequest(label),
            accessToken,
            cancellationToken);

    public Task<ModuleAuthCheck> VerifyModuleCredentialAsync(
        string moduleToken,
        string moduleId,
        CancellationToken cancellationToken = default) =>
        SendAsync<ModuleAuthCheck>(
            HttpMethod.Post,
            $"/v1/module/{Uri.EscapeDataString(moduleId)}/auth-check",
            null,
            moduleToken,
            cancellationToken);

    public Task<ModuleRuntimeStatus> GetModuleStatusAsync(
        string moduleToken,
        string moduleId,
        CancellationToken cancellationToken = default) =>
        SendAsync<ModuleRuntimeStatus>(
            HttpMethod.Get,
            $"/v1/module/{Uri.EscapeDataString(moduleId)}/status",
            null,
            moduleToken,
            cancellationToken);

    public Task<DiagnosticStarted> StartDiagnosticAsync(
        string accessToken,
        CancellationToken cancellationToken = default) =>
        StartDiagnosticAsync(accessToken, "ready", cancellationToken);

    public Task<DiagnosticStarted> StartDiagnosticAsync(
        string accessToken,
        string mode,
        CancellationToken cancellationToken = default) =>
        SendAsync<DiagnosticStarted>(
            HttpMethod.Post,
            "/v1/manager/diagnostics/test-action",
            new DiagnosticStartRequest(mode),
            accessToken,
            cancellationToken);

    public Task<DiagnosticResult> GetDiagnosticResultAsync(
        string accessToken,
        string diagnosticId,
        CancellationToken cancellationToken = default) =>
        SendAsync<DiagnosticResult>(
            HttpMethod.Get,
            $"/v1/manager/diagnostics/test-action/{Uri.EscapeDataString(diagnosticId)}",
            null,
            accessToken,
            cancellationToken);

    public Task LogoutAsync(
        string accessToken,
        CancellationToken cancellationToken = default) =>
        SendAsync<object>(
            HttpMethod.Post,
            "/v1/manager/logout",
            null,
            accessToken,
            cancellationToken);

    public Task RevokeCredentialAsync(
        string accessToken,
        string credentialId,
        CancellationToken cancellationToken = default) =>
        SendAsync<object>(
            HttpMethod.Delete,
            $"/v1/manager/module-credentials/{Uri.EscapeDataString(credentialId)}",
            null,
            accessToken,
            cancellationToken);

    private async Task<T> SendAsync<T>(
        HttpMethod method,
        string path,
        object? body,
        string? bearerToken,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(method, path);
        if (body is not null)
        {
            request.Content = JsonContent.Create(body, body.GetType(), options: Json);
        }
        if (!string.IsNullOrWhiteSpace(bearerToken))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue(
                "Bearer", bearerToken);
        }
        using var response = await _http.SendAsync(
            request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        // Pairing uses HTTP 202 as a non-terminal "authorization_pending"
        // state, not as a successful ManagerSession response.
        if (!response.IsSuccessStatusCode || response.StatusCode == System.Net.HttpStatusCode.Accepted)
        {
            var error = await ReadErrorAsync(response, cancellationToken);
            throw new ManagerApiException(response.StatusCode, error);
        }
        if (typeof(T) == typeof(object))
        {
            return (T)(object)new object();
        }
        var result = await response.Content.ReadFromJsonAsync<T>(Json, cancellationToken);
        return result ?? throw new InvalidDataException("Manager API returned an empty response.");
    }

    private static async Task<string> ReadErrorAsync(
        HttpResponseMessage response,
        CancellationToken cancellationToken)
    {
        try
        {
            var error = await response.Content.ReadFromJsonAsync<ApiError>(
                Json, cancellationToken);
            return string.IsNullOrWhiteSpace(error?.Status) ? "request_failed" : error.Status;
        }
        catch (JsonException)
        {
            return "request_failed";
        }
    }

    private static bool IsSafeBaseAddress(Uri address) =>
        address.Scheme == Uri.UriSchemeHttps ||
        (address.Scheme == Uri.UriSchemeHttp && address.IsLoopback);
}
