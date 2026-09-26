using System;
using System.Collections.Generic;
using BannerlordLink.Util;
// 26.09, владелец: «к стенам» и «к воротам» должны логично работать и в защите, и в атаке.
// Карта: двор слева (x < 0), поле справа (x > 0). Внешние ворота x=10, внутренние x=0;
// точка защитников у ворот — на 5 м ближе ко двору.
int failed = 0;
void Check(bool ok, string text) { Console.WriteLine((ok ? "ok   " : "FAIL ") + text); if (!ok) failed++; }
SiegeGate Gate(float x, bool outer, bool open) => new SiegeGate { Outer = outer, Inner = !outer, Open = open,
    Middle = new SiegePoint(x, 0, 0), Wait = new SiegePoint(x - 5, 0, 0) };
var me = new SiegePoint(30, 0, 0);
List<SiegeGate> Both(bool outerOpen, bool innerOpen) => new List<SiegeGate> { Gate(0, false, innerOpen), Gate(10, true, outerOpen) };

var d = SiegeOrderPolicy.PickGate(true, Both(false, false), me);
Check(d.Goal == GateGoal.Hold && d.Point.X == 5, "защита: внешние целы — держим их изнутри (x=5): " + d.Point.X);
d = SiegeOrderPolicy.PickGate(true, Both(true, false), me);
Check(d.Goal == GateGoal.Hold && d.Point.X == -5, "защита: внешние разбиты — к внутренним (x=-5): " + d.Point.X);
d = SiegeOrderPolicy.PickGate(true, Both(true, true), me);
Check(d.Goal == GateGoal.Hold && d.Point.X == -5, "защита: разбиты все — держим последний рубеж: " + d.Point.X);
d = SiegeOrderPolicy.PickGate(false, Both(false, false), me);
Check(d.Goal == GateGoal.Hold && d.Point.X == 14, "атака: внешние целы — встаём снаружи них (x=14), а не во дворе: " + d.Point.X);
d = SiegeOrderPolicy.PickGate(false, Both(true, false), me);
Check(d.Goal == GateGoal.Hold && d.Point.X == 4, "атака: внешние разбиты — к внутренним, снаружи (x=4): " + d.Point.X);
d = SiegeOrderPolicy.PickGate(false, Both(true, true), me);
Check(d.Goal == GateGoal.Breach && d.Point.X == -5, "атака: разбиты все — проходим во двор и в бой: " + d.Goal + " x=" + d.Point.X);
d = SiegeOrderPolicy.PickGate(false, new List<SiegeGate>(), me);
Check(d.Goal == GateGoal.None, "ворот нет — пусто, вызывающий берёт старый поиск");
var single = new SiegeGate { Outer = true, Inner = true, Open = false, Middle = new SiegePoint(10, 0, 0), Wait = new SiegePoint(5, 0, 0) };
d = SiegeOrderPolicy.PickGate(false, new List<SiegeGate> { single }, me);
Check(d.Goal == GateGoal.Hold && d.Point.X == 14, "одни ворота с обеими метками — работают как внешние");

// Стены: место A рядом с нами, врагов нет; место B дальше, у лестницы с врагами.
var spots = new List<SiegePoint> { new SiegePoint(2, 0, 5), new SiegePoint(40, 0, 5) };
var enemies = new List<SiegePoint> { new SiegePoint(42, 3, 0), new SiegePoint(41, -2, 0) };
var at = new SiegePoint(0, 0, 0);
Check(SiegeOrderPolicy.RankWallSpots(spots, at, enemies, true)[0] == 1, "стены, защита: туда, где враг лезет, а не к ближайшему своему");
Check(SiegeOrderPolicy.RankWallSpots(spots, at, enemies, false)[0] == 0, "стены, атака: к ближайшему месту, куда уже есть путь");
Check(SiegeOrderPolicy.RankWallSpots(spots, at, new List<SiegePoint>(), true)[0] == 0, "стены, защита без врагов рядом — ближайшее место");
Console.WriteLine(failed == 0 ? "ВСЕ ОК" : "ПРОВАЛОВ: " + failed);
return failed;
