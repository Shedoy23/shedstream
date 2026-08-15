using System.Net.Http;
using System.IO;
using System.Windows;
using Microsoft.Win32;
using ShedLink.Manager.Core;
using ShedLink.Manager.Core.Api;
using ShedLink.Manager.Core.Detection;
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
    private CancellationTokenSource? _pairingCancellation;
    private CancellationTokenSource? _installationCancellation;
    private ReadySession? _session;
    private GameInstallation? _game;
    private bool _installing;

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
        Loaded += MainWindow_Loaded;
        Closed += (_, _) =>
        {
            _pairingCancellation?.Cancel();
            _pairingCancellation?.Dispose();
            _installationCancellation?.Cancel();
            _installationCancellation?.Dispose();
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
            ShowConnected(_session);
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
        if (!ReleaseConfiguration.TryLoad(out _, out var verifier, out var reason))
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
                ReleaseConfiguration.ManifestPath,
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
        GameStatusText.Text = $"Найдено ({source}): {game.RootPath}{running}";
        UpdateInstallAvailability();
    }

    private void ShowConnected(ReadySession session)
    {
        AccountStatusText.Text = $"Подключён канал {session.ChannelId}";
        ConnectButton.Content = "Подключено";
        ConnectButton.IsEnabled = false;
        OverallStatusText.Text = "Аккаунт защищённо подключён. Проверяем игру и integration.";
        UpdateInstallAvailability();
    }

    private void UpdateInstallAvailability()
    {
        if (_installing)
        {
            InstallButton.IsEnabled = false;
            InstallButton.ToolTip = "Установка уже выполняется.";
            return;
        }
        if (_session is null || _game is null)
        {
            InstallButton.IsEnabled = false;
            InstallButton.ToolTip = "Сначала подключи Twitch и найди RimWorld.";
            return;
        }
        var releaseReady = ReleaseConfiguration.TryLoad(
            out _, out _, out var releaseReason);
        InstallButton.IsEnabled = releaseReady;
        InstallButton.ToolTip = releaseReady
            ? "Установить и настроить RimLink."
            : releaseReason;
        if (!releaseReady)
        {
            IntegrationStatusText.Text = releaseReason;
        }
    }

    private void SaveGameRoot(string gameRoot)
    {
        var state = _stateStore.LoadOrCreate();
        _stateStore.Save(state with { GameRoot = gameRoot });
    }

    private void SetBusy(bool busy, string? message = null)
    {
        ConnectButton.IsEnabled = !busy && _session is null;
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
