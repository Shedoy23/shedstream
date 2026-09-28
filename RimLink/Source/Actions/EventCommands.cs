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

        public abstract bool Execute();

        protected T Get<T>(string key, T fallback = default)
        {
            if (Data == null || !Data.ContainsKey(key)) return fallback;
            try { return (T)Convert.ChangeType(Data[key], typeof(T)); }
            catch { return fallback; }
        }

        // 2026-07-19: возвращаем результат TryExecute — движок может молча
        // отказать (нет точки высадки/условия воркера), раньше это глоталось.
        protected bool TryFireIncident(IncidentDef def)
        {
            if (def == null || HomeMap == null) return false;
            var parms = StorytellerUtility.DefaultParmsNow(def.category, HomeMap);
            parms.forced = true;
            return def.Worker.TryExecute(parms);
        }

        protected static bool FireGameConditionEvent(string defName, string message, MessageTypeDef messageType)
        {
            var def = DefDatabase<GameConditionDef>.GetNamed(defName, errorOnFail: false);
            if (def == null) return false;
            var map = Find.AnyPlayerHomeMap;
            if (map == null) return false;

            var conditions = map.gameConditionManager.ActiveConditions;
            for (int i = conditions.Count - 1; i >= 0; i--)
                if (conditions[i].def == def) { conditions[i].End(); break; }

            map.gameConditionManager.RegisterCondition(GameConditionMaker.MakeCondition(def, 60000));
            Messages.Message(message, messageType);
            return true;
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

        public override bool Execute()
        {
            if (HomeMap == null) return false;

            string key = Get("weather", "Rain");
            string defName = key;
            if (key == "thunderstorm") defName = "RainThunderstorm";

            if (GameConditionWeathers.Contains(defName))
                return FireAsGameCondition(defName);

            WeatherDef weather = DefDatabase<WeatherDef>.GetNamed(defName, errorOnFail: false);
            if (weather != null)
            {
                HomeMap.weatherManager.TransitionTo(weather);
                Messages.Message($"⛈ Погода изменена на: {weather.LabelCap}", MessageTypeDefOf.NeutralEvent);
                return true;
            }
            return FireAsGameCondition(defName);
        }

        private bool FireAsGameCondition(string defName)
        {
            var condDef = DefDatabase<GameConditionDef>.GetNamed(defName, errorOnFail: false);
            if (condDef == null) { RimLinkLog.Warn($"[RimLink] Weather: '{defName}' не найден"); return false; }

            var conditions = HomeMap.gameConditionManager.ActiveConditions;
            for (int i = conditions.Count - 1; i >= 0; i--)
                if (conditions[i].def == condDef) { conditions[i].End(); break; }

            HomeMap.gameConditionManager.RegisterCondition(GameConditionMaker.MakeCondition(condDef, 60000));
            Messages.Message($"☣️ {condDef.LabelCap} начались!", MessageTypeDefOf.ThreatBig);
            return true;
        }
    }

    // ────────────────────────────────────────────────────────────────────────────
    // Рейд (ИСПРАВЛЕНО: 100% LINQ выбор фракции, без Call API который ломается)
    // ────────────────────────────────────────────────────────────────────────────
    public class RaidEventCommand : BaseEventCommand
    {
        public RaidEventCommand(Dictionary<string, object> d) : base(d) { }

        public override bool Execute()
        {
            if (HomeMap == null) return false;

            int points = Math.Max(35, Math.Min(Get("points", 500), 3000));
            var def = DefDatabase<IncidentDef>.GetNamed("RaidEnemy", errorOnFail: false);
            if (def == null) return false;

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
                    RimLinkLog.Warn("[RimLink] RaidEvent: Не найдено фракций для рейда — отмена");
                    return false;
                }
            }

            bool fired = def.Worker.TryExecute(parms);
            if (fired)
                Messages.Message("🔴 Вражеский рейд начинается!", MessageTypeDefOf.ThreatBig);
            else
                RimLinkLog.Warn("[RimLink] RaidEvent: движок отказал (TryExecute=false) — рефанд");
            return fired;
        }
    }

    // ────────────────────────────────────────────────────────────────────────────
    // Грузовой под
    // ────────────────────────────────────────────────────────────────────────────
    public class ResourceDropCommand : BaseEventCommand
    {
        public ResourceDropCommand(Dictionary<string, object> d) : base(d) { }
        public override bool Execute()
        {
            var def = DefDatabase<IncidentDef>.GetNamed("ResourcePodCrash", errorOnFail: false);
            if (def != null && HomeMap != null)
                return TryFireIncident(def);
            RimLinkLog.Warn("[RimLink] ResourceDrop: Инцидент не найден");
            return false;
        }
    }

    // ────────────────────────────────────────────────────────────────────────────
    // Странник
    // ────────────────────────────────────────────────────────────────────────────
    public class WandererJoinCommand : BaseEventCommand
    {
        public WandererJoinCommand(Dictionary<string, object> d) : base(d) { }
        public override bool Execute()
        {
            var def = DefDatabase<IncidentDef>.GetNamed("WandererJoin", errorOnFail: false);
            if (def != null && HomeMap != null)
                return TryFireIncident(def);
            RimLinkLog.Warn("[RimLink] Wanderer: Инцидент не найден");
            return false;
        }
    }

    // ────────────────────────────────────────────────────────────────────────────
    // Животные
    // ────────────────────────────────────────────────────────────────────────────
    public class AnimalsEventCommand : BaseEventCommand
    {
        public AnimalsEventCommand(Dictionary<string, object> d) : base(d) { }

        public override bool Execute()
        {
            if (HomeMap == null) return false;
            bool aggressive = Get("aggressive", false);

            IncidentDef def = aggressive
                ? DefDatabase<IncidentDef>.GetNamed("ManhunterPack", errorOnFail: false)
                : DefDatabase<IncidentDef>.GetNamed("FarmAnimalsWanderIn", errorOnFail: false);

            if (def == null && !aggressive)
                def = DefDatabase<IncidentDef>.GetNamed("HerdMigration", errorOnFail: false);

            if (def != null)
            {
                bool fired = TryFireIncident(def);
                if (fired)
                    Messages.Message(aggressive ? "🐺 Животные в ярости!" : "🐾 Животные пришли в колонию!",
                                     aggressive ? MessageTypeDefOf.ThreatBig : MessageTypeDefOf.PositiveEvent);
                else
                    RimLinkLog.Warn("[RimLink] Animals: движок отказал (TryExecute=false) — рефанд");
                return fired;
            }
            RimLinkLog.Warn("[RimLink] Animals: Инцидент не найден");
            return false;
        }
    }

    // ────────────────────────────────────────────────────────────────────────────
    // Универсальный инцидент
    // ────────────────────────────────────────────────────────────────────────────
    public class FireIncidentCommand : ICommand
    {
        private readonly Dictionary<string, object> _data;
        public FireIncidentCommand(Dictionary<string, object> d) { _data = d; }

        public bool Execute()
        {
            Map map = Find.AnyPlayerHomeMap;
            if (map == null) { RimLinkLog.Warn("[RimLink] FireIncident: Нет карты"); return false; }

            string defName = "";
            if (_data.TryGetValue("incident_def", out var val1)) defName = val1?.ToString();
            if (string.IsNullOrEmpty(defName) && _data.TryGetValue("def_name", out var val2)) defName = val2?.ToString();
            if (string.IsNullOrEmpty(defName) && _data.TryGetValue("params", out var valParams))
            {
                if (valParams is Dictionary<string, object> dict && dict.TryGetValue("incident_def", out var v3))
                    defName = v3?.ToString();
            }

            if (string.IsNullOrEmpty(defName)) return false;

            var def = DefDatabase<IncidentDef>.GetNamed(defName, errorOnFail: false);
            if (def == null) return false;

            try
            {
                var parms = StorytellerUtility.DefaultParmsNow(def.category, map);
                parms.forced = true;

                // Читаем points из params если переданы; иначе ограничиваем дефолт
                // чтобы избежать зависания игры при богатой колонии
                float customPoints = -1f;
                if (_data.TryGetValue("points", out var topPoints)
                    && float.TryParse(topPoints?.ToString(), out float parsedTopPoints))
                    customPoints = parsedTopPoints;
                if (_data.TryGetValue("params", out var paramsVal) && paramsVal is Dictionary<string, object> pd)
                {
                    if (pd.TryGetValue("points", out var pv) && float.TryParse(pv?.ToString(), out float pp))
                        customPoints = pp;
                }
                if (customPoints > 0f)
                    parms.points = Math.Max(35f, Math.Min(customPoints, 3000f));
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

                bool fired = def.Worker.TryExecute(parms);
                if (fired)
                    Messages.Message($"🎲 {def.LabelCap} запущен!", MessageTypeDefOf.NeutralEvent);
                else
                    RimLinkLog.Warn($"[RimLink] FireIncident: движок отказал для '{defName}' (TryExecute=false) — рефанд");
                return fired;
            }
            catch (Exception e)
            {
                RimLinkLog.Err($"[RimLink] FireIncident: {e.Message}");
                return false;
            }
        }
    }
}
