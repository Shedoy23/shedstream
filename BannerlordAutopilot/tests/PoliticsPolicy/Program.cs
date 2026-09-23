using System;
using System.Collections.Generic;
using BannerlordAutopilot;

int failed = 0;
void Check(bool ok, string text) { Console.WriteLine((ok ? "ok   " : "FAIL ") + text); if (!ok) failed++; }
PoliticsCandidate K(string name, bool war = false, double sincePeace = 1000, float warSupport = 0, bool warOk = true,
    float peaceScore = 0, bool peaceOk = true, float ally = 0, bool allyOk = false, bool constant = false)
    => new PoliticsCandidate { Name = name, AtWar = war, DaysSincePeace = sincePeace, WarSupport = warSupport, WarPossible = warOk,
        PeaceScore = peaceScore, PeacePossible = peaceOk, AllianceSupport = ally, AlliancePossible = allyOk, ConstantWar = constant };
var d = PoliticsPolicy.Decide(new List<PoliticsCandidate> { K("Вландия", warSupport: 30), K("Стургия", warSupport: 80) },
    false, false, false, true, true, true);
Check(d.Move == PoliticsMove.War && d.Target.Name == "Стургия", "войн нет — войну тому, кого клан поддерживает сильнее");
d = PoliticsPolicy.Decide(new List<PoliticsCandidate> { K("Вландия", warSupport: 90, sincePeace: 10), K("Стургия", warSupport: 20) },
    false, false, false, true, true, true);
Check(d.Target?.Name == "Стургия", "с тем, с кем мир моложе 20 дней, войну не начинаем");
d = PoliticsPolicy.Decide(new List<PoliticsCandidate> { K("Вландия", war: true), K("Стургия", warSupport: 99) },
    false, false, false, true, true, true);
Check(d.Move != PoliticsMove.War, "одна война уже есть — новую не ищем");
d = PoliticsPolicy.Decide(new List<PoliticsCandidate> { K("Вландия", war: true, peaceScore: 10), K("Стургия", war: true, peaceScore: 50) },
    false, false, false, true, true, true);
Check(d.Move == PoliticsMove.Peace && d.Target.Name == "Стургия", "две войны — мир там, где он нужнее по оценке игры");
d = PoliticsPolicy.Decide(new List<PoliticsCandidate> { K("Вландия", war: true, peaceScore: 90, peaceOk: false), K("Стургия", war: true, peaceScore: 5) },
    false, false, false, true, true, true);
Check(d.Target?.Name == "Стургия", "враг не готов к миру — не предлагаем ему");
d = PoliticsPolicy.Decide(new List<PoliticsCandidate> { K("Вландия", war: true), K("Бандиты", war: true, constant: true) },
    false, false, false, true, true, true);
Check(d.Move != PoliticsMove.Peace, "вечная война не считается: одна настоящая война — мира не ищем");
d = PoliticsPolicy.Decide(new List<PoliticsCandidate> { K("Стургия", warSupport: 80) }, true, false, false, true, true, true);
Check(d.Move != PoliticsMove.War, "своя заявка на войну уже на голосовании — вторую не подаём");
d = PoliticsPolicy.Decide(new List<PoliticsCandidate> { K("Стургия", warSupport: 80) }, false, false, false, false, true, true);
Check(d.Move != PoliticsMove.War, "не хватает влияния на заявку — не подаём");
d = PoliticsPolicy.Decide(new List<PoliticsCandidate> { K("Вландия", war: true), K("Асераи", ally: 70, allyOk: true), K("Батания", ally: 40, allyOk: true) },
    false, false, false, true, true, true);
Check(d.Move == PoliticsMove.Alliance && d.Target.Name == "Асераи", "союз с тем, кого клан поддерживает выше порога");
return failed;
