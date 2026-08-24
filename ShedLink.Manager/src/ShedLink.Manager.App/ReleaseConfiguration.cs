using System.IO;
using System.Text.Json;
using ShedLink.Manager.Core.Detection;
using ShedLink.Manager.Core.Installation;

namespace ShedLink.Manager.App;

internal static class ReleaseConfiguration
{
    private static readonly IReadOnlyDictionary<string, string> TrustedPublisherKeys =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["shedlink-release-2026"] = """
                -----BEGIN PUBLIC KEY-----
                MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEA8JTva5enwqL4b4Qpf8Je
                5DvuG4ofsuItJ8TM4pLqNfYp8E6/oUuL4lCtYVBwkVWhX0SXB60qjJ3qHT3tnljz
                zL0G1jWgPm3R9WMGcMc2uQvgeoHZniqB/j+hX2mIr+Lri3YOhh8c//zJddeB46gc
                usNY5JXFzEyQxN3v1WXpItY98paqOLnAX6N89w7lfIA20YRuwvPmA8/51Rjj7Trw
                hjN5gtJBuC0Zag2VXQxwMeQ0hpPDIAMMtoAt9pyMLKj5HbOVVC9S5ciQ3lBU++ow
                OlCFYADzhv7+91czVGEvDe27Dht1RstZOlUA1p/X7xSJcjXKvm43QpR/G4P771nf
                HIA3O+X9ZTAxc0dtIMiKRUrMNvQHwgP2UeDQphl6VGoDIk89uZBX4JGMvG/KrFZ/
                fulsHTOyEfmhopKdEG4XW9I0q9vrH42j8xotKYan5p1IXuxY3iDmMgBIxsoWE9+N
                GMIWG5RiP5n/2kZVeON2E8XG/lWIs1SG4dMybZLpgQA4gGER9PHu5X/BJFlkwh72
                grpSSGuLdXr5F8BDdl+bkDLiJaECYtC4UbdQhsj9P6wraxs93+6PFhued0XdT6w2
                CAhrWI/or+gbEyxITEvJH/4+3UkXF8ykecDeTviazW0CJ0DoyT9m6Tt6uh78Tglr
                7swButTf+RKEsmKYHN1tGJkCAwEAAQ==
                -----END PUBLIC KEY-----
                """,
        };

    public static bool TrySelect(
        string integrationId,
        DetectedGameVersion? gameVersion,
        out InstallationRelease? release,
        out ArtifactSignatureVerifier? verifier,
        out string reason)
    {
        verifier = null;
        if (!TrySelectManifest(integrationId, gameVersion, out release, out reason))
        {
            return false;
        }
        var manifest = release!.Manifest;
        var artifact = manifest.Artifacts[0];
        if (artifact.Source.Kind != "https" || artifact.Source.Url is null ||
            manifest.Security.SignatureStatus != "signed" || artifact.Signature is null)
        {
            reason = "Совместимый безопасный HTTPS-релиз интеграции ещё не опубликован.";
            return false;
        }
        if (!TrustedPublisherKeys.ContainsKey(artifact.Signature.KeyId))
        {
            reason = "Ключ подписи этого релиза ещё не встроен в Manager.";
            return false;
        }
        verifier = new ArtifactSignatureVerifier(TrustedPublisherKeys);
        try
        {
            verifier.Verify(manifest, artifact);
        }
        catch (InvalidDataException)
        {
            verifier = null;
            reason = "Подпись совместимого релиза интеграции недействительна.";
            return false;
        }
        reason = string.Empty;
        return true;
    }

    public static bool TrySelectManifest(
        string integrationId,
        DetectedGameVersion? gameVersion,
        out InstallationRelease? release,
        out string reason)
    {
        release = null;
        if (gameVersion is null)
        {
            reason = "Не удалось определить совместимую версию выбранной игры.";
            return false;
        }
        if (!TryLoadReleases(out var releases, out reason))
        {
            return false;
        }
        release = InstallationReleaseSelector.SelectCompatible(
            releases!, integrationId, gameVersion.CompatibilityVersion);
        if (release is null)
        {
            reason = $"Для версии {gameVersion.FullVersion} нет совместимого релиза интеграции.";
            return false;
        }
        reason = string.Empty;
        return true;
    }

    public static bool TrySelectLatestManifest(
        string integrationId,
        out InstallationRelease? release,
        out string reason)
    {
        release = null;
        if (!TryLoadReleases(out var releases, out reason))
        {
            return false;
        }
        release = InstallationReleaseSelector.SelectLatest(releases!, integrationId);
        if (release is null)
        {
            reason = "Release-каталог не содержит выбранную интеграцию.";
            return false;
        }
        reason = string.Empty;
        return true;
    }

    public static bool TryListLatest(
        out IReadOnlyList<InstallationRelease>? releases,
        out string reason)
    {
        releases = null;
        if (!TryLoadReleases(out var loaded, out reason))
        {
            return false;
        }
        releases = new InstallationReleaseCatalog(loaded!).LatestIntegrations();
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
        // catch-ok: список шире общего — сюда входит JsonException, которого
        // в ManagerFailureMessage.IsExpected нет и быть не должно: битый JSON
        // каталога это не сбой операции пользователя, а негодный каталог.
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
