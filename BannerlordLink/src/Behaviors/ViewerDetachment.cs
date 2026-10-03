using System;
using System.Collections.Generic;
using TaleWorlds.Core;
using TaleWorlds.Engine;
using TaleWorlds.Library;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Behaviors
{
    /// <summary>03.10, владелец: «Вблизи» — герой подбегает, не бьёт, отходит на 5–7 м и
    /// снова (лог: сотни переходов «в упор → сближение» с той же целью). Герой оставался
    /// бойцом своего строя: у него было место в сетке, и строй (с RBM AI — каждый кадр)
    /// тянул его туда, а наш scripted-приказ — к врагу.
    ///
    /// Идея из движка (так же поступает BLT, код свой): пустой «отряд-отцепление»
    /// (IDetachment), к которому строй подключается, а герой выводится из сетки
    /// (Formation.DetachUnit). Своего веса у него нет (MinValue) — движок не набирает в
    /// него чужих бойцов; кадра места нет (GetAgentFrame = null) — тянуть героя некуда.
    /// Герой формально остаётся в своём строю (без переноса между строями — это давало
    /// вылеты и перебивалось генералом), но вне его сетки.
    ///
    /// Защита от вылета: DetachUnit только когда у бойца реальное место в сетке
    /// (FormationFileIndex/RankIndex ≥ 0): с -1 движок падает в LineFormation.RemoveUnit.
    /// Без места в сетке строй и так его не держит — ставим только Detachment.</summary>
    internal sealed class ViewerDetachment : IDetachment
    {
        private static readonly Dictionary<Formation, ViewerDetachment> ByFormation =
            new Dictionary<Formation, ViewerDetachment>();

        private readonly MBList<Formation> _users = new MBList<Formation>();
        private readonly List<Agent> _agents = new List<Agent>();
        private readonly Formation _formation;

        private ViewerDetachment(Formation formation) { _formation = formation; }

        /// <summary>Вывести бойца из сетки его строя. false — строя нет (нечего отцеплять).</summary>
        internal static bool Unhook(Agent agent)
        {
            var formation = agent?.Formation;
            if (formation == null) return false;
            if (agent.Detachment is ViewerDetachment) return true;
            if (!ByFormation.TryGetValue(formation, out var d))
            {
                d = new ViewerDetachment(formation);
                formation.JoinDetachment(d);
                ByFormation[formation] = d;
            }
            if (agent.Detachment != null) agent.Detachment.RemoveAgent(agent); // чужое (машина и т.п.)
            var unit = (IFormationUnit)agent;
            if (unit.FormationFileIndex >= 0 && unit.FormationRankIndex >= 0)
                formation.DetachUnit(agent, true);
            d._agents.Add(agent);
            agent.Detachment = d;
            agent.SetDetachmentWeight(1f);
            return true;
        }

        /// <summary>Вернуть бойца в сетку строя (приказ «в строй» или снятие приказа).
        /// Мёртвого/удалённого не возвращаем — только снимаем учёт.</summary>
        internal static void Rehook(Agent agent, bool alive)
        {
            if (agent == null || !(agent.Detachment is ViewerDetachment d)) return;
            d._agents.Remove(agent);
            agent.Detachment = null;
            if (alive && agent.Formation == d._formation) d._formation.AttachUnit(agent);
            if (d._agents.Count == 0)
            {
                ByFormation.Remove(d._formation);
                d._formation.LeaveDetachment(d);
            }
        }

        /// <summary>Конец миссии: формации исчезают вместе с ней.</summary>
        internal static void Reset() => ByFormation.Clear();

        internal static bool IsHooked(Agent agent) => agent?.Detachment is ViewerDetachment;

        // ── IDetachment: пустой «отряд», который движок никогда не наполняет и не ведёт ──
        public MBReadOnlyList<Formation> UserFormations => _users;
        public bool IsLoose => true;
        public bool IsAgentUsingOrInterested(Agent agent) => _agents.Contains(agent);
        public float? GetWeightOfNextSlot(BattleSideEnum side) => null;
        public float GetDetachmentWeight(BattleSideEnum side) => float.MinValue;
        public float ComputeAndCacheDetachmentWeight(BattleSideEnum side) => float.MinValue;
        public float GetDetachmentWeightFromCache() => float.MinValue;
        public void GetSlotIndexWeightTuples(List<(int, float)> slotIndexWeightTuples) { }
        public bool IsSlotAtIndexAvailableForAgent(int slotIndex, Agent agent) => false;
        public bool IsAgentEligible(Agent agent) => false;
        public void AddAgentAtSlotIndex(Agent agent, int slotIndex) { }
        public Agent GetMovingAgentAtSlotIndex(int slotIndex) => null;
        public void MarkSlotAtIndex(int slotIndex) { }
        public bool IsDetachmentRecentlyEvaluated() => true;
        public void UnmarkDetachment() { }
        public float? GetWeightOfAgentAtNextSlot(List<Agent> candidates, out Agent match) { match = null; return null; }
        public float? GetWeightOfAgentAtNextSlot(List<(Agent, float)> agentTemplateScores, out Agent match) { match = null; return null; }
        public float GetTemplateWeightOfAgent(Agent candidate) => float.MinValue;
        public List<float> GetTemplateCostsOfAgent(Agent candidate, List<float> oldValue) => oldValue ?? new List<float>();
        public float GetExactCostOfAgentAtSlot(Agent candidate, int slotIndex) => float.MaxValue;
        public float GetWeightOfOccupiedSlot(Agent detachedAgent) => float.MinValue;
        public float? GetWeightOfAgentAtOccupiedSlot(Agent detachedAgent, List<Agent> candidates, out Agent match) { match = null; return null; }
        public bool IsStandingPointAvailableForAgent(Agent agent) => false;
        public void AddAgent(Agent agent, int slotIndex, Agent.AIScriptedFrameFlags customFlags = Agent.AIScriptedFrameFlags.None) { }
        public void RemoveAgent(Agent detachedAgent) { _agents.Remove(detachedAgent); }
        public int GetNumberOfUsableSlots() => 0;
        public void FormationStartUsing(Formation formation) { if (!_users.Contains(formation)) _users.Add(formation); }
        public void FormationStopUsing(Formation formation) { _users.Remove(formation); }
        public bool IsUsedByFormation(Formation formation) => _users.Contains(formation);
        public WorldFrame? GetAgentFrame(Agent detachedAgent) => null;
        public void ResetEvaluation() { }
        public bool IsEvaluated() => true;
        public void SetAsEvaluated() { }
        public void OnFormationLeave(Formation formation)
        {
            // Строй уходит (распущен, перестроен): герои возвращаются под обычный ИИ, без сетки.
            foreach (var a in _agents.ToArray())
                if (a.Detachment == this) a.Detachment = null;
            _agents.Clear();
            ByFormation.Remove(_formation);
        }
    }
}
