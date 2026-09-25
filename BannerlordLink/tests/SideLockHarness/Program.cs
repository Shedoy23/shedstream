using System;
using BannerlordLink.Util;
// 25.09: зритель умирал за стримера и следующим призывом выходил против него.
class Program {
 static int failed, passed;
 static void Check(bool ok,string name){ Console.WriteLine((ok?"PASS ":"FAIL ")+name); if(ok)passed++; else failed++; }
 static int Main(){
  object battleA=new object(), battleB=new object();
  Check(ViewerSideLock.Allows(battleA,"alice",true),"первый призыв в бою — любая сторона");
  ViewerSideLock.Remember(battleA,"alice",true);
  Check(!ViewerSideLock.Allows(battleA,"alice",false),"вышел за стримера — против него в этом бою нельзя");
  Check(ViewerSideLock.Allows(battleA,"Alice",true),"за ту же сторону — можно снова (ник без учёта регистра)");
  Check(ViewerSideLock.Allows(battleA,"bob",false),"другого зрителя не задевает");
  Check(ViewerSideLock.Allows(battleA,"carol",true),"неудачный призыв (без Remember) сторону не закрепляет");
  Check(ViewerSideLock.Allows(battleA,"carol",false),"... и потом можно выбрать другую");
  ViewerSideLock.Remember(battleA,"bob",false);
  Check(!ViewerSideLock.Allows(battleA,"bob",true),"вышел против стримера — за него в этом бою нельзя");
  Check(ViewerSideLock.Allows(battleB,"alice",false),"новый бой — сторона выбирается заново");
  Check(ViewerSideLock.Allows(null,"alice",false),"вне боя замок не мешает");
  Console.WriteLine($"{passed} ok / {failed} FAIL"); return failed;
 }
}
