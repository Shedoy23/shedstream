namespace ShedLink.Manager.Core.Installation;

/// <summary>Picks the configuration format the manifest declares.</summary>
public static class ManagedConfigurationWriter
{
    public static ManagedConfigurationUpdate PrepareWrite(
        string kind,
        string path,
        IReadOnlyDictionary<string, string> selectorValues) => kind switch
    {
        "xml" => ManagedXmlConfiguration.PrepareWrite(path, selectorValues),
        "json" => ManagedJsonConfiguration.PrepareWrite(path, selectorValues),
        _ => throw new InvalidDataException(
            $"Unsupported configuration format: {kind}."),
    };
}
