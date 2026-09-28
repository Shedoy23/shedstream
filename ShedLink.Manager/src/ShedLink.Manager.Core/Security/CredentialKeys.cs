namespace ShedLink.Manager.Core.Security;

public static class CredentialKeys
{
    public static string ManagerRefresh(string installationId, string moduleId) =>
        $"{installationId}.{moduleId}.manager-refresh";

    public static string ModuleToken(string installationId, string moduleId) =>
        $"{installationId}.{moduleId}.module-token";

    public static string PendingModuleToken(string installationId, string moduleId) =>
        $"{installationId}.{moduleId}.pending-module-token";
}
