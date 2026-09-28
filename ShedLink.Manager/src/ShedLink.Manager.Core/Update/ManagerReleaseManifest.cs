using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace ShedLink.Manager.Core.Update;

public sealed record ManagerReleaseManifest
{
    [JsonPropertyName("schema_version")]
    public required int SchemaVersion { get; init; }

    [JsonPropertyName("product")]
    public required string Product { get; init; }

    [JsonPropertyName("version")]
    public required string Version { get; init; }

    [JsonPropertyName("artifact")]
    public required ManagerReleaseArtifact Artifact { get; init; }
}

public sealed record ManagerReleaseArtifact
{
    [JsonPropertyName("id")]
    public required string Id { get; init; }

    [JsonPropertyName("url")]
    public required Uri Url { get; init; }

    [JsonPropertyName("size_bytes")]
    public required long SizeBytes { get; init; }

    [JsonPropertyName("sha256")]
    public required string Sha256 { get; init; }

    [JsonPropertyName("format")]
    public required string Format { get; init; }

    [JsonPropertyName("archive_root")]
    public required string ArchiveRoot { get; init; }

    [JsonPropertyName("signature")]
    public required ManagerReleaseSignature Signature { get; init; }
}

public sealed record ManagerReleaseSignature
{
    [JsonPropertyName("algorithm")]
    public required string Algorithm { get; init; }

    [JsonPropertyName("key_id")]
    public required string KeyId { get; init; }

    [JsonPropertyName("value")]
    public required string Value { get; init; }
}

public static partial class ManagerReleaseManifestLoader
{
    public const string ProductId = "shedlink-manager";

    public static ManagerReleaseManifest Parse(string json)
    {
        ManagerReleaseManifest manifest;
        try
        {
            manifest = JsonSerializer.Deserialize<ManagerReleaseManifest>(json)
                ?? throw new InvalidDataException("Manager release manifest is empty.");
        }
        catch (JsonException exception)
        {
            throw new InvalidDataException("Manager release manifest is malformed.", exception);
        }
        Validate(manifest);
        return manifest;
    }

    private static void Validate(ManagerReleaseManifest manifest)
    {
        if (manifest.SchemaVersion != 1 || manifest.Product != ProductId ||
            !ManagerVersion.IsValid(manifest.Version))
        {
            throw new InvalidDataException("Unsupported manager release identity.");
        }
        var artifact = manifest.Artifact;
        if (artifact.Format != "zip" || artifact.SizeBytes <= 0 ||
            !Sha256Regex().IsMatch(artifact.Sha256) ||
            !IdentifierRegex().IsMatch(artifact.Id))
        {
            throw new InvalidDataException("Unsupported or invalid manager artifact contract.");
        }
        if (!artifact.Url.IsAbsoluteUri || artifact.Url.Scheme != Uri.UriSchemeHttps ||
            !string.IsNullOrEmpty(artifact.Url.UserInfo) ||
            string.IsNullOrWhiteSpace(artifact.Url.Host))
        {
            throw new InvalidDataException("Manager update requires a safe HTTPS URL.");
        }
        if (artifact.Signature.Algorithm != "rsa-pss-sha256" ||
            !IdentifierRegex().IsMatch(artifact.Signature.KeyId) ||
            string.IsNullOrWhiteSpace(artifact.Signature.Value))
        {
            throw new InvalidDataException("Manager update requires a publisher signature.");
        }
        Installation.PathBoundary.ValidateRelative(artifact.ArchiveRoot);
    }

    [GeneratedRegex("^[a-z][a-z0-9_-]{0,63}$", RegexOptions.CultureInvariant)]
    private static partial Regex IdentifierRegex();

    [GeneratedRegex("^[a-f0-9]{64}$", RegexOptions.CultureInvariant)]
    private static partial Regex Sha256Regex();
}
