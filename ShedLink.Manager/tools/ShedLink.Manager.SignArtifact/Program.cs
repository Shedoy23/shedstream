using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using ShedLink.Manager.Core.Installation;

try
{
    var options = ParseArgs(args);
    var manifestPath = Required(options, "manifest");
    var artifactPath = Required(options, "artifact");
    var keyPath = Required(options, "key");
    var keyId = Required(options, "key-id");
    var url = new Uri(Required(options, "url"), UriKind.Absolute);
    if (url.Scheme != Uri.UriSchemeHttps || !string.IsNullOrEmpty(url.UserInfo))
    {
        throw new ArgumentException("--url must be an absolute HTTPS URL without credentials.");
    }
    if (!Regex.IsMatch(keyId, "^[a-z][a-z0-9_-]{0,63}$"))
    {
        throw new ArgumentException("--key-id is invalid.");
    }

    var root = JsonNode.Parse(File.ReadAllText(manifestPath))?.AsObject()
        ?? throw new InvalidDataException("Manifest JSON is empty.");
    var artifacts = root["artifacts"]?.AsArray()
        ?? throw new InvalidDataException("Manifest has no artifacts.");
    if (artifacts.Count != 1 || artifacts[0] is not JsonObject artifact)
    {
        throw new InvalidDataException("Signer v1 requires exactly one artifact.");
    }
    var integrationId = Text(root, "integration_id");
    var releaseVersion = Text(root, "release_version");
    var artifactId = Text(artifact, "id");
    var expectedSize = artifact["size_bytes"]?.GetValue<long>()
        ?? throw new InvalidDataException("Artifact size is missing.");
    var expectedHash = Text(artifact, "sha256");
    var info = new FileInfo(artifactPath);
    if (!info.Exists || info.Length != expectedSize)
    {
        throw new InvalidDataException("Artifact size differs from manifest.");
    }
    using var input = info.OpenRead();
    var actualHash = Convert.ToHexString(SHA256.HashData(input)).ToLowerInvariant();
    if (!CryptographicOperations.FixedTimeEquals(
        System.Text.Encoding.ASCII.GetBytes(actualHash),
        System.Text.Encoding.ASCII.GetBytes(expectedHash)))
    {
        throw new InvalidDataException("Artifact SHA-256 differs from manifest.");
    }

    using var rsa = RSA.Create();
    rsa.ImportFromPem(File.ReadAllText(keyPath));
    if (rsa.KeySize < 3072)
    {
        throw new InvalidDataException("Production signing key must be at least 3072 bit.");
    }
    var signature = rsa.SignData(
        ArtifactSignatureVerifier.SigningPayload(
            integrationId, releaseVersion, artifactId, expectedSize, expectedHash),
        HashAlgorithmName.SHA256,
        RSASignaturePadding.Pss);

    artifact["source"] = new JsonObject
    {
        ["kind"] = "https",
        ["url"] = url.AbsoluteUri,
    };
    artifact["signature"] = new JsonObject
    {
        ["algorithm"] = "rsa-pss-sha256",
        ["key_id"] = keyId,
        ["value"] = Convert.ToBase64String(signature),
    };
    var security = root["security"]?.AsObject()
        ?? throw new InvalidDataException("Manifest security block is missing.");
    security["signature_status"] = "signed";

    var temporary = manifestPath + ".tmp";
    File.WriteAllText(temporary, root.ToJsonString(new JsonSerializerOptions
    {
        WriteIndented = true,
    }) + Environment.NewLine);
    var signedManifest = InstallationManifestLoader.Load(temporary);
    new ArtifactSignatureVerifier(new Dictionary<string, string>
    {
        [keyId] = rsa.ExportSubjectPublicKeyInfoPem(),
    }).Verify(signedManifest, signedManifest.Artifacts[0]);
    File.Move(temporary, manifestPath, overwrite: true);
    Console.WriteLine(
        $"SIGNED {integrationId} {releaseVersion} artifact={artifactId} key={keyId}");
    return 0;
}
catch (Exception exception)
{
    Console.Error.WriteLine("SIGN FAILED: " + exception.Message);
    return 1;
}

static Dictionary<string, string> ParseArgs(string[] values)
{
    if (values.Length == 0 || values.Length % 2 != 0)
    {
        throw new ArgumentException(
            "Usage: --manifest FILE --artifact ZIP --key PRIVATE.pem --key-id ID --url HTTPS_URL");
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

static string Required(IReadOnlyDictionary<string, string> options, string name) =>
    options.TryGetValue(name, out var value) && !string.IsNullOrWhiteSpace(value)
        ? value
        : throw new ArgumentException("Missing --" + name + ".");

static string Text(JsonObject value, string name) =>
    value[name]?.GetValue<string>()
    ?? throw new InvalidDataException("Manifest field is missing: " + name);
