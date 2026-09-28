using System.Text.Json;

namespace ShedLink.Manager.Core.State;

public sealed class ManagerStateStore
{
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = true,
    };

    public string FilePath { get; }

    public ManagerStateStore(string? filePath = null)
    {
        FilePath = filePath ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "ShedLink",
            "Manager",
            "state.json");
    }

    public ManagerState LoadOrCreate()
    {
        if (!File.Exists(FilePath))
        {
            var created = new ManagerState { InstallationId = Guid.NewGuid().ToString("N") };
            Save(created);
            return created;
        }
        var state = JsonSerializer.Deserialize<ManagerState>(
            File.ReadAllText(FilePath), Json);
        if (state is null || state.SchemaVersion != 1 ||
            !Guid.TryParseExact(state.InstallationId, "N", out _))
        {
            throw new InvalidDataException("Manager state is invalid or unsupported.");
        }
        return state;
    }

    public void Save(ManagerState state)
    {
        ArgumentNullException.ThrowIfNull(state);
        var directory = Path.GetDirectoryName(FilePath)
            ?? throw new InvalidOperationException("State path has no directory.");
        Directory.CreateDirectory(directory);
        var temporary = FilePath + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(state, Json));
        File.Move(temporary, FilePath, overwrite: true);
    }
}
