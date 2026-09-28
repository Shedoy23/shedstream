namespace ShedLink.Manager.Core.State;

public sealed record ManagerState
{
    public int SchemaVersion { get; init; } = 1;
    public required string InstallationId { get; init; }
    public Uri BackendUrl { get; init; } = new("https://shedoy23.ru");
    public string ModuleId { get; init; } = string.Empty;
    public long? ChannelId { get; init; }
    public string? CredentialId { get; init; }
    public string? GameRoot { get; init; }
    public string? InstalledReleaseVersion { get; init; }

    public IReadOnlyDictionary<string, IntegrationState> Integrations { get; init; } =
        new Dictionary<string, IntegrationState>(StringComparer.Ordinal);

    public IntegrationState Integration(string integrationId)
    {
        if (Integrations.TryGetValue(integrationId, out var integration))
        {
            return integration;
        }
        if (integrationId == ModuleId)
        {
            return new IntegrationState
            {
                CredentialId = CredentialId,
                GameRoot = GameRoot,
                InstalledReleaseVersion = InstalledReleaseVersion,
            };
        }
        return new IntegrationState();
    }

    public ManagerState WithIntegration(
        string integrationId,
        IntegrationState integration)
    {
        var updated = new Dictionary<string, IntegrationState>(
            Integrations, StringComparer.Ordinal);
        if (!string.IsNullOrWhiteSpace(ModuleId) && !updated.ContainsKey(ModuleId))
        {
            updated[ModuleId] = new IntegrationState
            {
                CredentialId = CredentialId,
                GameRoot = GameRoot,
                InstalledReleaseVersion = InstalledReleaseVersion,
            };
        }
        updated[integrationId] = integration;
        return this with
        {
            ModuleId = integrationId,
            CredentialId = integration.CredentialId,
            GameRoot = integration.GameRoot,
            InstalledReleaseVersion = integration.InstalledReleaseVersion,
            Integrations = updated,
        };
    }
}

public sealed record IntegrationState
{
    public string? CredentialId { get; init; }
    public string? GameRoot { get; init; }
    public string? InstalledReleaseVersion { get; init; }
}
