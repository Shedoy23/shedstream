namespace ShedLink.Manager.Core.Installation;

public sealed class InstallationReleaseCatalog
{
    private readonly IReadOnlyList<InstallationRelease> _releases;

    public InstallationReleaseCatalog(IEnumerable<InstallationRelease> releases)
    {
        _releases = releases.ToArray();
    }

    public static InstallationReleaseCatalog LoadDirectory(string directory)
    {
        var releases = Directory.EnumerateFiles(directory, "*.json")
            .Where(path => !path.EndsWith(
                ".schema.json", StringComparison.OrdinalIgnoreCase))
            .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
            .Select(path => new InstallationRelease(
                path, InstallationManifestLoader.Load(path)));
        return new InstallationReleaseCatalog(releases);
    }

    public IReadOnlyList<InstallationRelease> LatestIntegrations() =>
        _releases
            .GroupBy(release => release.Manifest.IntegrationId, StringComparer.Ordinal)
            .Select(group => InstallationReleaseSelector.SelectLatest(
                group.ToArray(), group.Key)!)
            .OrderBy(release => release.Manifest.Game?.DisplayName, StringComparer.CurrentCulture)
            .ToArray();

    public InstallationRelease? SelectLatest(string integrationId) =>
        InstallationReleaseSelector.SelectLatest(_releases, integrationId);

    public InstallationRelease? SelectCompatible(
        string integrationId,
        string compatibilityVersion) =>
        InstallationReleaseSelector.SelectCompatible(
            _releases, integrationId, compatibilityVersion);
}
