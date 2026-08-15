namespace ShedLink.Manager.Core.Detection;

public enum DetectionSource
{
    Steam,
    Manual,
}

public sealed record GameInstallation(
    string GameId,
    string RootPath,
    DetectionSource Source);
