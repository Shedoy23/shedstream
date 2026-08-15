using System.Net;
using System.Text;
using ShedLink.Manager.Core;
using ShedLink.Manager.Core.Api;
using ShedLink.Manager.Core.Security;
using ShedLink.Manager.Core.State;

var root = Path.Combine(Path.GetTempPath(), "shedlink-manager-test-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
try
{
    await TestCoordinatorAsync(root);
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

    var launch = await coordinator.BeginPairingAsync();
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

    var stateJson = File.ReadAllText(statePath);
    Assert(!stateJson.Contains("refresh-one", StringComparison.Ordinal),
        "refresh absent from JSON state");
    Assert(!stateJson.Contains("slmod_v1", StringComparison.Ordinal),
        "module token absent from JSON state");
    Assert(stateJson.Contains("credential-one", StringComparison.Ordinal),
        "non-secret credential id persisted");

    var restarted = new ManagerCoordinator(api, vault, new ManagerStateStore(statePath));
    var resumed = await restarted.ResumeAsync();
    Assert(resumed.AccessToken == "access-two", "session refreshed after restart");
    Assert(vault.Values.Values.Contains("refresh-two"), "rotated refresh stored");
    Assert(!vault.Values.Values.Contains("refresh-one"), "old refresh replaced");

    await restarted.LogoutAsync(resumed, revokeModuleCredential: true);
    Assert(vault.Values.Count == 0, "logout removes local credentials");
    Assert(handler.SawCredentialRevoke && handler.SawLogout, "server revoke and logout called");
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

static void Assert(bool condition, string label)
{
    if (!condition)
    {
        throw new InvalidOperationException("FAILED: " + label);
    }
    Console.WriteLine("  OK  " + label);
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
