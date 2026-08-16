namespace ShedLink.Manager.Core.Detection;

public sealed record DetectedGameVersion(string FullVersion, string CompatibilityVersion);

public static class GameVersionDetector
{
    /// <summary>
    /// Temporary shim over the manifest-driven detector; see
    /// <see cref="RimWorldDetectionService"/>.
    /// </summary>
    public static DetectedGameVersion? DetectRimWorld(string gameRoot) =>
        new GameDetectionService(RimWorldDetectionService.Descriptor).DetectVersion(gameRoot);

    public static string Compatibility(
        DetectedGameVersion? version,
        IReadOnlyList<string>? supportedVersions)
    {
        if (version is null || supportedVersions is null || supportedVersions.Count == 0)
        {
            return "unknown";
        }
        return supportedVersions.Contains(
            version.CompatibilityVersion, StringComparer.Ordinal)
            ? "supported"
            : "unsupported";
    }
}
