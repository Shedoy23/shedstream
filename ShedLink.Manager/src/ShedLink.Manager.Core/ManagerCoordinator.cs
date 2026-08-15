using System.Diagnostics;
using System.Security.Cryptography;
using ShedLink.Manager.Core.Api;
using ShedLink.Manager.Core.Security;
using ShedLink.Manager.Core.State;

namespace ShedLink.Manager.Core;

public sealed record PairingLaunch(Uri VerificationUri, string UserCode, int PollIntervalSeconds);

public sealed record ReadySession(
    string AccessToken,
    long AccessExpiresAt,
    long ChannelId,
    string ModuleId,
    string CredentialId);

public sealed class ManagerCoordinator
{
    private readonly ManagerApiClient _api;
    private readonly ICredentialVault _vault;
    private readonly ManagerStateStore _stateStore;
    private string? _pairingId;
    private string? _deviceSecret;

    public ManagerCoordinator(
        ManagerApiClient api,
        ICredentialVault vault,
        ManagerStateStore stateStore)
    {
        _api = api;
        _vault = vault;
        _stateStore = stateStore;
    }

    public async Task<PairingLaunch> BeginPairingAsync(
        string moduleId = "rimworld",
        CancellationToken cancellationToken = default)
    {
        var state = _stateStore.LoadOrCreate();
        var secretBytes = RandomNumberGenerator.GetBytes(32);
        _deviceSecret = Base64Url(secretBytes);
        var challenge = Base64Url(SHA256.HashData(
            System.Text.Encoding.UTF8.GetBytes(_deviceSecret)));
        var pairing = await _api.CreatePairingAsync(
            state.InstallationId, moduleId, challenge, cancellationToken);
        _pairingId = pairing.PairingId;
        return new PairingLaunch(
            pairing.VerificationUri,
            pairing.UserCode,
            Math.Max(1, pairing.Interval));
    }

    public static void OpenSystemBrowser(Uri verificationUri)
    {
        if (verificationUri.Scheme != Uri.UriSchemeHttps)
        {
            throw new InvalidOperationException("Pairing URL must use HTTPS.");
        }
        Process.Start(new ProcessStartInfo(verificationUri.AbsoluteUri)
        {
            UseShellExecute = true,
        });
    }

    public async Task<ReadySession?> TryCompletePairingAsync(
        string label = "ShedLink Manager",
        CancellationToken cancellationToken = default)
    {
        if (_pairingId is null || _deviceSecret is null)
        {
            throw new InvalidOperationException("Pairing has not been started.");
        }
        ManagerSession session;
        try
        {
            session = await _api.ExchangePairingAsync(
                _pairingId, _deviceSecret, cancellationToken);
        }
        catch (ManagerApiException exc) when (exc.ErrorCode == "authorization_pending")
        {
            return null;
        }

        var state = _stateStore.LoadOrCreate() with
        {
            ModuleId = session.ModuleId,
            ChannelId = session.ChannelId,
        };
        _vault.Write(CredentialKeys.ManagerRefresh(state.InstallationId), session.RefreshToken);
        _stateStore.Save(state);
        _pairingId = null;
        _deviceSecret = null;

        var existingToken = _vault.Read(
            CredentialKeys.ModuleToken(state.InstallationId, session.ModuleId));
        if (!string.IsNullOrEmpty(existingToken) && !string.IsNullOrEmpty(state.CredentialId))
        {
            return Ready(session, state.CredentialId);
        }
        var credential = await _api.IssueCredentialAsync(
            session.AccessToken, session.ModuleId, label, cancellationToken);
        _vault.Write(
            CredentialKeys.ModuleToken(state.InstallationId, session.ModuleId),
            credential.ModuleToken);
        state = state with { CredentialId = credential.CredentialId };
        _stateStore.Save(state);
        return Ready(session, credential.CredentialId);
    }

    public async Task<ReadySession> ResumeAsync(
        string label = "ShedLink Manager",
        CancellationToken cancellationToken = default)
    {
        var state = _stateStore.LoadOrCreate();
        var refreshToken = _vault.Read(CredentialKeys.ManagerRefresh(state.InstallationId));
        if (string.IsNullOrEmpty(refreshToken))
        {
            throw new InvalidOperationException("Manager is not paired.");
        }
        var session = await _api.RefreshAsync(refreshToken, cancellationToken);
        _vault.Write(CredentialKeys.ManagerRefresh(state.InstallationId), session.RefreshToken);
        state = state with { ModuleId = session.ModuleId, ChannelId = session.ChannelId };
        _stateStore.Save(state);

        var credentialId = state.CredentialId;
        var moduleToken = _vault.Read(
            CredentialKeys.ModuleToken(state.InstallationId, session.ModuleId));
        if (string.IsNullOrEmpty(moduleToken) || string.IsNullOrEmpty(credentialId))
        {
            var credential = await _api.IssueCredentialAsync(
                session.AccessToken, session.ModuleId, label, cancellationToken);
            _vault.Write(
                CredentialKeys.ModuleToken(state.InstallationId, session.ModuleId),
                credential.ModuleToken);
            credentialId = credential.CredentialId;
            state = state with { CredentialId = credentialId };
            _stateStore.Save(state);
        }
        return Ready(session, credentialId);
    }

    public async Task LogoutAsync(
        ReadySession session,
        bool revokeModuleCredential,
        CancellationToken cancellationToken = default)
    {
        var state = _stateStore.LoadOrCreate();
        if (revokeModuleCredential)
        {
            await _api.RevokeCredentialAsync(
                session.AccessToken, session.CredentialId, cancellationToken);
            _vault.Delete(CredentialKeys.ModuleToken(state.InstallationId, session.ModuleId));
        }
        await _api.LogoutAsync(session.AccessToken, cancellationToken);
        _vault.Delete(CredentialKeys.ManagerRefresh(state.InstallationId));
        _stateStore.Save(state with
        {
            ChannelId = null,
            CredentialId = revokeModuleCredential ? null : state.CredentialId,
        });
    }

    private static ReadySession Ready(ManagerSession session, string credentialId) => new(
        session.AccessToken,
        session.AccessExpiresAt,
        session.ChannelId,
        session.ModuleId,
        credentialId);

    private static string Base64Url(byte[] value) =>
        Convert.ToBase64String(value).TrimEnd('=').Replace('+', '-').Replace('/', '_');
}
