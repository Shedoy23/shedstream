using System.Security.Cryptography;

namespace ShedLink.Manager.Core.Installation;

public static class ArtifactVerifier
{
    public static void Verify(string path, InstallationArtifact artifact)
    {
        var info = new FileInfo(path);
        if (!info.Exists || info.Length != artifact.SizeBytes)
        {
            throw new InvalidDataException("Artifact size does not match the manifest.");
        }
        using var stream = info.OpenRead();
        var digest = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
        if (!CryptographicOperations.FixedTimeEquals(
            System.Text.Encoding.ASCII.GetBytes(digest),
            System.Text.Encoding.ASCII.GetBytes(artifact.Sha256)))
        {
            throw new InvalidDataException("Artifact SHA-256 does not match the manifest.");
        }
    }
}
