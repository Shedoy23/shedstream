using System;
// 30.09, багрепорт #81: laitru годами в плену у Баттании без войны. Правило берётся из исходника.
class Program {
 static int Main() {
  int failed = 0;
  void Check(bool ok, string t) { Console.WriteLine((ok ? "ok   " : "FAIL ") + t); if (!ok) failed++; }
  Check(Stuck.ShouldRelease(true, true, true, false), "держит сторона, с которой войны нет — отпускаем (случай laitru)");
  Check(Stuck.ShouldRelease(true, true, false, false), "тюремщика нет вовсе — отпускаем");
  Check(!Stuck.ShouldRelease(true, true, true, true), "держит воюющая сторона (и бандиты) — обычный плен, не трогаем");
  Check(!Stuck.ShouldRelease(false, true, true, false), "не герой зрителя — не наше дело");
  Check(!Stuck.ShouldRelease(true, false, false, false), "не в плену — ничего");
  Console.WriteLine(failed == 0 ? "ВСЕ ОК" : "ПРОВАЛОВ: " + failed);
  return failed;
 }
}
