using System;
using BannerlordLink.Util;
class Program {
 static int n;
 static void Check(bool value,string name) { if(!value) throw new Exception(name); n++; }
 static void Main() {
  Check(ProgressionPolicy.Focus(2,1,5,50000).Available,"focus price exact");
  Check(ProgressionPolicy.Focus(2,1,5,50000).CostGold==50000,"tier2");
  Check(ProgressionPolicy.Focus(0,2,5,70000).CostGold==70000,"bulk sums tiers");
  Check(ProgressionPolicy.Focus(3,1,3,999999).Reason=="native_focus_limit","mod lower cap");
  Check(ProgressionPolicy.Focus(5,1,8,999999).Reason=="focus_purchase_limit","no invented tier6");
  Check(ProgressionPolicy.Focus(4,2,8,999999).Reason=="focus_purchase_limit","no silent amount clamp");
  Check(ProgressionPolicy.Focus(-1,1,5,999999).Reason=="invalid_progression_value","negative focus");
  Check(ProgressionPolicy.Focus(0,0,5,999999).Reason=="invalid_amount","zero amount");
  Check(ProgressionPolicy.Focus(2,1,5,49999).Reason=="not_enough_hero_gold","gold boundary");
  Check(ProgressionPolicy.Attribute(7,1,7,999999).Reason=="native_attribute_limit","mod attr cap");
  Check(ProgressionPolicy.Attribute(10,1,20,999999).Reason=="attribute_purchase_limit","preserve attr balance");
  Check(ProgressionPolicy.Attribute(8,2,10,100000).CostGold==100000,"bulk attr");
  Check(ProgressionPolicy.ValidateExpected(2,50000,2,50000)==null,"matching quote");
  Check(ProgressionPolicy.ValidateExpected(3,60000,2,50000)=="stale_progression_value","stale value");
  Check(ProgressionPolicy.ValidateExpected(2,50000,2,1)=="stale_progression_price","stale price");
  Check(ProgressionPolicy.XpReason(330,1,1)=="skill_purchase_limit","xp policy cap");
  Check(ProgressionPolicy.XpReason(100,0,1)=="skill_learning_unavailable","zero learning");
  Check(ProgressionPolicy.XpReason(100,1,0)=="skill_learning_unavailable","zero multiplier");
  Check(ProgressionPolicy.XpReason(100,float.NaN,1)=="skill_learning_unavailable","invalid rate");
  Check(ProgressionPolicy.XpReason(100,0.5f,2)==null,"native learning allowed");
  Console.WriteLine($"PASS {n} progression checks");
 }
}
