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
            kingdom.Clans.Add(clan);
            Clan.All.Add(clan);

            bool ok = ClanIntegrity.DetachLeader(clan, hero, "endorphine13");
            hero.Clan = null;   // это делает сам хендлер сразу после отсоединения

            if (!ok)
            {
                Console.WriteLine("FAIL DetachLeader вернул false — лидер не отсоединён вовсе");
                failures++;
            }
            else if (ReferenceEquals(clan.Leader, hero))
            {
                Console.WriteLine(
                    "FAIL клан всё ещё считает лидером героя, у которого клана нет — " +
                    "ровно это состояние уронило игру 22.09 (Leader.Clan == null)");
                failures++;
            }
            else if (clan.Kingdom != null)
            {
                Console.WriteLine(
                    "FAIL клан без лидера остался в королевстве — ваниль переберёт его " +
                    "на суточном тике и упадёт");
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
            kingdom.Clans.Add(broken);
            Clan.All.Add(broken);

            int repaired = ClanIntegrity.RepairAll();

            if (repaired < 1)
            {
                Console.WriteLine(
                    "FAIL RepairAll не нашёл битый клан — загруженный сейв так и останется " +
                    "с висящим лидером и упадёт на следующем игровом дне");
                failures++;
            }
            else if (ReferenceEquals(broken.Leader, stray) || broken.Kingdom != null)
            {
                Console.WriteLine(
                    "FAIL RepairAll не вылечил клан: leader=" +
                    (broken.Leader == null ? "null" : "прежний") +
                    ", kingdom=" + (broken.Kingdom == null ? "null" : "остался"));
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
            kingdom.Clans.Add(healthy);
            Clan.All.Add(healthy);

            int repaired = ClanIntegrity.RepairAll();

            if (repaired != 0 || healthy.Kingdom == null || !ReferenceEquals(healthy.Leader, leader))
            {
                Console.WriteLine("FAIL ремонт тронул здоровый клан");
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
        public Kingdom Kingdom;
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
