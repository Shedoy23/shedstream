using System.IO;
using System.Text.Json;
using ShedLink.Manager.Core.Detection;
using ShedLink.Manager.Core.Installation;

namespace ShedLink.Manager.App;

internal static class ReleaseConfiguration
{
    private const string GameId = "rimworld";

    private static readonly IReadOnlyDictionary<string, string> TrustedPublisherKeys =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            // Production public keys are added only through the release runbook.
        };

    public static bool TrySelect(
        DetectedGameVersion? gameVersion,
        out InstallationRelease? release,
        out ArtifactSignatureVerifier? verifier,
        out string reason)
    {
        verifier = null;
        if (!TrySelectManifest(gameVersion, out release, out reason))
        {
            return false;
        }
        var manifest = release!.Manifest;
        var artifact = manifest.Artifacts[0];
        if (artifact.Source.Kind != "https" || artifact.Source.Url is null ||
            manifest.Security.SignatureStatus != "signed" || artifact.Signature is null)
        {
            reason = "Совместимый безопасный HTTPS-релиз RimLink ещё не опубликован.";
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

    public static bool TrySelectManifest(
        DetectedGameVersion? gameVersion,
        out InstallationRelease? release,
        out string reason)
    {
        release = null;
        if (gameVersion is null)
        {
            reason = "Не удалось определить совместимую версию RimWorld.";
            return false;
        }
        if (!TryLoadReleases(out var releases, out reason))
        {
            return false;
        }
        release = InstallationReleaseSelector.SelectCompatible(
            releases!, GameId, gameVersion.CompatibilityVersion);
        if (release is null)
        {
            reason = $"Для RimWorld {gameVersion.FullVersion} нет совместимого релиза RimLink.";
            return false;
        }
        reason = string.Empty;
        return true;
    }

    public static bool TrySelectLatestManifest(
        out InstallationRelease? release,
        out string reason)
    {
        release = null;
        if (!TryLoadReleases(out var releases, out reason))
        {
            return false;
        }
        release = InstallationReleaseSelector.SelectLatest(releases!, GameId);
        if (release is null)
        {
            reason = "Release-каталог не содержит RimLink.";
            return false;
        }
        reason = string.Empty;
        return true;
    }

    private static bool TryLoadReleases(
        out IReadOnlyList<InstallationRelease>? releases,
        out string reason)
    {
        releases = null;
        var directory = Path.Combine(AppContext.BaseDirectory, "Release");
        try
        {
            var loaded = Directory.EnumerateFiles(directory, "*.json")
                .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
                .Select(path => new InstallationRelease(
                    path, InstallationManifestLoader.Load(path)))
                .ToArray();
            if (loaded.Length == 0)
            {
                reason = "Release-каталог Manager пуст.";
                return false;
            }
            releases = loaded;
        }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException or
                JsonException or InvalidDataException)
        {
            reason = "Release-каталог Manager недоступен или повреждён.";
            return false;
        }
        reason = string.Empty;
        return true;
    }
}
