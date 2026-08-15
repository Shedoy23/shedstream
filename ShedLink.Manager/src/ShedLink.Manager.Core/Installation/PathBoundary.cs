namespace ShedLink.Manager.Core.Installation;

public static class PathBoundary
{
    public static void ValidateRelative(string value)
    {
        if (string.IsNullOrWhiteSpace(value) || Path.IsPathRooted(value))
        {
            throw new InvalidDataException("Path must be relative.");
        }
        var parts = value.Replace('\\', '/').Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length == 0 || parts.Any(part => part is "." or ".." || part.Contains(':')))
        {
            throw new InvalidDataException("Relative path escapes its allowed root.");
        }
    }

    public static string Within(string path, string root)
    {
        var fullRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) +
            Path.DirectorySeparatorChar;
        var fullPath = Path.GetFullPath(path);
        if (!fullPath.StartsWith(fullRoot, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("Path escapes its allowed root.");
        }
        return fullPath;
    }

    public static string CombineWithin(string root, string relative)
    {
        ValidateRelative(relative);
        return Within(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)), root);
    }
}
