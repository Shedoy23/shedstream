using System;
// 30.09: закон — переключатель; панель показывала «не действует», а в игре он был —
// 1500💎 уходили на отмену. Тест берёт НАСТОЯЩИЙ метод из исходника (generate.py).
class Program {
 static int Main() {
  int failed = 0;
  void Check(bool ok, string t) { Console.WriteLine((ok ? "ok   " : "FAIL ") + t); if (!ok) failed++; }
  Check(PolicyIntent.ResolvePolicyIntent("enact", true).Refusal == "policy_already_enacted", "хочет ввести, а закон уже действует — отказ с возвратом, а не отмена");
  Check(PolicyIntent.ResolvePolicyIntent("enact", false) == (true, null), "хочет ввести, закона нет — вводим");
  Check(PolicyIntent.ResolvePolicyIntent("remove", false).Refusal == "policy_already_removed", "хочет отменить, закона уже нет — отказ с возвратом");
  Check(PolicyIntent.ResolvePolicyIntent("remove", true) == (false, null), "хочет отменить, закон есть — отменяем");
  Check(PolicyIntent.ResolvePolicyIntent("", true) == (false, null) && PolicyIntent.ResolvePolicyIntent(null, false) == (true, null), "старый бэкенд без поля — прежний переключатель");
  Console.WriteLine(failed == 0 ? "ВСЕ ОК" : "ПРОВАЛОВ: " + failed);
  return failed;
 }
}
