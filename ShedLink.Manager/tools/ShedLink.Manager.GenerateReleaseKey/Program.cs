using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.RegularExpressions;

try
{
    var options = ParseArgs(args);
    var privatePath = AbsolutePath(Required(options, "private"), "--private");
    var publicPath = AbsolutePath(Required(options, "public"), "--public");
    var keyId = Required(options, "key-id");
    if (!Regex.IsMatch(keyId, "^[a-z][a-z0-9_-]{0,63}$"))
    {
        throw new ArgumentException("--key-id is invalid.");
    }
    if (string.Equals(privatePath, publicPath, StringComparison.OrdinalIgnoreCase))
    {
        throw new ArgumentException("Private and public key paths must differ.");
    }
    RejectRepositoryPath(privatePath);
    RejectRepositoryPath(publicPath);
    if (File.Exists(privatePath) || File.Exists(publicPath))
    {
        throw new IOException("A requested key output already exists; refusing to overwrite it.");
    }
    Directory.CreateDirectory(Path.GetDirectoryName(privatePath)!);
    Directory.CreateDirectory(Path.GetDirectoryName(publicPath)!);

    using var rsa = RSA.Create(4096);
    try
    {
        WriteNew(privatePath, rsa.ExportPkcs8PrivateKeyPem());
        RestrictToCurrentUser(privatePath);
        WriteNew(publicPath, rsa.ExportSubjectPublicKeyInfoPem());
        var fingerprint = Convert.ToHexString(
            SHA256.HashData(rsa.ExportSubjectPublicKeyInfo())).ToLowerInvariant();
        Console.WriteLine($"CREATED key_id={keyId}");
        Console.WriteLine($"PUBLIC_FINGERPRINT_SHA256={fingerprint}");
        Console.WriteLine($"PRIVATE={privatePath}");
        Console.WriteLine($"PUBLIC={publicPath}");
    }
    catch
    {
        File.Delete(privatePath);
        File.Delete(publicPath);
        throw;
    }
    return 0;
}
catch (Exception exception)
{
    Console.Error.WriteLine("KEY GENERATION FAILED: " + exception.Message);
    return 1;
}

static void WriteNew(string path, string contents)
{
    using var stream = new FileStream(
        path, FileMode.CreateNew, FileAccess.Write, FileShare.None);
    using var writer = new StreamWriter(stream);
    writer.Write(contents);
}

static void RestrictToCurrentUser(string path)
{
    var identity = WindowsIdentity.GetCurrent();
    var sid = identity.User
        ?? throw new InvalidOperationException("Current Windows SID is unavailable.");
    var security = new FileSecurity();
    security.SetAccessRuleProtection(isProtected: true, preserveInheritance: false);
    security.AddAccessRule(new FileSystemAccessRule(
        sid,
        FileSystemRights.FullControl,
        AccessControlType.Allow));
    new FileInfo(path).SetAccessControl(security);
}

static string AbsolutePath(string raw, string option)
{
    if (!Path.IsPathFullyQualified(raw))
    {
        throw new ArgumentException(option + " must be an absolute path.");
    }
    return Path.GetFullPath(raw);
}

static void RejectRepositoryPath(string path)
{
    var repository = Path.GetFullPath(Environment.CurrentDirectory)
        .TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
    if (path.StartsWith(repository, StringComparison.OrdinalIgnoreCase))
    {
        throw new ArgumentException("Release keys must be stored outside the repository.");
    }
}

static Dictionary<string, string> ParseArgs(string[] values)
{
    if (values.Length == 0 || values.Length % 2 != 0)
    {
        throw new ArgumentException(
            "Usage: --private ABSOLUTE.pem --public ABSOLUTE.pem --key-id ID");
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
