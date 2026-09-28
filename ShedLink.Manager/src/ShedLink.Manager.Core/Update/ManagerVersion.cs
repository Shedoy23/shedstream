namespace ShedLink.Manager.Core.Update;

/// <summary>
/// Compares Manager versions such as <c>0.1.0-alpha.2</c>. Build metadata after
/// <c>+</c> is ignored; a release outranks any pre-release of the same numbers.
/// </summary>
public static class ManagerVersion
{
    public static bool IsValid(string? version) => TryParse(version, out _, out _);

    /// <summary>Positive when <paramref name="left"/> is newer.</summary>
    public static int Compare(string left, string right)
    {
        if (!TryParse(left, out var leftCore, out var leftPre) ||
            !TryParse(right, out var rightCore, out var rightPre))
        {
            throw new InvalidDataException("Cannot compare malformed manager versions.");
        }
        var core = leftCore.CompareTo(rightCore);
        if (core != 0)
        {
            return core;
        }
        if (leftPre.Length == 0 || rightPre.Length == 0)
        {
            // "1.0.0" is newer than "1.0.0-alpha.1"; equal when both are releases.
            return rightPre.Length.CompareTo(leftPre.Length);
        }
        return ComparePrerelease(leftPre, rightPre);
    }

    /// <summary>
    /// Dot-separated identifiers, numeric ones compared as numbers: otherwise
    /// "alpha.10" would rank below "alpha.2" and updates would stop being offered
    /// after the ninth build.
    /// </summary>
    private static int ComparePrerelease(string left, string right)
    {
        var leftParts = left.Split('.');
        var rightParts = right.Split('.');
        for (var index = 0; index < Math.Min(leftParts.Length, rightParts.Length); index++)
        {
            var leftPart = leftParts[index];
            var rightPart = rightParts[index];
            int comparison;
            if (int.TryParse(leftPart, out var leftNumber) &&
                int.TryParse(rightPart, out var rightNumber))
            {
                comparison = leftNumber.CompareTo(rightNumber);
            }
            else
            {
                comparison = string.CompareOrdinal(leftPart, rightPart);
            }
            if (comparison != 0)
            {
                return comparison;
            }
        }
        return leftParts.Length.CompareTo(rightParts.Length);
    }

    private static bool TryParse(string? version, out Version core, out string prerelease)
    {
        core = new Version(0, 0);
        prerelease = string.Empty;
        if (string.IsNullOrWhiteSpace(version))
        {
            return false;
        }
        var text = version.Split('+', 2)[0];
        var parts = text.Split('-', 2);
        if (!Version.TryParse(parts[0], out var parsed))
        {
            return false;
        }
        if (parts.Length == 2)
        {
            if (string.IsNullOrWhiteSpace(parts[1]))
            {
                return false;
            }
            prerelease = parts[1];
        }
        core = parsed;
        return true;
    }
}
