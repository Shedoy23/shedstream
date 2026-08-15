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
        if (artifact.Format != "zip" || artifact.SizeBytes <= 0 ||
            !Sha256Regex().IsMatch(artifact.Sha256))
        {
            throw new InvalidDataException("Unsupported or invalid artifact contract.");
        }
        if (artifact.Source.Kind == "repository")
        {
            if (artifact.Source.Path is null || artifact.Source.Url is not null)
            {
                throw new InvalidDataException("Repository artifact source is invalid.");
            }
            PathBoundary.ValidateRelative(artifact.Source.Path);
        }
        else if (artifact.Source.Kind == "https")
        {
            if (!IsSafeHttpsUri(artifact.Source.Url) || artifact.Source.Path is not null ||
                manifest.Security.SignatureStatus != "signed" || artifact.Signature is null ||
                artifact.Signature.Algorithm != "rsa-pss-sha256" ||
                !IdentifierRegex().IsMatch(artifact.Signature.KeyId) ||
                string.IsNullOrWhiteSpace(artifact.Signature.Value))
            {
                throw new InvalidDataException(
                    "HTTPS artifacts require a valid publisher signature contract.");
            }
        }
        else
        {
            throw new InvalidDataException("Unsupported artifact source.");
        }
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

    [GeneratedRegex("^[a-z][a-z0-9_-]{0,63}$", RegexOptions.CultureInvariant)]
    private static partial Regex IdentifierRegex();

    [GeneratedRegex("^[a-f0-9]{64}$", RegexOptions.CultureInvariant)]
    private static partial Regex Sha256Regex();

    private static bool IsSafeHttpsUri(Uri? uri) =>
        uri is { IsAbsoluteUri: true } &&
        uri.Scheme == Uri.UriSchemeHttps &&
        string.IsNullOrEmpty(uri.UserInfo) &&
        !string.IsNullOrWhiteSpace(uri.Host);
}
