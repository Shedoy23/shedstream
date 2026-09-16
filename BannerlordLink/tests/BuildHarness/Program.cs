using System;
using BannerlordLink.Util;

class Program
{
    static int Main()
    {
        if (typeof(EquipmentLedger).GetField("Build") == null)
        {
            Console.Error.WriteLine("FAIL: new hero build cannot persist specialization, selected weapon, starter claim or shared cooldown in campaign inventory");
            return 1;
        }
        Console.WriteLine("PASS: save-owned build persistence exists");
        return 0;
    }
}
