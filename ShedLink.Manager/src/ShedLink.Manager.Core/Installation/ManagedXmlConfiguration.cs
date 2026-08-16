using System.Xml.Linq;

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

    public static ManagedConfigurationUpdate PrepareWrite(
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

        return ManagedConfiguration.PrepareWrite(
            path,
            temporary => document.Save(temporary, SaveOptions.DisableFormatting));
    }

    public static bool Complete(string path) => ManagedConfiguration.Complete(path);

    public static bool Recover(string path) => ManagedConfiguration.Recover(path);

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
}
