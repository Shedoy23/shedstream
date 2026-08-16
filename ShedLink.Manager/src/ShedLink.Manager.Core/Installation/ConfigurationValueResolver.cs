namespace ShedLink.Manager.Core.Installation;

public static class ConfigurationValueResolver
{
    public static IReadOnlyDictionary<string, string> Resolve(
        InstallationManifest manifest,
        Uri backendUrl,
        string moduleToken,
        long? channelId = null)
    {
        var values = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var field in manifest.Configuration.ManagedFields)
        {
            values[field.Selector] = field.ValueSource switch
            {
                "backend_url" => backendUrl.AbsoluteUri.TrimEnd('/'),
                "channel_module_token" => moduleToken,
                "channel_id" => (channelId ?? throw new InvalidDataException(
                    "Configuration needs the channel id, but the Manager session has none."))
                    .ToString(System.Globalization.CultureInfo.InvariantCulture),
                _ => throw new InvalidDataException(
                    $"Unsupported configuration value source: {field.ValueSource}."),
            };
        }
        return values;
    }
}
