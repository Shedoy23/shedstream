using System;
using System.Collections.Generic;
using System.Linq;
using BannerlordLink.Util;
using TaleWorlds.CampaignSystem;

// Гоняет НАСТОЯЩИЙ код BannerlordLink/src/Util/ClanIntegrity.cs (вытаскивается
// generate.py при сборке) против заглушек движка, которые ведут себя как ваниль
// 1.4.8: ChangeClanLeaderAction.ApplyWithoutSelectedNewLeader при отсутствии
// наследников НИЧЕГО не делает (подтверждено декомпиляцией,
// docs/BANNERLORD_CRASH_2026-09-22.md).
class Program
{
    static int Main()
    {
        int failures = 0;

        // 1. Зритель — единственный в клане, выходит. Клан обязан перестать
        //    считать его лидером, иначе ваниль упадёт на Leader.Clan.
        {
            Clan.All.Clear();
            var kingdom = new Kingdom { Name = "Вландия" };
            var hero = new Hero { Name = "endorphine13" };
            var clan = new Clan { Name = "[BLink] Рой пчел", Kingdom = kingdom };
            clan.SetLeader(hero);
            hero.Clan = clan;
            Clan.All.Add(clan);

            bool ok = ClanIntegrity.DetachLeader(clan, hero, "endorphine13");
            hero.Clan = null;   // это делает сам хендлер сразу после отсоединения

            if (!ok)
            {
                Console.WriteLine("FAIL DetachLeader вернул false — зритель не смог выйти из клана");
                failures++;
            }
            else if (clan.Kingdom != null)
            {
                Console.WriteLine(
                    "FAIL клан остался в королевстве — ваниль поведёт его на выборы " +
                    "и разыменует Leader.Clan");
                failures++;
            }
            else if (clan.Leader == null)
            {
                Console.WriteLine(
                    "FAIL лидер занулён: у неразбойничьего клана Leader обязан быть " +
                    "не-null, иначе ваниль падает на clan.Leader.Gold в суточном тике " +
                    "(проверено крашем 22.09 14:15)");
                failures++;
            }
        }

        // 2. Ремонт уже испорченного сейва: клан указывает на лидера, который
        //    из него ушёл. Такой сейв уже существует у владельца.
        {
            Clan.All.Clear();
            var kingdom = new Kingdom { Name = "Вландия" };
            var stray = new Hero { Name = "endorphine13", Clan = null };
            var broken = new Clan { Name = "[BLink] Рой пчел", Kingdom = kingdom, IsEliminated = true };
            broken.SetLeader(stray);
            Clan.All.Add(broken);

            int repaired = ClanIntegrity.RepairAll();

            if (repaired < 1)
            {
                Console.WriteLine(
                    "FAIL RepairAll не нашёл битый клан — загруженный сейв так и останется " +
                    "с висящим лидером и упадёт на следующем игровом дне");
                failures++;
            }
            else if (broken.Kingdom != null)
            {
                Console.WriteLine("FAIL RepairAll не вывел битый клан из королевства");
                failures++;
            }
            else if (broken.Leader == null)
            {
                Console.WriteLine(
                    "FAIL RepairAll занулил лидера — именно это уронило игру 22.09 в 14:15 " +
                    "(ClanVariablesCampaignBehavior.MakeClanFinancialEvaluation → clan.Leader.Gold)");
                failures++;
            }
        }

        // 3. Здоровый клан ремонт трогать не смеет.
        {
            Clan.All.Clear();
            var kingdom = new Kingdom { Name = "Вландия" };
            var leader = new Hero { Name = "kuro_gothic" };
            var healthy = new Clan { Name = "[BLink] Волки", Kingdom = kingdom };
            healthy.SetLeader(leader);
            leader.Clan = healthy;
            Clan.All.Add(healthy);

            int repaired = ClanIntegrity.RepairAll();

            if (repaired != 0 || healthy.Kingdom == null || !ReferenceEquals(healthy.Leader, leader))
            {
                Console.WriteLine("FAIL ремонт тронул здоровый клан");
                failures++;
            }
        }

        // 4. Клан с висящей ссылкой, но УЖЕ вне королевства, чинить нечего:
        //    он не попадает ни на выборы, ни в дипломатию. Считать это
        //    «вылечили» — врать в лог на каждой загрузке.
        {
            Clan.All.Clear();
            var stray = new Hero { Name = "endorphine13", Clan = null };
            var idle = new Clan { Name = "[BLink] Рой пчел" };
            idle.SetLeader(stray);
            Clan.All.Add(idle);

            int repaired = ClanIntegrity.RepairAll();

            if (repaired != 0)
            {
                Console.WriteLine(
                    "FAIL ремонт засчитал себе клан вне королевства — на каждой загрузке " +
                    "в логе будет «вылечено 1», хотя ничего не менялось");
                failures++;
            }
        }

        if (failures > 0)
        {
            Console.WriteLine($"{failures} check(s) failed");
            return 1;
        }
        Console.WriteLine("PASS отсоединение лидера, ремонт битого сейва, здоровый клан не тронут");
        return 0;
    }
}

namespace TaleWorlds.CampaignSystem
{
    public class Clan
    {
        public static List<Clan> All = new();
        public string Name;
        private Kingdom _kingdom;
        // Ваниль делает ровно `clan.Kingdom = null`, а сеттер сам чинит списки.
        public Kingdom Kingdom
        {
            get => _kingdom;
            set { _kingdom?.Clans.Remove(this); _kingdom = value; value?.Clans.Add(this); }
        }
        public bool IsEliminated;
        public List<Hero> Heroes = new();
        private Hero _leader;                       // имя как в движке: ищется рефлексией
        public Hero Leader => _leader;
        public void SetLeader(Hero hero) => _leader = hero;
    }

    public class Hero
    {
        public string Name;
        public Clan Clan;
        public bool IsAlive = true;
    }

    public class Kingdom
    {
        public string Name;
        public List<Clan> Clans = new();
    }
}

namespace TaleWorlds.CampaignSystem.Actions
{
    // Ваниль 1.4.8: при пустом GetHeirApparents() метод возвращается, не тронув
    // _leader. Заглушка повторяет это буквально.
    public static class ChangeClanLeaderAction
    {
        public static void ApplyWithoutSelectedNewLeader(Clan clan)
        {
            var heir = clan.Heroes.FirstOrDefault(h => h != null && h != clan.Leader && h.IsAlive);
            if (heir == null) return;
            clan.SetLeader(heir);
        }
    }

    public static class ChangeKingdomAction
    {
        public static void ApplyByLeaveKingdom(Clan clan, bool byOwnDecision)
        {
            clan.Kingdom?.Clans.Remove(clan);
            clan.Kingdom = null;
        }
    }
}

namespace HarmonyLib
{
    public static class AccessTools
    {
        public static System.Reflection.FieldInfo Field(Type type, string name) =>
            type.GetField(name, System.Reflection.BindingFlags.Instance
                              | System.Reflection.BindingFlags.NonPublic
                              | System.Reflection.BindingFlags.Public);
    }
}

namespace BannerlordLink
{
    public static class BannerlordLinkModule
    {
        public static void Log(string text) { }
    }
}
