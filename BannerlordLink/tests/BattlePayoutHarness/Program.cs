using System;
using BannerlordLink.Util;
int count=0,failed=0;
void Check(bool ok,string name){count++;if(!ok)failed++;Console.WriteLine((ok?"PASS ":"FAIL ")+name);}
var p=BattlePayoutPolicy.Calculate(800,2000,100,false,true);
Check(p.Participation == 2700 && p.Personal == 5714 && p.Retinue == 4094 && p.Total == 12508,"ordinary example component breakdown");
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
Check(BattlePayoutPolicy.Calculate(1e12,1e12,100,false,true).Total<=201600,"ordinary cap independent of retinue size");
Check(BattlePayoutPolicy.Calculate(1e12,1e12,500,true,true).Total<=322560,"large siege cap");
Check(BattlePayoutPolicy.Calculate(1e12,1e12,10,true,true).Total<=48384,"tiny siege cannot earn large siege prize");
// Balance contract: 100 useful HP at threat 1 per reference enemy; no boost.
foreach(bool won in new[]{false,true}) foreach(bool siege in new[]{false,true}) {
 var thirty=BattlePayoutPolicy.Calculate(3000,0,500,siege,won);
 var hundredThirty=BattlePayoutPolicy.Calculate(13000,0,500,siege,won);
 Check(hundredThirty.Total >= thirty.Total * 2.5,"130 reference kills pay at least 2.5x 30: " + won + " " + siege);
 Check(thirty.Participation <= thirty.Total * .25,"participation is a minority of active hero payout");
 var smallArmy=BattlePayoutPolicy.Calculate(0,6000,500,siege,won);
 var largeArmy=BattlePayoutPolicy.Calculate(0,26000,500,siege,won);
 Check(largeArmy.Total >= smallArmy.Total * 2.5,"retinue payout retains growth beyond 30 equivalents");
}
Check(BattlePayoutPolicy.Calculate(300,0,100,false,true).Total <= 5000,"a few targets cannot unlock a large participation payment");
Check(BattlePayoutPolicy.Calculate(3000,0,100,false,true).Total <= 30000,"30 reference kills do not nearly reach cap");
Check(BattlePayoutPolicy.Calculate(13000,0,100,false,true).Total >= 60000,"130 reference kills remain worthwhile");
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
Console.WriteLine($"{count-failed}/{count} passed");return failed==0?0:1;
