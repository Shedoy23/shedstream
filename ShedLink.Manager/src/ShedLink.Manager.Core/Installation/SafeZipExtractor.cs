using System.IO.Compression;

namespace ShedLink.Manager.Core.Installation;

public static class SafeZipExtractor
{
    private const long MaxExpandedBytes = 512L * 1024 * 1024;

    public static void Extract(string archivePath, string destination)
    {
        Directory.CreateDirectory(destination);
        using var archive = ZipFile.OpenRead(archivePath);
        var total = archive.Entries.Sum(entry => entry.Length);
        if (total > MaxExpandedBytes)
        {
            throw new InvalidDataException("Archive expands beyond the Manager safety limit.");
        }
        foreach (var entry in archive.Entries)
        {
            var unixMode = (entry.ExternalAttributes >> 16) & 0xF000;
            if (unixMode == 0xA000)
            {
                throw new InvalidDataException("Archive contains a symbolic link.");
            }
            var relative = entry.FullName.Replace('\\', '/');
            PathBoundary.ValidateRelative(relative.TrimEnd('/'));
            var output = PathBoundary.CombineWithin(destination, relative.TrimEnd('/'));
            if (relative.EndsWith("/", StringComparison.Ordinal))
            {
                Directory.CreateDirectory(output);
                continue;
            }
            Directory.CreateDirectory(Path.GetDirectoryName(output)!);
            using var input = entry.Open();
            using var file = new FileStream(output, FileMode.CreateNew, FileAccess.Write, FileShare.None);
            input.CopyTo(file);
        }
    }
}
