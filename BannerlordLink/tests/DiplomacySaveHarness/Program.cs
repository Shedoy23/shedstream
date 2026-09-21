using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.Serialization;
using TaleWorlds.SaveSystem;

internal static class Program
{
    static int Main(string[] args)
    {
        if (args.Length != 2) { Console.Error.WriteLine("Usage: DiplomacySaveHarness <BannerlordLink.dll> <game directory>"); return 2; }
        string game = args[1];
        string[] dirs = {
            Path.GetDirectoryName(Path.GetFullPath(args[0])),
            Path.Combine(game, "bin", "Win64_Shipping_Client"),
            Path.Combine(game, "Modules", "Native", "bin", "Win64_Shipping_Client"),
            Path.Combine(game, "Modules", "SandBox", "bin", "Win64_Shipping_Client"),
            @"X:\SteamLibrary\steamapps\workshop\content\261550\2859188632\bin\Win64_Shipping_Client"
        };
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
            string name = new AssemblyName(e.Name).Name + ".dll";
            string file = dirs.Select(d => Path.Combine(d, name)).FirstOrDefault(File.Exists);
            return file == null ? null : Assembly.LoadFrom(file);
        };
        try {
            // The game has these assemblies loaded before it discovers save definers.
            foreach (string name in new[] { "TaleWorlds.Library", "TaleWorlds.ObjectSystem", "TaleWorlds.Core", "TaleWorlds.CampaignSystem" })
                Assembly.LoadFrom(Path.Combine(dirs[1], name + ".dll"));
            return Run(Assembly.LoadFrom(Path.GetFullPath(args[0])));
        }
        catch (Exception e) { Console.Error.WriteLine(e); return 1; }
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    static int Run(Assembly mod)
    {
        int failures = 0;
        foreach (string name in new[] { "ViewerDeclareWarDecision", "ViewerMakePeaceDecision" })
        {
            Type type = mod.GetType("BannerlordLink.Actions." + name, true);
            // No campaign/native engine startup: inherited reference fields remain null.
            // This still exercises the exact runtime-type lookup that broke real saves.
            object decision = FormatterServices.GetUninitializedObject(type);
            var metadata = new MetaData();
            metadata.Add("ApplicationVersion", "v1.4.8.0");
            var driver = new InMemDriver();
            var saved = SaveManager.Save(decision, metadata, name, driver);
            if (!saved.Successful)
            {
                Console.WriteLine("FAIL " + name + ": " + string.Join("; ", saved.Errors.Select(e => e.Message)));
                failures++;
                continue;
            }
            var loaded = SaveManager.Load(name, driver);
            bool ok = loaded.Successful && loaded.Root.GetType() == type;
            Console.WriteLine((ok ? "PASS " : "FAIL ") + name + " real SaveManager save/load preserves runtime type");
            if (!ok) failures++;
        }
        return failures == 0 ? 0 : 1;
    }
}
