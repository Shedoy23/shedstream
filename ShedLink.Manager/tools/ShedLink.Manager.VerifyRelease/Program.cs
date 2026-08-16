using System.Security.Cryptography;
using ShedLink.Manager.Core.Installation;

try
{
    var options = ParseArgs(args);
    var manifestPath = RequiredFile(options, "manifest");
    var artifactPath = RequiredFile(options, "artifact");
    var publicKeyPath = RequiredFile(options, "public-key");
    var manifest = InstallationManifestLoader.Load(manifestPath);
    var artifact = manifest.Artifacts.Single();
    if (artifact.Source.Kind != "https" || artifact.Source.Url is null ||
        artifact.Signature is null)
    {
        throw new InvalidDataException("Release manifest is not a signed HTTPS release.");
    }
    ArtifactVerifier.Verify(artifactPath, artifact);
    var publicKeyPem = File.ReadAllText(publicKeyPath);
    new ArtifactSignatureVerifier(new Dictionary<string, string>
    {
        [artifact.Signature.KeyId] = publicKeyPem,
    }).Verify(manifest, artifact);

    var extractionRoot = Path.Combine(
        Path.GetTempPath(), "shedlink-release-verify-" + Guid.NewGuid().ToString("N"));
    Directory.CreateDirectory(extractionRoot);
    try
    {
        SafeZipExtractor.Extract(artifactPath, extractionRoot);
        var archiveRoot = PathBoundary.CombineWithin(extractionRoot, artifact.ArchiveRoot);
        foreach (var probe in manifest.Health.Where(
                     probe => probe.Required && probe.Kind == "path_exists"))
        {
            if (string.IsNullOrWhiteSpace(probe.Path))
            {
                throw new InvalidDataException(
                    "Required path health probe has no path: " + probe.Id);
            }
            var target = PathBoundary.CombineWithin(archiveRoot, probe.Path);
            if (!File.Exists(target) && !Directory.Exists(target))
            {
                throw new InvalidDataException(
                    "Release is missing required health probe path: " + probe.Id);
            }
        }
    }
    finally
    {
        Directory.Delete(extractionRoot, recursive: true);
    }

    using var rsa = RSA.Create();
    rsa.ImportFromPem(publicKeyPem);
    var fingerprint = Convert.ToHexString(
        SHA256.HashData(rsa.ExportSubjectPublicKeyInfo())).ToLowerInvariant();
    Console.WriteLine($"VERIFIED {manifest.IntegrationId} {manifest.ReleaseVersion}");
    Console.WriteLine($"URL={artifact.Source.Url.AbsoluteUri}");
    Console.WriteLine($"SIZE={artifact.SizeBytes}");
    Console.WriteLine($"SHA256={artifact.Sha256}");
    Console.WriteLine($"KEY_ID={artifact.Signature.KeyId}");
    Console.WriteLine($"PUBLIC_FINGERPRINT_SHA256={fingerprint}");
    return 0;
}
catch (Exception exception)
{
    Console.Error.WriteLine("RELEASE VERIFICATION FAILED: " + exception.Message);
    return 1;
}

static Dictionary<string, string> ParseArgs(string[] values)
{
    if (values.Length == 0 || values.Length % 2 != 0)
    {
        throw new ArgumentException(
            "Usage: --manifest FILE --artifact ZIP --public-key PUBLIC.pem");
    }
    var result = new Dictionary<string, string>(StringComparer.Ordinal);
    for (var index = 0; index < values.Length; index += 2)
    {
        if (!values[index].StartsWith("--", StringComparison.Ordinal))
        {
            throw new ArgumentException("Expected --option value pairs.");
        }
        result[values[index][2..]] = values[index + 1];
    }
    return result;
}

static string RequiredFile(IReadOnlyDictionary<string, string> options, string name)
{
    if (!options.TryGetValue(name, out var value) || string.IsNullOrWhiteSpace(value))
    {
        throw new ArgumentException("Missing --" + name + ".");
    }
    var path = Path.GetFullPath(value);
    return File.Exists(path)
        ? path
        : throw new FileNotFoundException("Required file does not exist.", path);
}
