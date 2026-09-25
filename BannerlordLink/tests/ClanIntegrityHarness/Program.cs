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

        // 5. Клан помечен «уничтожен», но в нём живые люди и свой лидер.
        //    Решение владельца 22.09: снимать флаг. Иначе зритель теряет
        //    королевство в панели, голос в королевстве и приём новых членов.
        {
            Clan.All.Clear();
            var kingdom = new Kingdom { Name = "Вландия" };
            var boss = new Hero { Name = "neyrahatomia" };
            var mate = new Hero { Name = "сосед" };
            var zombie = new Clan { Name = "[BLink] Рой пчёл", Kingdom = kingdom, IsEliminated = true };
            zombie.SetLeader(boss);
            boss.Clan = zombie; mate.Clan = zombie;
            zombie.Heroes.Add(boss); zombie.Heroes.Add(mate);
            Clan.All.Add(zombie);

            int repaired = ClanIntegrity.RepairAll();

            if (zombie.IsEliminated)
            {
                Console.WriteLine(
                    "FAIL флаг «уничтожен» остался на живом клане (в нём " +
                    zombie.Heroes.Count(h => h.IsAlive) + " живых, лидер свой) — " +
                    "зритель так и не увидит королевство в панели");
                failures++;
            }
            else if (zombie.Kingdom == null)
            {
                Console.WriteLine("FAIL заодно выкинули живой клан из королевства");
                failures++;
            }
            else if (repaired < 1)
            {
                Console.WriteLine("FAIL снятие флага не засчитано в отчёт");
                failures++;
            }
        }

        // 6. Уничтоженный клан БЕЗ живых не воскрешаем: там чинить нечего.
        {
            Clan.All.Clear();
            var kingdom = new Kingdom { Name = "Вландия" };
            var ghostLeader = new Hero { Name = "мертвец", IsAlive = false };
            var ghost = new Clan { Name = "[BLink] Пустой", Kingdom = kingdom, IsEliminated = true };
            ghost.SetLeader(ghostLeader); ghostLeader.Clan = ghost; ghost.Heroes.Add(ghostLeader);
            Clan.All.Add(ghost);

            ClanIntegrity.RepairAll();

            if (!ghost.IsEliminated)
            {
                Console.WriteLine("FAIL воскресили клан, в котором нет живых");
                failures++;
            }
        }

        // #61 (24.09): при роспуске королевства правителем кланы выводятся
        // заранее, но клан с застрявшим флагом «уничтожен» пропускался и оставался
        // в распущенном королевстве («Рой пчёл» 21.09 — флаг снят только 23.09).
        {
            var kingdom = new Kingdom { Name = "Пчелиный Каганат" };
            Clan MakeClan(string name, bool eliminated, bool alive)
            {
                var c = new Clan { Name = name, Kingdom = kingdom, IsEliminated = eliminated };
                var h = new Hero { Name = name + "_лидер", Clan = c, IsAlive = alive };
                c.Heroes.Add(h); c.SetLeader(h);
                return c;
            }
            var ruler = MakeClan("правитель", false, true);
            var normal = MakeClan("обычный", false, true);
            var stuck = MakeClan("Рой пчёл", true, true);
            var dead = MakeClan("мёртвый", true, false);
            ClanIntegrity.EvacuateForDissolution(kingdom, ruler);
            if (normal.Kingdom != null) { failures++; Console.WriteLine("FAIL живой клан не выведен"); }
            if (stuck.Kingdom != null || stuck.IsEliminated) { failures++; Console.WriteLine("FAIL клан с застрявшим флагом остался в распущенном королевстве"); }
            if (dead.Kingdom != null) { failures++; Console.WriteLine("FAIL мёртвый клан висит в распущенном королевстве"); }
            if (ruler.Kingdom != kingdom) { failures++; Console.WriteLine("FAIL клан правителя выводит обработчик, а не эвакуация"); }
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
        // Имена как в движке: флаг ищется рефлексией по `_isEliminated`.
        private bool _isEliminated;
        public bool IsEliminated { get => _isEliminated; set => _isEliminated = value; }
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
