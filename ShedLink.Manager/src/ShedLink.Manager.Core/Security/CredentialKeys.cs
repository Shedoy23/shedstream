namespace ShedLink.Manager.Core.Security;

public static class CredentialKeys
{
    public static string ManagerRefresh(string installationId) =>
        $"{installationId}.manager-refresh";

    public static string ModuleToken(string installationId, string moduleId) =>
        $"{installationId}.{moduleId}.module-token";
}
