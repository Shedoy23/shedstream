using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Reflection.Emit;

// Offline: managed command entry points and IL only. Never instantiate a module or tick game code.
internal static class SafetyContract
{
    private static int _failures, _checks;
    private static Type _probe;
    private static void Check(bool condition, string label)
    {
        ++_checks;
        if (!condition) ++_failures;
        Console.WriteLine((condition ? "PASS " : "FAIL ") + label);
    }
    private static object Call(string name, params object[] args)
    {
        return _probe.GetMethod(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static).Invoke(null, args);
    }
    private static int Flag(string name) { return (int)_probe.GetField(name, BindingFlags.NonPublic | BindingFlags.Static).GetValue(null); }
    private static void Reset()
    {
        foreach (string name in new[] { "_used", "_requested", "_cancelled" })
            _probe.GetField(name, BindingFlags.NonPublic | BindingFlags.Static).SetValue(null, 0);
    }
    private static bool RendererType(Type type)
    {
        return type != null && type.Namespace == "TaleWorlds.Engine"
            && (type.Name == "SceneView" || type.Name == "View" || type.Name == "Camera" || type.Name == "Texture");
    }
    private static bool HasRendererReferences(Type type)
    {
        foreach (var field in type.GetFields(BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Static | BindingFlags.Instance))
            if (RendererType(field.FieldType)) return true;
        var codes = new Dictionary<ushort, OpCode>();
        foreach (var field in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static))
        {
            var code = (OpCode)field.GetValue(null);
            codes[unchecked((ushort)code.Value)] = code;
        }
        foreach (var method in type.GetMethods(BindingFlags.DeclaredOnly | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.Instance))
        {
            var body = method.GetMethodBody();
            if (body == null) continue;
            var il = body.GetILAsByteArray();
            for (int offset = 0; offset < il.Length;)
            {
                ushort key = il[offset++];
                if (key == 0xfe) key = (ushort)(0xfe00 | il[offset++]);
                OpCode code = codes[key];
                if (code.OperandType == OperandType.InlineMethod || code.OperandType == OperandType.InlineTok)
                {
                    var member = method.Module.ResolveMember(BitConverter.ToInt32(il, offset));
                    if (RendererType(member.DeclaringType) || RendererType(member as Type)) return true;
                }
                switch (code.OperandType)
                {
                    case OperandType.InlineNone: break;
                    case OperandType.ShortInlineBrTarget: case OperandType.ShortInlineI:
                    case OperandType.ShortInlineVar: offset += 1; break;
                    case OperandType.InlineVar: offset += 2; break;
                    case OperandType.InlineI8: case OperandType.InlineR: offset += 8; break;
                    case OperandType.InlineSwitch: offset += 4 + 4 * BitConverter.ToInt32(il, offset); break;
                    default: offset += 4; break;
                }
            }
        }
        foreach (var nested in type.GetNestedTypes(BindingFlags.NonPublic | BindingFlags.Public))
            if (HasRendererReferences(nested)) return true;
        return false;
    }
    public static int Main(string[] args)
    {
        string game = @"X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord";
        AppDomain.CurrentDomain.AssemblyResolve += delegate(object sender, ResolveEventArgs e)
        {
            string name = new AssemblyName(e.Name).Name + ".dll";
            foreach (string directory in new[] { Path.GetDirectoryName(args[0]), Path.Combine(game, "bin", "Win64_Shipping_Client"), Path.Combine(game, "Modules", "SandBox", "bin", "Win64_Shipping_Client"), Path.Combine(game, "Modules", "Native", "bin", "Win64_Shipping_Client") })
            {
                string path = Path.Combine(directory, name);
                if (File.Exists(path)) return Assembly.LoadFrom(path);
            }
            return null;
        };
        _probe = Assembly.LoadFrom(args[0]).GetType("ShedLink.MapExportProbe.ProbeModule", true);
        Reset();
        string answer = (string)Call("Capture", new List<string> { "confirm-after-stream" });
        Check(answer.IndexOf("unsupported", StringComparison.OrdinalIgnoreCase) >= 0, "previous crashing command is explicitly unsupported");
        Check(Flag("_requested") == 0 && Flag("_used") == 0, "photo rejection neither queues native work nor consumes data attempt");
        Check(!HasRendererReferences(_probe), "compiled module has no renderer ownership, calls or nested cleanup callbacks");
        var data = _probe.GetMethod("Data", BindingFlags.Public | BindingFlags.Static);
        Check(data != null, "separate manual data entry point exists");
        if (data != null)
        {
            Reset();
            Call("Data", new List<string> { "confirm-after-stream" });
            Check(Flag("_requested") == 0 && Flag("_used") == 0, "old photo confirmation cannot trigger data export");
            Call("Data", new List<string> { "confirm-data-only", "extra" });
            Check(Flag("_requested") == 0 && Flag("_used") == 0, "extra arguments cannot enlarge or queue export");
            Call("Data", new List<string> { "confirm-data-only" });
            Check(Flag("_requested") == 1 && Flag("_used") == 1, "explicit data confirmation queues one attempt");
            _probe.GetField("_requested", BindingFlags.NonPublic | BindingFlags.Static).SetValue(null, 0);
            Call("Data", new List<string> { "confirm-data-only" });
            Check(Flag("_requested") == 0, "second data attempt is refused");
            Call("Cancel", new List<string>());
            Check(Flag("_cancelled") == 1, "cancel flag reaches application-thread guard");
        }
        var coordinate = _probe.GetMethod("GridCoordinate", BindingFlags.NonPublic | BindingFlags.Static);
        Check(coordinate != null, "terrain grid coordinate helper exists");
        if (coordinate != null)
        {
            Check((double)Call("GridCoordinate", 62d, 790d, 0, 96) == 62d && (double)Call("GridCoordinate", 62d, 790d, 95, 96) == 790d, "grid endpoints align with campaign bounds");
            Check((double)Call("GridCoordinate", 30d, 640d, 1, 80) > 30d, "rows increase in world Y without hidden flip");
            bool rejected = false;
            try { Call("GridCoordinate", double.NaN, 790d, 0, 96); } catch (TargetInvocationException e) { rejected = e.InnerException is ArgumentException; }
            Check(rejected, "non-finite bounds are rejected");
            rejected = false;
            try { Call("GridCoordinate", 62d, 790d, 96, 96); } catch (TargetInvocationException e) { rejected = e.InnerException is ArgumentException; }
            Check(rejected, "grid index cannot exceed grid size");
            rejected = false;
            try { Call("GridCoordinate", 62d, 790d, 0, 100000); } catch (TargetInvocationException e) { rejected = e.InnerException is ArgumentException; }
            Check(rejected, "grid size cannot exceed hard cap");
        }
        var rows = _probe.GetMethod("GridRows", BindingFlags.NonPublic | BindingFlags.Static);
        Check(rows != null, "grid rows helper exists");
        if (rows != null)
        {
            Check((int)Call("GridRows", 62d, 790d, 30d, 640d) == 80, "Calradia bounds give 96x80 grid (aspect kept)");
            Check((int)Call("GridRows", 0d, 10d, 0d, 100000d) == 128, "tall map is capped at 128 rows (export stays bounded)");
            Check((int)Call("GridRows", 0d, 100000d, 0d, 1d) == 2, "flat map keeps at least two rows (endpoints)");
            bool rejected = false;
            try { Call("GridRows", 0d, double.PositiveInfinity, 0d, 1d); } catch (TargetInvocationException e) { rejected = e.InnerException is ArgumentException; }
            Check(rejected, "infinite bounds are rejected before sizing the grid");
        }
        Console.WriteLine("Checks " + _checks + ", failures " + _failures + "; no game instance/ticks/native calls executed.");
        return _failures == 0 ? 0 : 1;
    }
}
