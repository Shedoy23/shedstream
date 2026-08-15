using System.IO;
using System.Text.Json;
using ShedLink.Manager.Core.Installation;

namespace ShedLink.Manager.App;

internal static class ReleaseConfiguration
{
    private static readonly IReadOnlyDictionary<string, string> TrustedPublisherKeys =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            // Production public keys are added only through the release runbook.
        };

    public static string ManifestPath => Path.Combine(
        AppContext.BaseDirectory, "Release", "rimworld-0.1.0.json");

    public static bool TryLoad(
        out InstallationManifest? manifest,
        out ArtifactSignatureVerifier? verifier,
        out string reason)
    {
        verifier = null;
        if (!TryLoadManifest(out manifest, out reason))
        {
            return false;
        }

        var artifact = manifest!.Artifacts[0];
        if (artifact.Source.Kind != "https" || artifact.Source.Url is null ||
            manifest.Security.SignatureStatus != "signed" || artifact.Signature is null)
        {
            reason = "Безопасный HTTPS-релиз RimLink ещё не опубликован.";
            return false;
        }
        if (!TrustedPublisherKeys.ContainsKey(artifact.Signature.KeyId))
        {
            reason = "Ключ подписи этого релиза ещё не встроен в Manager.";
            return false;
        }
        verifier = new ArtifactSignatureVerifier(TrustedPublisherKeys);
        reason = string.Empty;
        return true;
    }

    public static bool TryLoadManifest(
        out InstallationManifest? manifest,
        out string reason)
    {
        manifest = null;
        try
        {
            manifest = InstallationManifestLoader.Load(ManifestPath);
        }
        catch (Exception exception) when (
            exception is IOException or JsonException or InvalidDataException)
        {
            reason = "Release-манифест Manager недоступен или повреждён.";
            return false;
        }
        reason = string.Empty;
        return true;
    }
}
