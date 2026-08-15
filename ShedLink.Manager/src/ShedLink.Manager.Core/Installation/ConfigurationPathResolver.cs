namespace ShedLink.Manager.Core.Installation;

public static class ConfigurationPathResolver
{
    public static string Resolve(
        ConfigurationStore store,
        string? windowsLocalLowOverride = null)
    {
        if (store.Kind != "xml" || store.KnownFolder != "windows_local_low")
        {
            throw new InvalidDataException("Unsupported integration configuration store.");
        }
        var root = windowsLocalLowOverride ?? WindowsLocalLow();
        return PathBoundary.CombineWithin(root, store.RelativePath);
    }

    private static string WindowsLocalLow()
    {
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var appData = Path.GetDirectoryName(local);
        if (string.IsNullOrWhiteSpace(appData))
        {
            throw new InvalidOperationException("Windows LocalLow folder is unavailable.");
        }
        return Path.Combine(appData, "LocalLow");
    }
}
