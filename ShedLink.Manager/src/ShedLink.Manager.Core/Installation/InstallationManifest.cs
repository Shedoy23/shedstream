using System.Text.Json.Serialization;

namespace ShedLink.Manager.Core.Installation;

public sealed record InstallationManifest
{
    [JsonPropertyName("schema_version")]
    public required int SchemaVersion { get; init; }

    [JsonPropertyName("integration_id")]
    public required string IntegrationId { get; init; }

    [JsonPropertyName("release_version")]
    public required string ReleaseVersion { get; init; }

    [JsonPropertyName("game")]
    public ManifestGame? Game { get; init; }

    [JsonPropertyName("prerequisites")]
    public IReadOnlyList<InstallationPrerequisite> Prerequisites { get; init; } =
        Array.Empty<InstallationPrerequisite>();

    [JsonPropertyName("artifacts")]
    public required IReadOnlyList<InstallationArtifact> Artifacts { get; init; }

    [JsonPropertyName("installation")]
    public required InstallationRules Installation { get; init; }

    [JsonPropertyName("configuration")]
    public required ConfigurationRules Configuration { get; init; }

    [JsonPropertyName("health")]
    public required IReadOnlyList<HealthProbe> Health { get; init; }

    [JsonPropertyName("security")]
    public required ManifestSecurity Security { get; init; }
}

public sealed record InstallationPrerequisite
{
    [JsonPropertyName("id")]
    public required string Id { get; init; }

    [JsonPropertyName("path_pattern")]
    public string? PathPattern { get; init; }

    [JsonPropertyName("message")]
    public string? Message { get; init; }

    [JsonPropertyName("help_url")]
    public Uri? HelpUrl { get; init; }
}

public sealed record ManifestGame
{
    [JsonPropertyName("id")]
    public required string Id { get; init; }

    [JsonPropertyName("display_name")]
    public required string DisplayName { get; init; }

    [JsonPropertyName("supported_versions")]
    public required IReadOnlyList<string> SupportedVersions { get; init; }

    [JsonPropertyName("detection")]
    public IReadOnlyList<GameDetectionRule>? Detection { get; init; }

    [JsonPropertyName("process_names")]
    public IReadOnlyList<string>? ProcessNames { get; init; }

    [JsonPropertyName("version")]
    public GameVersionSource? Version { get; init; }
}

public sealed record GameDetectionRule
{
    [JsonPropertyName("kind")]
    public required string Kind { get; init; }

    [JsonPropertyName("app_id")]
    public long? AppId { get; init; }

    [JsonPropertyName("install_dir")]
    public string? InstallDir { get; init; }

    [JsonPropertyName("required_paths")]
    public IReadOnlyList<string>? RequiredPaths { get; init; }
}

public sealed record GameVersionSource
{
    [JsonPropertyName("kind")]
    public required string Kind { get; init; }

    [JsonPropertyName("path")]
    public required string Path { get; init; }

    [JsonPropertyName("compatibility_pattern")]
    public required string CompatibilityPattern { get; init; }
}

public sealed record InstallationArtifact
{
    [JsonPropertyName("id")]
    public required string Id { get; init; }

    [JsonPropertyName("source")]
    public required ArtifactSource Source { get; init; }

    [JsonPropertyName("size_bytes")]
    public required long SizeBytes { get; init; }

    [JsonPropertyName("sha256")]
    public required string Sha256 { get; init; }

    [JsonPropertyName("format")]
    public required string Format { get; init; }

    [JsonPropertyName("archive_root")]
    public required string ArchiveRoot { get; init; }

    [JsonPropertyName("signature")]
    public ArtifactSignature? Signature { get; init; }
}

public sealed record ArtifactSource
{
    [JsonPropertyName("kind")]
    public required string Kind { get; init; }

    [JsonPropertyName("path")]
    public string? Path { get; init; }

    [JsonPropertyName("url")]
    public Uri? Url { get; init; }
}

public sealed record ArtifactSignature
{
    [JsonPropertyName("algorithm")]
    public required string Algorithm { get; init; }

    [JsonPropertyName("key_id")]
    public required string KeyId { get; init; }

    [JsonPropertyName("value")]
    public required string Value { get; init; }
}

public sealed record ManifestSecurity
{
    [JsonPropertyName("publisher")]
    public required string Publisher { get; init; }

    [JsonPropertyName("signature_status")]
    public required string SignatureStatus { get; init; }
}

public sealed record InstallationRules
{
    [JsonPropertyName("target")]
    public required InstallationTarget Target { get; init; }
}

public sealed record InstallationTarget
{
    [JsonPropertyName("base")]
    public required string Base { get; init; }

    [JsonPropertyName("relative_path")]
    public required string RelativePath { get; init; }

    [JsonPropertyName("kind")]
    public string Kind { get; init; } = "directory";
}

public sealed record ConfigurationRules
{
    [JsonPropertyName("store")]
    public required ConfigurationStore Store { get; init; }

    [JsonPropertyName("managed_fields")]
    public required IReadOnlyList<ManagedField> ManagedFields { get; init; }
}

public sealed record ConfigurationStore
{
    [JsonPropertyName("kind")]
    public required string Kind { get; init; }

    [JsonPropertyName("base")]
    public required string Base { get; init; }

    [JsonPropertyName("relative_path")]
    public required string RelativePath { get; init; }
}

public sealed record ManagedField
{
    [JsonPropertyName("name")]
    public required string Name { get; init; }

    [JsonPropertyName("selector")]
    public required string Selector { get; init; }

    [JsonPropertyName("value_source")]
    public required string ValueSource { get; init; }

    [JsonPropertyName("secret")]
    public required bool Secret { get; init; }
}

public sealed record HealthProbe
{
    [JsonPropertyName("id")]
    public required string Id { get; init; }

    [JsonPropertyName("kind")]
    public required string Kind { get; init; }

    [JsonPropertyName("path")]
    public string? Path { get; init; }

    [JsonPropertyName("required")]
    public required bool Required { get; init; }
}
