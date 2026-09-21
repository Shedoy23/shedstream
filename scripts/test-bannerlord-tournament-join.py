"""Execute the production queue insertion method; repeated joins are idempotent."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
source=(root/'BannerlordLink/src/Behaviors/TournamentQueueBehavior.cs').read_text(encoding='utf-8')
start=source.index('        public (bool ok, string message) AddToQueue')
end=source.index('        public void RemoveFromQueue',start)
harness=r'''using System;
using System.Linq;
using System.Collections.Generic;
class Hero { public bool IsAlive=true; }
class HeroLookup { public static Hero Alive=new Hero(); public static Hero FindByUsername(string user)=>user=="alice"?Alive:null; }
class QueueEntry { public string Username; public Hero Hero; public int EntryFee; }
class Queue {
 const int TOURNAMENT_SIZE=16;
 readonly List<QueueEntry> _queue=new List<QueueEntry>();
 public int Count=>_queue.Count;
 public void PublishQueue(){}
 METHOD
}
class Program { static int Main(){try{
 var queue=new Queue();
 if(!queue.AddToQueue(" Alice ",0).ok)throw new Exception("Initial join rejected");
 if(!queue.AddToQueue("alice",0).ok)throw new Exception("Repeated registration must acknowledge existing membership");
 if(queue.Count!=1)throw new Exception("Repeated join duplicated hero");
 if(queue.AddToQueue("missing",0).ok)throw new Exception("Missing hero accepted");
 HeroLookup.Alive.IsAlive=false;
 if(queue.AddToQueue("alice",0).ok)throw new Exception("Dead hero accepted");
 Console.WriteLine("PASS tournament join: normalised user, duplicate acknowledgement without duplication, missing and dead hero");return 0;
 }catch(Exception e){Console.Error.WriteLine(e.Message);return 1;}}}
'''.replace('METHOD',source[start:end])
with tempfile.TemporaryDirectory(prefix='tournament-join-') as tmp:
 folder=Path(tmp)
 (folder/'Join.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net472</TargetFramework><LangVersion>latest</LangVersion></PropertyGroup></Project>')
 (folder/'Program.cs').write_text(harness,encoding='utf-8')
 result=subprocess.run(['dotnet','build',str(folder/'Join.csproj'),'-v:q'],capture_output=True,text=True)
 if result.returncode:
  print(result.stdout,result.stderr);raise SystemExit(result.returncode)
 raise SystemExit(subprocess.run([str(folder/'bin/Debug/net472/Join.exe')]).returncode)
