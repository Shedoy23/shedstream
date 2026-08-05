using System;
using System.Collections.Generic;
using RimWorld;
using Verse;
using RimLink.Components;

namespace RimLink.Actions
{
    // ────────────────────────────────────────────────────────────────────────────
    // Создание пешки зрителя
    // ────────────────────────────────────────────────────────────────────────────
    public class SpawnPawnCommand : ICommand
    {
        private readonly string _username;

        public SpawnPawnCommand(Dictionary<string, object> d)
        {
            _username = d["username"].ToString();
        }

        public bool Execute()
        {
            if (Find.AnyPlayerHomeMap == null)
            {
                Log.Warning("[RimLink] SpawnPawn: нет карты колонии");
                return false;
            }

            if (RimLinkMod.PawnManager.HasPawn(_username))
            {
                Log.Message($"[RimLink] SpawnPawn: у {_username} уже есть пешка");
                return false;
            }

            Map map = Find.AnyPlayerHomeMap;

            var request = new PawnGenerationRequest(
                kind:                       PawnKindDefOf.Colonist,
                faction:                    Faction.OfPlayer,
                context:                    PawnGenerationContext.NonPlayer,
                tile:                       -1,
                forceGenerateNewPawn:       true,
                allowDead:                  false,
                allowDowned:                false,
                canGeneratePawnRelations:   true,
                mustBeCapableOfViolence:    false,
                colonistRelationChanceFactor: 0f,
                forceAddFreeWarmLayerIfNeeded: true
            );

            Pawn pawn = PawnGenerator.GeneratePawn(request);

            // Имя: First='Twitch', Nick=username, Last='RimLink'
            // Это позволяет фильтровать пешек зрителей при синхронизации
            pawn.Name = new NameTriple("Twitch", _username, "RimLink");
            ViewerIdentity.Ensure(pawn, _username);
            pawn.SetFaction(Faction.OfPlayer);

            if (ModsConfig.IdeologyActive)
            {
                try
                {
                    var ideo = Faction.OfPlayer.ideos?.PrimaryIdeo;
                    if (ideo != null) pawn.ideo?.SetIdeo(ideo);
                }
                catch { }
            }

            IntVec3 spot;
            if (!RCellFinder.TryFindRandomPawnEntryCell(out spot, map, 0.5f))
                if (!CellFinder.TryFindRandomCellNear(map.Center, map, 30,
                        c => c.Standable(map) && !c.Fogged(map), out spot))
                    spot = CellFinder.RandomNotEdgeCell(8, map);
            GenSpawn.Spawn(pawn, spot, map);

            RimLinkMod.PawnManager.Register(_username, pawn);
            RimLinkMod.PawnManager.ForceSyncPawn(_username);

            try
            {
                Messages.Message(
                    $"✨ {_username} присоединился к колонии!",
                    pawn, MessageTypeDefOf.PositiveEvent);
            }
            catch (Exception ex)
            {
                Log.Warning($"[RimLink] SpawnPawn message: {ex.Message}");
            }
            return true;
        }
    }

    // ────────────────────────────────────────────────────────────────────────────
    // Лечение пешки
    // ────────────────────────────────────────────────────────────────────────────
    public class HealPawnCommand : ICommand
    {
        private readonly string _username;

        public HealPawnCommand(Dictionary<string, object> d)
        {
            _username = d["username"].ToString();
        }

        public bool Execute()
        {
            bool ok = RimLinkMod.PawnManager.HealPawn(_username);
            if (!ok) Log.Warning($"[RimLink] HealPawn: пешка {_username} не найдена или мертва");
            return ok;
        }
    }

    // ────────────────────────────────────────────────────────────────────────────
    // Воскрешение пешки
    // ────────────────────────────────────────────────────────────────────────────
    public class ResurrectPawnCommand : ICommand
    {
        private readonly string _username;

        public ResurrectPawnCommand(Dictionary<string, object> d)
        {
            _username = d["username"].ToString();
        }

        public bool Execute()
        {
            bool ok = RimLinkMod.PawnManager.ResurrectPawn(_username);
            if (!ok) Log.Warning($"[RimLink] ResurrectPawn: не удалось воскресить {_username}");
            return ok;
        }
    }

    // ────────────────────────────────────────────────────────────────────────────
    // Выдать предмет (одежда или оружие)
    // ────────────────────────────────────────────────────────────────────────────
    public class EquipItemCommand : ICommand
    {
        private readonly string _username;
        private readonly string _defName;

        public EquipItemCommand(Dictionary<string, object> d)
        {
            _username = d["username"].ToString();
            _defName  = d["def_name"].ToString();
        }

        public bool Execute()
        {
            bool ok = RimLinkMod.PawnManager.EquipItem(_username, _defName);
            if (!ok) Log.Warning($"[RimLink] EquipItem: не удалось надеть {_defName} на {_username}");
            return ok;
        }
    }

    // ────────────────────────────────────────────────────────────────────────────
    // Установить имплант
    // ────────────────────────────────────────────────────────────────────────────
    public class InstallImplantCommand : ICommand
    {
        private readonly string _username;
        private readonly string _defName;
        private readonly string _partHint;

        public InstallImplantCommand(Dictionary<string, object> d)
        {
            _username = d["username"].ToString();
            _defName  = d["def_name"].ToString();
            _partHint = d.ContainsKey("part_hint") ? d["part_hint"]?.ToString() ?? "" : "";
        }

        public bool Execute()
        {
            bool ok = RimLinkMod.PawnManager.InstallImplant(_username, _defName, _partHint);
            if (!ok) Log.Warning($"[RimLink] InstallImplant: не удалось установить {_defName} для {_username}");
            return ok;
        }
    }

    // ────────────────────────────────────────────────────────────────────────────
    // Прокачать навык нейротренером
    // ────────────────────────────────────────────────────────────────────────────
    public class TrainSkillCommand : ICommand
    {
        private readonly string _username;
        private readonly string _defName; // defName нейротренера, напр. "Neurotrainer_Shooting"

        public TrainSkillCommand(Dictionary<string, object> d)
        {
            _username = d["username"].ToString();
            _defName  = d["def_name"].ToString();
        }

        public bool Execute()
        {
            bool ok = RimLinkMod.PawnManager.TrainSkill(_username, _defName);
            if (!ok) Log.Warning($"[RimLink] TrainSkill: не удалось применить нейротренер {_defName} для {_username}");
            return ok;
        }
    }

    // ────────────────────────────────────────────────────────────────────────────
    // Установить уровень страсти к навыку
    // passion: 0 = None, 1 = Minor (⭐), 2 = Major (🔥)
    // ────────────────────────────────────────────────────────────────────────────
    public class SetPassionCommand : ICommand
    {
        private readonly string _username;
        private readonly string _skillDef;
        private readonly int    _passion;

        public SetPassionCommand(Dictionary<string, object> d)
        {
            _username = d["username"].ToString();
            _skillDef = d.ContainsKey("skill_def") ? d["skill_def"].ToString()
                      : d.ContainsKey("def_name")  ? d["def_name"].ToString()
                      : "";
            _passion  = d.ContainsKey("passion") ? Convert.ToInt32(d["passion"]) : 1;
        }

        public bool Execute()
        {
            bool ok = RimLinkMod.PawnManager.SetPassion(_username, _skillDef, _passion);
            if (!ok) Log.Warning($"[RimLink] SetPassion: не удалось установить страсть {_skillDef} для {_username}");
            return ok;
        }
    }
}
