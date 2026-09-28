using System;
namespace BannerlordLink.Util
{
    // ShedLink purchase policy; native limits are inputs, never inferred here.
    public static class ProgressionPolicy
    {
        public const int SkillPurchaseLimit = 330;
        public const int AttributePurchaseLimit = 10;
        public static int FocusPurchaseLimit => FocusPrices.Length;
        private static readonly int[] FocusPrices = { 30000, 40000, 50000, 60000, 75000 };
        public sealed class Quote
        {
            public int CostGold { get; internal set; }
            public string Reason { get; internal set; }
            public bool Available => Reason == null;
        }
        public static Quote Focus(int value, int amount, int nativeLimit, int gold)
        {
            var q = new Quote();
            if (amount < 1 || amount > FocusPurchaseLimit) q.Reason = "invalid_amount";
            else if (value < 0) q.Reason = "invalid_progression_value";
            else if ((long)value + amount > nativeLimit) q.Reason = "native_focus_limit";
            else if ((long)value + amount > FocusPurchaseLimit) q.Reason = "focus_purchase_limit";
            else { for (int i = value; i < value + amount; i++) q.CostGold += FocusPrices[i]; }
            if (q.Reason == null && gold < q.CostGold) q.Reason = "not_enough_hero_gold";
            return q;
        }
        public static Quote Attribute(int value, int amount, int nativeLimit, int gold)
        {
            var q = new Quote();
            if (amount < 1 || amount > AttributePurchaseLimit) q.Reason = "invalid_amount";
            else if (value < 0) q.Reason = "invalid_progression_value";
            else if ((long)value + amount > nativeLimit) q.Reason = "native_attribute_limit";
            else if ((long)value + amount > AttributePurchaseLimit) q.Reason = "attribute_purchase_limit";
            else q.CostGold = 50000 * amount;
            if (q.Reason == null && gold < q.CostGold) q.Reason = "not_enough_hero_gold";
            return q;
        }
        public static string ValidateExpected(int value, int cost, int expectedValue, int expectedCost)
            => value != expectedValue ? "stale_progression_value" : cost != expectedCost ? "stale_progression_price" : null;
        public static string XpReason(int level, float learningRate, float multiplier)
            => level >= SkillPurchaseLimit ? "skill_purchase_limit"
                : !(learningRate > 0) || float.IsInfinity(learningRate) || !(multiplier > 0) || float.IsInfinity(multiplier)
                ? "skill_learning_unavailable" : null;
    }
}
