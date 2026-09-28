namespace ShedLink.Manager.Core.Security;

public interface ICredentialVault
{
    void Write(string key, string secret);
    string? Read(string key);
    bool Delete(string key);
}
