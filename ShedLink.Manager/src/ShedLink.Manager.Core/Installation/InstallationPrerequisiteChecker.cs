namespace ShedLink.Manager.Core.Installation;

public sealed record MissingPrerequisite(string Id, string Message, Uri HelpUrl);

public static class InstallationPrerequisiteChecker
{
    public static MissingPrerequisite? FirstMissing(
        InstallationManifest manifest,
        string gameRoot)
    {
        foreach (var prerequisite in manifest.Prerequisites)
        {
            if (string.IsNullOrWhiteSpace(prerequisite.PathPattern) ||
                prerequisite.HelpUrl is null ||
                string.IsNullOrWhiteSpace(prerequisite.Message))
            {
                continue;
            }
            var relativeDirectory = Path.GetDirectoryName(prerequisite.PathPattern) ?? string.Empty;
            var pattern = Path.GetFileName(prerequisite.PathPattern);
            var directory = PathBoundary.CombineWithin(gameRoot,
                string.IsNullOrWhiteSpace(relativeDirectory) ? "." : relativeDirectory);
            var found = Directory.Exists(directory) &&
                Directory.EnumerateFileSystemEntries(directory, pattern).Any();
            if (!found)
            {
                return new MissingPrerequisite(
                    prerequisite.Id, prerequisite.Message, prerequisite.HelpUrl);
            }
        }
        return null;
    }
}
