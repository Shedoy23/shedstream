using System.Xml.Linq;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text.Json;

namespace ShedLink.Manager.Core.Installation;

public static class ManagedXmlConfiguration
{
    public static void Write(
        string path,
        IReadOnlyDictionary<string, string> selectorValues)
    {
        using var update = PrepareWrite(path, selectorValues);
        update.Commit();
    }

    public static ManagedXmlUpdate PrepareWrite(
        string path,
        IReadOnlyDictionary<string, string> selectorValues)
    {
        if (selectorValues.Count == 0)
        {
            throw new ArgumentException("At least one managed field is required.");
        }
        path = Path.GetFullPath(path);
        Recover(path);
        var firstParts = Parts(selectorValues.Keys.First());
        XDocument document;
        if (File.Exists(path))
        {
            document = XDocument.Load(path, LoadOptions.PreserveWhitespace);
            if (document.Root?.Name.LocalName != firstParts[0])
            {
                throw new InvalidDataException("Configuration XML has an unexpected root.");
            }
        }
        else
        {
            document = new XDocument(new XElement(firstParts[0]));
        }

        foreach (var pair in selectorValues)
        {
            var parts = Parts(pair.Key);
            if (document.Root!.Name.LocalName != parts[0])
            {
                throw new InvalidDataException("Managed selectors use different XML roots.");
            }
            var current = document.Root;
            foreach (var part in parts.Skip(1))
            {
                current = current.Element(part) ?? Add(current, part);
            }
            current.Value = pair.Value;
        }

        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temporary = path + ".shedlink-write.tmp";
        var backup = path + ".shedlink-backup";
        var journal = path + ".shedlink-transaction.json";
        var hadOriginal = File.Exists(path);
        document.Save(temporary, SaveOptions.DisableFormatting);
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
            return new ManagedXmlUpdate(path);
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

    private static string[] Parts(string selector)
    {
        var parts = selector.Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length < 2 || parts.Any(part =>
            part.Any(character => !char.IsLetterOrDigit(character) && character is not '_' and not '-')))
        {
            throw new InvalidDataException("Managed XML selector is invalid.");
        }
        return parts;
    }

    private static XElement Add(XElement parent, string name)
    {
        var child = new XElement(name);
        parent.Add(child);
        return child;
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

public sealed class ManagedXmlUpdate : IDisposable
{
    private readonly string _path;
    private bool _finished;

    internal ManagedXmlUpdate(string path) => _path = path;

    public void Commit()
    {
        if (_finished)
        {
            return;
        }
        ManagedXmlConfiguration.Complete(_path);
        _finished = true;
    }

    public void Rollback()
    {
        if (_finished)
        {
            return;
        }
        ManagedXmlConfiguration.Recover(_path);
        _finished = true;
    }

    public void Dispose() => Rollback();
}
