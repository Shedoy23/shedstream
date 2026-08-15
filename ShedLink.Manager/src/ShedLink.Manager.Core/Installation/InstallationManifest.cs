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

    [JsonPropertyName("artifacts")]
    public required IReadOnlyList<InstallationArtifact> Artifacts { get; init; }

    [JsonPropertyName("installation")]
    public required InstallationRules Installation { get; init; }

    [JsonPropertyName("configuration")]
    public required ConfigurationRules Configuration { get; init; }

    [JsonPropertyName("health")]
    public required IReadOnlyList<HealthProbe> Health { get; init; }
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
}

public sealed record ArtifactSource
{
    [JsonPropertyName("kind")]
    public required string Kind { get; init; }

    [JsonPropertyName("path")]
    public required string Path { get; init; }
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

    [JsonPropertyName("known_folder")]
    public required string KnownFolder { get; init; }

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
