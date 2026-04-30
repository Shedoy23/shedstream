using System;
using System.Collections.Generic;
using System.Linq;
using RimWorld;
using Verse;

namespace RimLink.Managers
{
    public class EventManager
    {
        // ── Ценовые тиры (исходя из реальной экономики: 50💎/мин базово) ────────
        // T0 Мирный      2 500💎 — зритель с короной (250/мин) копит ~10 мин
        // T1 Лёгкий      5 000💎 — ~20 мин
        // T2 Средний    10 000💎 — ~40 мин
        // T3 Тяжёлый    20 000💎 — ~80 мин
        // T4 Катастрофа 40 000💎 — ~160 мин (~2.7ч)
        // T5 Конец света 80 000💎 — ~320 мин (~5.3ч) — разрушитель мира, мегаторнадо
        private const int T0 =  2500;
        private const int T1 =  5000;
        private const int T2 = 10000;
        private const int T3 = 20000;
        private const int T4 = 40000;
        private const int T5 = 80000;

        // Тирофикация ивентов: defName → DangerTier
        // Используется для сортировки в магазине и визуальных бейджей
        private static readonly Dictionary<string, string> TierByDef = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            // T0 Мирный
            { "Clear", "T0" }, { "Overcast", "T0" }, { "Rain", "T0" }, { "FoggyRain", "T0" },
            { "Fog", "T0" }, { "Windy", "T0" }, { "SnowGentle", "T0" }, { "Rainbow", "T0" },
            { "VEE_FertileRains", "T0" }, { "VCE_FestiveSnow", "T0" },
            { "Aurora", "T0" }, { "Eclipse", "T0" }, { "SolarFlare", "T0" },
            { "PsychicSoothe", "T0" }, { "TraderCaravanArrival", "T0" }, { "OrbitalTraderArrival", "T0" },
            { "WandererJoin", "T0" }, { "WandererJoinAbasia", "T0" }, { "SelfTame", "T0" },
            { "ResourcePodCrash", "T0" }, { "FarmAnimalsWanderIn", "T0" }, { "TravelerGroup", "T0" },
            { "VisitorGroup", "T0" }, { "RaidFriendly", "T0" }, { "StrangerInBlackJoin", "T0" },
            { "HousekeeperCatWanderIn", "T0" }, { "WanderersSkylantern", "T0" },
            { "AnimaTreeSpawn", "T0" }, { "GauranlenPodSpawn", "T0" }, { "PoluxTreeSpawn", "T0" },
            { "BoomshroomSprout", "T0" }, { "AmbrosiaSprout", "T0" }, { "VEE_CropSprout", "T0" },
            { "VEE_CaravanAnimalsWanderIn", "T0" },
            { "VEE_BattleAnimalsWanderIn", "T0" }, { "VEE_WandererJoinsTraitor", "T0" },
            { "VEE_WildMenWanderIn", "T0" }, { "VAEWaste_WasteAnimalsWanderIn", "T0" },
            { "VSE_ManInTheCoatJoin", "T0" }, { "VSE_Reinforcements", "T0" },
            { "VTE_CaravanArriveForItems", "T0" }, { "VTE_Collectors", "T0" },
            { "VEE_Alphabeavers", "T0" }, { "VEE_AnimalPodCrash", "T0" }, { "Alphabeavers", "T0" },
            { "VEE_Cargopodsapparel", "T0" }, { "VEE_Cargopodsweapons", "T0" },
            { "VGE_EscapePodCrash", "T0" }, { "VME_JunkChunkDrop", "T0" }, { "ShipChunkDrop", "T0" },
            // T1 Лёгкий
            { "HerdMigration", "T1" }, { "ThrumboPasses", "T1" },
            { "FrenziedAnimals", "T1" }, { "AnimalInsanitySingle", "T1" },
            { "AnimalInsanityMass", "T1" }, { "AnimalInsanityMassPurple", "T1" },
            { "ManhunterAmbush", "T1" }, { "MeteoriteImpact", "T1" }, { "OrbitalDebris", "T1" },
            { "ShortCircuit", "T1" }, { "CropBlight", "T1" }, { "ColdSnap", "T1" },
            { "HeatWave", "T1" }, { "Flashstorm", "T1" }, { "Drought", "T1" },
            { "VEE_Drought", "T1" }, { "SeasonalFlooding", "T1" }, { "LavaEmergence", "T1" },
            { "LavaFlow", "T1" }, { "NoxiousHaze", "T1" }, { "BioluminescentSpores", "T1" },
            { "GillRot", "T1" }, { "CaravanDemand", "T1" }, { "CaravanMeeting", "T1" },
            { "RansomDemand", "T1" }, { "ProtectionFee", "T1" },
            { "CaravanArrivalTributeCollector", "T1" }, { "RefugeePodCrash", "T1" },
            { "ProblemCauser", "T1" }, { "VEE_SpaceBattle", "T1" }, { "VEE_MeteoriteShower", "T1" },
            { "VEE_MigratoryHerds", "T1" }, { "VEE_HuntingParty", "T1" },
            { "VEE_TidalFloodingIncident", "T1" }, { "VGE_AsteroidShower", "T1" },
            { "VGE_Comet", "T1" }, { "VGE_DustCloud", "T1" }, { "VGE_MicrometeorStorm", "T1" },
            { "VGE_SpaceDebris", "T1" }, { "AEXP_ExtintAnimalsPasses", "T1" },
            { "RM_VultureFlock", "T1" }, { "RM_WanderingMechanoids", "T1" },
            { "VSIE_OneNightStand", "T1" }, { "VPE_EltexMeteorite", "T1" },
            { "VRE_FungoidShipPartCrash", "T1" }, { "WildManWandersIn", "T1" },
            { "RainThunderstorm", "T1" }, { "DryThunderstorm", "T1" }, { "SnowHard", "T1" },
            { "Blizzard", "T1" }, { "Sandstorm", "T1" }, { "TorrentialRain", "T1" },

            // T2 Средний
            { "Infestation", "T2" }, { "Infestation_Jelly", "T2" }, { "DeepDrillInfestation", "T2" },
            { "ManhunterPack", "T2" }, { "ManhunterPackPurple", "T2" }, { "MechCluster", "T2" },
            { "DefoliatorShipPartCrash", "T2" }, { "PsychicEmanatorShipPartCrash", "T2" },
            { "HateChanters", "T2" }, { "WastepackInfestation", "T2" }, { "HarbingerTreeSpawn", "T2" },
            { "MetalhorrorImplantation", "T2" }, { "UnnaturalCorpseArrival", "T2" },
            { "VEE_Infestation", "T2" }, { "VEE_GlobalWarming", "T2" }, { "VEE_IceAge", "T2" },
            { "VEE_LongNight", "T2" }, { "VEE_Earthquake", "T2" }, { "VEE_TornadoAlley", "T2" },
            { "VEE_PsychicBloom", "T2" }, { "VEE_PsychicRain", "T2" }, { "VESWW_FullMapFlashstorm", "T2" },
            { "VESWW_MeteorStorm", "T2" }, { "VGE_GravitationalAnomaly", "T2" },
            { "VGE_ToxicDustCloud", "T2" }, { "VFEI_InfestedChunkCrash", "T2" },
            { "VFEI_InfestedModuleCrash", "T2" }, { "VFEI_InfestedPartCrash", "T2" },
            { "VFEI_LargeInfestation", "T2" }, { "VFEI_RoamingInsectoids", "T2" }, { "VFEI_BurrowSiege", "T2" },
            { "BloodRain", "T2" }, { "Ambush", "T2" }, { "ChickenVOID_DroneCustomizable", "T2" },
            { "GrayPall", "T2" }, { "BlindFog", "T2" }, { "NeutronFog", "T2" },
            { "ToxRain", "T2" }, { "PsychicDrone", "T2" }, { "VPE_Hurricane", "T2" },
            { "VPE_RadioactiveFog", "T2" },

            // T3 Тяжёлый
            { "RaidEnemy", "T3" }, { "RaidEnemyPurple", "T3" }, { "ShamblerAssault", "T3" },
            { "ShamblerSwarm", "T3" }, { "ChimeraAssault", "T3" }, { "GorehulkAssault", "T3" },
            { "FleshbeastAttack", "T3" }, { "DevourerAssault", "T3" }, { "GhoulAttack", "T3" },
            { "Revenant", "T3" }, { "RevenantEmergence", "T3" }, { "SightstealerArrival", "T3" },
            { "SightstealerSwarm", "T3" }, { "Nociosphere", "T3" }, { "PsychicRitualSiege", "T3" },
            { "Void_Stalker", "T3" }, { "CreepJoinerJoin", "T3" }, { "VREA_ArchonRaid", "T3" },
            { "VFED_Raid_Absolver", "T3" }, { "VFED_ImperialPatrol", "T3" }, { "VFEM_PillageRaid", "T3" },
            { "VFEI_HordeWaveRaid", "T3" }, { "Wolfein_DroneRaid", "T3" }, { "Wolfein_RebelRaid", "T3" },
            { "VOID_BlackTitan_ShipPartCrash", "T3" }, { "VOID_DefoliatorShipPartCrash", "T3" },
            { "VOID_DevilHound_ShipPartCrash", "T3" }, { "VOID_VolatileLeaper_ShipPartCrash", "T3" },
            { "VOID_N4Manhunter_DeathRow", "T3" }, { "VOID_N4Manhunter_RedZone", "T3" },
            { "VRE_BloodMoon", "T3" }, { "ToxicFallout", "T3" }, { "VolcanicAsh", "T3" },

            // T4 Катастрофа
            { "VESWW_OrbitalBombardement", "T4" }, { "VREA_PsychicStorm", "T4" },
            { "MegaTornado", "T4" }, { "VolcanicWinter", "T4" }, { "DeathPall", "T4" },
            { "MetalHell", "T4" }, { "VPEH_Bloodstorm", "T4" },

            // T5 Конец света
            { "Void_PlanetKiller", "T5" }, { "VESWW_WorldEnder", "T5" },
            { "VPE_MegaTornado", "T5" }, { "TornadoMega", "T5" }, { "WorldEndingEvent", "T5" },
        };

        // Базовые цены по категории (fallback если ивент не в PerEventPrices)
        private static readonly Dictionary<string, int> BasePriceByCategory = new Dictionary<string, int>
        {
            { "ThreatSmall",    T2 },  // насекомые, мелкие угрозы
            { "ThreatBig",      T3 },  // рейды, крупные угрозы
            { "OrbitalVisitor", T0 },  // торговцы — чисто польза
            { "FactionArrival", T1 },  // визиты фракций
            { "AllyAssistance", T1 },  // помощь союзников
            { "DiseaseHuman",   T1 },  // болезни людей
            { "DiseaseAnimal",  T1 },  // болезни животных
            { "Misc",           T1 },  // разное — по умолчанию лёгкое
            { "Weather",        T1 },  // погода — по умолчанию лёгкое
        };

        // Точечные цены для конкретных ивентов (переопределяют категорию)
        private static readonly Dictionary<string, int> PerEventPrices = new Dictionary<string, int>
        {
            // ── T0 Мирный ────────────────────────────────────────────────────
            { "TraderCaravanArrival",         T0 },
            { "OrbitalTraderArrival",         T0 },
            { "WandererJoin",                 T0 },
            { "WandererJoinAbasia",           T0 },
            { "SelfTame",                     T0 },
            { "ResourcePodCrash",             T0 },
            { "FarmAnimalsWanderIn",          T0 },
            { "TravelerGroup",                T0 },
            { "VisitorGroup",                 T0 },
            { "RaidFriendly",                 T0 },
            { "StrangerInBlackJoin",          T0 },
            { "HousekeeperCatWanderIn",       T0 },
            { "WanderersSkylantern",          T0 },
            { "AnimaTreeSpawn",               T0 },
            { "GauranlenPodSpawn",            T0 },
            { "PoluxTreeSpawn",               T0 },
            { "BoomshroomSprout",             T0 },
            { "AmbrosiaSprout",               T0 },
            { "VEE_CropSprout",               T0 },
            { "VEE_FertileRains",             T0 },
            { "VEE_CaravanAnimalsWanderIn",   T0 },
            { "VEE_BattleAnimalsWanderIn",    T0 },
            { "VEE_WandererJoinsTraitor",     T0 },
            { "VEE_WildMenWanderIn",          T0 },
            { "VAEWaste_WasteAnimalsWanderIn",T0 },
            { "VSE_ManInTheCoatJoin",         T0 },
            { "VSE_Reinforcements",           T0 },
            { "VTE_CaravanArriveForItems",    T0 },
            { "VTE_Collectors",               T0 },
            { "VEE_Alphabeavers",             T0 },
            { "VEE_AnimalPodCrash",           T0 },
            { "Alphabeavers",                 T0 },
            { "VEE_Cargopodsapparel",         T0 },
            { "VEE_Cargopodsweapons",         T0 },
            { "VGE_EscapePodCrash",           T0 },
            { "VME_JunkChunkDrop",            T0 },
            { "ShipChunkDrop",                T0 },

            // ── T1 Лёгкий ────────────────────────────────────────────────────
            { "HerdMigration",                T1 },
            { "ThrumboPasses",                T1 },
            { "FrenziedAnimals",              T1 },
            { "AnimalInsanitySingle",         T1 },
            { "AnimalInsanityMass",           T1 },
            { "AnimalInsanityMassPurple",     T1 },
            { "ManhunterAmbush",              T1 },
            { "MeteoriteImpact",              T1 },
            { "OrbitalDebris",                T1 },
            { "ShortCircuit",                 T1 },
            { "CropBlight",                   T1 },
            { "ColdSnap",                     T1 },
            { "HeatWave",                     T1 },
            { "Flashstorm",                   T1 },
            { "Drought",                      T1 },
            { "VEE_Drought",                  T1 },
            { "SeasonalFlooding",             T1 },
            { "LavaEmergence",                T1 },
            { "LavaFlow",                     T1 },
            { "NoxiousHaze",                  T1 },
            { "BioluminescentSpores",         T1 },
            { "GillRot",                      T1 },
            { "CaravanDemand",                T1 },
            { "CaravanMeeting",               T1 },
            { "RansomDemand",                 T1 },
            { "ProtectionFee",                T1 },
            { "CaravanArrivalTributeCollector",T1},
            { "RefugeePodCrash",              T1 },
            { "ProblemCauser",                T1 },
            { "VEE_SpaceBattle",              T1 },
            { "VEE_MeteoriteShower",          T1 },
            { "VEE_MigratoryHerds",           T1 },
            { "VEE_HuntingParty",             T1 },
            { "VEE_TidalFloodingIncident",    T1 },
            { "VGE_AsteroidShower",           T1 },
            { "VGE_Comet",                    T1 },
            { "VGE_DustCloud",                T1 },
            { "VGE_MicrometeorStorm",         T1 },
            { "VGE_SpaceDebris",              T1 },
            { "AEXP_ExtintAnimalsPasses",     T1 },
            { "RM_VultureFlock",              T1 },
            { "RM_WanderingMechanoids",       T1 },
            { "VSIE_OneNightStand",           T1 },
            { "VPE_EltexMeteorite",           T1 },
            { "VRE_FungoidShipPartCrash",     T1 },
            { "WildManWandersIn",             T1 },

            // ── T2 Средний ───────────────────────────────────────────────────
            { "Infestation",                  T2 },
            { "Infestation_Jelly",            T2 },
            { "DeepDrillInfestation",         T2 },
            { "ManhunterPack",                T2 },
            { "ManhunterPackPurple",          T2 },
            { "MechCluster",                  T2 },
            { "DefoliatorShipPartCrash",      T2 },
            { "PsychicEmanatorShipPartCrash", T2 },
            { "HateChanters",                 T2 },
            { "WastepackInfestation",         T2 },
            { "HarbingerTreeSpawn",           T2 },
            { "MetalhorrorImplantation",      T2 },
            { "UnnaturalCorpseArrival",       T2 },
            { "VEE_Infestation",              T2 },
            { "VEE_GlobalWarming",            T2 },
            { "VEE_IceAge",                   T2 },
            { "VEE_LongNight",                T2 },
            { "VEE_Earthquake",               T2 },
            { "VEE_TornadoAlley",             T2 },
            { "VEE_PsychicBloom",             T2 },
            { "VEE_PsychicRain",              T2 },
            { "VESWW_FullMapFlashstorm",      T2 },
            { "VESWW_MeteorStorm",            T2 },
            { "VGE_GravitationalAnomaly",     T2 },
            { "VGE_ToxicDustCloud",           T2 },
            { "VFEI_InfestedChunkCrash",      T2 },
            { "VFEI_InfestedModuleCrash",     T2 },
            { "VFEI_InfestedPartCrash",       T2 },
            { "VFEI_LargeInfestation",        T2 },
            { "VFEI_RoamingInsectoids",       T2 },
            { "VFEI_BurrowSiege",             T2 },
            { "BloodRain",                    T2 },
            { "Ambush",                       T2 },
            { "ChickenVOID_DroneCustomizable",T2 },

            // ── T3 Тяжёлый ───────────────────────────────────────────────────
            { "RaidEnemy",                    T3 },
            { "RaidEnemyPurple",              T3 },
            { "ShamblerAssault",              T3 },
            { "ShamblerSwarm",                T3 },
            { "ChimeraAssault",               T3 },
            { "GorehulkAssault",              T3 },
            { "FleshbeastAttack",             T3 },
            { "DevourerAssault",              T3 },
            { "GhoulAttack",                  T3 },
            { "Revenant",                     T3 },
            { "RevenantEmergence",            T3 },
            { "SightstealerArrival",          T3 },
            { "SightstealerSwarm",            T3 },
            { "Nociosphere",                  T3 },
            { "PsychicRitualSiege",           T3 },
            { "Void_Stalker",                 T3 },
            { "CreepJoinerJoin",              T3 },
            { "VREA_ArchonRaid",              T3 },
            { "VFED_Raid_Absolver",           T3 },
            { "VFED_ImperialPatrol",          T3 },
            { "VFEM_PillageRaid",             T3 },
            { "VFEI_HordeWaveRaid",           T3 },
            { "Wolfein_DroneRaid",            T3 },
            { "Wolfein_RebelRaid",            T3 },
            { "VOID_BlackTitan_ShipPartCrash",T3 },
            { "VOID_DefoliatorShipPartCrash", T3 },
            { "VOID_DevilHound_ShipPartCrash",T3 },
            { "VOID_VolatileLeaper_ShipPartCrash", T3 },
            { "VOID_N4Manhunter_DeathRow",    T3 },
            { "VOID_N4Manhunter_RedZone",     T3 },
            { "VRE_BloodMoon",                T3 },

            // ── T4 Катастрофа ─────────────────────────────────────────────────
            { "VESWW_OrbitalBombardement",    T4 },
            { "VREA_PsychicStorm",            T4 },
            { "MegaTornado",                  T4 },

            // ── T5 Конец света ────────────────────────────────────────────────
            { "Void_PlanetKiller",            T5 },  // Разрушитель миров (Anomaly)
            { "VESWW_WorldEnder",             T5 },  // Конец света из VESWW
            { "VPE_MegaTornado",              T5 },  // Мегаторнадо из VPE
            { "TornadoMega",                  T5 },  // Мегаторнадо альтернативное имя
            { "WorldEndingEvent",             T5 },  // Общий ивент конца света
        };

        // Блэклист — ивенты которые НЕЛЬЗЯ вызывать вручную (только технические/квестовые)
        private static readonly HashSet<string> Blacklist = new HashSet<string>
        {
            // ── Технические/квестовые ванильные ──────────────────────────────
            "QuestSummoning", "GiveQuest", "GiveQuest_Standard", "GiveQuest_Anomaly",
            "PawnHangingGive",

            // ── Идут через GameCondition (weather_*), не дублируем ────────────
            "Aurora", "Eclipse", "ToxicFallout", "VolcanicWinter",
            "SolarFlare", "PsychicDrone", "PsychicSoothe", "NeutronFog",
            "DeathPall",

            // ── Anomaly — ТОЛЬКО технические триггеры прогресса монолита ──────
            "VoidCuriosity",
            "Void_Contact",
            "WarpedObelisk_Abductor", "WarpedObelisk_Duplicator", "WarpedObelisk_Mutator",
            "MonolithMigration",
            "PitGate",
            "FleshmassHeart",
            "UnnaturalDarkness",
            "GoldenCubeArrival",
            "MysteriousCargoCube", "MysteriousCargoRevenantSpine", "MysteriousCargoUnnaturalCorpse",

            // ── Внутренние варианты/дубли ─────────────────────────────────────
            "DroughtInitial",
            "ProtectionFeeLTS",
            "RefugeePodCrash_Baby",
            "RefugeePodCrash_Ghoul",
            "ShamblerSwarmAnimals",
            "SmallShamblerSwarm",
            "CreepJoinerJoin_Metalhorror",
            "DevourerWaterAssault",
            "HarbingerTreeProvoked",
            "GameEndedWanderersJoin",

            // ── Дубли из модов ──────────────────────────────────────────────
            "ChickenVOID_SolarFlare",
            "ChickenVOID_ToxicFalloutCustomizable",
            "VEE_Aurora",
            "VGE_SpaceSolarFlare",

            // ── Технические моды ──────────────────────────────────────────────
            "CBC_Incident",
            "Isekai_HuntSpawn",
            "Isekai_WorldBossSpawn",

            // ── VRE квестовые ─────────────────────────────────────────────────
            "VRE_ChestburstWandererJoinQuest",
        };

        // Эмодзи для IncidentDef
        private static readonly Dictionary<string, string> IncidentEmojis = new Dictionary<string, string>
        {
            { "RaidEnemy",                  "⚔️"  },
            { "RaidFriendly",               "🤝"  },
            { "TraderCaravanArrival",        "🐪"  },
            { "OrbitalTraderArrival",        "🛸"  },
            { "WandererJoin",               "🧍"  },
            { "ResourcePodCrash",           "📦"  },
            { "ManhunterPack",              "🐺"  },
            { "SelfTame",                   "🐾"  },
            { "Infestation",                "🪲"  },
            { "ShortCircuit",               "⚡"  },
            { "HerdMigration",              "🦌"  },
            { "DeepDrillInfestation",       "🪲"  },
            { "PsychicInsanityPulse",       "😵"  },
            { "PsychicSuppression",         "😔"  },
            { "CrashedShipPart",            "🚀"  },
            { "DefoliatorShipPartCrash",    "☠️"  },
            { "PsychicEmanatorShipPartCrash","😵" },
            { "MechCluster",                "🤖"  },
            { "DiseaseAnimal",              "🐄"  },
            { "NociosphereArrival",         "💀"  },
        };

        // Цвета тиров для фронтенда
        private static readonly Dictionary<string, string> TierColors = new Dictionary<string, string>
        {
            { "T0", "#4ade80" }, { "T1", "#60a5fa" }, { "T2", "#fbbf24" },
            { "T3", "#fb923c" }, { "T4", "#f87171" }, { "T5", "#dc2626" },
        };

        private static readonly Dictionary<string, string> TierLabels = new Dictionary<string, string>
        {
            { "T0", "Мирный" }, { "T1", "Лёгкий" }, { "T2", "Средний" },
            { "T3", "Тяжёлый" }, { "T4", "Катастрофа" }, { "T5", "Конец света" },
        };

        private static string GetTierForIncident(IncidentDef def)
        {
            if (def == null) return "T1";
            
            // Сначала проверяем по словарю TierByDef
            if (TierByDef.TryGetValue(def.defName, out string tier))
            {
                return tier;
            }
            
            // Если ивента нет в TierByDef, определяем через категорию
            if (def.category != null && BasePriceByCategory.TryGetValue(def.category.defName, out int bp))
            {
                switch (bp)
                {
                    case T2: return "T2";
                    case T3: return "T3";
                    case T4: return "T4";
                    default:  return "T1";
                }
            }
            
            // Fallback для неизвестных категорий
            return "T1";
        }

        /// <summary>
        /// Проверяет, можно ли вызвать ивент вручную.
        /// Объединяет все проверки фильтрации в одном месте.
        /// </summary>
        private static bool IsValidIncident(IncidentDef def)
        {
            if (def == null || string.IsNullOrEmpty(def.defName)) return false;
            if (def.category == null || def.workerClass == null) return false;
            if (string.IsNullOrEmpty(def.label) || def.label.Length < 2) return false;
            if (Blacklist.Contains(def.defName)) return false;
            if (def.defName.EndsWith("_Internal") || def.defName.EndsWith("_Test")) return false;
            if (def.defName.StartsWith("Debug")) return false;
            if (def.defName.IndexOf("GiveQuest", System.StringComparison.OrdinalIgnoreCase) >= 0) return false;
            if (def.defName.IndexOf("QuestGive", System.StringComparison.OrdinalIgnoreCase) >= 0) return false;
            return true;
        }

        public List<object> BuildEventCatalog(PriceSettings prices)
        {
            var result = new List<object>();
            var seenIds     = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var seenLabels  = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            // 1. IncidentDef — умный фильтр
            foreach (var def in DefDatabase<IncidentDef>.AllDefs.OrderBy(d => d.label))
            {
                try
                {
                    if (!IsValidIncident(def)) continue;
                    if (!prices.IsEnabled(def.defName)) continue;
                    if (!seenIds.Add(def.defName)) continue;
                    // Пропускаем ивенты с одинаковым лейблом (дубли из разных модов)
                    string labelKey = (def.LabelCap.ToString() ?? "").Trim();
                    if (!string.IsNullOrEmpty(labelKey) && !seenLabels.Add(labelKey)) continue;

                    string catName    = def.category.defName;
                    string tier       = GetTierForIncident(def);
                    int    basePrice  = PerEventPrices.TryGetValue(def.defName, out int ep)
                                        ? ep
                                        : BasePriceByCategory.TryGetValue(catName, out int bp) ? bp : T1;
                    int    finalPrice = prices.GetPrice(def.defName, "incident", basePrice);
                    string emoji      = IncidentEmojis.TryGetValue(def.defName, out string e) ? e : "🎲";
                    string tierColor  = TierColors.TryGetValue(tier, out string tc) ? tc : "#adadb8";
                    string tierLabel  = TierLabels.TryGetValue(tier, out string tl) ? tl : "";

                    string defLabel = def.LabelCap.ToString();

                    // Очки угрозы по тиру — фиксированные, не зависят от богатства колонии.
                    // Ограничивает размер рейда и предотвращает фриз от патфайндинга 80+ рейдеров.
                    // T0/T1 — 0 (не боевые), T2 — 800, T3 — 2000, T4 — 4000, T5 — 6000
                    int threatPoints = tier switch
                    {
                        "T2" => 800,
                        "T3" => 2000,
                        "T4" => 4000,
                        "T5" => 6000,
                        _    => 0,   // T0/T1 — не боевые, points не нужен
                    };

                    var incidentParams = new Dictionary<string, object> { { "incident_def", def.defName } };
                    if (threatPoints > 0) incidentParams["points"] = threatPoints;

                    result.Add(new Dictionary<string, object>
                    {
                        { "id",          def.defName  },
                        { "name",        emoji + " " + defLabel },
                        { "cost",        finalPrice   },
                        { "cmd",         "fire_incident" },
                        { "params",      incidentParams },
                        { "category",    catName      },
                        { "tier",        tier         },
                        { "tier_label",  tierLabel    },
                        { "tier_color",  tierColor    },
                    });
                }
                catch (Exception ex)
                {
                    Log.Warning($"[RimLink] BuildEventCatalog: пропущен IncidentDef '{def?.defName}' — {ex.Message}");
                }
            }

            Log.Message($"[RimLink] EventCatalog: {result.Count} ивентов");
            return result;
        }
    }
}