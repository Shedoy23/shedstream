using System.Text.Json;

namespace ShedLink.Manager.Core.Installation;

public static class AtomicDirectoryTransaction
{
    public static void Replace(
        string source,
        string target,
        string allowedRoot,
        Action<string> verify,
        Action<string>? failpoint = null)
    {
        using var replacement = Prepare(source, target, allowedRoot, verify, failpoint);
        replacement.Commit();
    }

    public static AtomicDirectoryReplacement Prepare(
        string source,
        string target,
        string allowedRoot,
        Action<string> verify,
        Action<string>? failpoint = null)
    {
        source = Path.GetFullPath(source);
        if (!Directory.Exists(source) || IsReparsePoint(source))
        {
            throw new InvalidDataException("Installation source is missing or unsafe.");
        }
        target = PathBoundary.Within(target, allowedRoot);
        if (Directory.Exists(target) && IsReparsePoint(target))
        {
            throw new InvalidDataException("Installation target cannot be a reparse point.");
        }
        var (stage, backup, journal) = TransactionPaths(target, allowedRoot);
        Recover(target, allowedRoot);
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        DeleteTree(stage);
        DeleteTree(backup);

        try
        {
            CopyTree(source, stage);
            verify(stage);
            WritePhase(journal, "prepared");
            failpoint?.Invoke("prepared");

            if (Directory.Exists(target))
            {
                Directory.Move(target, backup);
            }
            WritePhase(journal, "backed_up");
            failpoint?.Invoke("backed_up");

            Directory.Move(stage, target);
            WritePhase(journal, "installed");
            failpoint?.Invoke("installed");
            return new AtomicDirectoryReplacement(target, allowedRoot);
        }
        catch
        {
            if (!Recover(target, allowedRoot))
            {
                DeleteTree(stage);
            }
            throw;
        }
    }

    public static AtomicDirectoryReplacement? PrepareRemoval(
        string target,
        string allowedRoot,
        Action<string>? failpoint = null)
    {
        target = PathBoundary.Within(target, allowedRoot);
        Recover(target, allowedRoot);
        if (!Directory.Exists(target))
        {
            return null;
        }
        if (IsReparsePoint(target))
        {
            throw new InvalidDataException("Installation target cannot be a reparse point.");
        }
        var (stage, backup, journal) = TransactionPaths(target, allowedRoot);
        DeleteTree(stage);
        DeleteTree(backup);
        try
        {
            WritePhase(journal, "prepared");
            Directory.Move(target, backup);
            WritePhase(journal, "backed_up");
            failpoint?.Invoke("removed");
            return new AtomicDirectoryReplacement(target, allowedRoot);
        }
        catch
        {
            Recover(target, allowedRoot);
            throw;
        }
    }

    public static bool Complete(string target, string allowedRoot)
    {
        target = PathBoundary.Within(target, allowedRoot);
        var (stage, backup, journal) = TransactionPaths(target, allowedRoot);
        if (!File.Exists(journal))
        {
            return false;
        }
        DeleteTree(stage);
        DeleteTree(backup);
        File.Delete(journal);
        File.Delete(journal + ".tmp");
        return true;
    }

    public static bool Recover(string target, string allowedRoot)
    {
        target = PathBoundary.Within(target, allowedRoot);
        var (stage, backup, journal) = TransactionPaths(target, allowedRoot);
        if (!File.Exists(journal))
        {
            return false;
        }
        string? phase = null;
        try
        {
            phase = JsonSerializer.Deserialize<TransactionJournal>(
                File.ReadAllText(journal))?.Phase;
        }
        catch (JsonException)
        {
            // A corrupted journal still prefers the intact backup below.
        }

        if (Directory.Exists(backup))
        {
            DeleteTree(target);
            Directory.Move(backup, target);
        }
        else if (phase is "backed_up" or "installed")
        {
            DeleteTree(target);
        }
        DeleteTree(stage);
        File.Delete(journal);
        File.Delete(journal + ".tmp");
        return true;
    }

    private static (string Stage, string Backup, string Journal) TransactionPaths(
        string target,
        string allowedRoot)
    {
        var parent = Path.GetDirectoryName(target)!;
        var name = Path.GetFileName(target);
        return (
            PathBoundary.Within(Path.Combine(parent, $".{name}.shedlink-stage"), allowedRoot),
            PathBoundary.Within(Path.Combine(parent, $".{name}.shedlink-backup"), allowedRoot),
            PathBoundary.Within(Path.Combine(parent, $".{name}.shedlink-transaction.json"), allowedRoot));
    }

    private static void WritePhase(string journal, string phase)
    {
        var temporary = journal + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(new TransactionJournal(phase)));
        File.Move(temporary, journal, overwrite: true);
    }

    private static void CopyTree(string source, string destination)
    {
        Directory.CreateDirectory(destination);
        foreach (var directory in Directory.EnumerateDirectories(source))
        {
            if (IsReparsePoint(directory))
            {
                throw new InvalidDataException("Installation source contains a reparse point.");
            }
            CopyTree(directory, Path.Combine(destination, Path.GetFileName(directory)));
        }
        foreach (var file in Directory.EnumerateFiles(source))
        {
            if (IsReparsePoint(file))
            {
                throw new InvalidDataException("Installation source contains a reparse point.");
            }
            var output = Path.Combine(destination, Path.GetFileName(file));
            File.Copy(file, output, overwrite: false);
        }
    }

    private static bool IsReparsePoint(string path) =>
        (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0;

    private static void DeleteTree(string path)
    {
        if (Directory.Exists(path))
        {
            Directory.Delete(path, recursive: !IsReparsePoint(path));
        }
    }

    private sealed record TransactionJournal(
        [property: System.Text.Json.Serialization.JsonPropertyName("phase")] string Phase);
}

public sealed class AtomicDirectoryReplacement : IDisposable
{
    private readonly string _target;
    private readonly string _allowedRoot;
    private bool _finished;

    internal AtomicDirectoryReplacement(string target, string allowedRoot)
    {
        _target = target;
        _allowedRoot = allowedRoot;
    }

    public void Commit()
    {
        if (_finished)
        {
            return;
        }
        AtomicDirectoryTransaction.Complete(_target, _allowedRoot);
        _finished = true;
    }

    public void Rollback()
    {
        if (_finished)
        {
            return;
        }
        AtomicDirectoryTransaction.Recover(_target, _allowedRoot);
        _finished = true;
    }

    public void Dispose() => Rollback();
}
