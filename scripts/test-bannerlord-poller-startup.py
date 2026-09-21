"""Execute the actual module startup block with a controllable network probe."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'BannerlordLink/src/BannerlordLinkModule.cs').read_text(encoding='utf-8')
start = source.index('                Config = BackendConfig.LoadOrCreate(Log);')
end = source.index('\n            catch (Exception ex)', start)
block = source[start:end].rsplit('}', 1)[0]
harness = r'''
using System;
using System.Threading.Tasks;
class BackendConfig {
 public static string Token="configured";
 public string ModuleToken=Token;
 public static BackendConfig LoadOrCreate(Action<string> log)=>new BackendConfig();
}
class BackendClient {
 public static TaskCompletionSource<bool> Probe;
 public BackendClient(BackendConfig config,Action<string> log){}
 public Task<bool> PingAsync()=>Probe.Task;
 public Task<bool> PostEventAsync(string module,string kind,string data)=>Task.FromResult(false);
}
class ActionRegistry { public static int Registered; public static void RegisterDefaults(){Registered++;} }
class ActionPoller {
 public static int Started;
 public ActionPoller(BackendClient client,string module,Action<string> log){}
 public void Start(){if(ActionRegistry.Registered==0)throw new Exception("handlers missing");Started++;}
}
class PowerCache { public static Task RefreshAsync(BackendClient backend)=>Task.CompletedTask; }
class Module {
 BackendConfig Config; BackendClient Backend; ActionPoller Poller;
 const string MOD_VERSION="test";
 void Log(string message){}
 public void Start(){ STARTUP_BLOCK }
}
class Program {
 static int Main(){
  try {
   BackendClient.Probe=new TaskCompletionSource<bool>();
   new Module().Start();
   if(ActionPoller.Started!=1)throw new Exception("poller must start even while initial connectivity probe is unavailable");
   BackendClient.Probe.SetResult(false);
   Task.Delay(50).Wait();
   if(ActionPoller.Started!=1)throw new Exception("failed probe must not disable or duplicate polling");
   BackendClient.Probe=new TaskCompletionSource<bool>();
   new Module().Start();BackendClient.Probe.SetResult(true);Task.Delay(50).Wait();
   if(ActionPoller.Started!=2)throw new Exception("failed handshake must not disable polling");
   BackendConfig.Token="";BackendClient.Probe=new TaskCompletionSource<bool>();
   new Module().Start();BackendClient.Probe.SetResult(true);Task.Delay(50).Wait();
   if(ActionPoller.Started!=2)throw new Exception("unconfigured module must not start polling");
   Console.WriteLine("PASS startup: unavailable probe, failed probe, failed handshake, missing token, handlers before polling");return 0;
  }catch(Exception e){Console.Error.WriteLine(e.Message);return 1;}
 }
}
'''.replace('STARTUP_BLOCK', block)
with tempfile.TemporaryDirectory(prefix='bannerlord-poll-start-') as tmp:
    folder = Path(tmp)
    (folder/'Startup.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net472</TargetFramework><LangVersion>latest</LangVersion></PropertyGroup></Project>')
    (folder/'Program.cs').write_text(harness, encoding='utf-8')
    result = subprocess.run(['dotnet', 'build', str(folder/'Startup.csproj'), '-v:q'], capture_output=True, text=True)
    if result.returncode:
        print(result.stdout, result.stderr)
        raise SystemExit(result.returncode)
    raise SystemExit(subprocess.run([str(folder/'bin/Debug/net472/Startup.exe')]).returncode)
