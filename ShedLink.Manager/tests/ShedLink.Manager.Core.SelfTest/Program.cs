using System.Net;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using ShedLink.Manager.Core;
using ShedLink.Manager.Core.Api;
using ShedLink.Manager.Core.Detection;
using ShedLink.Manager.Core.Diagnostics;
using ShedLink.Manager.Core.Installation;
using ShedLink.Manager.Core.Security;
using ShedLink.Manager.Core.State;
using ShedLink.Manager.Core.Update;

var root = Path.Combine(Path.GetTempPath(), "shedlink-manager-test-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
try
{
    await TestCoordinatorAsync(root);
    TestRimWorldDetection(root);
    TestManifestDrivenDetection(root);
    TestJsonConfigurationStore(root);
    TestFailureMessages();
    TestDeniedWriteScenario(root);
    await TestInstallationAsync(root);
    await TestHttpsDistributionAsync(root);
    await TestManagerUpdateAsync(root);
    TestDiagnosticReport(root);
    TestWindowsVault();
    Console.WriteLine("ALL GREEN — Manager core keeps secrets out of local state and survives restart.");
    return 0;
}
finally
{
    Directory.Delete(root, recursive: true);
}

static async Task TestCoordinatorAsync(string root)
{
    var handler = new FakeManagerHandler();
    var api = new ManagerApiClient(new HttpClient(handler)
    {
        BaseAddress = new Uri("https://manager.test"),
    });
    var vault = new MemoryVault();
    var statePath = Path.Combine(root, "state.json");
    var store = new ManagerStateStore(statePath);
    var coordinator = new ManagerCoordinator(api, vault, store);

    var launch = await coordinator.BeginPairingAsync("rimworld");
    Assert(launch.UserCode == "ABCD-EFGH", "pairing user code");
    Assert(launch.VerificationUri.Scheme == "https", "pairing HTTPS URL");
    Assert(!handler.LastCreateBody.Contains("device-secret", StringComparison.Ordinal),
        "raw device secret is not sent during create");
    Assert(await coordinator.TryCompletePairingAsync() is null, "pending exchange");
    var ready = await coordinator.TryCompletePairingAsync();
    Assert(ready is not null && ready.ChannelId == 98319857, "approved exchange");
    Assert(vault.Values.Values.Contains("refresh-one"), "refresh stored in vault");
    Assert(vault.Values.Values.Contains("slmod_v1.credential-one.secret"),
        "module credential stored in vault");
    var checkedCredential = await api.VerifyModuleCredentialAsync(
        "slmod_v1.credential-one.secret", "rimworld");
    Assert(checkedCredential is { Status: "ok", ModuleId: "rimworld" },
        "module credential auth-check does not require heartbeat");
    var runtimeStatus = await api.GetModuleStatusAsync(
        "slmod_v1.credential-one.secret", "rimworld");
    Assert(runtimeStatus is { Online: false, LastSeenAt: null, AgeSeconds: null },
        "module status reports real missing heartbeat");
    var diagnostic = await api.StartDiagnosticAsync(ready!.AccessToken);
    var diagnosticResult = await api.GetDiagnosticResultAsync(
        ready.AccessToken, diagnostic.DiagnosticId);
    Assert(diagnostic is { Status: "queued", ExpiresIn: 120 } &&
        diagnosticResult is { Status: "acked", Error: null },
        "safe diagnostic follows real queue and ACK contract");
    var refusedDiagnostic = await api.StartDiagnosticAsync(
        ready.AccessToken, "refuse");
    var refusedResult = await api.GetDiagnosticResultAsync(
        ready.AccessToken, refusedDiagnostic.DiagnosticId);
    Assert(refusedDiagnostic.Mode == "refuse" &&
        refusedResult is { Status: "failed", Mode: "refuse" } &&
        refusedResult.Error!.Contains("diagnostic_refuse", StringComparison.Ordinal),
        "reliability diagnostic records safe module refusal");
    var lostAckDiagnostic = await api.StartDiagnosticAsync(
        ready.AccessToken, "lost_ack");
    var lostAckResult = await api.GetDiagnosticResultAsync(
        ready.AccessToken, lostAckDiagnostic.DiagnosticId);
    Assert(lostAckDiagnostic.Mode == "lost_ack" &&
        lostAckResult is
        { Status: "expired", Mode: "lost_ack", Error: "simulated_ack_timeout" },
        "reliability diagnostic records and cleans lost ACK");

    var rotation = new CredentialRotationService(api, vault, store);
    var manifestPath = Path.Combine(
        Environment.CurrentDirectory,
        "manifests",
        "installation",
        "rimworld-0.1.1.json");
    var rotationConfigRoot = Path.Combine(root, "rotation-local-low");
    handler.RejectAuthCheck = true;
    try
    {
        await rotation.RotateAsync(ready, manifestPath,
            windowsLocalLowOverride: rotationConfigRoot);
        throw new InvalidOperationException("FAILED: failed rotation remains recoverable");
    }
    catch (ManagerApiException)
    {
        Assert(vault.Values.Values.Contains("slmod_v1.credential-one.secret") &&
            vault.Values.Values.Contains("slmod_v1.credential-two.secret"),
            "failed rotation keeps current and pending credentials in vault");
    }
    handler.RejectAuthCheck = false;
    var recoveredRotation = await rotation.RecoverPendingAsync(
        ready, manifestPath, rotationConfigRoot);
    Assert(recoveredRotation?.CredentialId == "credential-two" &&
        vault.Values.Values.Contains("slmod_v1.credential-two.secret") &&
        !vault.Values.Values.Contains("slmod_v1.credential-one.secret") &&
        File.ReadAllText(recoveredRotation.ConfigPath).Contains(
            "slmod_v1.credential-two.secret", StringComparison.Ordinal),
        "credential rotation recovers config, vault and state");

    var stateJson = File.ReadAllText(statePath);
    Assert(!stateJson.Contains("refresh-one", StringComparison.Ordinal),
        "refresh absent from JSON state");
    Assert(!stateJson.Contains("slmod_v1", StringComparison.Ordinal),
        "module token absent from JSON state");
    Assert(stateJson.Contains("credential-two", StringComparison.Ordinal),
        "non-secret credential id persisted");

    var multiGame = store.LoadOrCreate();
    var rimworldState = multiGame.Integration("rimworld");
    multiGame = multiGame.WithIntegration("bannerlord", new IntegrationState
    {
        CredentialId = "bannerlord-credential",
        GameRoot = @"D:\Games\Bannerlord",
        InstalledReleaseVersion = "0.1.0",
    });
    store.Save(multiGame);
    var reloadedMultiGame = store.LoadOrCreate();
    Assert(reloadedMultiGame.Integration("rimworld").CredentialId == "credential-two" &&
        reloadedMultiGame.Integration("bannerlord").GameRoot == @"D:\Games\Bannerlord",
        "each integration keeps its own game path, release and credential");
    Assert(CredentialKeys.ManagerRefresh(
            reloadedMultiGame.InstallationId, "rimworld") !=
        CredentialKeys.ManagerRefresh(reloadedMultiGame.InstallationId, "bannerlord"),
        "each integration keeps its own protected Manager session");
    store.Save(reloadedMultiGame.WithIntegration("rimworld", rimworldState));

    var restarted = new ManagerCoordinator(api, vault, new ManagerStateStore(statePath));
    var resumed = await restarted.ResumeAsync("rimworld");
    Assert(resumed.AccessToken == "access-two", "session refreshed after restart");
    Assert(vault.Values.Values.Contains("refresh-two"), "rotated refresh stored");
    Assert(!vault.Values.Values.Contains("refresh-one"), "old refresh replaced");

    await restarted.LogoutAsync(resumed, revokeModuleCredential: true);
    Assert(vault.Values.Count == 0, "logout removes local credentials");
    Assert(handler.SawCredentialRevoke && handler.SawLogout, "server revoke and logout called");
}

static void TestDiagnosticReport(string root)
{
    var gameRoot = Path.Combine(root, "diagnostic-game");
    Directory.CreateDirectory(gameRoot);
    File.WriteAllText(Path.Combine(gameRoot, "Version.txt"), "1.6.4871 rev590\n");
    var manifest = InstallationManifestLoader.Load(Path.Combine(
        Environment.CurrentDirectory, "manifests", "installation", "rimworld-0.1.1.json"));
    var gameVersion = new GameDetectionService(manifest.Game!).DetectVersion(gameRoot);
    Assert(gameVersion is { FullVersion: "1.6.4871 rev590", CompatibilityVersion: "1.6" } &&
        GameVersionDetector.Compatibility(gameVersion, new[] { "1.5", "1.6" }) == "supported",
        "diagnostic reads real RimWorld version and compatibility");
    Assert(GameVersionDetector.Compatibility(
            gameVersion, new[] { "1.4", "1.5" }) == "unsupported",
        "unsupported RimWorld version fails compatibility gate");
    var report = DiagnosticReportBuilder.Build(new DiagnosticReportInput(
        "1.0.0", "manager-v1", "https://manager.test/private?token=hidden",
        gameVersion!.FullVersion, "supported", null, "RepairRequired",
        "existing integration was not installed by this Manager",
        Array.Empty<string>(), true, 3,
        new[]
        {
            @"Config C:\Users\Edward\AppData token=refresh-secret",
            "Authorization: Bearer slmod_v1.credential.secret",
            "RimLink готов",
        }));
    Assert(!report.Contains("refresh-secret", StringComparison.Ordinal) &&
        !report.Contains("slmod_v1", StringComparison.Ordinal) &&
        !report.Contains("Edward", StringComparison.Ordinal) &&
        !report.Contains("/private", StringComparison.Ordinal),
        "diagnostic report redacts secrets and private paths");
    Assert(report.Contains("RimLink готов", StringComparison.Ordinal) &&
        report.Contains("manager.test", StringComparison.Ordinal) &&
        report.Contains("1.6.4871 rev590", StringComparison.Ordinal) &&
        report.Contains("unknown/unmanaged", StringComparison.Ordinal) &&
        report.Contains("existing integration was not installed", StringComparison.Ordinal),
        "diagnostic report preserves useful health context");
}

static void TestWindowsVault()
{
    var vault = new WindowsCredentialVault("ShedLink.Manager.SelfTest");
    var key = Guid.NewGuid().ToString("N");
    const string secret = "sltest_v1.super-secret-value";
    try
    {
        Assert(vault.Read(key) is null, "native vault starts empty");
        vault.Write(key, secret);
        Assert(vault.Read(key) == secret, "native vault roundtrip");
    }
    finally
    {
        vault.Delete(key);
    }
    Assert(vault.Read(key) is null, "native vault cleanup");
}

static void TestRimWorldDetection(string root)
{
    var steam = Path.Combine(root, "steam");
    var library = Path.Combine(root, "library");
    var game = Path.Combine(library, "steamapps", "common", "RimWorld");
    Directory.CreateDirectory(Path.Combine(steam, "steamapps"));
    Directory.CreateDirectory(Path.Combine(game, "Mods"));
    File.WriteAllText(Path.Combine(game, "RimWorldWin64.exe"), string.Empty);
    File.WriteAllText(
        Path.Combine(library, "steamapps", "appmanifest_294100.acf"),
        "\"AppState\" { \"appid\" \"294100\" }");
    var escapedLibrary = library.Replace("\\", "\\\\");
    File.WriteAllText(
        Path.Combine(steam, "steamapps", "libraryfolders.vdf"),
        $"\"libraryfolders\" {{ \"1\" {{ \"path\" \"{escapedLibrary}\" }} }}");

    var manifest = InstallationManifestLoader.Load(Path.Combine(
        Environment.CurrentDirectory, "manifests", "installation", "rimworld-0.1.1.json"));
    var detector = new GameDetectionService(manifest.Game!);
    var detected = detector.Detect(new[] { steam });
    Assert(detected?.RootPath == Path.GetFullPath(game), "Steam library detection");
    Assert(detected?.Source == DetectionSource.Steam, "Steam detection source");
    var manual = detector.ValidateManual(game);
    Assert(manual.Source == DetectionSource.Manual, "manual path validation");
    try
    {
        detector.ValidateManual(root);
        throw new InvalidOperationException("FAILED: invalid manual path rejected");
    }
    catch (InvalidDataException)
    {
        Console.WriteLine("  OK  invalid manual path rejected");
    }
}

static async Task TestInstallationAsync(string root)
{
    var productionManifest = InstallationManifestLoader.Load(Path.Combine(
        Environment.CurrentDirectory,
        "manifests",
        "installation",
        "rimworld-0.1.1.json"));
    Assert(productionManifest.IntegrationId == "rimworld" &&
        productionManifest.Installation.Target.RelativePath == "Mods/RimLink",
        "production installation manifest parsed");
    var releases = new[]
    {
        new InstallationRelease("rimworld-0.1.1.json", productionManifest),
        new InstallationRelease("rimworld-0.2.0.json",
            productionManifest with { ReleaseVersion = "0.2.0" }),
        new InstallationRelease("rimworld-0.3.0.json", productionManifest with
        {
            ReleaseVersion = "0.3.0",
            Game = productionManifest.Game! with { SupportedVersions = new[] { "1.7" } },
        }),
    };
    var selectedRelease = InstallationReleaseSelector.SelectCompatible(
        releases, "rimworld", "1.6");
    Assert(selectedRelease?.Manifest.ReleaseVersion == "0.2.0",
        "release catalog selects newest compatible integration");
    Assert(InstallationReleaseSelector.SelectCompatible(
            releases, "rimworld", "1.4") is null,
        "release catalog fails closed without compatible integration");

    var inspectionGame = Path.Combine(root, "inspection-game");
    var missingInspection = InstallationInspector.Inspect(
        productionManifest, inspectionGame, null);
    Assert(missingInspection.Condition == InstallationCondition.NotInstalled,
        "installation inspector detects missing integration");
    Directory.CreateDirectory(missingInspection.TargetPath);
    var brokenInspection = InstallationInspector.Inspect(
        productionManifest, inspectionGame, productionManifest.ReleaseVersion);
    Assert(brokenInspection.Condition == InstallationCondition.RepairRequired &&
        brokenInspection.FailedProbeIds.Contains("assembly_present"),
        "installation inspector detects repair requirement");
    Directory.CreateDirectory(Path.Combine(missingInspection.TargetPath, "Assemblies"));
    File.WriteAllText(
        Path.Combine(missingInspection.TargetPath, "Assemblies", "RimLink.dll"), "test");
    var updateInspection = InstallationInspector.Inspect(
        productionManifest, inspectionGame, "0.0.9");
    Assert(updateInspection.Condition == InstallationCondition.UpdateAvailable,
        "installation inspector detects available update");
    var healthyInspection = InstallationInspector.Inspect(
        productionManifest, inspectionGame, productionManifest.ReleaseVersion);
    Assert(healthyInspection.Condition == InstallationCondition.Healthy,
        "installation inspector detects healthy current version");

    var repository = Path.Combine(root, "repository");
    var archive = Path.Combine(repository, "artifact.zip");
    var game = Path.Combine(root, "install-game");
    var target = Path.Combine(game, "Mods", "RimLink");
    Directory.CreateDirectory(repository);
    Directory.CreateDirectory(target);
    File.WriteAllText(Path.Combine(target, "old-version.txt"), "old");
    using (var zip = ZipFile.Open(archive, ZipArchiveMode.Create))
    {
        var assembly = zip.CreateEntry("RimLink/Assemblies/RimLink.dll");
        using var writer = new StreamWriter(assembly.Open());
        writer.Write("new-version");
    }
    var size = new FileInfo(archive).Length;
    var hash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(archive)))
        .ToLowerInvariant();
    var manifestPath = Path.Combine(repository, "manifest.json");
    File.WriteAllText(manifestPath, $$$"""
    {
      "schema_version": 1,
      "integration_id": "rimworld",
      "release_version": "test-1",
      "artifacts": [{
        "id": "rimlink_mod",
        "source": {"kind": "repository", "path": "artifact.zip"},
        "size_bytes": {{{size}}},
        "sha256": "{{{hash}}}",
        "format": "zip",
        "archive_root": "RimLink"
      }],
      "installation": {"target": {"base": "game_root", "relative_path": "Mods/RimLink"}},
      "configuration": {
        "store": {"kind": "xml", "base": "windows_local_low", "relative_path": "RimLink/settings.xml"},
        "managed_fields": [
          {"name": "server_url", "selector": "/SettingsBlock/ModSettings/serverUrl", "value_source": "backend_url", "secret": false},
          {"name": "module_token", "selector": "/SettingsBlock/ModSettings/moduleToken", "value_source": "channel_module_token", "secret": true}
        ]
      },
      "health": [{"id": "assembly_present", "kind": "path_exists", "path": "Assemblies/RimLink.dll", "required": true}],
      "security": {"publisher": "shedoy23", "signature_status": "unsigned"}
    }
    """);

    var installer = new PackageInstaller();
    var installed = installer.InstallRepositoryArtifact(manifestPath, repository, game);
    Assert(File.Exists(Path.Combine(installed.TargetPath, "Assemblies", "RimLink.dll")),
        "verified package installed");
    Assert(!File.Exists(Path.Combine(target, "old-version.txt")),
        "old package atomically replaced");

    Directory.Delete(target, recursive: true);
    Directory.CreateDirectory(target);
    File.WriteAllText(Path.Combine(target, "rollback-marker.txt"), "keep");
    try
    {
        installer.InstallRepositoryArtifact(
            manifestPath,
            repository,
            game,
            phase =>
            {
                if (phase == "installed")
                {
                    throw new IOException("simulated interruption");
                }
            });
        throw new InvalidOperationException("FAILED: interrupted install rolled back");
    }
    catch (IOException exception) when (exception.Message == "simulated interruption")
    {
        Assert(File.Exists(Path.Combine(target, "rollback-marker.txt")),
            "interrupted install rolled back");
    }

    var backup = Path.Combine(game, "Mods", ".RimLink.shedlink-backup");
    var journal = Path.Combine(game, "Mods", ".RimLink.shedlink-transaction.json");
    Directory.Move(target, backup);
    Directory.CreateDirectory(target);
    File.WriteAllText(Path.Combine(target, "partial.txt"), "partial");
    File.WriteAllText(journal, "{\"phase\":\"installed\"}");
    Assert(AtomicDirectoryTransaction.Recover(target, game), "crash journal detected");
    Assert(File.Exists(Path.Combine(target, "rollback-marker.txt")),
        "crash recovery restored previous version");

    var badArchive = Path.Combine(repository, "traversal.zip");
    using (var zip = ZipFile.Open(badArchive, ZipArchiveMode.Create))
    {
        using var writer = new StreamWriter(zip.CreateEntry("../escape.txt").Open());
        writer.Write("escape");
    }
    try
    {
        SafeZipExtractor.Extract(badArchive, Path.Combine(root, "bad-extract"));
        throw new InvalidOperationException("FAILED: ZIP traversal rejected");
    }
    catch (InvalidDataException)
    {
        Console.WriteLine("  OK  ZIP traversal rejected");
    }

    var config = Path.Combine(root, "config", "rimlink.xml");
    Directory.CreateDirectory(Path.GetDirectoryName(config)!);
    File.WriteAllText(config,
        "<SettingsBlock><ModSettings><customValue>keep-me</customValue>" +
        "<moduleToken>old</moduleToken></ModSettings></SettingsBlock>");
    ManagedXmlConfiguration.Write(config, new Dictionary<string, string>
    {
        ["/SettingsBlock/ModSettings/serverUrl"] = "https://shedoy23.ru",
        ["/SettingsBlock/ModSettings/moduleToken"] = "slmod_v1.test.secret",
    });
    var configured = File.ReadAllText(config);
    Assert(configured.Contains("keep-me", StringComparison.Ordinal),
        "unmanaged XML field preserved");
    Assert(configured.Contains("slmod_v1.test.secret", StringComparison.Ordinal),
        "managed module credential written");
    Assert(!File.Exists(config + ".shedlink-write.tmp") &&
        !File.Exists(config + ".shedlink-backup") &&
        !File.Exists(config + ".shedlink-transaction.json"),
        "config transaction artifacts cleaned");
    var access = new FileInfo(config).GetAccessControl();
    var currentUser = WindowsIdentity.GetCurrent().User!;
    var rules = access.GetAccessRules(
        includeExplicit: true,
        includeInherited: true,
        typeof(SecurityIdentifier)).Cast<FileSystemAccessRule>().ToArray();
    Assert(access.AreAccessRulesProtected && rules.Length > 0 &&
        rules.All(rule => currentUser.Equals(rule.IdentityReference)),
        "secret config ACL limited to current user");

    File.WriteAllText(Path.Combine(target, "transaction-marker.txt"), "stable");
    using (var prepared = installer.PrepareRepositoryArtifact(
        manifestPath, repository, game))
    {
        Assert(!File.Exists(Path.Combine(target, "transaction-marker.txt")),
            "prepared package visible before final commit");
    }
    Assert(File.Exists(Path.Combine(target, "transaction-marker.txt")),
        "uncommitted package preparation rolled back");

    var beforeConfig = File.ReadAllText(config);
    using (ManagedXmlConfiguration.PrepareWrite(config, new Dictionary<string, string>
    {
        ["/SettingsBlock/ModSettings/serverUrl"] = "https://rollback.test",
        ["/SettingsBlock/ModSettings/moduleToken"] = "slmod_v1.rollback.secret",
    }))
    {
        Assert(File.ReadAllText(config).Contains("slmod_v1.rollback.secret", StringComparison.Ordinal),
            "prepared config visible before final commit");
    }
    Assert(File.ReadAllText(config) == beforeConfig,
        "uncommitted config preparation rolled back");

    var operationRoot = Path.Combine(root, "operation");
    var operationGame = Path.Combine(operationRoot, "game");
    var operationConfigRoot = Path.Combine(operationRoot, "local-low");
    var operationStatePath = Path.Combine(operationRoot, "manager", "state.json");
    Directory.CreateDirectory(Path.Combine(operationGame, "Mods", "RimLink"));
    var operationStore = new ManagerStateStore(operationStatePath);
    var operationState = operationStore.LoadOrCreate() with
    {
        ModuleId = "rimworld",
        BackendUrl = new Uri("https://manager.test"),
    };
    operationStore.Save(operationState);
    var operationVault = new MemoryVault();
    operationVault.Write(
        CredentialKeys.ModuleToken(operationState.InstallationId, "rimworld"),
        "slmod_v1.operation.secret");
    var operationHandler = new FakeManagerHandler();
    var operationApi = new ManagerApiClient(new HttpClient(operationHandler)
    {
        BaseAddress = operationState.BackendUrl,
    });
    var operationService = new IntegrationInstallationService(
        operationApi, operationVault, operationStore);
    var operationResult = await operationService.InstallRepositoryAsync(
        manifestPath, repository, operationGame, operationConfigRoot);
    var operationConfig = ConfigurationPathResolver.Resolve(
        InstallationManifestLoader.Load(manifestPath).Configuration.Store,
        operationConfigRoot);
    Assert(File.Exists(Path.Combine(operationResult.TargetPath, "Assemblies", "RimLink.dll")) &&
        File.ReadAllText(operationConfig).Contains("slmod_v1.operation.secret", StringComparison.Ordinal),
        "package and config committed after authenticated verify");

    var installedFiles = SnapshotDirectory(operationResult.TargetPath);
    var installedConfig = File.ReadAllText(operationConfig);
    var repeatedResult = await operationService.InstallRepositoryAsync(
        manifestPath, repository, operationGame, operationConfigRoot);
    Assert(repeatedResult.TargetPath == operationResult.TargetPath &&
        repeatedResult.ReleaseVersion == operationResult.ReleaseVersion &&
        SnapshotDirectory(repeatedResult.TargetPath) == installedFiles &&
        File.ReadAllText(operationConfig) == installedConfig,
        "repeated install leaves identical files and config");

    var operationMods = Path.Combine(operationGame, "Mods");
    Assert(!Directory.Exists(Path.Combine(operationMods, ".RimLink.shedlink-stage")) &&
        !Directory.Exists(Path.Combine(operationMods, ".RimLink.shedlink-backup")) &&
        !File.Exists(Path.Combine(operationMods, ".RimLink.shedlink-transaction.json")),
        "repeated install leaves no transaction artifacts");

    File.Delete(Path.Combine(operationResult.TargetPath, "Assemblies", "RimLink.dll"));
    File.WriteAllText(Path.Combine(operationResult.TargetPath, "damaged-leftover.txt"), "junk");
    var repairResult = await operationService.InstallRepositoryAsync(
        manifestPath, repository, operationGame, operationConfigRoot);
    Assert(SnapshotDirectory(repairResult.TargetPath) == installedFiles &&
        File.ReadAllText(operationConfig) == installedConfig,
        "repair after damage restores the same installation");

    File.WriteAllText(Path.Combine(operationResult.TargetPath, "stable-marker.txt"), "keep");
    var stableConfig = File.ReadAllText(operationConfig);
    operationHandler.RejectAuthCheck = true;
    try
    {
        await operationService.InstallRepositoryAsync(
            manifestPath, repository, operationGame, operationConfigRoot);
        throw new InvalidOperationException("FAILED: auth-check failure rolls back operation");
    }
    catch (ManagerApiException)
    {
        Assert(File.Exists(Path.Combine(operationResult.TargetPath, "stable-marker.txt")) &&
            File.ReadAllText(operationConfig) == stableConfig,
            "auth-check failure rolls back package and config");
    }

    operationHandler.RejectAuthCheck = false;
    try
    {
        await operationService.InstallRepositoryAsync(
            manifestPath,
            repository,
            operationGame,
            operationConfigRoot,
            phase =>
            {
                if (phase == "verified")
                {
                    throw new IOException("simulated verified crash");
                }
            });
        throw new InvalidOperationException("FAILED: verified crash journal retained");
    }
    catch (IOException exception) when (exception.Message == "simulated verified crash")
    {
        var restartedOperation = new IntegrationInstallationService(
            operationApi, operationVault, operationStore);
        Assert(restartedOperation.RecoverPending() &&
            !File.Exists(Path.Combine(operationResult.TargetPath, "stable-marker.txt")) &&
            File.ReadAllText(operationConfig).Contains(
                "slmod_v1.operation.secret", StringComparison.Ordinal),
            "verified crash completed on restart");
    }

    File.WriteAllText(Path.Combine(operationResult.TargetPath, "uninstall-marker.txt"), "keep");
    try
    {
        AtomicDirectoryTransaction.PrepareRemoval(
            operationResult.TargetPath,
            operationGame,
            phase =>
            {
                if (phase == "removed")
                {
                    throw new IOException("simulated removal failure");
                }
            });
        throw new InvalidOperationException("FAILED: interrupted removal rolled back");
    }
    catch (IOException exception) when (exception.Message == "simulated removal failure")
    {
        Assert(File.Exists(Path.Combine(operationResult.TargetPath, "uninstall-marker.txt")),
            "interrupted removal rolled back");
    }

    var preservedConfig = File.ReadAllText(operationConfig);
    try
    {
        operationService.Uninstall(
            manifestPath,
            operationGame,
            operationConfigRoot,
            phase =>
            {
                if (phase == "verified")
                {
                    throw new IOException("simulated uninstall crash");
                }
            });
        throw new InvalidOperationException("FAILED: uninstall crash journal retained");
    }
    catch (IOException exception) when (exception.Message == "simulated uninstall crash")
    {
        var restartedUninstall = new IntegrationInstallationService(
            operationApi, operationVault, operationStore);
        Assert(restartedUninstall.RecoverPending() &&
            !Directory.Exists(operationResult.TargetPath) &&
            File.ReadAllText(operationConfig) == preservedConfig,
            "verified uninstall completed and config preserved after restart");
        Assert(!restartedUninstall.Uninstall(
            manifestPath, operationGame, operationConfigRoot),
            "repeated uninstall is idempotent");
    }
}

static async Task TestHttpsDistributionAsync(string root)
{
    var repository = Path.Combine(root, "repository");
    var archivePath = Path.Combine(repository, "artifact.zip");
    var repositoryManifest = File.ReadAllText(Path.Combine(repository, "manifest.json"));
    var remoteText = repositoryManifest
        .Replace(
            "\"source\": {\"kind\": \"repository\", \"path\": \"artifact.zip\"}",
            "\"source\": {\"kind\": \"https\", \"url\": \"https://downloads.test/rimlink.zip\"}",
            StringComparison.Ordinal)
        .Replace(
            "\"archive_root\": \"RimLink\"",
            "\"archive_root\": \"RimLink\", \"signature\": {\"algorithm\": \"rsa-pss-sha256\", \"key_id\": \"test_release_key\", \"value\": \"AA==\"}",
            StringComparison.Ordinal)
        .Replace(
            "\"signature_status\": \"unsigned\"",
            "\"signature_status\": \"signed\"",
            StringComparison.Ordinal);
    var remoteManifestPath = Path.Combine(repository, "remote-manifest.json");
    File.WriteAllText(remoteManifestPath, remoteText);
    var unsignedManifest = InstallationManifestLoader.Load(remoteManifestPath);
    using var signingKey = RSA.Create(2048);
    var signature = signingKey.SignData(
        ArtifactSignatureVerifier.SigningPayload(
            unsignedManifest, unsignedManifest.Artifacts[0]),
        HashAlgorithmName.SHA256,
        RSASignaturePadding.Pss);
    remoteText = remoteText.Replace(
        "\"value\": \"AA==\"",
        "\"value\": \"" + Convert.ToBase64String(signature) + "\"",
        StringComparison.Ordinal);
    File.WriteAllText(remoteManifestPath, remoteText);
    var signedManifest = InstallationManifestLoader.Load(remoteManifestPath);
    var verifier = new ArtifactSignatureVerifier(new Dictionary<string, string>
    {
        ["test_release_key"] = signingKey.ExportSubjectPublicKeyInfoPem(),
    });
    verifier.Verify(signedManifest, signedManifest.Artifacts[0]);
    Console.WriteLine("  OK  publisher RSA-PSS signature verified");

    var archiveBytes = File.ReadAllBytes(archivePath);
    var remoteGame = Path.Combine(root, "remote-game");
    Directory.CreateDirectory(Path.Combine(remoteGame, "Mods"));
    using (var downloader = new SecureArtifactDownloader(
        new ArtifactDownloadHandler(archiveBytes, HttpStatusCode.OK)))
    {
        var installed = await new PackageInstaller().InstallHttpsArtifactAsync(
            remoteManifestPath, remoteGame, downloader, verifier);
        Assert(File.Exists(Path.Combine(installed.TargetPath, "Assemblies", "RimLink.dll")),
            "signed HTTPS artifact installed");
    }

    var httpsOperationRoot = Path.Combine(root, "https-operation");
    var httpsOperationGame = Path.Combine(httpsOperationRoot, "game");
    var httpsOperationState = new ManagerStateStore(
        Path.Combine(httpsOperationRoot, "manager", "state.json"));
    var httpsState = httpsOperationState.LoadOrCreate() with
    {
        ModuleId = "rimworld",
        BackendUrl = new Uri("https://manager.test"),
    };
    httpsOperationState.Save(httpsState);
    var httpsVault = new MemoryVault();
    httpsVault.Write(
        CredentialKeys.ModuleToken(httpsState.InstallationId, "rimworld"),
        "slmod_v1.https.secret");
    var httpsApi = new ManagerApiClient(new HttpClient(new FakeManagerHandler())
    {
        BaseAddress = httpsState.BackendUrl,
    });
    using (var downloader = new SecureArtifactDownloader(
        new ArtifactDownloadHandler(archiveBytes, HttpStatusCode.OK)))
    {
        var installed = await new IntegrationInstallationService(
            httpsApi, httpsVault, httpsOperationState).InstallHttpsAsync(
                remoteManifestPath,
                httpsOperationGame,
                downloader,
                verifier,
                Path.Combine(httpsOperationRoot, "local-low"));
        Assert(File.Exists(Path.Combine(installed.TargetPath, "Assemblies", "RimLink.dll")),
            "signed HTTPS package, config and auth-check committed together");
    }

    var redirectTarget = Path.Combine(root, "redirect-download.zip");
    using (var downloader = new SecureArtifactDownloader(
        new ArtifactDownloadHandler(Array.Empty<byte>(), HttpStatusCode.Redirect)))
    {
        try
        {
            await downloader.DownloadAsync(
                signedManifest.Artifacts[0].Source.Url!,
                signedManifest,
                signedManifest.Artifacts[0],
                verifier,
                redirectTarget);
            throw new InvalidOperationException("FAILED: HTTPS redirect rejected");
        }
        catch (InvalidDataException)
        {
            Assert(!File.Exists(redirectTarget), "HTTPS redirect rejected and temp removed");
        }
    }

    var tampered = archiveBytes.ToArray();
    tampered[0] ^= 0x01;
    var tamperedTarget = Path.Combine(root, "tampered-download.zip");
    using (var downloader = new SecureArtifactDownloader(
        new ArtifactDownloadHandler(tampered, HttpStatusCode.OK)))
    {
        try
        {
            await downloader.DownloadAsync(
                signedManifest.Artifacts[0].Source.Url!,
                signedManifest,
                signedManifest.Artifacts[0],
                verifier,
                tamperedTarget);
            throw new InvalidOperationException("FAILED: tampered download rejected");
        }
        catch (InvalidDataException)
        {
            Assert(!File.Exists(tamperedTarget), "tampered download rejected and temp removed");
        }
    }

    var existingTarget = Path.Combine(root, "existing-download.zip");
    File.WriteAllText(existingTarget, "owner-data");
    using (var downloader = new SecureArtifactDownloader(
        new ArtifactDownloadHandler(archiveBytes, HttpStatusCode.OK)))
    {
        try
        {
            await downloader.DownloadAsync(
                signedManifest.Artifacts[0].Source.Url!,
                signedManifest,
                signedManifest.Artifacts[0],
                verifier,
                existingTarget);
            throw new InvalidOperationException("FAILED: existing download target preserved");
        }
        catch (IOException)
        {
            Assert(File.ReadAllText(existingTarget) == "owner-data",
                "existing download target preserved");
        }
    }

    File.WriteAllText(
        remoteManifestPath,
        remoteText.Replace(
            "\"signature_status\": \"signed\"",
            "\"signature_status\": \"unsigned\"",
            StringComparison.Ordinal));
    try
    {
        InstallationManifestLoader.Load(remoteManifestPath);
        throw new InvalidOperationException("FAILED: unsigned HTTPS manifest rejected");
    }
    catch (InvalidDataException)
    {
        Console.WriteLine("  OK  unsigned HTTPS manifest rejected");
    }
}

static void TestJsonConfigurationStore(string root)
{
    // Bannerlord-shaped: flat config.json inside the mod folder in the game.
    var gameRoot = Path.Combine(root, "json-config-game");
    var store = new ConfigurationStore
    {
        Kind = "json",
        Base = "game_root",
        RelativePath = "Modules/Shedoy23.BannerlordLink/config.json",
    };
    var configPath = ConfigurationPathResolver.Resolve(store, null, gameRoot);
    Assert(configPath == Path.GetFullPath(Path.Combine(gameRoot, store.RelativePath)),
        "configuration can live inside the game folder");
    try
    {
        ConfigurationPathResolver.Resolve(store);
        throw new InvalidOperationException("FAILED: game-root config needs a game folder");
    }
    catch (InvalidDataException)
    {
        Assert(true, "game-root configuration without a known game folder fails safely");
    }

    Directory.CreateDirectory(Path.GetDirectoryName(configPath)!);
    File.WriteAllText(configPath,
        "{\n  \"backend_url\": \"https://old.test\",\n  \"poll_interval_ms\": 3000\n}\n");
    ManagedConfigurationWriter.PrepareWrite(store.Kind, configPath,
        new Dictionary<string, string>
        {
            ["/backend_url"] = "https://manager.test",
            ["/module_token"] = "slmod_v1.bannerlord.secret",
            ["/channel_id"] = "123456",
        }).Commit();

    var written = File.ReadAllText(configPath);
    using var document = JsonDocument.Parse(written);
    var rootElement = document.RootElement;
    string? Text(string key) => rootElement.TryGetProperty(key, out var value) &&
        value.ValueKind == JsonValueKind.String ? value.GetString() : null;
    long? Number(string key) => rootElement.TryGetProperty(key, out var value) &&
        value.ValueKind == JsonValueKind.Number ? value.GetInt64() : null;
    Assert(Text("backend_url") == "https://manager.test" &&
        Text("module_token") == "slmod_v1.bannerlord.secret" &&
        Number("channel_id") == 123456,
        "json configuration writes the managed fields");
    Assert(Number("poll_interval_ms") == 3000,
        "json configuration keeps settings it does not manage");
    Assert(!File.Exists(configPath + ".shedlink-write.tmp") &&
        !File.Exists(configPath + ".shedlink-backup") &&
        !File.Exists(configPath + ".shedlink-transaction.json"),
        "json configuration transaction artifacts cleaned");

    var before = File.ReadAllText(configPath);
    using (ManagedConfigurationWriter.PrepareWrite(store.Kind, configPath,
        new Dictionary<string, string> { ["/module_token"] = "slmod_v1.rollback" }))
    {
        Assert(File.ReadAllText(configPath).Contains("slmod_v1.rollback", StringComparison.Ordinal),
            "prepared json configuration visible before commit");
    }
    Assert(File.ReadAllText(configPath) == before,
        "uncommitted json configuration rolled back");

    var manifestForValues = InstallationManifestLoader.Load(Path.Combine(
        Environment.CurrentDirectory, "manifests", "installation", "rimworld-0.1.1.json"));
    var channelManifest = manifestForValues with
    {
        Configuration = manifestForValues.Configuration with
        {
            ManagedFields = new[]
            {
                new ManagedField
                {
                    Name = "channel_id",
                    Selector = "/channel_id",
                    ValueSource = "channel_id",
                    Secret = false,
                },
            },
        },
    };
    Assert(ConfigurationValueResolver.Resolve(
            channelManifest, new Uri("https://manager.test"), "token", 4242)["/channel_id"] == "4242",
        "channel id is available to integrations that need it");
    try
    {
        ConfigurationValueResolver.Resolve(
            channelManifest, new Uri("https://manager.test"), "token");
        throw new InvalidOperationException("FAILED: missing channel id fails safely");
    }
    catch (InvalidDataException)
    {
        Assert(true, "integration needing a channel id refuses a session without one");
    }
}

static void TestDeniedWriteScenario(string root)
{
    // Матрица R3, строка «недостаточно прав на запись». Проверка текста живёт
    // в TestFailureMessages; здесь проверяется другое — что установка в папку
    // без прав ДОХОДИТ до этого текста, а не до чего-то третьего. Именно этот
    // разрыв прятал дефект: тип исключения не совпадал ни с одним фильтром
    // обработчиков, и вместо сообщения приложение закрывалось.
    var repository = Path.Combine(root, "denied-repository");
    var game = Path.Combine(root, "denied-game");
    Directory.CreateDirectory(repository);
    Directory.CreateDirectory(game);
    var archive = Path.Combine(repository, "artifact.zip");
    using (var zip = ZipFile.Open(archive, ZipArchiveMode.Create))
    {
        using var writer = new StreamWriter(
            zip.CreateEntry("RimLink/Assemblies/RimLink.dll").Open());
        writer.Write("payload");
    }
    var size = new FileInfo(archive).Length;
    var hash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(archive)))
        .ToLowerInvariant();
    var manifestPath = Path.Combine(repository, "manifest.json");
    File.WriteAllText(manifestPath, $$$"""
    {
      "schema_version": 1,
      "integration_id": "rimworld",
      "release_version": "denied-1",
      "artifacts": [{
        "id": "rimlink_mod",
        "source": {"kind": "repository", "path": "artifact.zip"},
        "size_bytes": {{{size}}},
        "sha256": "{{{hash}}}",
        "format": "zip",
        "archive_root": "RimLink"
      }],
      "installation": {"target": {"base": "game_root", "relative_path": "Mods/RimLink"}},
      "configuration": {
        "store": {"kind": "xml", "base": "windows_local_low", "relative_path": "RimLink/settings.xml"},
        "managed_fields": [
          {"name": "server_url", "selector": "/SettingsBlock/ModSettings/serverUrl", "value_source": "backend_url", "secret": false}
        ]
      },
      "health": [{"id": "assembly_present", "kind": "path_exists", "path": "Assemblies/RimLink.dll", "required": true}],
      "security": {"publisher": "shedoy23", "signature_status": "unsigned"}
    }
    """);

    using var identity = WindowsIdentity.GetCurrent();
    var user = identity.User!;
    var directory = new DirectoryInfo(game);
    var security = directory.GetAccessControl();
    var deny = new FileSystemAccessRule(
        user,
        FileSystemRights.CreateDirectories | FileSystemRights.CreateFiles |
            FileSystemRights.Write,
        InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit,
        PropagationFlags.None,
        AccessControlType.Deny);
    security.AddAccessRule(deny);
    directory.SetAccessControl(security);
    try
    {
        // Запрет мог не примениться (процесс под особым токеном) — тогда
        // сценарий не воспроизведён, и молчать об этом нельзя.
        var blocked = false;
        try
        {
            Directory.CreateDirectory(Path.Combine(game, "probe"));
        }
        catch (UnauthorizedAccessException)
        {
            blocked = true;
        }
        if (!blocked)
        {
            Console.WriteLine("  SKIP  denied-write scenario: ACL not enforced for this token");
            return;
        }

        Exception? caught = null;
        try
        {
            new PackageInstaller().InstallRepositoryArtifact(manifestPath, repository, game);
        }
        catch (Exception exception)
        {
            caught = exception;
        }
        Assert(caught is not null,
            "установка в папку без прав не выдаёт себя за успешную");
        Assert(ManagerFailureMessage.IsExpected(caught!),
            "сбой прав доходит до обработчика, а не роняет Manager");
        Assert(ManagerFailureMessage.For(caught!).Contains(
                "Windows не дал записать", StringComparison.Ordinal),
            "сбой прав объясняется человеку именно как отказ Windows");
    }
    finally
    {
        security = directory.GetAccessControl();
        security.RemoveAccessRule(deny);
        directory.SetAccessControl(security);
    }
}

static void TestFailureMessages()
{
    // Матрица R3 (ROADMAP): каждая ошибка обязана объясниться человеку и
    // назвать следующее действие. Сбои приходят этими типами.
    var matrix = new (string Case, Exception Error)[]
    {
        ("недостаточно прав на запись", new UnauthorizedAccessException("denied")),
        ("диск/файл занят",             new IOException("locked")),
        ("повреждённая установка",      new InvalidDataException("hash mismatch")),
        ("backend недоступен",          new HttpRequestException("no route")),
        ("сервер молчит",               new TaskCanceledException("timeout")),
        ("отозванная credential",       new ManagerApiException(
                                            System.Net.HttpStatusCode.Unauthorized,
                                            "invalid_module_credential")),
        ("сервер отклонил запрос",      new ManagerApiException(
                                            System.Net.HttpStatusCode.BadRequest,
                                            "module_scope_not_approved")),
    };

    // «Следующее действие» проверяем по глаголу в повелительном наклонении.
    // Признак грубый и намеренно такой: он ловит ровно тот случай, ради
    // которого критерий и написан, — сообщение, которое называет проблему и
    // молчит о том, что теперь делать.
    var imperatives = new[]
    {
        "повтори", "проверь", "закрой", "войди", "смени", "напиши",
        "собери", "попробуй", "перенеси", "освободи",
    };
    var fallback = ManagerFailureMessage.For(new NotSupportedException("unknown"));

    foreach (var (name, error) in matrix)
    {
        var message = ManagerFailureMessage.For(error);
        Assert(ManagerFailureMessage.IsExpected(error),
            $"обработчик ловит сбой «{name}», а не роняет Manager");
        Assert(message != fallback,
            $"у сбоя «{name}» есть свой текст, а не общая отговорка");
        Assert(imperatives.Any(verb =>
                message.Contains(verb, StringComparison.OrdinalIgnoreCase)),
            $"текст сбоя «{name}» называет следующее действие");
    }

    Assert(fallback.Contains("диагностическ", StringComparison.OrdinalIgnoreCase),
        "даже неизвестный сбой отправляет за диагностикой, а не в тупик");
}

static void TestManifestDrivenDetection(string root)
{
    // A second game the code has never heard of, described only by a manifest.
    var bannerlordLike = new ManifestGame
    {
        Id = "testgame",
        DisplayName = "Test Game",
        SupportedVersions = new[] { "1.2" },
        ProcessNames = new[] { "TestGameNeverRunning" },
        Version = new GameVersionSource
        {
            Kind = "text_file",
            Path = "bin/version.dat",
            CompatibilityPattern = @"^\d+\.\d+",
        },
        Detection = new GameDetectionRule[]
        {
            new() { Kind = "steam", AppId = 777777, InstallDir = "TestGame" },
            new()
            {
                Kind = "manual",
                RequiredPaths = new[] { "TestGame.exe", "Modules" },
            },
        },
    };
    var service = new GameDetectionService(bannerlordLike);

    var library = Path.Combine(root, "second-game-library");
    var installed = Path.Combine(library, "steamapps", "common", "TestGame");
    Directory.CreateDirectory(Path.Combine(installed, "Modules"));
    Directory.CreateDirectory(Path.Combine(installed, "bin"));
    File.WriteAllText(Path.Combine(installed, "TestGame.exe"), "game");
    File.WriteAllText(Path.Combine(library, "steamapps", "appmanifest_777777.acf"), "steam");
    File.WriteAllText(Path.Combine(installed, "bin", "version.dat"), "\n1.2.3 rev42\n");

    var detected = service.Detect(new[] { library });
    Assert(detected is { GameId: "testgame", Source: DetectionSource.Steam } &&
        Path.GetFullPath(detected.RootPath) == Path.GetFullPath(installed),
        "manifest describes a game the code does not know");

    var version = service.DetectVersion(installed);
    Assert(version is { FullVersion: "1.2.3 rev42", CompatibilityVersion: "1.2" } &&
        GameVersionDetector.Compatibility(version, bannerlordLike.SupportedVersions) == "supported",
        "manifest describes where the game version is written");

    var xmlVersionGame = bannerlordLike with
    {
        Version = new GameVersionSource
        {
            Kind = "text_file",
            Path = "bin/version.xml",
            CompatibilityPattern = "Value=\"v(\\d+\\.\\d+)\\.\\d+\"",
        },
    };
    File.WriteAllText(
        Path.Combine(installed, "bin", "version.xml"),
        "<?xml version='1.0' encoding='utf-8'?>\n<Version Value=\"v1.3.15\" />\n");
    var xmlVersion = new GameDetectionService(xmlVersionGame).DetectVersion(installed);
    Assert(xmlVersion is
        { FullVersion: "<Version Value=\"v1.3.15\" />", CompatibilityVersion: "1.3" },
        "version detection searches the whole file and uses the first capture group");

    File.Delete(Path.Combine(installed, "TestGame.exe"));
    Assert(!service.IsValidGameRoot(installed) && service.Detect(new[] { library }) is null,
        "missing required file rejects the folder for that game");

    var blind = new GameDetectionService(bannerlordLike with { Detection = null });
    Assert(!blind.IsValidGameRoot(root),
        "game without declared evidence accepts no folder at all");

    // The shipped RimWorld manifest must carry the same facts the code used to hold.
    var shipped = InstallationManifestLoader.Load(Path.Combine(
        Environment.CurrentDirectory, "manifests", "installation", "rimworld-0.1.1.json"));
    var rimworld = new GameDetectionService(shipped.Game!);
    var rimworldRoot = Path.Combine(root, "manifest-rimworld");
    Directory.CreateDirectory(Path.Combine(rimworldRoot, "Mods"));
    File.WriteAllText(Path.Combine(rimworldRoot, "RimWorldWin64.exe"), "game");
    File.WriteAllText(Path.Combine(rimworldRoot, "Version.txt"), "1.6.4871 rev590\n");
    var rimworldVersion = rimworld.DetectVersion(rimworldRoot);
    Assert(rimworld.IsValidGameRoot(rimworldRoot) &&
        rimworldVersion?.CompatibilityVersion == "1.6" &&
        rimworldVersion.FullVersion == "1.6.4871 rev590",
        "shipped RimWorld manifest detects the game without hardcoded knowledge");

    var bannerlordManifest = InstallationManifestLoader.Load(Path.Combine(
        Environment.CurrentDirectory, "manifests", "installation", "bannerlord-0.1.0.json"));
    var bannerlord = new GameDetectionService(bannerlordManifest.Game!);
    var bannerlordRoot = Path.Combine(root, "manifest-bannerlord");
    Directory.CreateDirectory(Path.Combine(
        bannerlordRoot, "bin", "Win64_Shipping_Client"));
    Directory.CreateDirectory(Path.Combine(bannerlordRoot, "Modules", "Native"));
    File.WriteAllText(
        Path.Combine(bannerlordRoot, "bin", "Win64_Shipping_Client", "Version.xml"),
        "<Version>\n  <Singleplayer Value=\"v1.3.15\" />\n</Version>\n");
    File.WriteAllText(
        Path.Combine(bannerlordRoot, "Modules", "Native", "SubModule.xml"), "game");
    var bannerlordVersion = bannerlord.DetectVersion(bannerlordRoot);
    Assert(bannerlord.IsValidGameRoot(bannerlordRoot) &&
        bannerlordVersion?.CompatibilityVersion == "1.3",
        "shipped Bannerlord manifest detects the game without hardcoded knowledge");

    var catalog = InstallationReleaseCatalog.LoadDirectory(Path.Combine(
        Environment.CurrentDirectory, "manifests", "installation"));
    var integrations = catalog.LatestIntegrations();
    Assert(integrations.Any(item => item.Manifest.IntegrationId == "rimworld") &&
        integrations.Any(item => item.Manifest.IntegrationId == "bannerlord"),
        "release catalog discovers integrations without a hardcoded game list");
}

static async Task TestManagerUpdateAsync(string root)
{
    Assert(ManagerVersion.Compare("0.2.0", "0.1.0") > 0 &&
        ManagerVersion.Compare("0.1.0", "0.1.0-alpha.1") > 0 &&
        ManagerVersion.Compare("0.1.0-alpha.10", "0.1.0-alpha.2") > 0 &&
        ManagerVersion.Compare("0.1.0-alpha.2", "0.1.0-alpha.2+build") == 0,
        "manager version ordering handles pre-release numbers");

    var updateRoot = Path.Combine(root, "manager-update");
    var packageDirectory = Path.Combine(updateRoot, "installed");
    var executableName = "ShedLink.Manager.App.exe";
    var executable = Path.Combine(packageDirectory, executableName);
    Directory.CreateDirectory(Path.Combine(packageDirectory, "Release"));
    File.WriteAllText(executable, "old-manager");
    File.WriteAllText(
        Path.Combine(packageDirectory, "Release", "rimworld-0.1.1.json"), "old-catalog");

    var archiveRoot = "ShedLink.Manager-0.2.0-win-x64";
    var archivePath = Path.Combine(updateRoot, "manager.zip");
    using (var zip = ZipFile.Open(archivePath, ZipArchiveMode.Create))
    {
        using (var writer = new StreamWriter(
            zip.CreateEntry($"{archiveRoot}/{executableName}").Open()))
        {
            writer.Write("new-manager");
        }
        using (var writer = new StreamWriter(
            zip.CreateEntry($"{archiveRoot}/Release/rimworld-0.1.1.json").Open()))
        {
            writer.Write("new-catalog");
        }
    }
    var archiveBytes = File.ReadAllBytes(archivePath);
    var sha = Convert.ToHexString(SHA256.HashData(archiveBytes)).ToLowerInvariant();
    using var signingKey = RSA.Create(2048);
    var signature = Convert.ToBase64String(signingKey.SignData(
        ArtifactSignatureVerifier.SigningPayload(
            "shedlink-manager", "0.2.0", "manager_package", archiveBytes.Length, sha),
        HashAlgorithmName.SHA256,
        RSASignaturePadding.Pss));
    var manifestJson = $$"""
    {
      "schema_version": 1,
      "product": "shedlink-manager",
      "version": "0.2.0",
      "artifact": {
        "id": "manager_package",
        "url": "https://downloads.test/manager.zip",
        "size_bytes": {{archiveBytes.Length}},
        "sha256": "{{sha}}",
        "format": "zip",
        "archive_root": "{{archiveRoot}}",
        "signature": {
          "algorithm": "rsa-pss-sha256",
          "key_id": "test_release_key",
          "value": "{{signature}}"
        }
      }
    }
    """;
    var trusted = new ArtifactSignatureVerifier(new Dictionary<string, string>
    {
        ["test_release_key"] = signingKey.ExportSubjectPublicKeyInfoPem(),
    });
    var manifestUrl = new Uri("https://downloads.test/manager-latest.json");

    using (var service = new ManagerUpdateService(
        trusted, packageDirectory, executableName,
        new ManagerUpdateHandler(manifestJson, archiveBytes)))
    {
        var current = await service.CheckAsync(manifestUrl, "0.2.0");
        Assert(!current.UpdateAvailable, "manager update check accepts the current version");
        var newer = await service.CheckAsync(manifestUrl, "0.1.0-alpha.2");
        Assert(newer.UpdateAvailable && newer.AvailableVersion == "0.2.0",
            "manager update check offers a newer version");
        try
        {
            await service.StageAsync(manifestUrl, "0.2.0");
            throw new InvalidOperationException("FAILED: manager update refuses a downgrade");
        }
        catch (InvalidDataException)
        {
            Assert(File.ReadAllText(executable) == "old-manager",
                "manager update refuses a replayed older manifest");
        }
    }

    var tampered = archiveBytes.ToArray();
    tampered[^1] ^= 0xFF;
    using (var service = new ManagerUpdateService(
        trusted, packageDirectory, executableName,
        new ManagerUpdateHandler(manifestJson, tampered)))
    {
        try
        {
            await service.StageAsync(manifestUrl, "0.1.0");
            throw new InvalidOperationException("FAILED: manager update rejects tampered bytes");
        }
        catch (InvalidDataException)
        {
            Assert(File.ReadAllText(executable) == "old-manager",
                "manager update rejects tampered download");
        }
    }

    using var otherKey = RSA.Create(2048);
    var untrusted = new ArtifactSignatureVerifier(new Dictionary<string, string>
    {
        ["test_release_key"] = otherKey.ExportSubjectPublicKeyInfoPem(),
    });
    using (var service = new ManagerUpdateService(
        untrusted, packageDirectory, executableName,
        new ManagerUpdateHandler(manifestJson, archiveBytes)))
    {
        try
        {
            await service.StageAsync(manifestUrl, "0.1.0");
            throw new InvalidOperationException("FAILED: manager update rejects a foreign key");
        }
        catch (InvalidDataException)
        {
            Assert(File.ReadAllText(executable) == "old-manager",
                "manager update rejects a package signed by another key");
        }
    }

    using (var service = new ManagerUpdateService(
        trusted, packageDirectory, executableName,
        new ManagerUpdateHandler(manifestJson, archiveBytes, redirectManifest: true)))
    {
        try
        {
            await service.CheckAsync(manifestUrl, "0.1.0");
            throw new InvalidOperationException("FAILED: manager update rejects redirects");
        }
        catch (InvalidDataException)
        {
            Assert(true, "manager update rejects a redirected manifest");
        }
    }

    using (var service = new ManagerUpdateService(
        trusted, packageDirectory, executableName,
        new ManagerUpdateHandler(manifestJson, archiveBytes)))
    {
        var staged = await service.StageAsync(manifestUrl, "0.1.0-alpha.2");
        Assert(staged.Version == "0.2.0" && File.ReadAllText(executable) == "old-manager",
            "staged manager update does not touch the running package");
        var relaunch = service.Apply(staged);
        Assert(relaunch == executable &&
            File.ReadAllText(executable) == "new-manager" &&
            File.ReadAllText(Path.Combine(
                packageDirectory, "Release", "rimworld-0.1.1.json")) == "new-catalog",
            "applied manager update replaced executable and catalog");
        var displaced = executable + ".shedlink-previous";
        Assert(File.Exists(displaced) && File.ReadAllText(displaced) == "old-manager",
            "previous manager executable kept aside for the running process");
        Assert(service.CleanupPrevious() && !File.Exists(displaced) &&
            !service.CleanupPrevious(),
            "previous manager executable removed on the next start");
    }
}

static string SnapshotDirectory(string root)
{
    var entries = Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories)
        .Select(path => Path.GetRelativePath(root, path) + "=" +
            Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))))
        .OrderBy(entry => entry, StringComparer.Ordinal);
    return string.Join("\n", entries);
}

static void Assert(bool condition, string label)
{
    if (!condition)
    {
        throw new InvalidOperationException("FAILED: " + label);
    }
    Console.WriteLine("  OK  " + label);
}

sealed class ManagerUpdateHandler : HttpMessageHandler
{
    private readonly string _manifest;
    private readonly byte[] _package;
    private readonly bool _redirectManifest;

    public ManagerUpdateHandler(string manifest, byte[] package, bool redirectManifest = false)
    {
        _manifest = manifest;
        _package = package;
        _redirectManifest = redirectManifest;
    }

    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        var path = request.RequestUri!.AbsolutePath;
        if (path.EndsWith(".json", StringComparison.Ordinal))
        {
            if (_redirectManifest)
            {
                var moved = new HttpResponseMessage(HttpStatusCode.Found);
                moved.Headers.Location = new Uri("https://elsewhere.test/manager-latest.json");
                return Task.FromResult(moved);
            }
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(_manifest),
            });
        }
        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent(_package),
        });
    }
}

sealed class MemoryVault : ICredentialVault
{
    public Dictionary<string, string> Values { get; } = new();
    public void Write(string key, string secret) => Values[key] = secret;
    public string? Read(string key) => Values.GetValueOrDefault(key);
    public bool Delete(string key) => Values.Remove(key);
}

sealed class FakeManagerHandler : HttpMessageHandler
{
    private int _exchangeCount;
    public string LastCreateBody { get; private set; } = string.Empty;
    public bool SawCredentialRevoke { get; private set; }
    public bool SawLogout { get; private set; }
    public bool RejectAuthCheck { get; set; }

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        var path = request.RequestUri!.AbsolutePath;
        var body = request.Content is null
            ? string.Empty
            : await request.Content.ReadAsStringAsync(cancellationToken);
        if (path == "/v1/manager/pairings")
        {
            LastCreateBody = body;
            return Json(HttpStatusCode.OK,
                """{"status":"ok","pairing_id":"pairing-one","user_code":"ABCD-EFGH","verification_uri":"https://manager.test/manager/pair?code=ABCD-EFGH","expires_at":1000,"expires_in":600,"interval":1}""");
        }
        if (path.EndsWith("/exchange", StringComparison.Ordinal))
        {
            _exchangeCount++;
            return _exchangeCount == 1
                ? Json(HttpStatusCode.Accepted, """{"status":"authorization_pending"}""")
                : Json(HttpStatusCode.OK, Session("access-one", "refresh-one"));
        }
        if (path == "/v1/manager/session/refresh")
        {
            return Json(HttpStatusCode.OK, Session("access-two", "refresh-two"));
        }
        if (path == "/v1/manager/module-credentials")
        {
            var access = request.Headers.Authorization?.Parameter;
            if (access != "access-one" && access != "access-two")
            {
                throw new InvalidOperationException(
                    "FAILED: credential request is authenticated (got " +
                    (access ?? "<null>") + ")");
            }
            return Json(HttpStatusCode.Created,
                """{"status":"ok","credential_id":"credential-one","module_token":"slmod_v1.credential-one.secret","module_id":"rimworld","channel_id":98319857,"label":"test","expires_at":999999}""");
        }
        if (path == "/v1/manager/module-credentials/credential-one/rotate")
        {
            return Json(HttpStatusCode.Created,
                """{"status":"ok","credential_id":"credential-two","module_token":"slmod_v1.credential-two.secret","module_id":"rimworld","channel_id":98319857,"label":"test","expires_at":999999,"overlap_until":999}""");
        }
        if (path == "/v1/module/rimworld/auth-check")
        {
            if (RejectAuthCheck)
            {
                return Json(HttpStatusCode.Unauthorized,
                    """{"detail":{"status":"auth_failed"}}""");
            }
            return Json(HttpStatusCode.OK, """{"status":"ok","module_id":"rimworld"}""");
        }
        if (path == "/v1/module/rimworld/status")
        {
            return Json(HttpStatusCode.OK,
                """{"status":"ok","module_id":"rimworld","online":false,"last_seen_at":null,"age_seconds":null,"online_window_seconds":60}""");
        }
        if (path == "/v1/manager/diagnostics/test-action")
        {
            if (body.Contains("lost_ack", StringComparison.Ordinal))
            {
                return Json(HttpStatusCode.Created,
                    """{"status":"queued","diagnostic_id":"diag-test-lost","expires_in":120,"mode":"lost_ack"}""");
            }
            if (body.Contains("refuse", StringComparison.Ordinal))
            {
                return Json(HttpStatusCode.Created,
                    """{"status":"queued","diagnostic_id":"diag-test-refuse","expires_in":120,"mode":"refuse"}""");
            }
            return Json(HttpStatusCode.Created,
                """{"status":"queued","diagnostic_id":"diag-test-one","expires_in":120,"mode":"ready"}""");
        }
        if (path == "/v1/manager/diagnostics/test-action/diag-test-one")
        {
            return Json(HttpStatusCode.OK,
                """{"status":"acked","diagnostic_id":"diag-test-one","created_at":1,"completed_at":2,"error":null}""");
        }
        if (path == "/v1/manager/diagnostics/test-action/diag-test-refuse")
        {
            return Json(HttpStatusCode.OK,
                """{"status":"failed","diagnostic_id":"diag-test-refuse","created_at":1,"completed_at":2,"error":"Unknown command: diagnostic_refuse","mode":"refuse"}""");
        }
        if (path == "/v1/manager/diagnostics/test-action/diag-test-lost")
        {
            return Json(HttpStatusCode.OK,
                """{"status":"expired","diagnostic_id":"diag-test-lost","created_at":1,"completed_at":121,"error":"simulated_ack_timeout","mode":"lost_ack"}""");
        }
        if (request.Method == HttpMethod.Delete && path.Contains("module-credentials"))
        {
            SawCredentialRevoke = true;
            return Json(HttpStatusCode.OK, """{"status":"ok"}""");
        }
        if (path == "/v1/manager/logout")
        {
            SawLogout = true;
            return Json(HttpStatusCode.OK, """{"status":"ok"}""");
        }
        return Json(HttpStatusCode.NotFound, """{"status":"not_found"}""");
    }

    private static string Session(string access, string refresh) =>
        $$"""{"status":"ok","access_token":"{{access}}","access_expires_at":9999,"refresh_token":"{{refresh}}","session_expires_at":999999,"channel_id":98319857,"module_id":"rimworld"}""";

    private static HttpResponseMessage Json(HttpStatusCode status, string value) => new(status)
    {
        Content = new StringContent(value, Encoding.UTF8, "application/json"),
    };
}

sealed class ArtifactDownloadHandler : HttpMessageHandler
{
    private readonly byte[] _payload;
    private readonly HttpStatusCode _status;

    public ArtifactDownloadHandler(byte[] payload, HttpStatusCode status)
    {
        _payload = payload;
        _status = status;
    }

    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        if (request.RequestUri?.Scheme != Uri.UriSchemeHttps)
        {
            throw new InvalidOperationException("Downloader attempted a non-HTTPS request.");
        }
        var response = new HttpResponseMessage(_status)
        {
            Content = new ByteArrayContent(_payload),
        };
        if ((int)_status is >= 300 and <= 399)
        {
            response.Headers.Location = new Uri("http://downgrade.test/artifact.zip");
        }
        return Task.FromResult(response);
    }
}
