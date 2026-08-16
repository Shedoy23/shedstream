using System.Diagnostics;
using System.Text.RegularExpressions;
using Microsoft.Win32;
using ShedLink.Manager.Core.Installation;

namespace ShedLink.Manager.Core.Detection;

/// <summary>
/// Finds a game from what its installation manifest declares. Nothing here knows
/// which game it is looking at: adding a game is a manifest, not a code change.
/// </summary>
public sealed partial class GameDetectionService
{
    private readonly ManifestGame _game;

    public GameDetectionService(ManifestGame game)
    {
        _game = game;
    }

    public GameInstallation? Detect(IEnumerable<string>? steamRoots = null)
    {
        var steamRules = Rules("steam")
            .Where(rule => rule.AppId is > 0 && !string.IsNullOrWhiteSpace(rule.InstallDir));
        var roots = steamRoots ?? DiscoverSteamRoots();
        var libraries = ExpandLibraryRoots(roots).ToArray();
        foreach (var rule in steamRules)
        {
            foreach (var library in libraries)
            {
                var stamp = Path.Combine(
                    library, "steamapps", $"appmanifest_{rule.AppId}.acf");
                var candidate = Path.Combine(
                    library, "steamapps", "common", rule.InstallDir!);
                if (File.Exists(stamp) && IsValidGameRoot(candidate))
                {
                    return new GameInstallation(
                        _game.Id, Path.GetFullPath(candidate), DetectionSource.Steam);
                }
            }
        }
        return null;
    }

    public GameInstallation ValidateManual(string path)
    {
        if (!IsValidGameRoot(path))
        {
            throw new InvalidDataException(
                $"В выбранной папке не найдены обязательные файлы {_game.DisplayName}: " +
                string.Join(", ", RequiredPaths()) + ".");
        }
        return new GameInstallation(
            _game.Id, Path.GetFullPath(path), DetectionSource.Manual);
    }

    public bool IsGameRunning() =>
        (_game.ProcessNames ?? Array.Empty<string>())
            .Any(name => Process.GetProcessesByName(name).Length > 0);

    public bool IsValidGameRoot(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return false;
        }
        var required = RequiredPaths();
        if (required.Count == 0)
        {
            // Without declared evidence any folder would pass; refuse instead.
            return false;
        }
        return required.All(relative =>
        {
            var full = Path.Combine(path, relative);
            return File.Exists(full) || Directory.Exists(full);
        });
    }

    public DetectedGameVersion? DetectVersion(string gameRoot)
    {
        var source = _game.Version;
        if (source is null || source.Kind != "text_file")
        {
            return null;
        }
        var path = Path.Combine(gameRoot, source.Path);
        if (!File.Exists(path))
        {
            return null;
        }
        string? fullVersion;
        try
        {
            fullVersion = File.ReadLines(path)
                .Select(line => line.Trim())
                .FirstOrDefault(line => line.Length > 0);
        }
        catch (IOException)
        {
            return null;
        }
        if (fullVersion is null)
        {
            return null;
        }
        Match match;
        try
        {
            match = Regex.Match(
                fullVersion,
                source.CompatibilityPattern,
                RegexOptions.CultureInvariant,
                TimeSpan.FromSeconds(1));
        }
        catch (Exception exception) when (
            exception is ArgumentException or RegexMatchTimeoutException)
        {
            return null;
        }
        return match.Success
            ? new DetectedGameVersion(fullVersion, match.Value)
            : null;
    }

    private IReadOnlyList<string> RequiredPaths() =>
        Rules("manual")
            .SelectMany(rule => rule.RequiredPaths ?? Array.Empty<string>())
            .Where(path => !string.IsNullOrWhiteSpace(path))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();

    private IEnumerable<GameDetectionRule> Rules(string kind) =>
        (_game.Detection ?? Array.Empty<GameDetectionRule>())
            .Where(rule => rule.Kind == kind);

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
