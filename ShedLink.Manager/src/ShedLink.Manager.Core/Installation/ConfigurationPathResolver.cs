namespace ShedLink.Manager.Core.Installation;

public static class ConfigurationPathResolver
{
    public static string Resolve(
        ConfigurationStore store,
        string? windowsLocalLowOverride = null,
        string? gameRoot = null)
    {
        var root = store.Base switch
        {
            "windows_local_low" => windowsLocalLowOverride ?? WindowsLocalLow(),
            "game_root" => gameRoot ?? throw new InvalidDataException(
                "Configuration lives in the game folder, but no game folder is known."),
            _ => throw new InvalidDataException("Unsupported integration configuration store."),
        };
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
