namespace ShedLink.Manager.Core.Installation;

public sealed record InstallationResult(
    string IntegrationId,
    string ReleaseVersion,
    string TargetPath);

public sealed class PackageInstaller
{
    public InstallationResult InstallRepositoryArtifact(
        string manifestPath,
        string repositoryRoot,
        string gameRoot,
        Action<string>? failpoint = null)
    {
        var manifest = InstallationManifestLoader.Load(manifestPath);
        var artifact = manifest.Artifacts[0];
        var archivePath = PathBoundary.CombineWithin(repositoryRoot, artifact.Source.Path);
        ArtifactVerifier.Verify(archivePath, artifact);
        var target = PathBoundary.CombineWithin(
            gameRoot, manifest.Installation.Target.RelativePath);
        var temporary = Path.Combine(
            Path.GetTempPath(), "ShedLink", "Manager", Guid.NewGuid().ToString("N"));
        try
        {
            SafeZipExtractor.Extract(archivePath, temporary);
            var source = PathBoundary.CombineWithin(temporary, artifact.ArchiveRoot);
            if (!Directory.Exists(source))
            {
                throw new InvalidDataException("Archive root is missing.");
            }
            AtomicDirectoryTransaction.Replace(
                source,
                target,
                gameRoot,
                staged => VerifyRequiredPaths(staged, manifest.Health),
                failpoint);
            return new InstallationResult(
                manifest.IntegrationId,
                manifest.ReleaseVersion,
                target);
        }
        finally
        {
            if (Directory.Exists(temporary))
            {
                Directory.Delete(temporary, recursive: true);
            }
        }
    }

    private static void VerifyRequiredPaths(
        string stagedRoot,
        IReadOnlyList<HealthProbe> probes)
    {
        foreach (var probe in probes.Where(probe =>
            probe.Required && probe.Kind == "path_exists"))
        {
            if (string.IsNullOrWhiteSpace(probe.Path))
            {
                throw new InvalidDataException("Required path probe has no path.");
            }
            var path = PathBoundary.CombineWithin(stagedRoot, probe.Path);
            if (!File.Exists(path) && !Directory.Exists(path))
            {
                throw new InvalidDataException($"Required installed path is missing: {probe.Id}.");
            }
        }
    }
}
