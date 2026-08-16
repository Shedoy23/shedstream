namespace ShedLink.Manager.Core.Installation;

public enum InstallationCondition
{
    NotInstalled,
    Healthy,
    UpdateAvailable,
    RepairRequired,
    UnsafeTarget,
}

public sealed record InstallationInspection(
    InstallationCondition Condition,
    string TargetPath,
    string? InstalledVersion,
    string AvailableVersion,
    IReadOnlyList<string> FailedProbeIds);

public static class InstallationInspector
{
    public static InstallationInspection Inspect(
        InstallationManifest manifest,
        string gameRoot,
        string? installedVersion)
    {
        var target = PathBoundary.CombineWithin(
            gameRoot, manifest.Installation.Target.RelativePath);
        if (!Directory.Exists(target))
        {
            return Result(InstallationCondition.NotInstalled, Array.Empty<string>());
        }
        if ((File.GetAttributes(target) & FileAttributes.ReparsePoint) != 0)
        {
            return Result(InstallationCondition.UnsafeTarget, Array.Empty<string>());
        }

        var failed = manifest.Health
            .Where(probe => probe.Required && probe.Kind == "path_exists")
            .Where(probe => string.IsNullOrWhiteSpace(probe.Path) ||
                !ExistsWithin(target, probe.Path!))
            .Select(probe => probe.Id)
            .ToArray();
        if (failed.Length > 0 || string.IsNullOrWhiteSpace(installedVersion))
        {
            return Result(InstallationCondition.RepairRequired, failed);
        }
        if (!string.Equals(
            installedVersion, manifest.ReleaseVersion, StringComparison.Ordinal))
        {
            return Result(InstallationCondition.UpdateAvailable, failed);
        }
        return Result(InstallationCondition.Healthy, failed);

        InstallationInspection Result(
            InstallationCondition condition,
            IReadOnlyList<string> failedProbeIds) => new(
                condition,
                target,
                installedVersion,
                manifest.ReleaseVersion,
                failedProbeIds);
    }

    private static bool ExistsWithin(string target, string relativePath)
    {
        var path = PathBoundary.CombineWithin(target, relativePath);
        return File.Exists(path) || Directory.Exists(path);
    }
}
