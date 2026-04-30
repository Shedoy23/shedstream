using System;
using System.Collections.Generic;
using System.Linq;
using RimWorld;
using Verse;

namespace RimLink.Actions
{
    public interface ICommand
    {
        void Execute();
    }

    /// <summary>
    /// Общие helper-методы для команд.
    /// </summary>
    internal static class CommandHelpers
    {
        /// <summary>
        /// Получает def_name из словаря данных, проверяя несколько ключей.
        /// </summary>
        public static string GetDefName(Dictionary<string, object> data, params string[] keys)
        {
            foreach (var key in keys)
            {
                if (data.TryGetValue(key, out var val) && val != null)
                    return val.ToString();
            }
            return "";
        }

        /// <summary>
        /// Проверяет Biotech, находит пешку и GeneDef.
        /// </summary>
        public static bool TryGetGeneAndPawn(string username, string geneDefName, out Pawn pawn, out GeneDef geneDef)
        {
            pawn = null;
            geneDef = null;

            if (!ModsConfig.BiotechActive)
            {
                Log.Warning("[RimLink] Biotech DLC не активен");
                return false;
            }
            if (!RimLinkMod.PawnManager.TryGetPawn(username, out pawn) || pawn == null)
            {
                Log.Warning($"[RimLink] Пешка {username} не найдена");
                return false;
            }
            geneDef = DefDatabase<GeneDef>.GetNamed(geneDefName, errorOnFail: false);
            if (geneDef == null)
            {
                Log.Warning($"[RimLink] GeneDef '{geneDefName}' не найден");
                return false;
            }
            if (pawn.genes == null)
            {
                Log.Warning($"[RimLink] У пешки {username} нет генома");
                return false;
            }
            return true;
        }

        private static readonly HashSet<string> AnomalyPrefixes = new HashSet<string> { "Void_", "VOID_" };
        private static readonly HashSet<string> AnomalyKeywords = new HashSet<string>
        {
            "Ghoul", "Revenant", "Shambler", "Sightstealer", "Chimera",
            "Gorehulk", "Fleshmass", "Fleshbeast", "MetalhorrorImplantation",
            "Nociosphere", "HarbingerTree", "Devourer"
        };

        public static bool IsAnomalyEvent(string defName)
        {
            if (AnomalyPrefixes.Any(p => defName.StartsWith(p))) return true;
            return AnomalyKeywords.Any(k => defName.Contains(k));
        }
    }

    /// <summary>
    /// Фабрика команд. Связывает строку "type" из JSON с C# классом.
    /// </summary>
    public static class CommandFactory
    {
        public static ICommand Create(string type, Dictionary<string, object> data)
        {
            switch (type)
            {
                // ── Пешки ──────────────────────────────────────────────
                case "spawn_pawn":     return new SpawnPawnCommand(data);
                case "heal_pawn":      return new HealPawnCommand(data);
                case "resurrect_pawn": return new ResurrectPawnCommand(data);

                // ── Магазин / Инвентарь ────────────────────────────────
                case "equip_item":     return new EquipItemCommand(data);
                case "install_implant":return new InstallImplantCommand(data);
                case "train_skill":    return new TrainSkillCommand(data);

                // ── Ивенты (Специфические) ─────────────────────────────
                // Эти классы находятся в файле EventCommands.cs
                case "event_weather":  return new WeatherEventCommand(data);
                case "event_raid":     return new RaidEventCommand(data);
                case "event_drop":     return new ResourceDropCommand(data);
                case "event_wanderer": return new WandererJoinCommand(data);
                case "event_animals":  return new AnimalsEventCommand(data);

                // ── Навыки ─────────────────────────────────────────────
                case "set_passion":    return new SetPassionCommand(data);

                // ── Черты ──────────────────────────────────────────────
                case "add_trait":      return new AddTraitCommand(data);
                case "remove_trait":   return new RemoveTraitCommand(data);

                // ── Биотех (Ксенотипы/Гены) ────────────────────────────
                case "add_xenotype":   return new AddXenotypeCommand(data);
                case "add_gene":       return new AddGeneCommand(data);
                case "remove_gene":    return new RemoveGeneCommand(data);

                // ── Универсальный ивент (Вызывает любой IncidentDef по имени) ──
                case "fire_incident":  return new FireIncidentCommand(data);

                default:
                    Log.Warning($"[RimLink] Неизвестная команда: '{type}'");
                    return null;
            }
        }
    }

    public class AddTraitCommand : ICommand
    {
        private readonly string _username;
        private readonly string _traitDef;
        private readonly int _degree;

        public AddTraitCommand(Dictionary<string, object> d)
        {
            _username = d["username"].ToString();
            string raw = d.ContainsKey("trait_def") ? d["trait_def"].ToString()
                       : d.ContainsKey("def_name")  ? d["def_name"].ToString()
                       : "";

            if (raw.Contains(":") && !d.ContainsKey("degree"))
            {
                var parts = raw.Split(':');
                _traitDef = parts[0];
                int.TryParse(parts[1], out _degree);
            }
            else
            {
                _traitDef = raw;
                _degree   = d.ContainsKey("degree") ? Convert.ToInt32(d["degree"]) : 0;
            }
        }

        public void Execute()
        {
            if (!RimLinkMod.PawnManager.AddTrait(_username, _traitDef, _degree))
                Log.Warning($"[RimLink] AddTrait: Ошибка добавления {_traitDef}");
        }
    }

    public class RemoveTraitCommand : ICommand
    {
        private readonly string _username;
        private readonly string _traitDef;

        public RemoveTraitCommand(Dictionary<string, object> d)
        {
            _username = d["username"].ToString();
            _traitDef = d.ContainsKey("trait_def") ? d["trait_def"].ToString()
                      : d.ContainsKey("def_name")  ? d["def_name"].ToString()
                      : "";
        }

        public void Execute()
        {
            if (!RimLinkMod.PawnManager.RemoveTrait(_username, _traitDef))
                Log.Warning($"[RimLink] RemoveTrait: Ошибка удаления {_traitDef}");
        }
    }

    public class AddXenotypeCommand : ICommand
    {
        private readonly string _username;
        private readonly string _xenotypeDef;

        public AddXenotypeCommand(Dictionary<string, object> d)
        {
            _username    = d["username"].ToString();
            _xenotypeDef = d.ContainsKey("def_name") ? d["def_name"].ToString() : "";
        }

        public void Execute()
        {
            if (!ModsConfig.BiotechActive || string.IsNullOrEmpty(_xenotypeDef)) return;
            
            if (!RimLinkMod.PawnManager.TryGetPawn(_username, out var pawn) || pawn == null) return;

            var xeno = DefDatabase<XenotypeDef>.GetNamed(_xenotypeDef, errorOnFail: false);
            if (xeno == null) return;
            if (pawn.genes == null) return;

            try
            {
                // Удаляем старые ксеногены
                var old = new List<Gene>(pawn.genes.Xenogenes);
                foreach (var g in old) pawn.genes.RemoveGene(g);

                // Ставим новые
                if (xeno.genes != null)
                {
                    foreach (var geneDef in xeno.genes)
                        if (geneDef != null && !pawn.genes.HasActiveGene(geneDef))
                            pawn.genes.AddGene(geneDef, xenogene: true);
                }
                pawn.genes.xenotypeName = xeno.label ?? xeno.defName;

                Messages.Message($"🧬 {_username} стал {xeno.LabelCap}!", pawn, MessageTypeDefOf.PositiveEvent);
                RimLinkMod.PawnManager.ForceSyncPawn(_username);
            }
            catch (Exception e) { Log.Error($"[RimLink] AddXenotype: {e.Message}"); }
        }
    }

    public class AddGeneCommand : ICommand
    {
        private readonly string _username;
        private readonly string _geneDef;

        public AddGeneCommand(Dictionary<string, object> d)
        {
            _username = d["username"].ToString();
            _geneDef  = CommandHelpers.GetDefName(d, "def_name", "gene_def");
        }

        public void Execute()
        {
            if (!CommandHelpers.TryGetGeneAndPawn(_username, _geneDef, out var pawn, out var def)) return;
            if (pawn.genes.HasActiveGene(def)) return;

            pawn.genes.AddGene(def, xenogene: true);
            Messages.Message($"🧬 {_username} получил ген {def.LabelCap}!", pawn, MessageTypeDefOf.PositiveEvent);
            RimLinkMod.PawnManager.ForceSyncPawn(_username);
        }
    }

    public class RemoveGeneCommand : ICommand
    {
        private readonly string _username;
        private readonly string _geneDef;

        public RemoveGeneCommand(Dictionary<string, object> d)
        {
            _username = d["username"].ToString();
            _geneDef  = CommandHelpers.GetDefName(d, "def_name", "gene_def");
        }

        public void Execute()
        {
            if (!CommandHelpers.TryGetGeneAndPawn(_username, _geneDef, out var pawn, out var def)) return;
            var gene = pawn.genes.GetGene(def);
            if (gene == null) return;

            pawn.genes.RemoveGene(gene);
            Messages.Message($"🧬 {_username} потерял ген {def.LabelCap}!", pawn, MessageTypeDefOf.NeutralEvent);
            RimLinkMod.PawnManager.ForceSyncPawn(_username);
        }
    }
}