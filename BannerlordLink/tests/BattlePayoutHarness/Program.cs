using System;
using BannerlordLink.Util;
int count=0,failed=0;
void Check(bool ok,string name){count++;if(!ok)failed++;Console.WriteLine((ok?"PASS ":"FAIL ")+name);}
var p=BattlePayoutPolicy.Calculate(800,2000,100,false,true);
Check(p.Total == p.Participation + p.Personal + p.Retinue && p.Personal > 0 && p.Retinue > 0,"ordinary example component breakdown");
Check(BattlePayoutPolicy.Calculate(0,0,100,false,true).Total==0,"spawn without contribution earns zero");
Check(BattlePayoutPolicy.Calculate(0,2000,100,false,true).Total>0,"retinue-only owner earns reward");
Check(BattlePayoutPolicy.Calculate(800,0,100,false,true).Total>0,"solo hero still viable");
Check(BattlePayoutPolicy.Calculate(800,2000,100,false,false).Total>0,"defeat retains contribution");
Check(BattlePayoutPolicy.Calculate(double.NaN,0,100,false,true).Total==0,"invalid score rejected");
Check(BattlePayoutPolicy.Calculate(double.PositiveInfinity,0,100,false,true).Total==0,"infinite score rejected");
Check(BattlePayoutPolicy.Calculate(-1,-1,100,false,true).Total==0,"negative score clamped");
Check(BattlePayoutPolicy.Threat(1)==.4 && BattlePayoutPolicy.Threat(100)==1.5,"target threat bounded");
foreach(int enemies in new[]{10,49,50,199,200,1000})foreach(bool siege in new[]{false,true}){
 int previous=0;
 for(int score=0;score<=10000;score++){
  int reward=BattlePayoutPolicy.Calculate(score,score,enemies,siege,true).Total;
  if(reward<previous){Check(false,"monotonic rewards");break;}
  previous=reward;
 }
 Check(previous>0,"monotonic across score sweep "+enemies+" "+siege);
}
Check(BattlePayoutPolicy.Calculate(1e12,1e12,100,false,true).Total<=1605600,"ordinary cap independent of retinue size");
Check(BattlePayoutPolicy.Calculate(1e12,1e12,500,true,true).Total<=2568960,"large siege cap");
// 22.09 (Codex, решение владельца): малые бои x0.8 вместо x0.24 — потолок
// малой осады 385344*0.8/0.24 = 1284480; смысл проверки прежний: меньше большой.
Check(BattlePayoutPolicy.Calculate(1e12,1e12,10,true,true).Total<BattlePayoutPolicy.Calculate(1e12,1e12,500,true,true).Total,"tiny siege cannot earn large siege prize");
foreach(var scenario in new[]{(enemies:100,siege:false,cap:1605600),(enemies:500,siege:true,cap:2568960),(enemies:10,siege:true,cap:1284480)}) {
 var ceiling=BattlePayoutPolicy.Calculate(1e12,1e12,scenario.enemies,scenario.siege,true);
 Check(ceiling.Total >= scenario.cap-6 && ceiling.Total <= scenario.cap,"потолок после перекалибровки 22.09 достижим " + scenario.cap);
}
// Observed 2026-09-21 19:00 battle, same field defeat / no subscription boost.
// Inputs are actual payout damage points, NOT kills * assumed target HP.
var good=BattlePayoutPolicy.Calculate(2749.5,343.3,1754,false,false); // fikoos418: 28 human kills
var strong=BattlePayoutPolicy.Calculate(3709.8,440.4,1754,false,false); // slopkom: 36 human kills
var top=BattlePayoutPolicy.Calculate(6724.8,668.6,1754,false,false); // slopkom_nyi_item: 59 human kills
var topOther=BattlePayoutPolicy.Calculate(5657.4,547.4,1754,false,false); // dzirtdourden: 65 human kills
Check(good.Total >= 140000 && good.Total <= 170000,"observed 28-kill effort receives worthwhile intermediate reward");
Check(strong.Total >= 170000 && strong.Total <= 210000,"observed 37-counter effort rewards additional contribution");
Check(top.Total >= 250000 && top.Total <= 300000,"observed top effort earns substantial reward below ceiling");
Check(topOther.Total >= 220000 && topOther.Total <= 270000,"another observed top effort remains worthwhile");
Check(top.Total >= good.Total * 1.7,"observed top contribution stays distinct from good contribution");
Check(good.Participation <= good.Total * .35,"participation does not dominate a good effort");
Check(top.Personal < BattlePayoutPolicy.Multiplier * 100000 * 1.2 * .7,"top observed personal effort still leaves headroom");
var army=BattlePayoutPolicy.Calculate(45.9,4600.7,212,false,true); // shedoy23 before x2 subscription boost
Check(army.Total >= 110000 && army.Total <= 150000,"observed strong retinue effort remains worthwhile");
Check(BattlePayoutPolicy.Calculate(300,0,100,false,true).Total <= 24000,"a few targets cannot unlock full participation");
foreach(int points in new[]{500,1000,2000,3000,5000,7000,10000}) {
 var a=BattlePayoutPolicy.Calculate(points,0,100,false,true);
 var b=BattlePayoutPolicy.Calculate(points+1000,0,100,false,true);
 Check(b.Total-a.Total >= 4000,"continued personal growth around observed range " + points);
 var r=BattlePayoutPolicy.Calculate(0,points,100,false,true);
 var r2=BattlePayoutPolicy.Calculate(0,points+1000,100,false,true);
 Check(r2.Total>r.Total,"continued retinue growth " + points);
}
// Фактические входы и выплаты боя 21.09 22:09 (лог [BattlePayout v2], DLL до множителя).
// Очки в журнале с одним знаком после запятой, поэтому допуск 2 монеты на часть.
foreach(var o in new[]{
 (p:572.6,r:22.0,part:4377,pers:15027,ret:380),
 (p:196.3,r:631.9,part:3841,pers:5613,ret:9494),
 (p:1279.3,r:240.5,part:10496,pers:29078,ret:3946),
 (p:20.0,r:0.0,part:150,pers:597,ret:0),
 (p:447.3,r:898.5,part:6724,pers:12069,ret:12766),
 (p:302.5,r:614.1,part:4571,pers:8436,ret:9263),
}) {
 var now=BattlePayoutPolicy.Calculate(o.p,o.r,103,false,true);
 Check(Math.Abs(now.Participation-2*o.part)<=2 && Math.Abs(now.Personal-2*o.pers)<=2 && Math.Abs(now.Retinue-2*o.ret)<=2,
  "ровно вдвое против фактической выплаты 21.09 ("+o.part+"/"+o.pers+"/"+o.ret+" -> "+now.Participation+"/"+now.Personal+"/"+now.Retinue+")");
}
// 22.09, решение владельца: такой вклад в осаду обязан оцениваться не меньше
// миллиона. Входы — фактические из лога осады 22.09 (enemies=1650, победа).
var siegeTop=BattlePayoutPolicy.Calculate(10501.7,1692.5,1650,true,true);   // slopkom_nyi_item
var siegeMid=BattlePayoutPolicy.Calculate(7914.4,1116.2,1650,true,true);    // slopkom
var siegeLow=BattlePayoutPolicy.Calculate(4574.7,1656.2,1650,true,true);    // igotpaws
Check(siegeTop.Personal >= 1000000,
 "личная часть за 10 500 очков в осаде не меньше миллиона (сейчас "+siegeTop.Personal+")");
Check(siegeTop.Personal > siegeMid.Personal * 1.15,
 "вклад 10 500 против 7 900 различим не на проценты ("+siegeTop.Personal+" против "+siegeMid.Personal+")");
Check(siegeMid.Personal > siegeLow.Personal * 1.3,
 "вклад 7 900 против 4 600 различим ("+siegeMid.Personal+" против "+siegeLow.Personal+")");

{ var small=BattlePayoutPolicy.Calculate(8000,1000,49,false,true).Total; var mid=BattlePayoutPolicy.Calculate(8000,1000,100,false,true).Total;
  Check(Math.Abs(small-0.8*mid)<=6,"small battle multiplier is 0.8 ("+small+" vs "+mid+")"); }
var ledger=new BattleDamageLedger<object>();var target=new object();ledger.Track(target,100);
Check(ledger.Hit(target,80,20)==80,"first attacker earns actual damage");
Check(ledger.Hit(target,200,0)==20,"second attacker overkill capped at remainder");
Check(ledger.Hit(target,200,0)==0,"duplicate hit gives nothing");
Check(ledger.Finish(target)&&!ledger.Finish(target),"death bonus once per target");
Check(ledger.Hit(target,50,0)==0,"dead target cannot farm");
var wounded=new object();ledger.Track(wounded,30);Check(ledger.Hit(wounded,200,0)==30,"wounded target actual initial HP");
var blocked=new object();ledger.Track(blocked,100);Check(ledger.Hit(blocked,50,100)==0,"blocked blow no damage credit");
Check(ledger.Hit(blocked,50,50)==50,"real blow after block");
Check(ledger.Hit(blocked,0,100)==0,"healing no payout");
Check(ledger.Hit(blocked,100,0)==50,"healing loop limited by original life budget");
ledger.Track(blocked,100);Check(ledger.Hit(blocked,100,0)==0,"repeated registration cannot replenish life budget");
Check(ledger.Hit(new object(),100,0)==0,"unknown target fails closed");
// 26.09, владелец: добивка всем участникам, по размеру боя 30/15/5 тыс.
Check(BattlePayoutPolicy.WithFloor(default,650).Total==30000,"большой бой без урона: участие добито до 30000");
Check(BattlePayoutPolicy.WithFloor(default,120).Total==15000,"средний бой: до 15000");
Check(BattlePayoutPolicy.WithFloor(default,40).Total==5000,"стычка с бандитами: до 5000");
Check(BattlePayoutPolicy.WithFloor(default,200).Total==30000 && BattlePayoutPolicy.WithFloor(default,199).Total==15000
   && BattlePayoutPolicy.WithFloor(default,50).Total==15000 && BattlePayoutPolicy.WithFloor(default,49).Total==5000,"границы 200 и 50");
var weak=BattlePayoutPolicy.Calculate(130.6,166.9,635,false,false); // stepuhatgn 25.09: 16370 по формуле
var weakFloored=BattlePayoutPolicy.WithFloor(weak,635);
Check(weakFloored.Total==30000 && weakFloored.Personal==weak.Personal && weakFloored.Retinue==weak.Retinue,
   "добивка идёт в участие, личная и свита не трогаются: "+weak.Total+" -> "+weakFloored.Total);
var strongPay=BattlePayoutPolicy.Calculate(3709.8,440.4,1754,false,false);
Check(BattlePayoutPolicy.WithFloor(strongPay,1754).Total==strongPay.Total,"выше порога выплата не меняется");
Console.WriteLine($"{count-failed}/{count} passed");return failed==0?0:1;
