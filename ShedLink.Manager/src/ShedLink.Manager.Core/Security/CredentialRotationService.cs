using System.Text.Json;
using System.Text.Json.Serialization;
using ShedLink.Manager.Core.Api;
using ShedLink.Manager.Core.Installation;
using ShedLink.Manager.Core.State;

namespace ShedLink.Manager.Core.Security;

public sealed record CredentialRotationResult(
    string CredentialId,
    string ModuleId,
    string ConfigPath);

public sealed class CredentialRotationService
{
    private static readonly JsonSerializerOptions Json = new() { WriteIndented = true };

    private readonly ManagerApiClient _api;
    private readonly ICredentialVault _vault;
    private readonly ManagerStateStore _stateStore;
    private readonly string _journalPath;

    public bool HasPending => File.Exists(_journalPath);

    public CredentialRotationService(
        ManagerApiClient api,
        ICredentialVault vault,
        ManagerStateStore stateStore,
        string? journalPath = null)
    {
        _api = api;
        _vault = vault;
        _stateStore = stateStore;
        _journalPath = journalPath ?? Path.Combine(
            Path.GetDirectoryName(stateStore.FilePath)!, "credential-rotation.json");
    }

    public async Task<CredentialRotationResult> RotateAsync(
        ReadySession session,
        string manifestPath,
        string label = "ShedLink Manager",
        string? windowsLocalLowOverride = null,
        CancellationToken cancellationToken = default)
    {
        if (File.Exists(_journalPath))
        {
            return await RecoverPendingAsync(
                session, manifestPath, windowsLocalLowOverride, cancellationToken)
                ?? throw new InvalidOperationException("Credential rotation recovery failed.");
        }
        var state = _stateStore.LoadOrCreate();
        ValidateSession(state, session);
        var currentToken = _vault.Read(
            CredentialKeys.ModuleToken(state.InstallationId, session.ModuleId));
        if (string.IsNullOrWhiteSpace(currentToken) ||
            string.IsNullOrWhiteSpace(state.CredentialId))
        {
            throw new InvalidOperationException("Current module credential is unavailable.");
        }

        var replacement = await _api.RotateCredentialAsync(
            session.AccessToken,
            state.CredentialId,
            label,
            cancellationToken);
        var pendingKey = CredentialKeys.PendingModuleToken(
            state.InstallationId, session.ModuleId);
        _vault.Write(pendingKey, replacement.ModuleToken);
        var manifest = InstallationManifestLoader.Load(manifestPath);
        var configPath = ConfigurationPathResolver.Resolve(
            manifest.Configuration.Store, windowsLocalLowOverride);
        var journal = new RotationJournal(
            "issued",
            session.ModuleId,
            state.CredentialId,
            replacement.CredentialId,
            configPath);
        WriteJournal(journal);
        return await ApplyPendingAsync(
            journal, session, manifest, replacement.ModuleToken, cancellationToken);
    }

    public async Task<CredentialRotationResult?> RecoverPendingAsync(
        ReadySession session,
        string manifestPath,
        string? windowsLocalLowOverride = null,
        CancellationToken cancellationToken = default)
    {
        if (!File.Exists(_journalPath))
        {
            return null;
        }
        var journal = ReadJournal();
        var state = _stateStore.LoadOrCreate();
        ValidateSession(state, session, journal.ModuleId);
        var manifest = InstallationManifestLoader.Load(manifestPath);
        var expectedConfig = ConfigurationPathResolver.Resolve(
            manifest.Configuration.Store, windowsLocalLowOverride);
        if (!string.Equals(
            expectedConfig, journal.ConfigPath, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("Credential rotation config path changed.");
        }
        var pendingToken = _vault.Read(
            CredentialKeys.PendingModuleToken(state.InstallationId, journal.ModuleId));
        if (string.IsNullOrWhiteSpace(pendingToken))
        {
            throw new InvalidOperationException(
                "Pending module credential is unavailable; issue a fresh credential.");
        }
        if (journal.Phase == "verified")
        {
            ManagedXmlConfiguration.Complete(journal.ConfigPath);
            return Activate(journal, state, pendingToken);
        }
        if (journal.Phase != "issued")
        {
            throw new InvalidDataException("Credential rotation journal phase is invalid.");
        }
        return await ApplyPendingAsync(
            journal, session, manifest, pendingToken, cancellationToken);
    }

    private async Task<CredentialRotationResult> ApplyPendingAsync(
        RotationJournal journal,
        ReadySession session,
        InstallationManifest manifest,
        string pendingToken,
        CancellationToken cancellationToken)
    {
        ManagedXmlUpdate? update = null;
        try
        {
            var state = _stateStore.LoadOrCreate();
            update = ManagedXmlConfiguration.PrepareWrite(
                journal.ConfigPath,
                ConfigurationValueResolver.Resolve(
                    manifest, state.BackendUrl, pendingToken));
            var auth = await _api.VerifyModuleCredentialAsync(
                pendingToken, journal.ModuleId, cancellationToken);
            if (auth.Status != "ok" || auth.ModuleId != journal.ModuleId)
            {
                throw new InvalidDataException("Replacement credential auth-check failed.");
            }
            WriteJournal(journal with { Phase = "verified" });
            update.Commit();
            return Activate(journal, state, pendingToken);
        }
        catch
        {
            update?.Rollback();
            throw;
        }
    }

    private CredentialRotationResult Activate(
        RotationJournal journal,
        ManagerState state,
        string pendingToken)
    {
        _vault.Write(
            CredentialKeys.ModuleToken(state.InstallationId, journal.ModuleId),
            pendingToken);
        _stateStore.Save(state with { CredentialId = journal.NewCredentialId });
        _vault.Delete(CredentialKeys.PendingModuleToken(
            state.InstallationId, journal.ModuleId));
        File.Delete(_journalPath);
        File.Delete(_journalPath + ".tmp");
        return new CredentialRotationResult(
            journal.NewCredentialId, journal.ModuleId, journal.ConfigPath);
    }

    private static void ValidateSession(
        ManagerState state,
        ReadySession session,
        string? expectedModuleId = null)
    {
        var moduleId = expectedModuleId ?? state.ModuleId;
        if (session.ModuleId != moduleId || state.ModuleId != moduleId)
        {
            throw new InvalidDataException("Credential rotation module scope changed.");
        }
    }

    private RotationJournal ReadJournal()
    {
        try
        {
            return JsonSerializer.Deserialize<RotationJournal>(
                File.ReadAllText(_journalPath), Json)
                ?? throw new InvalidDataException("Credential rotation journal is empty.");
        }
        catch (JsonException exception)
        {
            throw new InvalidDataException("Credential rotation journal is damaged.", exception);
        }
    }

    private void WriteJournal(RotationJournal journal)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(_journalPath)!);
        var temporary = _journalPath + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(journal, Json));
        File.Move(temporary, _journalPath, overwrite: true);
    }

    private sealed record RotationJournal(
        [property: JsonPropertyName("phase")] string Phase,
        [property: JsonPropertyName("module_id")] string ModuleId,
        [property: JsonPropertyName("old_credential_id")] string OldCredentialId,
        [property: JsonPropertyName("new_credential_id")] string NewCredentialId,
        [property: JsonPropertyName("config_path")] string ConfigPath);
}
