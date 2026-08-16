using System.Text.RegularExpressions;

namespace ShedLink.Manager.Core.Detection;

public sealed record DetectedGameVersion(string FullVersion, string CompatibilityVersion);

public static partial class GameVersionDetector
{
    public static DetectedGameVersion? DetectRimWorld(string gameRoot)
    {
        var path = Path.Combine(gameRoot, "Version.txt");
        if (!File.Exists(path))
        {
            return null;
        }
        var fullVersion = File.ReadLines(path)
            .Select(line => line.Trim())
            .FirstOrDefault(line => line.Length > 0);
        if (fullVersion is null)
        {
            return null;
        }
        var match = MajorMinorRegex().Match(fullVersion);
        return match.Success
            ? new DetectedGameVersion(fullVersion, match.Value)
            : null;
    }

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

    [GeneratedRegex(@"^\d+\.\d+", RegexOptions.CultureInvariant)]
    private static partial Regex MajorMinorRegex();
}
