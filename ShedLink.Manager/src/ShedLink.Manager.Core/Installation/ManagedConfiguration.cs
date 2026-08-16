using System.Security.AccessControl;
using System.Security.Principal;
using System.Text.Json;

namespace ShedLink.Manager.Core.Installation;

/// <summary>
/// The crash-safe part of writing a mod's configuration: journal, backup,
/// atomic replace and a user-only ACL. Formats differ only in how the new file
/// is produced, so XML and JSON share everything below.
/// </summary>
public static class ManagedConfiguration
{
    /// <param name="writeTemporary">
    /// Writes the complete new file to the given path. Kept as a callback so each
    /// format keeps its own serializer and byte-for-byte output.
    /// </param>
    public static ManagedConfigurationUpdate PrepareWrite(
        string path,
        Action<string> writeTemporary)
    {
        path = Path.GetFullPath(path);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temporary = path + ".shedlink-write.tmp";
        var backup = path + ".shedlink-backup";
        var journal = path + ".shedlink-transaction.json";
        var hadOriginal = File.Exists(path);
        writeTemporary(temporary);
        RestrictToCurrentUser(temporary);
        try
        {
            WriteJournal(journal, new ConfigurationJournal("prepared", hadOriginal));
            if (hadOriginal)
            {
                File.Move(path, backup);
            }
            WriteJournal(journal, new ConfigurationJournal("backed_up", hadOriginal));
            File.Move(temporary, path);
            WriteJournal(journal, new ConfigurationJournal("installed", hadOriginal));
            return new ManagedConfigurationUpdate(path);
        }
        catch
        {
            Recover(path);
            File.Delete(temporary);
            throw;
        }
    }

    public static bool Complete(string path)
    {
        path = Path.GetFullPath(path);
        var journal = path + ".shedlink-transaction.json";
        if (!File.Exists(journal))
        {
            return false;
        }
        File.Delete(path + ".shedlink-backup");
        File.Delete(path + ".shedlink-write.tmp");
        File.Delete(journal);
        File.Delete(journal + ".tmp");
        return true;
    }

    public static bool Recover(string path)
    {
        path = Path.GetFullPath(path);
        var backup = path + ".shedlink-backup";
        var temporary = path + ".shedlink-write.tmp";
        var journal = path + ".shedlink-transaction.json";
        if (!File.Exists(journal))
        {
            return false;
        }
        ConfigurationJournal? state = null;
        try
        {
            state = JsonSerializer.Deserialize<ConfigurationJournal>(
                File.ReadAllText(journal));
        }
        catch (JsonException)
        {
            // Prefer an intact backup even if the small journal was damaged.
        }
        if (File.Exists(backup))
        {
            File.Delete(path);
            File.Move(backup, path);
        }
        else if (state?.HadOriginal == false)
        {
            File.Delete(path);
        }
        File.Delete(temporary);
        File.Delete(journal);
        File.Delete(journal + ".tmp");
        return true;
    }

    private static void RestrictToCurrentUser(string path)
    {
        if (!OperatingSystem.IsWindows())
        {
            throw new PlatformNotSupportedException(
                "Secret configuration ACL requires Windows.");
        }
        using var identity = WindowsIdentity.GetCurrent();
        var user = identity.User
            ?? throw new InvalidOperationException("Current Windows user SID is unavailable.");
        var security = new FileSecurity();
        security.SetOwner(user);
        security.SetAccessRuleProtection(isProtected: true, preserveInheritance: false);
        security.AddAccessRule(new FileSystemAccessRule(
            user,
            FileSystemRights.FullControl,
            AccessControlType.Allow));
        new FileInfo(path).SetAccessControl(security);
    }

    private static void WriteJournal(string path, ConfigurationJournal state)
    {
        var temporary = path + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(state));
        File.Move(temporary, path, overwrite: true);
    }

    private sealed record ConfigurationJournal(
        [property: System.Text.Json.Serialization.JsonPropertyName("phase")] string Phase,
        [property: System.Text.Json.Serialization.JsonPropertyName("had_original")] bool HadOriginal);
}

public sealed class ManagedConfigurationUpdate : IDisposable
{
    private readonly string _path;
    private bool _finished;

    internal ManagedConfigurationUpdate(string path) => _path = path;

    public void Commit()
    {
        if (_finished)
        {
            return;
        }
        ManagedConfiguration.Complete(_path);
        _finished = true;
    }

    public void Rollback()
    {
        if (_finished)
        {
            return;
        }
        ManagedConfiguration.Recover(_path);
        _finished = true;
    }

    public void Dispose() => Rollback();
}
