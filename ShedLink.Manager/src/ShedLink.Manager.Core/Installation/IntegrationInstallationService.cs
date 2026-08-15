using System.Text.Json;
using System.Text.Json.Serialization;
using ShedLink.Manager.Core.Api;
using ShedLink.Manager.Core.Security;
using ShedLink.Manager.Core.State;

namespace ShedLink.Manager.Core.Installation;

public sealed class IntegrationInstallationService
{
    private static readonly JsonSerializerOptions JournalJson = new()
    {
        WriteIndented = true,
    };

    private readonly ManagerApiClient _api;
    private readonly ICredentialVault _vault;
    private readonly ManagerStateStore _stateStore;
    private readonly PackageInstaller _packageInstaller;
    private readonly string _journalPath;

    public IntegrationInstallationService(
        ManagerApiClient api,
        ICredentialVault vault,
        ManagerStateStore stateStore,
        PackageInstaller? packageInstaller = null,
        string? journalPath = null)
    {
        _api = api;
        _vault = vault;
        _stateStore = stateStore;
        _packageInstaller = packageInstaller ?? new PackageInstaller();
        _journalPath = journalPath ?? Path.Combine(
            Path.GetDirectoryName(stateStore.FilePath)!, "installation-transaction.json");
    }

    public async Task<InstallationResult> InstallRepositoryAsync(
        string manifestPath,
        string repositoryRoot,
        string gameRoot,
        string? windowsLocalLowOverride = null,
        Action<string>? failpoint = null,
        CancellationToken cancellationToken = default)
    {
        return await InstallPreparedAsync(
            manifestPath,
            gameRoot,
            windowsLocalLowOverride,
            () => Task.FromResult(_packageInstaller.PrepareRepositoryArtifact(
                manifestPath, repositoryRoot, gameRoot)),
            failpoint,
            cancellationToken);
    }

    public async Task<InstallationResult> InstallHttpsAsync(
        string manifestPath,
        string gameRoot,
        SecureArtifactDownloader downloader,
        ArtifactSignatureVerifier signatureVerifier,
        string? windowsLocalLowOverride = null,
        Action<string>? failpoint = null,
        CancellationToken cancellationToken = default)
    {
        return await InstallPreparedAsync(
            manifestPath,
            gameRoot,
            windowsLocalLowOverride,
            () => _packageInstaller.PrepareHttpsArtifactAsync(
                manifestPath,
                gameRoot,
                downloader,
                signatureVerifier,
                cancellationToken: cancellationToken),
            failpoint,
            cancellationToken);
    }

    public bool Uninstall(
        string manifestPath,
        string gameRoot,
        string? windowsLocalLowOverride = null,
        Action<string>? failpoint = null)
    {
        RecoverPending();
        var manifest = InstallationManifestLoader.Load(manifestPath);
        var state = _stateStore.LoadOrCreate();
        ValidateScope(manifest, state);
        var configPath = ConfigurationPathResolver.Resolve(
            manifest.Configuration.Store, windowsLocalLowOverride);
        var targetPath = PathBoundary.CombineWithin(
            gameRoot, manifest.Installation.Target.RelativePath);
        var journal = new InstallationOperationJournal(
            "applying", Path.GetFullPath(gameRoot), targetPath, configPath);
        WriteJournal(journal);
        AtomicDirectoryReplacement? removal = null;
        var verified = false;
        try
        {
            removal = AtomicDirectoryTransaction.PrepareRemoval(targetPath, gameRoot);
            if (removal is null)
            {
                File.Delete(_journalPath);
                File.Delete(_journalPath + ".tmp");
                return false;
            }
            verified = true;
            WriteJournal(journal with { Phase = "verified" });
            failpoint?.Invoke("verified");
            removal.Commit();
            File.Delete(_journalPath);
            File.Delete(_journalPath + ".tmp");
            return true;
        }
        catch
        {
            if (!verified)
            {
                removal?.Rollback();
                File.Delete(_journalPath);
                File.Delete(_journalPath + ".tmp");
            }
            throw;
        }
    }

    private async Task<InstallationResult> InstallPreparedAsync(
        string manifestPath,
        string gameRoot,
        string? windowsLocalLowOverride,
        Func<Task<PreparedInstallation>> preparePackage,
        Action<string>? failpoint,
        CancellationToken cancellationToken)
    {
        RecoverPending();
        var manifest = InstallationManifestLoader.Load(manifestPath);
        var state = _stateStore.LoadOrCreate();
        ValidateScope(manifest, state);
        var moduleToken = _vault.Read(
            CredentialKeys.ModuleToken(state.InstallationId, state.ModuleId));
        if (string.IsNullOrWhiteSpace(moduleToken))
        {
            throw new InvalidOperationException("Module credential is unavailable.");
        }
        var configPath = ConfigurationPathResolver.Resolve(
            manifest.Configuration.Store, windowsLocalLowOverride);
        var targetPath = PathBoundary.CombineWithin(
            gameRoot, manifest.Installation.Target.RelativePath);
        var journal = new InstallationOperationJournal(
            "applying", Path.GetFullPath(gameRoot), targetPath, configPath);
        WriteJournal(journal);

        PreparedInstallation? package = null;
        ManagedXmlUpdate? configuration = null;
        var verified = false;
        try
        {
            package = await preparePackage();
            configuration = ManagedXmlConfiguration.PrepareWrite(
                configPath,
                ConfigurationValues(manifest, state.BackendUrl, moduleToken));
            var auth = await _api.VerifyModuleCredentialAsync(
                moduleToken, manifest.IntegrationId, cancellationToken);
            if (auth.Status != "ok" || auth.ModuleId != manifest.IntegrationId)
            {
                throw new InvalidDataException("Backend returned an invalid auth-check response.");
            }

            verified = true;
            WriteJournal(journal with { Phase = "verified" });
            failpoint?.Invoke("verified");
            package.Commit();
            configuration.Commit();
            File.Delete(_journalPath);
            File.Delete(_journalPath + ".tmp");
            return package.Result;
        }
        catch
        {
            if (!verified)
            {
                configuration?.Rollback();
                package?.Rollback();
                File.Delete(_journalPath);
                File.Delete(_journalPath + ".tmp");
            }
            throw;
        }
    }

    public bool RecoverPending()
    {
        if (!File.Exists(_journalPath))
        {
            return false;
        }
        InstallationOperationJournal journal;
        try
        {
            journal = JsonSerializer.Deserialize<InstallationOperationJournal>(
                File.ReadAllText(_journalPath), JournalJson)
                ?? throw new InvalidDataException("Installation journal is empty.");
        }
        catch (JsonException exception)
        {
            throw new InvalidDataException("Installation journal is damaged.", exception);
        }

        if (journal.Phase == "verified")
        {
            AtomicDirectoryTransaction.Complete(journal.TargetPath, journal.GameRoot);
            ManagedXmlConfiguration.Complete(journal.ConfigPath);
        }
        else if (journal.Phase == "applying")
        {
            ManagedXmlConfiguration.Recover(journal.ConfigPath);
            AtomicDirectoryTransaction.Recover(journal.TargetPath, journal.GameRoot);
        }
        else
        {
            throw new InvalidDataException("Installation journal phase is invalid.");
        }
        File.Delete(_journalPath);
        File.Delete(_journalPath + ".tmp");
        return true;
    }

    private static void ValidateScope(InstallationManifest manifest, ManagerState state)
    {
        if (!string.Equals(manifest.IntegrationId, state.ModuleId, StringComparison.Ordinal))
        {
            throw new InvalidDataException("Manifest and Manager session module do not match.");
        }
    }

    private static IReadOnlyDictionary<string, string> ConfigurationValues(
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

    private void WriteJournal(InstallationOperationJournal journal)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(_journalPath)!);
        var temporary = _journalPath + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(journal, JournalJson));
        File.Move(temporary, _journalPath, overwrite: true);
    }

    private sealed record InstallationOperationJournal(
        [property: JsonPropertyName("phase")] string Phase,
        [property: JsonPropertyName("game_root")] string GameRoot,
        [property: JsonPropertyName("target_path")] string TargetPath,
        [property: JsonPropertyName("config_path")] string ConfigPath);
}
