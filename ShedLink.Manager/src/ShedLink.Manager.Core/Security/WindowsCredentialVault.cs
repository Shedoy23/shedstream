using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;

namespace ShedLink.Manager.Core.Security;

public sealed class WindowsCredentialVault : ICredentialVault
{
    private const int CredentialTypeGeneric = 1;
    private const int PersistenceLocalMachine = 2;
    private const int ErrorNotFound = 1168;
    private const int MaxBlobBytes = 2560;
    private readonly string _prefix;

    public WindowsCredentialVault(string application = "ShedLink.Manager")
    {
        if (!OperatingSystem.IsWindows())
        {
            throw new PlatformNotSupportedException(
                "Windows Credential Manager is available only on Windows.");
        }
        _prefix = NormalizeSegment(application);
    }

    public void Write(string key, string secret)
    {
        ArgumentNullException.ThrowIfNull(secret);
        var bytes = Encoding.Unicode.GetByteCount(secret);
        if (bytes > MaxBlobBytes)
        {
            throw new ArgumentOutOfRangeException(nameof(secret), "Credential is too large.");
        }

        var blob = Marshal.StringToCoTaskMemUni(secret);
        try
        {
            var credential = new NativeCredential
            {
                Type = CredentialTypeGeneric,
                TargetName = Target(key),
                CredentialBlobSize = bytes,
                CredentialBlob = blob,
                Persist = PersistenceLocalMachine,
                UserName = Environment.UserName,
            };
            if (!CredWrite(ref credential, 0))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
        }
        finally
        {
            Marshal.ZeroFreeCoTaskMemUnicode(blob);
        }
    }

    public string? Read(string key)
    {
        if (!CredRead(Target(key), CredentialTypeGeneric, 0, out var pointer))
        {
            var error = Marshal.GetLastWin32Error();
            if (error == ErrorNotFound)
            {
                return null;
            }
            throw new Win32Exception(error);
        }
        try
        {
            var credential = Marshal.PtrToStructure<NativeCredential>(pointer);
            return credential.CredentialBlobSize == 0
                ? string.Empty
                : Marshal.PtrToStringUni(
                    credential.CredentialBlob,
                    credential.CredentialBlobSize / sizeof(char));
        }
        finally
        {
            CredFree(pointer);
        }
    }

    public bool Delete(string key)
    {
        if (CredDelete(Target(key), CredentialTypeGeneric, 0))
        {
            return true;
        }
        var error = Marshal.GetLastWin32Error();
        if (error == ErrorNotFound)
        {
            return false;
        }
        throw new Win32Exception(error);
    }

    private string Target(string key) => $"{_prefix}/{NormalizeSegment(key)}";

    private static string NormalizeSegment(string value)
    {
        value = (value ?? string.Empty).Trim();
        if (value.Length is < 1 or > 180 || value.Any(c => c < 32 || c is '/' or '\\'))
        {
            throw new ArgumentException("Credential key contains invalid characters.");
        }
        return value;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct NativeCredential
    {
        public int Flags;
        public int Type;
        public string TargetName;
        public string? Comment;
        public long LastWritten;
        public int CredentialBlobSize;
        public IntPtr CredentialBlob;
        public int Persist;
        public int AttributeCount;
        public IntPtr Attributes;
        public string? TargetAlias;
        public string UserName;
    }

    [DllImport("advapi32.dll", EntryPoint = "CredWriteW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredWrite(ref NativeCredential credential, int flags);

    [DllImport("advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredRead(
        string target,
        int type,
        int reservedFlag,
        out IntPtr credentialPtr);

    [DllImport("advapi32.dll", EntryPoint = "CredDeleteW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredDelete(string target, int type, int flags);

    [DllImport("advapi32.dll")]
    private static extern void CredFree(IntPtr credential);
}
