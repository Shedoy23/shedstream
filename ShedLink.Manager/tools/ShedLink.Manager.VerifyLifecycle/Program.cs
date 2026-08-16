using System.Security.Cryptography;
using System.Text;
using ShedLink.Manager.Core.Installation;

string? rehearsalRoot = null;
var succeeded = false;
try
{
    var options = ParseArgs(args);
    var manifestPath = RequiredFile(options, "manifest");
    var publicKeyPath = RequiredFile(options, "public-key");
    var seedGameRoot = RequiredDirectory(options, "seed-game-root");
    var oldVersion = options.GetValueOrDefault("old-version", "0.1.0");
    if (string.IsNullOrWhiteSpace(oldVersion))
    {
        throw new ArgumentException("--old-version cannot be empty.");
    }

    var manifest = InstallationManifestLoader.Load(manifestPath);
    var artifact = manifest.Artifacts.Single();
    if (artifact.Source.Kind != "https" || artifact.Source.Url is null ||
        artifact.Signature is null)
    {
        throw new InvalidDataException("Lifecycle rehearsal requires a signed HTTPS release.");
    }

    var seedTarget = PathBoundary.CombineWithin(
        seedGameRoot, manifest.Installation.Target.RelativePath);
    if (!Directory.Exists(seedTarget))
    {
        throw new DirectoryNotFoundException(
            "The installed integration was not found in the seed game root: " + seedTarget);
    }
    if ((File.GetAttributes(seedTarget) & FileAttributes.ReparsePoint) != 0)
    {
        throw new InvalidDataException("The seed integration cannot be a reparse point.");
    }

    var seedFingerprintBefore = TreeFingerprint(seedTarget);
    rehearsalRoot = Path.Combine(
        Path.GetTempPath(), "ShedLink", "Lifecycle", Guid.NewGuid().ToString("N"));
    var gameRoot = Path.Combine(rehearsalRoot, "RimWorld");
    var target = PathBoundary.CombineWithin(
        gameRoot, manifest.Installation.Target.RelativePath);
    Directory.CreateDirectory(Path.GetDirectoryName(target)!);
    CopyTree(seedTarget, target);

    AssertCondition(
        InstallationInspector.Inspect(manifest, gameRoot, manifest.ReleaseVersion),
        InstallationCondition.Healthy,
        "seed copy");

    var requiredPathProbe = manifest.Health.FirstOrDefault(
        probe => probe.Required && probe.Kind == "path_exists" &&
            !string.IsNullOrWhiteSpace(probe.Path))
        ?? throw new InvalidDataException("Manifest has no required path probe for repair.");
    var damagedPath = PathBoundary.CombineWithin(target, requiredPathProbe.Path!);
    if (File.Exists(damagedPath))
    {
        File.Delete(damagedPath);
    }
    else if (Directory.Exists(damagedPath))
    {
        Directory.Delete(damagedPath, recursive: true);
    }
    else
    {
        throw new InvalidDataException("Seed copy is already missing repair probe path.");
    }
    var damaged = InstallationInspector.Inspect(
        manifest, gameRoot, manifest.ReleaseVersion);
    AssertCondition(damaged, InstallationCondition.RepairRequired, "damaged copy");
    if (!damaged.FailedProbeIds.Contains(requiredPathProbe.Id, StringComparer.Ordinal))
    {
        throw new InvalidDataException("Repair inspection did not report the damaged probe.");
    }

    var publicKeyPem = File.ReadAllText(publicKeyPath);
    var signatureVerifier = new ArtifactSignatureVerifier(
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            [artifact.Signature.KeyId] = publicKeyPem,
        });
    signatureVerifier.Verify(manifest, artifact);
    using var downloader = new SecureArtifactDownloader();
    var installer = new PackageInstaller();

    await installer.InstallHttpsArtifactAsync(
        manifestPath, gameRoot, downloader, signatureVerifier);
    AssertCondition(
        InstallationInspector.Inspect(manifest, gameRoot, manifest.ReleaseVersion),
        InstallationCondition.Healthy,
        "repaired copy");
    AssertNoTransactionArtifacts(target);

    var legacyMarker = Path.Combine(target, "shedlink-lifecycle-old-version.marker");
    File.WriteAllText(legacyMarker, oldVersion, Encoding.UTF8);
    AssertCondition(
        InstallationInspector.Inspect(manifest, gameRoot, oldVersion),
        InstallationCondition.UpdateAvailable,
        "outdated copy");

    await installer.InstallHttpsArtifactAsync(
        manifestPath, gameRoot, downloader, signatureVerifier);
    AssertCondition(
        InstallationInspector.Inspect(manifest, gameRoot, manifest.ReleaseVersion),
        InstallationCondition.Healthy,
        "updated copy");
    if (File.Exists(legacyMarker))
    {
        throw new InvalidDataException("Update did not replace the outdated directory completely.");
    }
    AssertNoTransactionArtifacts(target);

    var seedFingerprintAfter = TreeFingerprint(seedTarget);
    if (!CryptographicOperations.FixedTimeEquals(
        Convert.FromHexString(seedFingerprintBefore),
        Convert.FromHexString(seedFingerprintAfter)))
    {
        throw new InvalidDataException("The original RimLink installation changed during rehearsal.");
    }

    succeeded = true;
    Console.WriteLine($"LIFECYCLE VERIFIED {manifest.IntegrationId} {manifest.ReleaseVersion}");
    Console.WriteLine("STATES=Healthy -> RepairRequired -> Healthy -> UpdateAvailable -> Healthy");
    Console.WriteLine($"URL={artifact.Source.Url.AbsoluteUri}");
    Console.WriteLine($"SHA256={artifact.Sha256}");
    Console.WriteLine($"KEY_ID={artifact.Signature.KeyId}");
    Console.WriteLine($"SEED_FINGERPRINT_SHA256={seedFingerprintAfter}");
    Console.WriteLine("ORIGINAL_INSTALLATION=UNCHANGED");
    return 0;
}
catch (Exception exception)
{
    Console.Error.WriteLine("LIFECYCLE VERIFICATION FAILED: " + exception.Message);
    if (rehearsalRoot is not null && Directory.Exists(rehearsalRoot))
    {
        Console.Error.WriteLine("PRESERVED_REHEARSAL_ROOT=" + rehearsalRoot);
    }
    return 1;
}
finally
{
    if (succeeded && rehearsalRoot is not null && Directory.Exists(rehearsalRoot))
    {
        Directory.Delete(rehearsalRoot, recursive: true);
    }
}

static void AssertCondition(
    InstallationInspection inspection,
    InstallationCondition expected,
    string step)
{
    if (inspection.Condition != expected)
    {
        throw new InvalidDataException(
            $"Unexpected {step} condition: {inspection.Condition}; expected {expected}.");
    }
}

static void AssertNoTransactionArtifacts(string target)
{
    var parent = Path.GetDirectoryName(target)!;
    var name = Path.GetFileName(target);
    var leftovers = new[]
    {
        Path.Combine(parent, $".{name}.shedlink-stage"),
        Path.Combine(parent, $".{name}.shedlink-backup"),
        Path.Combine(parent, $".{name}.shedlink-transaction.json"),
        Path.Combine(parent, $".{name}.shedlink-transaction.json.tmp"),
    }.Where(path => File.Exists(path) || Directory.Exists(path)).ToArray();
    if (leftovers.Length > 0)
    {
        throw new InvalidDataException(
            "Lifecycle transaction artifacts were not cleaned: " +
            string.Join(", ", leftovers));
    }
}

static string TreeFingerprint(string root)
{
    using var aggregate = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
    foreach (var file in EnumerateSafeFiles(root)
                 .OrderBy(path => Path.GetRelativePath(root, path), StringComparer.OrdinalIgnoreCase))
    {
        if ((File.GetAttributes(file) & FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidDataException("Integration tree contains a reparse point.");
        }
        var relative = Path.GetRelativePath(root, file).Replace('\\', '/');
        aggregate.AppendData(Encoding.UTF8.GetBytes(relative + "\n"));
        using var stream = File.OpenRead(file);
        var fileHash = SHA256.HashData(stream);
        aggregate.AppendData(fileHash);
    }
    return Convert.ToHexString(aggregate.GetHashAndReset()).ToLowerInvariant();
}

static IEnumerable<string> EnumerateSafeFiles(string root)
{
    foreach (var directory in Directory.EnumerateDirectories(root))
    {
        if ((File.GetAttributes(directory) & FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidDataException("Integration tree contains a reparse point.");
        }
        foreach (var file in EnumerateSafeFiles(directory))
        {
            yield return file;
        }
    }
    foreach (var file in Directory.EnumerateFiles(root))
    {
        yield return file;
    }
}

static void CopyTree(string source, string destination)
{
    Directory.CreateDirectory(destination);
    foreach (var directory in Directory.EnumerateDirectories(source))
    {
        if ((File.GetAttributes(directory) & FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidDataException("Seed integration contains a reparse point.");
        }
        CopyTree(directory, Path.Combine(destination, Path.GetFileName(directory)));
    }
    foreach (var file in Directory.EnumerateFiles(source))
    {
        if ((File.GetAttributes(file) & FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidDataException("Seed integration contains a reparse point.");
        }
        File.Copy(file, Path.Combine(destination, Path.GetFileName(file)), overwrite: false);
    }
}

static Dictionary<string, string> ParseArgs(string[] values)
{
    if (values.Length == 0 || values.Length % 2 != 0)
    {
        throw new ArgumentException(
            "Usage: --manifest FILE --public-key PUBLIC.pem --seed-game-root DIRECTORY " +
            "[--old-version VERSION]");
    }
    var result = new Dictionary<string, string>(StringComparer.Ordinal);
    for (var index = 0; index < values.Length; index += 2)
    {
        if (!values[index].StartsWith("--", StringComparison.Ordinal))
        {
            throw new ArgumentException("Expected --option value pairs.");
        }
        var name = values[index][2..];
        if (!result.TryAdd(name, values[index + 1]))
        {
            throw new ArgumentException("Duplicate --" + name + ".");
        }
    }
    return result;
}

static string RequiredFile(IReadOnlyDictionary<string, string> options, string name)
{
    var path = RequiredPath(options, name);
    return File.Exists(path)
        ? path
        : throw new FileNotFoundException("Required file does not exist.", path);
}

static string RequiredDirectory(IReadOnlyDictionary<string, string> options, string name)
{
    var path = RequiredPath(options, name);
    return Directory.Exists(path)
        ? path
        : throw new DirectoryNotFoundException("Required directory does not exist: " + path);
}

static string RequiredPath(IReadOnlyDictionary<string, string> options, string name)
{
    if (!options.TryGetValue(name, out var value) || string.IsNullOrWhiteSpace(value))
    {
        throw new ArgumentException("Missing --" + name + ".");
    }
    return Path.GetFullPath(value);
}
