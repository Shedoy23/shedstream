using System.Diagnostics;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace ShedLink.Manager.Core.Detection;

public sealed partial class RimWorldDetectionService
{
    private const string SteamAppId = "294100";

    public GameInstallation? Detect(IEnumerable<string>? steamRoots = null)
    {
        var roots = steamRoots ?? DiscoverSteamRoots();
        foreach (var library in ExpandLibraryRoots(roots))
        {
            var manifest = Path.Combine(
                library, "steamapps", $"appmanifest_{SteamAppId}.acf");
            var candidate = Path.Combine(library, "steamapps", "common", "RimWorld");
            if (File.Exists(manifest) && IsValidGameRoot(candidate))
            {
                return new GameInstallation("rimworld", Path.GetFullPath(candidate), DetectionSource.Steam);
            }
        }
        return null;
    }

    public GameInstallation ValidateManual(string path)
    {
        if (!IsValidGameRoot(path))
        {
            throw new InvalidDataException(
                "В выбранной папке не найдены RimWorldWin64.exe и папка Mods.");
        }
        return new GameInstallation(
            "rimworld", Path.GetFullPath(path), DetectionSource.Manual);
    }

    public bool IsGameRunning() =>
        Process.GetProcessesByName("RimWorldWin64").Length > 0;

    public static bool IsValidGameRoot(string? path) =>
        !string.IsNullOrWhiteSpace(path) &&
        File.Exists(Path.Combine(path, "RimWorldWin64.exe")) &&
        Directory.Exists(Path.Combine(path, "Mods"));

    private static IEnumerable<string> DiscoverSteamRoots()
    {
        var found = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        AddRegistryValue(found, Registry.CurrentUser, @"SOFTWARE\Valve\Steam", "SteamPath");
        AddRegistryValue(found, Registry.LocalMachine, @"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath");
        var conventional = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Steam");
        if (Directory.Exists(conventional))
        {
            found.Add(conventional);
        }
        return found;
    }

    private static void AddRegistryValue(
        HashSet<string> target,
        RegistryKey hive,
        string subkey,
        string valueName)
    {
        try
        {
            using var key = hive.OpenSubKey(subkey);
            if (key?.GetValue(valueName) is string value && Directory.Exists(value))
            {
                target.Add(value);
            }
        }
        catch (Exception exception) when (
            exception is UnauthorizedAccessException or IOException or System.Security.SecurityException)
        {
            // Missing/locked registry data is a normal detection miss; manual selection remains available.
        }
    }

    private static IEnumerable<string> ExpandLibraryRoots(IEnumerable<string> roots)
    {
        var libraries = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var rootValue in roots)
        {
            if (string.IsNullOrWhiteSpace(rootValue))
            {
                continue;
            }
            var root = Path.GetFullPath(rootValue);
            libraries.Add(root);
            var vdf = Path.Combine(root, "steamapps", "libraryfolders.vdf");
            if (!File.Exists(vdf))
            {
                continue;
            }
            try
            {
                var text = File.ReadAllText(vdf);
                foreach (Match match in LibraryPathRegex().Matches(text))
                {
                    var path = match.Groups[1].Value.Replace("\\\\", "\\");
                    if (Directory.Exists(path))
                    {
                        libraries.Add(Path.GetFullPath(path));
                    }
                }
            }
            catch (IOException)
            {
                // Steam can rewrite the VDF while Manager reads it; this root is simply skipped.
            }
        }
        return libraries;
    }

    [GeneratedRegex("\\\"path\\\"\\s+\\\"([^\\\"]+)\\\"", RegexOptions.IgnoreCase)]
    private static partial Regex LibraryPathRegex();
}
