using System.Net;
using ShedLink.Manager.Core.Installation;

namespace ShedLink.Manager.Core.Update;

public sealed record ManagerUpdateCheck(
    bool UpdateAvailable,
    string CurrentVersion,
    string? AvailableVersion,
    string Reason);

public sealed record StagedManagerUpdate(string Version, string StagedRoot);

/// <summary>
/// Updates the Manager itself through the same trust path used for game mods:
/// signed manifest, exact size and SHA-256, publisher signature verified before
/// anything is unpacked, then an in-place swap of the running executable.
/// </summary>
public sealed class ManagerUpdateService : IDisposable
{
    private const long MaxManifestBytes = 64 * 1024;
    private const string PreviousSuffix = ".shedlink-previous";

    private readonly HttpClient _http;
    private readonly SecureArtifactDownloader _downloader;
    private readonly ArtifactSignatureVerifier _signatureVerifier;
    private readonly string _packageDirectory;
    private readonly string _executableName;

    public ManagerUpdateService(
        ArtifactSignatureVerifier signatureVerifier,
        string packageDirectory,
        string executableName,
        HttpMessageHandler? handler = null)
    {
        _signatureVerifier = signatureVerifier;
        _packageDirectory = Path.GetFullPath(packageDirectory);
        _executableName = executableName;
        handler ??= new HttpClientHandler
        {
            AllowAutoRedirect = false,
            UseCookies = false,
        };
        _http = new HttpClient(handler, disposeHandler: false)
        {
            Timeout = TimeSpan.FromSeconds(30),
        };
        _downloader = new SecureArtifactDownloader(handler);
    }

    public async Task<ManagerUpdateCheck> CheckAsync(
        Uri manifestUrl,
        string currentVersion,
        CancellationToken cancellationToken = default)
    {
        var manifest = await FetchManifestAsync(manifestUrl, cancellationToken);
        // Refusing equal or older versions keeps a replayed old manifest from
        // walking the Manager backwards into a fixed defect.
        if (ManagerVersion.Compare(manifest.Version, currentVersion) <= 0)
        {
            return new ManagerUpdateCheck(
                false, currentVersion, manifest.Version, "Установлена актуальная версия.");
        }
        return new ManagerUpdateCheck(
            true, currentVersion, manifest.Version,
            $"Доступна версия {manifest.Version}.");
    }

    public async Task<StagedManagerUpdate> StageAsync(
        Uri manifestUrl,
        string currentVersion,
        CancellationToken cancellationToken = default)
    {
        var manifest = await FetchManifestAsync(manifestUrl, cancellationToken);
        if (ManagerVersion.Compare(manifest.Version, currentVersion) <= 0)
        {
            throw new InvalidDataException("Manager update is not newer than the current version.");
        }
        var artifact = manifest.Artifact;
        var workRoot = Path.Combine(
            Path.GetTempPath(), "ShedLink", "ManagerUpdate", Guid.NewGuid().ToString("N"));
        var archivePath = Path.Combine(workRoot, "manager.zip");
        var extracted = Path.Combine(workRoot, "extracted");
        try
        {
            await _downloader.DownloadVerifiedAsync(
                artifact.Url, artifact.SizeBytes, artifact.Sha256, archivePath, cancellationToken);
            _signatureVerifier.Verify(
                ManagerReleaseManifestLoader.ProductId,
                manifest.Version,
                artifact.Id,
                artifact.SizeBytes,
                artifact.Sha256,
                artifact.Signature.Algorithm,
                artifact.Signature.KeyId,
                artifact.Signature.Value);
            SafeZipExtractor.Extract(archivePath, extracted);
            var staged = PathBoundary.CombineWithin(extracted, artifact.ArchiveRoot);
            if (!Directory.Exists(staged) ||
                !File.Exists(Path.Combine(staged, _executableName)))
            {
                throw new InvalidDataException("Manager update package has no executable.");
            }
            File.Delete(archivePath);
            return new StagedManagerUpdate(manifest.Version, staged);
        }
        catch
        {
            DeleteTree(workRoot);
            throw;
        }
    }

    /// <summary>
    /// Swaps the staged package in. Windows allows renaming a running executable
    /// but not overwriting it, so the current one is moved aside and removed on
    /// the next start. Returns the executable to relaunch.
    /// </summary>
    public string Apply(StagedManagerUpdate staged)
    {
        var executable = Path.Combine(_packageDirectory, _executableName);
        var displaced = executable + PreviousSuffix;
        DeleteFile(displaced);
        var moved = false;
        try
        {
            if (File.Exists(executable))
            {
                File.Move(executable, displaced);
                moved = true;
            }
            CopyTree(staged.StagedRoot, _packageDirectory);
            if (!File.Exists(executable))
            {
                throw new IOException("Manager update did not produce an executable.");
            }
        }
        catch
        {
            if (moved && !File.Exists(executable))
            {
                File.Move(displaced, executable);
            }
            throw;
        }
        finally
        {
            DeleteTree(Path.GetDirectoryName(Path.GetDirectoryName(staged.StagedRoot)!)!);
        }
        return executable;
    }

    /// <summary>Removes the displaced executable left by a previous update.</summary>
    public bool CleanupPrevious()
    {
        var displaced = Path.Combine(_packageDirectory, _executableName + PreviousSuffix);
        if (!File.Exists(displaced))
        {
            return false;
        }
        return DeleteFile(displaced);
    }

    public void Dispose()
    {
        _http.Dispose();
        _downloader.Dispose();
    }

    private async Task<ManagerReleaseManifest> FetchManifestAsync(
        Uri manifestUrl,
        CancellationToken cancellationToken)
    {
        if (!manifestUrl.IsAbsoluteUri || manifestUrl.Scheme != Uri.UriSchemeHttps ||
            !string.IsNullOrEmpty(manifestUrl.UserInfo))
        {
            throw new InvalidDataException("Manager update manifest requires a safe HTTPS URL.");
        }
        using var response = await _http.GetAsync(
            manifestUrl, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        if ((int)response.StatusCode is >= 300 and <= 399)
        {
            throw new InvalidDataException("Manager update manifest redirects are not allowed.");
        }
        response.EnsureSuccessStatusCode();
        if (response.Content.Headers.ContentLength is long declared &&
            declared > MaxManifestBytes)
        {
            throw new InvalidDataException("Manager update manifest is too large.");
        }
        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
        using var reader = new StreamReader(stream);
        var buffer = new char[MaxManifestBytes + 1];
        var read = await reader.ReadBlockAsync(buffer, cancellationToken);
        if (read > MaxManifestBytes)
        {
            throw new InvalidDataException("Manager update manifest is too large.");
        }
        return ManagerReleaseManifestLoader.Parse(new string(buffer, 0, read));
    }

    private static void CopyTree(string source, string destination)
    {
        Directory.CreateDirectory(destination);
        foreach (var directory in Directory.EnumerateDirectories(source))
        {
            CopyTree(directory, Path.Combine(destination, Path.GetFileName(directory)));
        }
        foreach (var file in Directory.EnumerateFiles(source))
        {
            File.Copy(file, Path.Combine(destination, Path.GetFileName(file)), overwrite: true);
        }
    }

    private static bool DeleteFile(string path)
    {
        try
        {
            if (!File.Exists(path))
            {
                return false;
            }
            File.Delete(path);
            return true;
        }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException)
        {
            // A locked leftover is harmless; the next start tries again.
            return false;
        }
    }

    private static void DeleteTree(string path)
    {
        try
        {
            if (Directory.Exists(path))
            {
                Directory.Delete(path, recursive: true);
            }
        }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException)
        {
        }
    }
}
