using ShedLink.Manager.Core.Installation;

namespace ShedLink.Manager.Core.Detection;

/// <summary>
/// Temporary shim: the detection logic now lives in <see cref="GameDetectionService"/>
/// and is driven by the installation manifest. This keeps the current single-game
/// UI compiling until it passes the manifest itself, and it is the last place in
/// Core that names RimWorld. Delete it with that change.
/// </summary>
public sealed class RimWorldDetectionService
{
    internal static readonly ManifestGame Descriptor = new()
    {
        Id = "rimworld",
        DisplayName = "RimWorld",
        SupportedVersions = new[] { "1.5", "1.6" },
        ProcessNames = new[] { "RimWorldWin64" },
        Version = new GameVersionSource
        {
            Kind = "text_file",
            Path = "Version.txt",
            CompatibilityPattern = @"^\d+\.\d+",
        },
        Detection = new GameDetectionRule[]
        {
            new() { Kind = "steam", AppId = 294100, InstallDir = "RimWorld" },
            new()
            {
                Kind = "manual",
                RequiredPaths = new[] { "RimWorldWin64.exe", "Mods" },
            },
        },
    };

    private static readonly GameDetectionService Service = new(Descriptor);

    public GameInstallation? Detect(IEnumerable<string>? steamRoots = null) =>
        Service.Detect(steamRoots);

    public GameInstallation ValidateManual(string path) => Service.ValidateManual(path);

    public bool IsGameRunning() => Service.IsGameRunning();

    public static bool IsValidGameRoot(string? path) => Service.IsValidGameRoot(path);
}
