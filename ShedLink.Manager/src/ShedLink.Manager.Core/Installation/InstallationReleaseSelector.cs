namespace ShedLink.Manager.Core.Installation;

public sealed record InstallationRelease(string ManifestPath, InstallationManifest Manifest);

public static class InstallationReleaseSelector
{
    public static InstallationRelease? SelectCompatible(
        IEnumerable<InstallationRelease> releases,
        string gameId,
        string compatibilityVersion) =>
        Order(releases.Where(release => release.Manifest.Game is not null &&
            string.Equals(release.Manifest.Game.Id, gameId, StringComparison.Ordinal) &&
            release.Manifest.Game.SupportedVersions.Contains(
                compatibilityVersion, StringComparer.Ordinal)))
        .FirstOrDefault();

    public static InstallationRelease? SelectLatest(
        IEnumerable<InstallationRelease> releases,
        string gameId) =>
        Order(releases.Where(release => release.Manifest.Game is null ||
            string.Equals(release.Manifest.Game.Id, gameId, StringComparison.Ordinal)))
        .FirstOrDefault();

    private static IOrderedEnumerable<InstallationRelease> Order(
        IEnumerable<InstallationRelease> releases) =>
        releases
            .OrderByDescending(
                release => ParseVersion(release.Manifest.ReleaseVersion),
                Comparer<Version>.Default)
            .ThenByDescending(
                release => release.Manifest.ReleaseVersion,
                StringComparer.Ordinal);

    private static Version ParseVersion(string value) =>
        Version.TryParse(value, out var version) ? version : new Version(0, 0);
}
