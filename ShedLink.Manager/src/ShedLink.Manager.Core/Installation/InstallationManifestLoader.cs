using System.Text.Json;
using System.Text.RegularExpressions;

namespace ShedLink.Manager.Core.Installation;

public static partial class InstallationManifestLoader
{
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNameCaseInsensitive = false,
    };

    public static InstallationManifest Load(string path)
    {
        var manifest = JsonSerializer.Deserialize<InstallationManifest>(
            File.ReadAllText(path), Json)
            ?? throw new InvalidDataException("Installation manifest is empty.");
        Validate(manifest);
        return manifest;
    }

    private static void Validate(InstallationManifest manifest)
    {
        if (manifest.SchemaVersion != 1 ||
            !IdentifierRegex().IsMatch(manifest.IntegrationId) ||
            string.IsNullOrWhiteSpace(manifest.ReleaseVersion))
        {
            throw new InvalidDataException("Unsupported installation manifest identity.");
        }
        if (manifest.Artifacts.Count != 1)
        {
            throw new InvalidDataException("Manager v1 requires exactly one artifact.");
        }
        var artifact = manifest.Artifacts[0];
        if (artifact.Source.Kind != "repository" || artifact.Format != "zip" ||
            artifact.SizeBytes <= 0 || !Sha256Regex().IsMatch(artifact.Sha256))
        {
            throw new InvalidDataException("Unsupported or invalid artifact contract.");
        }
        PathBoundary.ValidateRelative(artifact.Source.Path);
        PathBoundary.ValidateRelative(artifact.ArchiveRoot);
        if (manifest.Installation.Target.Base != "game_root")
        {
            throw new InvalidDataException("Manager v1 supports only game_root targets.");
        }
        PathBoundary.ValidateRelative(manifest.Installation.Target.RelativePath);
        if (manifest.Configuration.Store.Kind != "xml" ||
            manifest.Configuration.Store.KnownFolder != "windows_local_low")
        {
            throw new InvalidDataException("Unsupported configuration store.");
        }
        PathBoundary.ValidateRelative(manifest.Configuration.Store.RelativePath);
        if (manifest.Configuration.ManagedFields.Count == 0 ||
            manifest.Configuration.ManagedFields.Any(field =>
                string.IsNullOrWhiteSpace(field.Name) ||
                string.IsNullOrWhiteSpace(field.Selector) ||
                !field.Selector.StartsWith("/", StringComparison.Ordinal)))
        {
            throw new InvalidDataException("Invalid managed configuration fields.");
        }
    }

    [GeneratedRegex("^[a-z][a-z0-9_]{1,63}$", RegexOptions.CultureInvariant)]
    private static partial Regex IdentifierRegex();

    [GeneratedRegex("^[a-f0-9]{64}$", RegexOptions.CultureInvariant)]
    private static partial Regex Sha256Regex();
}
