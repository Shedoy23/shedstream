namespace ShedLink.Manager.Core.Installation;

public static class ConfigurationValueResolver
{
    public static IReadOnlyDictionary<string, string> Resolve(
        InstallationManifest manifest,
        Uri backendUrl,
        string moduleToken)
    {
        var values = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var field in manifest.Configuration.ManagedFields)
        {
            values[field.Selector] = field.ValueSource switch
            {
                "backend_url" => backendUrl.AbsoluteUri.TrimEnd('/'),
                "channel_module_token" => moduleToken,
                _ => throw new InvalidDataException(
                    $"Unsupported configuration value source: {field.ValueSource}."),
            };
        }
        return values;
    }
}
