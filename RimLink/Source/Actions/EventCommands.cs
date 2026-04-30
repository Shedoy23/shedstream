using System;
using System.Collections.Generic;
using System.Linq;
using RimWorld;
using Verse;

namespace RimLink.Actions
{
    // ────────────────────────────────────────────────────────────────────────────
    // Базовый класс для ивент-команд
    // ────────────────────────────────────────────────────────────────────────────
    public abstract class BaseEventCommand : ICommand
    {
        protected readonly Dictionary<string, object> Data;
        protected Map HomeMap => Find.AnyPlayerHomeMap;

        protected BaseEventCommand(Dictionary<string, object> data) { Data = data; }

        public abstract void Execute();

        protected T Get<T>(string key, T fallback = default)
        {
            if (Data == null || !Data.ContainsKey(key)) return fallback;
            try { return (T)Convert.ChangeType(Data[key], typeof(T)); }
            catch { return fallback; }
        }

        protected void TryFireIncident(IncidentDef def)
        {
            if (def == null || HomeMap == null) return;
            var parms = StorytellerUtility.DefaultParmsNow(def.category, HomeMap);
            parms.forced = true;
            def.Worker.TryExecute(parms);
        }

        protected static void FireGameConditionEvent(string defName, string message, MessageTypeDef messageType)
        {
            var def = DefDatabase<GameConditionDef>.GetNamed(defName, errorOnFail: false);
            if (def == null) return;
            var map = Find.AnyPlayerHomeMap;
            if (map == null) return;

            var conditions = map.gameConditionManager.ActiveConditions;
            for (int i = conditions.Count - 1; i >= 0; i--)
                if (conditions[i].def == def) { conditions[i].End(); break; }

            map.gameConditionManager.RegisterCondition(GameConditionMaker.MakeCondition(def, 60000));
            Messages.Message(message, messageType);
        }
    }

    // ────────────────────────────────────────────────────────────────────────────
    // Погода (Weather)
    // ────────────────────────────────────────────────────────────────────────────
    public class WeatherEventCommand : BaseEventCommand
    {
        private static readonly HashSet<string> GameConditionWeathers = new HashSet<string>
        {
            "ToxicFallout", "VolcanicWinter", "DeathPall", "NeutronFog",
            "PsychicDrone", "PsychicSoothe", "SolarFlare"
        };

        public WeatherEventCommand(Dictionary<string, object> d) : base(d) { }

        public override void Execute()
        {
            if (HomeMap == null) return;

            string key = Get("weather", "Rain");
            string defName = key;
            if (key == "thunderstorm") defName = "RainThunderstorm";
            
            if (GameConditionWeathers.Contains(defName))
            {
                FireAsGameCondition(defName);
                return;
            }

            WeatherDef weather = DefDatabase<WeatherDef>.GetNamed(defName, errorOnFail: false);
            if (weather != null)
            {
                HomeMap.weatherManager.TransitionTo(weather);
                Messages.Message($"⛈ Погода изменена на: {weather.LabelCap}", MessageTypeDefOf.NeutralEvent);
            }
            else
                FireAsGameCondition(defName);
        }

        private void FireAsGameCondition(string defName)
        {
            var condDef = DefDatabase<GameConditionDef>.GetNamed(defName, errorOnFail: false);
            if (condDef == null) { Log.Warning($"[RimLink] Weather: '{defName}' не найден"); return; }

            var conditions = HomeMap.gameConditionManager.ActiveConditions;
            for (int i = conditions.Count - 1; i >= 0; i--)
                if (conditions[i].def == condDef) { conditions[i].End(); break; }

            HomeMap.gameConditionManager.RegisterCondition(GameConditionMaker.MakeCondition(condDef, 60000));
            Messages.Message($"☣️ {condDef.LabelCap} начались!", MessageTypeDefOf.ThreatBig);
        }
    }

    // ────────────────────────────────────────────────────────────────────────────
    // Рейд (ИСПРАВЛЕНО: 100% LINQ выбор фракции, без Call API который ломается)
    // ────────────────────────────────────────────────────────────────────────────
    public class RaidEventCommand : BaseEventCommand
    {
        public RaidEventCommand(Dictionary<string, object> d) : base(d) { }

        public override void Execute()
        {
            if (HomeMap == null) return;

            int points = Get("points", 500);
            var def = DefDatabase<IncidentDef>.GetNamed("RaidEnemy", errorOnFail: false);
            if (def == null) return;

            var parms = StorytellerUtility.DefaultParmsNow(def.category, HomeMap);
            parms.points = points;
            parms.forced = true;
            parms.raidStrategy = RaidStrategyDefOf.ImmediateAttack;
            parms.raidArrivalMode = PawnsArrivalModeDefOf.EdgeWalkIn;

            // 🔍 БЕЗОПАСНЫЙ ПОИСК ФРАКЦИИ (работает на любой версии RimWorld)
            var enemies = Find.FactionManager.AllFactions
                .Where(f => f != Faction.OfPlayer && f.def.humanlikeFaction && f.HostileTo(Faction.OfPlayer))
                .ToList();

            if (enemies.Count > 0)
            {
                parms.faction = enemies.RandomElement();
            }
            else
            {
                // Фоллбек: если нет явных врагов, берем любую человеческую фракцию
                var fallback = Find.FactionManager.AllFactions
                    .FirstOrDefault(f => f != Faction.OfPlayer && f.def.humanlikeFaction);

                if (fallback != null)
                    parms.faction = fallback;
                else
                {
                    Log.Warning("[RimLink] RaidEvent: Не найдено фракций для рейда — отмена");
                    return;
                }
            }

            def.Worker.TryExecute(parms);
            Messages.Message("🔴 Вражеский рейд начинается!", MessageTypeDefOf.ThreatBig);
        }
    }

    // ────────────────────────────────────────────────────────────────────────────
    // Грузовой под
    // ────────────────────────────────────────────────────────────────────────────
    public class ResourceDropCommand : BaseEventCommand
    {
        public ResourceDropCommand(Dictionary<string, object> d) : base(d) { }
        public override void Execute()
        {
            var def = DefDatabase<IncidentDef>.GetNamed("ResourcePodCrash", errorOnFail: false);
            if (def != null && HomeMap != null)
                TryFireIncident(def);
            else
                Log.Warning("[RimLink] ResourceDrop: Инцидент не найден");
        }
    }

    // ────────────────────────────────────────────────────────────────────────────
    // Странник
    // ────────────────────────────────────────────────────────────────────────────
    public class WandererJoinCommand : BaseEventCommand
    {
        public WandererJoinCommand(Dictionary<string, object> d) : base(d) { }
        public override void Execute()
        {
            var def = DefDatabase<IncidentDef>.GetNamed("WandererJoin", errorOnFail: false);
            if (def != null && HomeMap != null)
                TryFireIncident(def);
            else
                Log.Warning("[RimLink] Wanderer: Инцидент не найден");
        }
    }

    // ────────────────────────────────────────────────────────────────────────────
    // Животные
    // ────────────────────────────────────────────────────────────────────────────
    public class AnimalsEventCommand : BaseEventCommand
    {
        public AnimalsEventCommand(Dictionary<string, object> d) : base(d) { }

        public override void Execute()
        {
            if (HomeMap == null) return;
            bool aggressive = Get("aggressive", false);

            IncidentDef def = aggressive
                ? DefDatabase<IncidentDef>.GetNamed("ManhunterPack", errorOnFail: false)
                : DefDatabase<IncidentDef>.GetNamed("FarmAnimalsWanderIn", errorOnFail: false);

            if (def == null && !aggressive)
                def = DefDatabase<IncidentDef>.GetNamed("HerdMigration", errorOnFail: false);

            if (def != null)
            {
                TryFireIncident(def);
                Messages.Message(aggressive ? "🐺 Животные в ярости!" : "🐾 Животные пришли в колонию!",
                                 aggressive ? MessageTypeDefOf.ThreatBig : MessageTypeDefOf.PositiveEvent);
            }
            else
                Log.Warning("[RimLink] Animals: Инцидент не найден");
        }
    }

    // ────────────────────────────────────────────────────────────────────────────
    // Универсальный инцидент
    // ────────────────────────────────────────────────────────────────────────────
    public class FireIncidentCommand : ICommand
    {
        private readonly Dictionary<string, object> _data;
        public FireIncidentCommand(Dictionary<string, object> d) { _data = d; }

        public void Execute()
        {
            Map map = Find.AnyPlayerHomeMap;
            if (map == null) { Log.Warning("[RimLink] FireIncident: Нет карты"); return; }

            string defName = "";
            if (_data.TryGetValue("incident_def", out var val1)) defName = val1?.ToString();
            if (string.IsNullOrEmpty(defName) && _data.TryGetValue("def_name", out var val2)) defName = val2?.ToString();
            if (string.IsNullOrEmpty(defName) && _data.TryGetValue("params", out var valParams))
            {
                if (valParams is Dictionary<string, object> dict && dict.TryGetValue("incident_def", out var v3))
                    defName = v3?.ToString();
            }

            if (string.IsNullOrEmpty(defName)) return;

            var def = DefDatabase<IncidentDef>.GetNamed(defName, errorOnFail: false);
            if (def == null) return;

            try
            {
                var parms = StorytellerUtility.DefaultParmsNow(def.category, map);
                parms.forced = true;

                // Читаем points из params если переданы; иначе ограничиваем дефолт
                // чтобы избежать зависания игры при богатой колонии
                float customPoints = -1f;
                if (_data.TryGetValue("params", out var paramsVal) && paramsVal is Dictionary<string, object> pd)
                {
                    if (pd.TryGetValue("points", out var pv) && float.TryParse(pv?.ToString(), out float pp))
                        customPoints = pp;
                }
                if (customPoints > 0f)
                    parms.points = customPoints;
                else
                    // Safety cap — если points не передан в params (старый каталог)
                    // Ограничиваем 3000, чтобы не фризить игру при богатой колонии
                    parms.points = Math.Min(parms.points, 3000f);

                bool isAlly = defName.Contains("Join") || defName.Contains("Trader");

                // 🔍 БЕЗОПАСНЫЙ ПОИСК ФРАКЦИИ (чистый LINQ)
                if (!isAlly && (def.category == IncidentCategoryDefOf.ThreatBig || def.workerClass?.Name?.Contains("Raid") == true))
                {
                    var enemies = Find.FactionManager.AllFactions
                        .Where(f => f.HostileTo(Faction.OfPlayer) && f.def.humanlikeFaction)
                        .ToList();
                    if (enemies.Count > 0) parms.faction = enemies.RandomElement();
                }
                else if (isAlly)
                {
                    var allies = Find.FactionManager.AllFactions
                        .Where(f => !f.HostileTo(Faction.OfPlayer) && f.def.humanlikeFaction)
                        .ToList();
                    if (allies.Count > 0) parms.faction = allies.RandomElement();
                }

                // Ищем клетку для спавна (безопасно для 1.6)
                string workerType = def.workerClass?.Name ?? "";
                if (workerType.Contains("ShipPart") || workerType.Contains("Siege") || workerType.Contains("Crash") || workerType.Contains("Raid"))
                {
                    try 
                    {
                        IntVec3 cell = CellFinder.RandomNotEdgeCell(12, map);
                        if (cell.IsValid) parms.spawnCenter = cell;
                    } 
                    catch { /* Пропускаем, игра сама найдет точку */ }
                }

                def.Worker.TryExecute(parms);
                Messages.Message($"🎲 {def.LabelCap} запущен!", MessageTypeDefOf.NeutralEvent);
            }
            catch (Exception e)
            {
                Log.Error($"[RimLink] FireIncident: {e.Message}");
            }
        }
    }
}