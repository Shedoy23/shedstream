using System.Xml.Linq;
using System.Security.AccessControl;
using System.Security.Principal;

namespace ShedLink.Manager.Core.Installation;

public static class ManagedXmlConfiguration
{
    public static void Write(
        string path,
        IReadOnlyDictionary<string, string> selectorValues)
    {
        if (selectorValues.Count == 0)
        {
            throw new ArgumentException("At least one managed field is required.");
        }
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
        var temporary = path + ".tmp";
        document.Save(temporary, SaveOptions.DisableFormatting);
        RestrictToCurrentUser(temporary);
        File.Move(temporary, path, overwrite: true);
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
}
