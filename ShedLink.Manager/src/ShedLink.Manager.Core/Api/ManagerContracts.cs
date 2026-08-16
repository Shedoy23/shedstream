using System.Text.Json.Serialization;

namespace ShedLink.Manager.Core.Api;

public sealed record PairingCreated(
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("pairing_id")] string PairingId,
    [property: JsonPropertyName("user_code")] string UserCode,
    [property: JsonPropertyName("verification_uri")] Uri VerificationUri,
    [property: JsonPropertyName("expires_at")] double ExpiresAt,
    [property: JsonPropertyName("expires_in")] int ExpiresIn,
    [property: JsonPropertyName("interval")] int Interval);

public sealed record ManagerSession(
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("access_token")] string AccessToken,
    [property: JsonPropertyName("access_expires_at")] long AccessExpiresAt,
    [property: JsonPropertyName("refresh_token")] string RefreshToken,
    [property: JsonPropertyName("session_expires_at")] double SessionExpiresAt,
    [property: JsonPropertyName("channel_id")] long ChannelId,
    [property: JsonPropertyName("module_id")] string ModuleId);

public sealed record ModuleCredential(
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("credential_id")] string CredentialId,
    [property: JsonPropertyName("module_token")] string ModuleToken,
    [property: JsonPropertyName("module_id")] string ModuleId,
    [property: JsonPropertyName("channel_id")] long ChannelId,
    [property: JsonPropertyName("label")] string Label,
    [property: JsonPropertyName("expires_at")] double ExpiresAt,
    [property: JsonPropertyName("overlap_until")] double? OverlapUntil = null);

public sealed record ModuleAuthCheck(
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("module_id")] string ModuleId);

public sealed record ModuleRuntimeStatus(
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("module_id")] string ModuleId,
    [property: JsonPropertyName("online")] bool Online,
    [property: JsonPropertyName("last_seen_at")] double? LastSeenAt,
    [property: JsonPropertyName("age_seconds")] int? AgeSeconds,
    [property: JsonPropertyName("online_window_seconds")] int OnlineWindowSeconds);

internal sealed record PairingCreateRequest(
    string InstallationId,
    string ModuleId,
    string DeviceChallenge);

internal sealed record PairingExchangeRequest(string DeviceSecret);

internal sealed record RefreshRequest(string RefreshToken);

internal sealed record CredentialRequest(string ModuleId, string Label);

internal sealed record ApiError(string? Status);
