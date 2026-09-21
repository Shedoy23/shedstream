"""Exercise actual snapshot publisher with a controlled backend, no running game."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
source=(root/'BannerlordLink/src/Behaviors/TournamentQueueBehavior.cs').read_text(encoding='utf-8')
start=source.index('        public void PublishQueue()')
end=source.index('        private void TickQueue',start)
harness=r'''using System;
using System.Linq;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
class Hero { public bool IsAlive=true; }
class Entry { public string Username; public Hero Hero=new Hero(); public int EntryFee=0; }
class Campaign { public static Campaign Current=new Campaign(); public string UniqueGameId="save-a"; }
class EquipmentShopBehavior { public static EquipmentShopBehavior Instance=new EquipmentShopBehavior(); public string SessionId="session-a"; }
class JsonConvert { public static object Captured; public static string SerializeObject(object value){Captured=value;return "snapshot";} }
class Backend {
 public int Calls; public TaskCompletionSource<bool> Pending=new TaskCompletionSource<bool>();
 public Task<bool> PostEventAsync(string module,string kind,string payload){if(kind!="tournament.queue_snapshot")throw new Exception("wrong event");Interlocked.Increment(ref Calls);return Pending.Task;}
}
class BannerlordLinkModule { public static Backend Backend=new Backend(); public static void Log(string message){} }
class Queue {
 readonly List<Entry> _queue=new List<Entry>();
 readonly Stopwatch _queueRefresh=Stopwatch.StartNew();
 long _queueSequence; bool _sessionLaunched; volatile bool _publishingQueue;
 public void Launch(){_sessionLaunched=true;}
 public void Add(string user){_queue.Add(new Entry{Username=user});}
 public void Clear(){_queue.Clear();}
 public bool Busy=>_publishingQueue;
 METHOD
}
class Program {
 static object Field(object obj,string name)=>obj.GetType().GetProperty(name).GetValue(obj);
 static void Check(bool condition,string message){if(!condition)throw new Exception(message);}
 static void Idle(Queue q){Check(SpinWait.SpinUntil(()=>!q.Busy,3000),"publisher remained stuck");}
 static int Main(){try{
 var q=new Queue();var backend=BannerlordLinkModule.Backend;
 q.PublishQueue();Check(backend.Calls==0,"sent before save loaded");
 q.Add("saved-viewer");q.Launch();q.PublishQueue();
 Check(SpinWait.SpinUntil(()=>backend.Calls==1,3000),"restored queue not published");
 var captured=JsonConvert.Captured;
 q.Clear();q.PublishQueue();Check(backend.Calls==1,"concurrent send");
 Check(((Array)Field(captured,"entries")).Length==1,"captured snapshot mutated after queue changed");
 Check((string)Field(captured,"save_id")=="save-a" && (string)Field(captured,"equipment_session_id")=="session-a","missing fences");
 backend.Pending.SetException(new Exception("offline"));Idle(q);
 backend.Pending=new TaskCompletionSource<bool>();q.PublishQueue();
 Check(SpinWait.SpinUntil(()=>backend.Calls==2,3000),"failed send did not allow retry");
 Check(((Array)Field(JsonConvert.Captured,"entries")).Length==0,"empty queue was not published");
 Check((long)Field(JsonConvert.Captured,"queue_seq")==2,"retry must have newer sequence");
 backend.Pending.SetResult(false);Idle(q);
 backend.Pending=new TaskCompletionSource<bool>();q.PublishQueue();
 Check(SpinWait.SpinUntil(()=>backend.Calls==3,3000),"negative ACK did not allow retry");
 backend.Pending.SetResult(true);Idle(q);
 Console.WriteLine("PASS queue publisher: loaded save gate, snapshot capture, single flight, failed/negative ACK retry, empty queue, session and sequence");return 0;
 }catch(Exception e){Console.Error.WriteLine(e.Message);return 1;}}
}
'''.replace('METHOD',source[start:end])
with tempfile.TemporaryDirectory(prefix='tournament-publish-') as tmp:
 folder=Path(tmp)
 (folder/'Publish.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net472</TargetFramework><LangVersion>latest</LangVersion></PropertyGroup></Project>')
 (folder/'Program.cs').write_text(harness,encoding='utf-8')
 result=subprocess.run(['dotnet','build',str(folder/'Publish.csproj'),'-v:q'],capture_output=True,text=True)
 if result.returncode:
  print(result.stdout,result.stderr);raise SystemExit(result.returncode)
 raise SystemExit(subprocess.run([str(folder/'bin/Debug/net472/Publish.exe')]).returncode)
