using System.Net.Http;
using System.IO;
using System.Windows;
using Microsoft.Win32;
using ShedLink.Manager.Core;
using ShedLink.Manager.Core.Api;
using ShedLink.Manager.Core.Detection;
using ShedLink.Manager.Core.Diagnostics;
using ShedLink.Manager.Core.Installation;
using ShedLink.Manager.Core.Security;
using ShedLink.Manager.Core.State;

namespace ShedLink.Manager.App;

public partial class MainWindow : Window
{
    private readonly ManagerStateStore _stateStore = new();
    private readonly RimWorldDetectionService _detector = new();
    private readonly HttpClient _http;
    private readonly ManagerApiClient _api;
    private readonly WindowsCredentialVault _vault;
    private readonly ManagerCoordinator _coordinator;
    private readonly IntegrationInstallationService _installationService;
    private readonly CredentialRotationService _rotationService;
    private CancellationTokenSource? _pairingCancellation;
    private CancellationTokenSource? _installationCancellation;
    private CancellationTokenSource? _diagnosticsCancellation;
    private CancellationTokenSource? _testCancellation;
    private ReadySession? _session;
    private GameInstallation? _game;
    private bool _installing;
    private bool _testingReady;
    private bool _testingReliability;
    private ModuleRuntimeStatus? _runtimeStatus;

    public MainWindow()
    {
        InitializeComponent();
        var state = _stateStore.LoadOrCreate();
        _http = new HttpClient { BaseAddress = state.BackendUrl };
        _http.Timeout = TimeSpan.FromSeconds(15);
        _api = new ManagerApiClient(_http);
        _vault = new WindowsCredentialVault();
        _coordinator = new ManagerCoordinator(
            _api,
            _vault,
            _stateStore);
        _installationService = new IntegrationInstallationService(
            _api, _vault, _stateStore);
        _rotationService = new CredentialRotationService(
            _api, _vault, _stateStore);
        Loaded += MainWindow_Loaded;
        Closed += (_, _) =>
        {
            _pairingCancellation?.Cancel();
            _pairingCancellation?.Dispose();
            _installationCancellation?.Cancel();
            _installationCancellation?.Dispose();
            _diagnosticsCancellation?.Cancel();
            _diagnosticsCancellation?.Dispose();
            _testCancellation?.Cancel();
            _testCancellation?.Dispose();
            _http.Dispose();
        };
    }

    private async void MainWindow_Loaded(object sender, RoutedEventArgs e)
    {
        try
        {
            if (_installationService.RecoverPending())
            {
                OverallStatusText.Text = "Незавершённая установка безопасно восстановлена.";
            }
        }
        catch (InvalidDataException exception)
        {
            OverallStatusText.Text = "Не удалось восстановить установку: " + exception.Message;
        }
        DetectGame();
        var state = _stateStore.LoadOrCreate();
        if (state.ChannelId is null)
        {
            AccountStatusText.Text = "Не подключён";
            OverallStatusText.Text = "Войди через Twitch и проверь папку RimWorld.";
            return;
        }
        try
        {
            SetBusy(true, "Восстанавливаем защищённую сессию…");
            _session = await _coordinator.ResumeAsync();
            CredentialRotationResult? recovered = null;
            if (_rotationService.HasPending)
            {
                if (!TrySelectManifestForCurrentGame(out var recoveryRelease, out var reason))
                {
                    throw new InvalidOperationException(reason);
                }
                recovered = await _rotationService.RecoverPendingAsync(
                    _session, recoveryRelease!.ManifestPath);
            }
            if (recovered is not null)
            {
                _session = _session with { CredentialId = recovered.CredentialId };
            }
            ShowConnected(_session);
            if (recovered is not null)
            {
                OverallStatusText.Text = "Незавершённая смена ключа безопасно завершена.";
            }
        }
        catch (Exception exception) when (
            exception is ManagerApiException or HttpRequestException or TaskCanceledException or InvalidOperationException)
        {
            AccountStatusText.Text = "Нужно войти заново";
            OverallStatusText.Text = FriendlyError(exception);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void ConnectButton_Click(object sender, RoutedEventArgs e)
    {
        _pairingCancellation?.Cancel();
        _pairingCancellation?.Dispose();
        _pairingCancellation = new CancellationTokenSource(TimeSpan.FromMinutes(10));
        try
        {
            var stored = _stateStore.LoadOrCreate();
            if (stored.ChannelId is not null)
            {
                try
                {
                    SetBusy(true, "Повторяем защищённое подключение…");
                    _session = await _coordinator.ResumeAsync(
                        cancellationToken: _pairingCancellation.Token);
                    ShowConnected(_session);
                    return;
                }
                catch (ManagerApiException exception) when (IsTerminalSessionError(exception))
                {
                    // The old Manager session is unusable; module credential remains
                    // independently valid and will be reused after a fresh pairing.
                }
                catch (InvalidOperationException)
                {
                    // Local refresh credential is absent; a fresh pairing is required.
                }
            }
            SetBusy(true, "Создаём безопасное подключение…");
            var launch = await _coordinator.BeginPairingAsync(
                cancellationToken: _pairingCancellation.Token);
            PairingCodeText.Text = "Код: " + launch.UserCode;
            AccountStatusText.Text = "Подтверди подключение в открывшемся браузере";
            ManagerCoordinator.OpenSystemBrowser(launch.VerificationUri);

            while (!_pairingCancellation.IsCancellationRequested)
            {
                await Task.Delay(
                    TimeSpan.FromSeconds(launch.PollIntervalSeconds),
                    _pairingCancellation.Token);
                _session = await _coordinator.TryCompletePairingAsync(
                    cancellationToken: _pairingCancellation.Token);
                if (_session is not null)
                {
                    PairingCodeText.Text = string.Empty;
                    ShowConnected(_session);
                    return;
                }
            }
        }
        catch (OperationCanceledException)
        {
            AccountStatusText.Text = "Время подключения истекло — попробуй ещё раз";
        }
        catch (Exception exception) when (
            exception is ManagerApiException or HttpRequestException or InvalidOperationException)
        {
            AccountStatusText.Text = "Подключение не выполнено";
            OverallStatusText.Text = FriendlyError(exception);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void DisconnectButton_Click(object sender, RoutedEventArgs e)
    {
        if (_session is null)
        {
            return;
        }
        var decision = MessageBox.Show(
            this,
            "Выйти из Manager?\n\n" +
            "Да — выйти и отозвать ключ RimLink (интеграция сразу отключится).\n" +
            "Нет — выйти только из Manager, оставив установленный RimLink подключённым.\n" +
            "Отмена — ничего не менять.",
            "Выход из ShedLink Manager",
            MessageBoxButton.YesNoCancel,
            MessageBoxImage.Question);
        if (decision == MessageBoxResult.Cancel)
        {
            return;
        }
        var revokeModuleCredential = decision == MessageBoxResult.Yes;
        try
        {
            SetBusy(true, revokeModuleCredential
                ? "Отзываем ключ RimLink и завершаем сессию…"
                : "Завершаем сессию Manager…");
            _diagnosticsCancellation?.Cancel();
            _testCancellation?.Cancel();
            await _coordinator.LogoutAsync(_session, revokeModuleCredential);
            _session = null;
            _runtimeStatus = null;
            AccountStatusText.Text = "Не подключён";
            PairingCodeText.Text = string.Empty;
            ConnectButton.Content = "Войти через Twitch";
            RuntimeStatusText.Text = revokeModuleCredential
                ? "Ключ RimLink отозван. Для продолжения подключись заново."
                : "Manager отключён; установленный RimLink продолжает работать.";
            OverallStatusText.Text = revokeModuleCredential
                ? "Сессия и ключ отозваны. Конфигурация сохранена для восстановления."
                : "Сессия Manager завершена без отключения интеграции.";
            UpdateInstallAvailability(updateReleaseMessage: false);
        }
        catch (Exception exception) when (
            exception is ManagerApiException or HttpRequestException or
                TaskCanceledException or InvalidOperationException)
        {
            OverallStatusText.Text = FriendlyError(exception);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private void ChooseGameButton_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFolderDialog
        {
            Title = "Выбери папку RimWorld",
            Multiselect = false,
        };
        if (dialog.ShowDialog(this) != true)
        {
            return;
        }
        try
        {
            _game = _detector.ValidateManual(dialog.FolderName);
            SaveGameRoot(_game.RootPath);
            ShowGame(_game);
        }
        catch (InvalidDataException exception)
        {
            MessageBox.Show(this, exception.Message, "Это не папка RimWorld",
                MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    private async void InstallButton_Click(object sender, RoutedEventArgs e)
    {
        if (_session is null || _game is null)
        {
            UpdateInstallAvailability();
            return;
        }
        var gameVersion = GameVersionDetector.DetectRimWorld(_game.RootPath);
        if (!ReleaseConfiguration.TrySelect(
                gameVersion, out var release, out var verifier, out var reason))
        {
            IntegrationStatusText.Text = reason;
            UpdateInstallAvailability();
            return;
        }
        if (_detector.IsGameRunning())
        {
            IntegrationStatusText.Text = "Закрой RimWorld перед установкой RimLink.";
            return;
        }

        _installing = true;
        _installationCancellation?.Cancel();
        _installationCancellation?.Dispose();
        _installationCancellation = new CancellationTokenSource(TimeSpan.FromMinutes(5));
        UpdateInstallAvailability();
        IntegrationStatusText.Text = "Скачиваем, проверяем и настраиваем RimLink…";
        OverallStatusText.Text = "Не закрывай Manager до завершения проверки.";
        try
        {
            using var downloader = new SecureArtifactDownloader();
            var installed = await _installationService.InstallHttpsAsync(
                release!.ManifestPath,
                _game.RootPath,
                downloader,
                verifier!,
                cancellationToken: _installationCancellation.Token);
            var state = _stateStore.LoadOrCreate();
            _stateStore.Save(state with
            {
                GameRoot = _game.RootPath,
                InstalledReleaseVersion = installed.ReleaseVersion,
            });
            IntegrationStatusText.Text =
                $"RimLink {installed.ReleaseVersion} установлен и ключ проверен.";
            OverallStatusText.Text =
                "Запусти RimWorld: Technical Ready подтвердит heartbeat мода.";
        }
        catch (Exception exception) when (
            exception is ManagerApiException or HttpRequestException or
                TaskCanceledException or InvalidOperationException or
                InvalidDataException or IOException)
        {
            IntegrationStatusText.Text =
                "Установка не выполнена; прежняя версия восстановлена.";
            OverallStatusText.Text = FriendlyError(exception);
        }
        finally
        {
            _installing = false;
            _installationCancellation?.Dispose();
            _installationCancellation = null;
            UpdateInstallAvailability();
        }
    }

    private void RemoveButton_Click(object sender, RoutedEventArgs e)
    {
        if (_game is null)
        {
            UpdateInstallAvailability();
            return;
        }
        if (!ReleaseConfiguration.TrySelectLatestManifest(out var release, out var reason))
        {
            IntegrationStatusText.Text = reason;
            return;
        }
        if (_detector.IsGameRunning())
        {
            IntegrationStatusText.Text = "Закрой RimWorld перед удалением RimLink.";
            return;
        }
        if (MessageBox.Show(
            this,
            "Удалить мод RimLink? Настройки и защищённый ключ останутся, чтобы его можно было восстановить.",
            "Удаление RimLink",
            MessageBoxButton.YesNo,
            MessageBoxImage.Question) != MessageBoxResult.Yes)
        {
            return;
        }

        _installing = true;
        UpdateInstallAvailability();
        try
        {
            _installationService.Uninstall(
                release!.ManifestPath, _game.RootPath);
            var state = _stateStore.LoadOrCreate();
            _stateStore.Save(state with { InstalledReleaseVersion = null });
            IntegrationStatusText.Text =
                "RimLink удалён. Настройки сохранены для восстановления.";
            OverallStatusText.Text = "Интеграция отключена локально; ключ не отозван.";
        }
        catch (Exception exception) when (
            exception is InvalidOperationException or InvalidDataException or IOException)
        {
            IntegrationStatusText.Text = "Удаление не выполнено; мод восстановлен.";
            OverallStatusText.Text = FriendlyError(exception);
        }
        finally
        {
            _installing = false;
            UpdateInstallAvailability(updateReleaseMessage: false);
        }
    }

    private async void RotateButton_Click(object sender, RoutedEventArgs e)
    {
        if (_session is null)
        {
            UpdateInstallAvailability();
            return;
        }
        if (_detector.IsGameRunning())
        {
            MessageBox.Show(
                "Закрой RimWorld перед сменой ключа, чтобы мод не продолжил использовать старый ключ.",
                "RimWorld запущен", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }
        var inspection = InspectIntegration();
        if (inspection?.Condition is InstallationCondition.NotInstalled or
            InstallationCondition.UnsafeTarget || inspection is null)
        {
            IntegrationStatusText.Text = "Сначала установи или восстанови RimLink.";
            UpdateInstallAvailability(updateReleaseMessage: false);
            return;
        }
        if (MessageBox.Show(
                "Создать новый ключ RimLink и заменить старый? Настройки будут обновлены автоматически.",
                "Смена ключа RimLink", MessageBoxButton.YesNo,
                MessageBoxImage.Question) != MessageBoxResult.Yes)
        {
            return;
        }
        try
        {
            SetBusy(true, "Безопасно меняем ключ RimLink…");
            if (!TrySelectManifestForCurrentGame(out var release, out var reason))
            {
                throw new InvalidOperationException(reason);
            }
            var result = await _rotationService.RotateAsync(
                _session, release!.ManifestPath);
            _session = _session with { CredentialId = result.CredentialId };
            IntegrationStatusText.Text = "Ключ RimLink заменён и проверен.";
            OverallStatusText.Text = "Новый ключ активен. RimWorld можно запускать.";
        }
        catch (Exception exception) when (
            exception is ManagerApiException or HttpRequestException or
                TaskCanceledException or InvalidOperationException or InvalidDataException)
        {
            OverallStatusText.Text = FriendlyError(exception) +
                " Если новый ключ уже был выдан, Manager продолжит замену при следующем запуске.";
        }
        finally
        {
            SetBusy(false);
            UpdateInstallAvailability(updateReleaseMessage: false);
        }
    }

    private void DiagnosticReportButton_Click(object sender, RoutedEventArgs e)
    {
        var state = _stateStore.LoadOrCreate();
        var inspection = InspectIntegration();
        var gameVersion = _game is null
            ? null
            : GameVersionDetector.DetectRimWorld(_game.RootPath);
        ReleaseConfiguration.TrySelectLatestManifest(out var diagnosticRelease, out _);
        var manifest = diagnosticRelease?.Manifest;
        var integrationVersion = inspection?.Condition == InstallationCondition.NotInstalled
            ? "not installed"
            : inspection?.InstalledVersion ?? state.InstalledReleaseVersion;
        var report = DiagnosticReportBuilder.Build(new DiagnosticReportInput(
            typeof(MainWindow).Assembly.GetName().Version?.ToString() ?? "unknown",
            "manager-v1 / module-v1",
            state.BackendUrl.ToString(),
            gameVersion?.FullVersion,
            GameVersionDetector.Compatibility(
                gameVersion, manifest?.Game?.SupportedVersions),
            integrationVersion,
            inspection?.Condition.ToString() ?? "Unknown",
            InstallationReason(inspection),
            inspection?.FailedProbeIds ?? Array.Empty<string>(),
            _runtimeStatus?.Online,
            _runtimeStatus?.AgeSeconds,
            new[]
            {
                AccountStatusText.Text,
                GameStatusText.Text,
                IntegrationStatusText.Text,
                RuntimeStatusText.Text,
                OverallStatusText.Text,
            }));
        var preview = new DiagnosticPreviewWindow(report) { Owner = this };
        if (preview.ShowDialog() == true)
        {
            OverallStatusText.Text = "Диагностический отчёт сохранён после предпросмотра.";
        }
    }

    private static string InstallationReason(InstallationInspection? inspection)
    {
        if (inspection is null)
        {
            return "game or release manifest is unavailable";
        }
        return inspection.Condition switch
        {
            InstallationCondition.NotInstalled => "integration is not installed",
            InstallationCondition.UnsafeTarget => "installation target is an unsafe link",
            InstallationCondition.UpdateAvailable => "a newer integration release is available",
            InstallationCondition.Healthy => "managed installation and required files are healthy",
            InstallationCondition.RepairRequired when
                inspection.FailedProbeIds.Count > 0 &&
                string.IsNullOrWhiteSpace(inspection.InstalledVersion) =>
                "installation is unmanaged and required files are missing",
            InstallationCondition.RepairRequired when inspection.FailedProbeIds.Count > 0 =>
                "required integration files are missing",
            InstallationCondition.RepairRequired =>
                "existing integration was not installed by this Manager",
            _ => "installation state is unknown",
        };
    }

    private void DetectGame()
    {
        var state = _stateStore.LoadOrCreate();
        if (RimWorldDetectionService.IsValidGameRoot(state.GameRoot))
        {
            _game = new GameInstallation(
                "rimworld", state.GameRoot!, DetectionSource.Manual);
        }
        else
        {
            _game = _detector.Detect();
            if (_game is not null)
            {
                SaveGameRoot(_game.RootPath);
            }
        }
        if (_game is null)
        {
            GameStatusText.Text = "Не нашли автоматически. Выбери папку игры вручную.";
            InstallButton.IsEnabled = false;
            return;
        }
        ShowGame(_game);
    }

    private void ShowGame(GameInstallation game)
    {
        var source = game.Source == DetectionSource.Steam ? "Steam" : "выбрано вручную";
        var running = _detector.IsGameRunning() ? " · игра сейчас запущена" : string.Empty;
        var version = GameVersionDetector.DetectRimWorld(game.RootPath);
        var versionText = version is null ? string.Empty : $" · версия {version.FullVersion}";
        GameStatusText.Text = $"Найдено ({source}): {game.RootPath}{versionText}{running}";
        UpdateInstallAvailability();
    }

    private void ShowConnected(ReadySession session)
    {
        AccountStatusText.Text = $"Подключён канал {session.ChannelId}";
        ConnectButton.Content = "Подключено";
        ConnectButton.IsEnabled = false;
        DisconnectButton.IsEnabled = true;
        OverallStatusText.Text = "Аккаунт защищённо подключён. Проверяем игру и integration.";
        UpdateInstallAvailability();
        StartDiagnostics();
    }

    private void StartDiagnostics()
    {
        _diagnosticsCancellation?.Cancel();
        _diagnosticsCancellation?.Dispose();
        _diagnosticsCancellation = new CancellationTokenSource();
        _ = RunDiagnosticsLoopAsync(_diagnosticsCancellation.Token);
    }

    private async Task RunDiagnosticsLoopAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                var state = _stateStore.LoadOrCreate();
                var token = _vault.Read(
                    CredentialKeys.ModuleToken(state.InstallationId, state.ModuleId));
                if (string.IsNullOrWhiteSpace(token))
                {
                    RuntimeStatusText.Text = "Защищённый ключ мода отсутствует.";
                }
                else
                {
                    var runtime = await _api.GetModuleStatusAsync(
                        token, state.ModuleId, cancellationToken);
                    _runtimeStatus = runtime;
                    RuntimeStatusText.Text = RuntimeMessage(runtime);
                    UpdateTechnicalReadyAvailability();
                }
            }
            catch (ManagerApiException exception) when (
                exception.StatusCode == System.Net.HttpStatusCode.NotFound)
            {
                _runtimeStatus = null;
                RuntimeStatusText.Text =
                    "Диагностика heartbeat станет доступна после обновления backend.";
                UpdateTechnicalReadyAvailability();
            }
            catch (ManagerApiException exception)
            {
                _runtimeStatus = null;
                RuntimeStatusText.Text =
                    $"Диагностика отклонена сервером: {exception.ErrorCode}.";
                UpdateTechnicalReadyAvailability();
            }
            catch (HttpRequestException)
            {
                _runtimeStatus = null;
                RuntimeStatusText.Text = "Backend сейчас недоступен.";
                UpdateTechnicalReadyAvailability();
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                return;
            }

            try
            {
                await Task.Delay(TimeSpan.FromSeconds(15), cancellationToken);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }
    }

    private static string RuntimeMessage(ModuleRuntimeStatus runtime)
    {
        if (runtime.Online)
        {
            return runtime.AgeSeconds is > 0
                ? $"Мод на связи · heartbeat {runtime.AgeSeconds} сек. назад."
                : "Мод на связи · heartbeat только что получен.";
        }
        if (runtime.AgeSeconds is int age)
        {
            return age < 120
                ? $"Мод не на связи · последний heartbeat {age} сек. назад."
                : $"Мод не на связи · последний heartbeat {age / 60} мин. назад.";
        }
        return "Настоящий heartbeat мода ещё не получен. Запусти RimWorld.";
    }

    private async void TestReadyButton_Click(object sender, RoutedEventArgs e)
    {
        if (_session is null || _runtimeStatus?.Online != true)
        {
            UpdateTechnicalReadyAvailability();
            return;
        }
        _testCancellation?.Cancel();
        _testCancellation?.Dispose();
        _testCancellation = new CancellationTokenSource(TimeSpan.FromMinutes(3));
        _testingReady = true;
        UpdateTechnicalReadyAvailability();
        OverallStatusText.Text = "Отправляем безопасную проверку через игровую очередь…";
        try
        {
            var started = await _api.StartDiagnosticAsync(
                _session.AccessToken, _testCancellation.Token);
            var result = await WaitForDiagnosticAsync(started, _testCancellation.Token);
            OverallStatusText.Text = result?.Status switch
            {
                "acked" => "Technical Ready ✓ Backend, очередь, RimLink и ACK работают.",
                "failed" => $"RimLink отклонил проверку: {result.Error ?? "unknown"}.",
                "expired" => "Проверка истекла: RimLink не подтвердил команду вовремя.",
                _ => "Проверка истекла без подтверждения RimLink.",
            };
        }
        catch (ManagerApiException exception)
        {
            OverallStatusText.Text = FriendlyError(exception);
        }
        catch (OperationCanceledException)
        {
            OverallStatusText.Text = "Проверка готовности остановлена.";
        }
        finally
        {
            _testingReady = false;
            _testCancellation?.Dispose();
            _testCancellation = null;
            UpdateTechnicalReadyAvailability();
        }
    }

    private async void ReliabilityButton_Click(object sender, RoutedEventArgs e)
    {
        if (_session is null || _runtimeStatus?.Online != true)
        {
            UpdateTechnicalReadyAvailability();
            return;
        }
        _testCancellation?.Cancel();
        _testCancellation?.Dispose();
        _testCancellation = new CancellationTokenSource(TimeSpan.FromMinutes(4));
        _testingReliability = true;
        UpdateTechnicalReadyAvailability();
        try
        {
            OverallStatusText.Text = "Проверяем безопасный отказ RimLink…";
            var refused = await _api.StartDiagnosticAsync(
                _session.AccessToken, "refuse", _testCancellation.Token);
            var refusedResult = await WaitForDiagnosticAsync(
                refused, _testCancellation.Token);
            if (refusedResult?.Status != "failed" ||
                !(refusedResult.Error ?? "").Contains(
                    "diagnostic_refuse", StringComparison.Ordinal))
            {
                OverallStatusText.Text =
                    "Проверка отказа не дала ожидаемый безопасный результат.";
                return;
            }

            OverallStatusText.Text =
                "Отказ обработан ✓ Имитируем потерю ACK (до 2 минут)…";
            var lost = await _api.StartDiagnosticAsync(
                _session.AccessToken, "lost_ack", _testCancellation.Token);
            var lostResult = await WaitForDiagnosticAsync(
                lost, _testCancellation.Token);
            OverallStatusText.Text = lostResult is
                { Status: "expired", Error: "simulated_ack_timeout" }
                ? "Reliability Ready ✓ Отказ и потерянный ACK обработаны безопасно."
                : "Потерянный ACK не завершился ожидаемой безопасной очисткой.";
        }
        catch (ManagerApiException exception)
        {
            OverallStatusText.Text = FriendlyError(exception);
        }
        catch (OperationCanceledException)
        {
            OverallStatusText.Text = "Проверка отказов остановлена.";
        }
        finally
        {
            _testingReliability = false;
            _testCancellation?.Dispose();
            _testCancellation = null;
            UpdateTechnicalReadyAvailability();
        }
    }

    private async Task<DiagnosticResult?> WaitForDiagnosticAsync(
        DiagnosticStarted started,
        CancellationToken cancellationToken)
    {
        if (_session is null)
            return null;
        var deadline = DateTime.UtcNow.AddSeconds(Math.Max(1, started.ExpiresIn + 5));
        while (DateTime.UtcNow < deadline)
        {
            var result = await _api.GetDiagnosticResultAsync(
                _session.AccessToken,
                started.DiagnosticId,
                cancellationToken);
            if (result.Status is "acked" or "failed" or "expired")
                return result;
            await Task.Delay(TimeSpan.FromSeconds(2), cancellationToken);
        }
        return null;
    }

    private void UpdateTechnicalReadyAvailability()
    {
        var inspection = InspectIntegration();
        var filesReady = inspection is not null &&
            inspection.Condition is not InstallationCondition.NotInstalled
                and not InstallationCondition.UnsafeTarget &&
            inspection.FailedProbeIds.Count == 0;
        var compatible = TryGetGameCompatibility(out var compatibilityReason);
        var canTest = !_installing && !_testingReady && !_testingReliability &&
            _session is not null &&
            _runtimeStatus?.Online == true && filesReady && compatible;
        TestReadyButton.IsEnabled = canTest;
        ReliabilityButton.IsEnabled = canTest;
        TestReadyButton.ToolTip = _testingReady
            ? "Проверка уже выполняется."
            : !compatible
                ? compatibilityReason
                : _runtimeStatus?.Online != true
                    ? "Сначала запусти RimWorld и дождись heartbeat."
                    : !filesReady
                        ? "Сначала установи или восстанови RimLink."
                        : "Проверить реальную очередь и ACK без изменения игры.";
        ReliabilityButton.ToolTip = _testingReliability
            ? "Проверка отказов уже выполняется."
            : !canTest
                ? TestReadyButton.ToolTip
                : "Проверить безопасный отказ и очистку потерянного ACK без списаний.";
    }

    private void UpdateInstallAvailability(bool updateReleaseMessage = true)
    {
        UpdateTechnicalReadyAvailability();
        if (_installing)
        {
            InstallButton.IsEnabled = false;
            RemoveButton.IsEnabled = false;
            RotateButton.IsEnabled = false;
            InstallButton.ToolTip = "Установка уже выполняется.";
            return;
        }
        var inspection = InspectIntegration();
        var installed = inspection is not null &&
            inspection.Condition != InstallationCondition.NotInstalled;
        InstallButton.Content = inspection?.Condition switch
        {
            InstallationCondition.UpdateAvailable => "Обновить",
            InstallationCondition.RepairRequired => "Восстановить",
            InstallationCondition.Healthy => "Переустановить",
            _ => "Установить",
        };
        RemoveButton.IsEnabled = installed &&
            inspection?.Condition != InstallationCondition.UnsafeTarget;
        RemoveButton.ToolTip = inspection?.Condition switch
        {
            InstallationCondition.UnsafeTarget =>
                "Автоматическое удаление небезопасной ссылки запрещено.",
            not InstallationCondition.NotInstalled when installed =>
                "Удалить мод, сохранив настройки и ключ.",
            _ => "RimLink не установлен в выбранной игре.",
        };
        var canRotate = _session is not null && installed &&
            inspection?.Condition != InstallationCondition.UnsafeTarget;
        RotateButton.IsEnabled = canRotate;
        RotateButton.ToolTip = canRotate
            ? "Заменить ключ RimLink с проверкой и безопасным восстановлением."
            : "Сначала подключи аккаунт и установи RimLink.";
        if (inspection is not null && updateReleaseMessage)
        {
            IntegrationStatusText.Text = InspectionMessage(inspection);
        }
        if (_session is null || _game is null)
        {
            InstallButton.IsEnabled = false;
            InstallButton.ToolTip = "Сначала подключи Twitch и найди RimWorld.";
            return;
        }
        var gameVersion = GameVersionDetector.DetectRimWorld(_game.RootPath);
        var releaseReady = ReleaseConfiguration.TrySelect(
            gameVersion, out _, out _, out var releaseReason);
        var compatible = TryGetGameCompatibility(out var compatibilityReason);
        InstallButton.IsEnabled = releaseReady && compatible &&
            inspection?.Condition != InstallationCondition.UnsafeTarget;
        InstallButton.ToolTip = !compatible
            ? compatibilityReason
            : releaseReady
            ? "Установить и настроить RimLink."
            : releaseReason;
        if (!releaseReady && updateReleaseMessage)
        {
            IntegrationStatusText.Text = inspection is null
                ? releaseReason
                : $"{InspectionMessage(inspection)} {releaseReason}";
        }
    }

    private bool TryGetGameCompatibility(out string reason)
    {
        if (_game is null)
        {
            reason = "Сначала найди установленный RimWorld.";
            return false;
        }
        var version = GameVersionDetector.DetectRimWorld(_game.RootPath);
        if (version is null)
        {
            reason = "Не удалось определить версию RimWorld из Version.txt.";
            return false;
        }
        if (!ReleaseConfiguration.TrySelectManifest(
                version, out var release, out reason) || release?.Manifest.Game is null)
        {
            return false;
        }
        if (GameVersionDetector.Compatibility(
                version, release.Manifest.Game.SupportedVersions) != "supported")
        {
            reason = $"RimWorld {version.FullVersion} не поддерживается. Поддерживаются: " +
                string.Join(", ", release.Manifest.Game.SupportedVersions) + ".";
            return false;
        }
        reason = $"RimWorld {version.FullVersion} поддерживается.";
        return true;
    }

    private InstallationInspection? InspectIntegration()
    {
        if (_game is null ||
            !ReleaseConfiguration.TrySelectLatestManifest(out var release, out _))
        {
            return null;
        }
        var state = _stateStore.LoadOrCreate();
        return InstallationInspector.Inspect(
            release!.Manifest, _game.RootPath, state.InstalledReleaseVersion);
    }

    private bool TrySelectManifestForCurrentGame(
        out InstallationRelease? release,
        out string reason)
    {
        var version = _game is null
            ? null
            : GameVersionDetector.DetectRimWorld(_game.RootPath);
        return ReleaseConfiguration.TrySelectManifest(version, out release, out reason);
    }

    private static string InspectionMessage(InstallationInspection inspection) =>
        inspection.Condition switch
        {
            InstallationCondition.NotInstalled =>
                $"RimLink не установлен. Доступна версия {inspection.AvailableVersion}.",
            InstallationCondition.Healthy =>
                $"RimLink {inspection.InstalledVersion} установлен, обязательные файлы на месте.",
            InstallationCondition.UpdateAvailable =>
                $"Установлена версия {inspection.InstalledVersion}; доступна {inspection.AvailableVersion}.",
            InstallationCondition.RepairRequired =>
                "RimLink найден, но версия неизвестна или обязательные файлы повреждены.",
            InstallationCondition.UnsafeTarget =>
                "Папка RimLink является небезопасной ссылкой; автоматические операции заблокированы.",
            _ => "Состояние RimLink неизвестно.",
        };

    private void SaveGameRoot(string gameRoot)
    {
        var state = _stateStore.LoadOrCreate();
        _stateStore.Save(state with { GameRoot = gameRoot });
    }

    private void SetBusy(bool busy, string? message = null)
    {
        ConnectButton.IsEnabled = !busy && _session is null;
        DisconnectButton.IsEnabled = !busy && _session is not null;
        if (busy)
        {
            RotateButton.IsEnabled = false;
        }
        if (message is not null)
        {
            OverallStatusText.Text = message;
        }
    }

    private static string FriendlyError(Exception exception) => exception switch
    {
        ManagerApiException api when api.ErrorCode == "manager_auth_unavailable" =>
            "Manager API пока не включён на сервере.",
        ManagerApiException api => $"Сервер отклонил запрос: {api.ErrorCode}.",
        TaskCanceledException => "Сервер не ответил вовремя.",
        HttpRequestException => "Не удалось связаться с ShedLink backend.",
        InvalidOperationException invalid => invalid.Message,
        _ => "Неожиданная ошибка Manager.",
    };

    private static bool IsTerminalSessionError(ManagerApiException exception) =>
        exception.ErrorCode is
            "invalid_refresh_token" or
            "refresh_reuse_detected" or
            "manager_session_expired" or
            "invalid_manager_session";
}
