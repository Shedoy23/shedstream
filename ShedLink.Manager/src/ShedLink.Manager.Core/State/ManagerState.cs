namespace ShedLink.Manager.Core.State;

public sealed record ManagerState
{
    public int SchemaVersion { get; init; } = 1;
    public required string InstallationId { get; init; }
    public Uri BackendUrl { get; init; } = new("https://shedoy23.ru");
    public string ModuleId { get; init; } = "rimworld";
    public long? ChannelId { get; init; }
    public string? CredentialId { get; init; }
    public string? GameRoot { get; init; }
    public string? InstalledReleaseVersion { get; init; }
}
