using System.Net;
using System.Security.Cryptography;

namespace ShedLink.Manager.Core.Installation;

public sealed class SecureArtifactDownloader : IDisposable
{
    private readonly HttpClient _http;

    public SecureArtifactDownloader(HttpMessageHandler? handler = null)
    {
        handler ??= new HttpClientHandler
        {
            AllowAutoRedirect = false,
            UseCookies = false,
        };
        _http = new HttpClient(handler, disposeHandler: true)
        {
            Timeout = TimeSpan.FromMinutes(2),
        };
    }

    public async Task DownloadAsync(
        Uri source,
        InstallationManifest manifest,
        InstallationArtifact artifact,
        ArtifactSignatureVerifier signatureVerifier,
        string destination,
        CancellationToken cancellationToken = default)
    {
        if (source.Scheme != Uri.UriSchemeHttps || !source.IsAbsoluteUri ||
            !string.IsNullOrEmpty(source.UserInfo))
        {
            throw new InvalidDataException("Artifact download requires a safe HTTPS URL.");
        }
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
        if (File.Exists(destination))
        {
            throw new IOException("Artifact destination already exists.");
        }
        var ownsDestination = false;
        try
        {
            using var response = await _http.GetAsync(
                source, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
            if (IsRedirect(response.StatusCode))
            {
                throw new InvalidDataException("Artifact redirects are not allowed.");
            }
            response.EnsureSuccessStatusCode();
            if (response.Content.Headers.ContentLength is long contentLength &&
                contentLength != artifact.SizeBytes)
            {
                throw new InvalidDataException("Artifact Content-Length does not match manifest.");
            }

            await using var input = await response.Content.ReadAsStreamAsync(cancellationToken);
            await using var output = new FileStream(
                destination, FileMode.CreateNew, FileAccess.Write, FileShare.None,
                bufferSize: 81920, useAsync: true);
            ownsDestination = true;
            using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            var buffer = new byte[81920];
            long total = 0;
            while (true)
            {
                var read = await input.ReadAsync(buffer, cancellationToken);
                if (read == 0)
                {
                    break;
                }
                total += read;
                if (total > artifact.SizeBytes)
                {
                    throw new InvalidDataException("Artifact exceeds manifest size.");
                }
                hash.AppendData(buffer, 0, read);
                await output.WriteAsync(buffer.AsMemory(0, read), cancellationToken);
            }
            if (total != artifact.SizeBytes)
            {
                throw new InvalidDataException("Artifact is truncated.");
            }
            var digest = Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
            if (!CryptographicOperations.FixedTimeEquals(
                System.Text.Encoding.ASCII.GetBytes(digest),
                System.Text.Encoding.ASCII.GetBytes(artifact.Sha256)))
            {
                throw new InvalidDataException("Downloaded artifact SHA-256 does not match.");
            }
            signatureVerifier.Verify(manifest, artifact);
        }
        catch
        {
            if (ownsDestination)
            {
                File.Delete(destination);
            }
            throw;
        }
    }

    public void Dispose() => _http.Dispose();

    private static bool IsRedirect(HttpStatusCode status) =>
        (int)status is >= 300 and <= 399;
}
