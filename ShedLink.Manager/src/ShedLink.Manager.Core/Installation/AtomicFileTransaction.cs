using System.Text.Json;

namespace ShedLink.Manager.Core.Installation;

/// <summary>Crash-safe replacement of one managed file without touching its neighbours.</summary>
public static class AtomicFileTransaction
{
    public static AtomicFileReplacement Prepare(
        string source,
        string target,
        string allowedRoot,
        Action<string>? failpoint = null)
    {
        source = Path.GetFullPath(source);
        if (!File.Exists(source) || IsReparsePoint(source))
        {
            throw new InvalidDataException("Installation source file is missing or unsafe.");
        }
        target = PathBoundary.Within(target, allowedRoot);
        if (Directory.Exists(target) || File.Exists(target) && IsReparsePoint(target))
        {
            throw new InvalidDataException("Installation target file is unsafe.");
        }
        Recover(target, allowedRoot);
        var (stage, backup, journal) = Paths(target, allowedRoot);
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        Delete(stage);
        Delete(backup);
        try
        {
            File.Copy(source, stage, overwrite: false);
            Write(journal, "prepared");
            failpoint?.Invoke("prepared");
            if (File.Exists(target))
            {
                File.Move(target, backup);
            }
            Write(journal, "backed_up");
            failpoint?.Invoke("backed_up");
            File.Move(stage, target);
            Write(journal, "installed");
            failpoint?.Invoke("installed");
            return new AtomicFileReplacement(target, allowedRoot);
        }
        catch
        {
            Recover(target, allowedRoot);
            throw;
        }
    }

    public static AtomicFileReplacement? PrepareRemoval(string target, string allowedRoot)
    {
        target = PathBoundary.Within(target, allowedRoot);
        Recover(target, allowedRoot);
        if (!File.Exists(target)) return null;
        if (IsReparsePoint(target)) throw new InvalidDataException("Installation target file is unsafe.");
        var (_, backup, journal) = Paths(target, allowedRoot);
        Delete(backup);
        Write(journal, "prepared");
        File.Move(target, backup);
        Write(journal, "backed_up");
        return new AtomicFileReplacement(target, allowedRoot);
    }

    public static bool Complete(string target, string allowedRoot)
    {
        var (stage, backup, journal) = Paths(PathBoundary.Within(target, allowedRoot), allowedRoot);
        if (!File.Exists(journal)) return false;
        Delete(stage); Delete(backup); Delete(journal); Delete(journal + ".tmp");
        return true;
    }

    public static bool Recover(string target, string allowedRoot)
    {
        target = PathBoundary.Within(target, allowedRoot);
        var (stage, backup, journal) = Paths(target, allowedRoot);
        if (!File.Exists(journal)) return false;
        string? phase = null;
        try { phase = JsonSerializer.Deserialize<Journal>(File.ReadAllText(journal))?.Phase; }
        catch (JsonException) { }
        if (File.Exists(backup))
        {
            Delete(target);
            File.Move(backup, target);
        }
        else if (phase is "backed_up" or "installed")
        {
            Delete(target);
        }
        Delete(stage); Delete(journal); Delete(journal + ".tmp");
        return true;
    }

    private static (string Stage, string Backup, string Journal) Paths(string target, string root)
    {
        var parent = Path.GetDirectoryName(target)!;
        var name = Path.GetFileName(target);
        return (
            PathBoundary.Within(Path.Combine(parent, $".{name}.shedlink-stage"), root),
            PathBoundary.Within(Path.Combine(parent, $".{name}.shedlink-backup"), root),
            PathBoundary.Within(Path.Combine(parent, $".{name}.shedlink-transaction.json"), root));
    }

    private static void Write(string path, string phase)
    {
        File.WriteAllText(path + ".tmp", JsonSerializer.Serialize(new Journal(phase)));
        File.Move(path + ".tmp", path, overwrite: true);
    }

    private static void Delete(string path) { if (File.Exists(path)) File.Delete(path); }
    private static bool IsReparsePoint(string path) =>
        (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0;
    private sealed record Journal(string Phase);
}

public sealed class AtomicFileReplacement : IAtomicReplacement
{
    private readonly string _target;
    private readonly string _root;
    private bool _finished;
    internal AtomicFileReplacement(string target, string root) { _target = target; _root = root; }
    public void Commit() { if (!_finished) AtomicFileTransaction.Complete(_target, _root); _finished = true; }
    public void Rollback() { if (!_finished) AtomicFileTransaction.Recover(_target, _root); _finished = true; }
    public void Dispose() => Rollback();
}
