using System.Text.Json;
using System.Text.Json.Nodes;

namespace ShedLink.Manager.Core.Installation;

/// <summary>
/// Flat JSON configuration, as used by mods that parse their settings without a
/// JSON library. Selectors are <c>/key</c>; unknown keys written by the mod or
/// the user are preserved.
/// </summary>
public static class ManagedJsonConfiguration
{
    private static readonly JsonSerializerOptions Formatting = new()
    {
        WriteIndented = true,
    };

    public static void Write(
        string path,
        IReadOnlyDictionary<string, string> selectorValues)
    {
        using var update = PrepareWrite(path, selectorValues);
        update.Commit();
    }

    public static ManagedConfigurationUpdate PrepareWrite(
        string path,
        IReadOnlyDictionary<string, string> selectorValues)
    {
        if (selectorValues.Count == 0)
        {
            throw new ArgumentException("At least one managed field is required.");
        }
        path = Path.GetFullPath(path);
        Recover(path);
        JsonObject document;
        if (File.Exists(path))
        {
            try
            {
                document = JsonNode.Parse(File.ReadAllText(path)) as JsonObject
                    ?? throw new InvalidDataException(
                        "Configuration JSON must be an object.");
            }
            catch (JsonException exception)
            {
                throw new InvalidDataException(
                    "Configuration JSON is malformed.", exception);
            }
        }
        else
        {
            document = new JsonObject();
        }

        foreach (var pair in selectorValues)
        {
            document[Key(pair.Key)] = ParseScalar(pair.Value);
        }

        return ManagedConfiguration.PrepareWrite(
            path,
            temporary => File.WriteAllText(
                temporary, document.ToJsonString(Formatting) + Environment.NewLine));
    }

    public static bool Complete(string path) => ManagedConfiguration.Complete(path);

    public static bool Recover(string path) => ManagedConfiguration.Recover(path);

    private static string Key(string selector)
    {
        var parts = selector.Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length != 1 || parts[0].Any(character =>
            !char.IsLetterOrDigit(character) && character is not '_' and not '-'))
        {
            throw new InvalidDataException(
                "Managed JSON selector must name a single top-level key.");
        }
        return parts[0];
    }

    /// <summary>
    /// Mods that hand-parse JSON expect numbers unquoted, so a value that is a
    /// plain integer is written as a number and everything else as a string.
    /// </summary>
    private static JsonNode ParseScalar(string value) =>
        long.TryParse(value, out var number)
            ? JsonValue.Create(number)
            : JsonValue.Create(value);
}
