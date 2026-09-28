using System.Security.Cryptography;
using System.Text;

namespace ShedLink.Manager.Core.Installation;

public sealed class ArtifactSignatureVerifier
{
    private readonly IReadOnlyDictionary<string, string> _publicKeys;

    public ArtifactSignatureVerifier(IReadOnlyDictionary<string, string> publicKeys)
    {
        _publicKeys = publicKeys;
    }

    public void Verify(InstallationManifest manifest, InstallationArtifact artifact)
    {
        var signature = artifact.Signature
            ?? throw new InvalidDataException("Artifact signature is missing.");
        Verify(
            SigningPayload(manifest, artifact),
            signature.Algorithm,
            signature.KeyId,
            signature.Value);
    }

    /// <summary>Same trust rules for artifacts described outside an installation manifest.</summary>
    public void Verify(
        string integrationId,
        string releaseVersion,
        string artifactId,
        long sizeBytes,
        string sha256,
        string algorithm,
        string keyId,
        string signatureValue) => Verify(
            SigningPayload(integrationId, releaseVersion, artifactId, sizeBytes, sha256),
            algorithm,
            keyId,
            signatureValue);

    private void Verify(byte[] payload, string algorithm, string keyId, string signatureValue)
    {
        if (algorithm != "rsa-pss-sha256" ||
            !_publicKeys.TryGetValue(keyId, out var publicKeyPem))
        {
            throw new InvalidDataException("Artifact publisher key is not trusted.");
        }
        byte[] signatureBytes;
        try
        {
            signatureBytes = Convert.FromBase64String(signatureValue);
        }
        catch (FormatException exception)
        {
            throw new InvalidDataException("Artifact signature is malformed.", exception);
        }
        try
        {
            using var rsa = RSA.Create();
            rsa.ImportFromPem(publicKeyPem);
            if (!rsa.VerifyData(
                payload,
                signatureBytes,
                HashAlgorithmName.SHA256,
                RSASignaturePadding.Pss))
            {
                throw new InvalidDataException("Artifact publisher signature is invalid.");
            }
        }
        catch (CryptographicException exception)
        {
            throw new InvalidDataException("Artifact publisher key is invalid.", exception);
        }
    }

    public static byte[] SigningPayload(
        InstallationManifest manifest,
        InstallationArtifact artifact) => SigningPayload(
            manifest.IntegrationId,
            manifest.ReleaseVersion,
            artifact.Id,
            artifact.SizeBytes,
            artifact.Sha256);

    public static byte[] SigningPayload(
        string integrationId,
        string releaseVersion,
        string artifactId,
        long sizeBytes,
        string sha256) => Encoding.UTF8.GetBytes(
            "ShedLink-Artifact-v1\n" +
            integrationId + "\n" +
            releaseVersion + "\n" +
            artifactId + "\n" +
            sizeBytes + "\n" +
            sha256 + "\n");
}
