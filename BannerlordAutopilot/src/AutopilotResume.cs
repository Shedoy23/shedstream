using System;
using System.Collections.Generic;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.Library;

namespace BannerlordAutopilot
{
    /// <summary>Автовозврат после самовыключения (23.09.2026).
    ///
    /// Цель владельца — автопилот играет, пока стримера нет. Любое новое, ещё не
    /// встречавшееся состояние выключает автопилот (Disable с причиной) — и
    /// включить его некому. Здесь: когда отряд снова на свободной карте и прошло
    /// 20 с, включаемся сами. Не больше 3 раз за 30 минут — одна и та же ошибка
    /// по кругу не будет крутиться бесконечно. После F12 — никогда: это решение
    /// человека. Действовать в неизвестном состоянии автопилот по-прежнему не
    /// будет: возврат только на свободной карте, где он работает штатно.</summary>
    public partial class AutopilotBehavior
    {
        private const int AutoResumeDelaySeconds = 20;
        private const int AutoResumeLimit = 3;
        private static readonly TimeSpan AutoResumeWindow = TimeSpan.FromMinutes(30);

        private bool _resumeArmed;
        private DateTime _disabledAt;
        private string _disabledReason;
        private readonly Queue<DateTime> _resumes = new Queue<DateTime>();

        private void ArmAutoResume(string reason, bool wasApply)
        {
            bool byPlayer = reason != null && reason.StartsWith("выключено игроком", StringComparison.Ordinal);
            _resumeArmed = wasApply && !byPlayer;
            _disabledAt = Clock();
            _disabledReason = reason;
        }

        /// <summary>Вызывается из кадрового опроса, пока автопилот выключен.</summary>
        internal bool TryAutoResume()
        {
            if (!_resumeArmed || _mode != Mode.Off) return false;
            DateTime now = Clock();
            if (now - _disabledAt < TimeSpan.FromSeconds(AutoResumeDelaySeconds)) return false;
            MobileParty party = MobileParty.MainParty;
            if (party == null || !party.IsActive || UnsupportedState(party) != null || !IsOnFreeMap(party)
                || !MapIsActiveScreen() || InformationManager.IsAnyInquiryActive()) return false;
            while (_resumes.Count > 0 && now - _resumes.Peek() > AutoResumeWindow) _resumes.Dequeue();
            if (_resumes.Count >= AutoResumeLimit)
            {
                _resumeArmed = false;
                AutopilotLog.Write("АВТОВОЗВРАТ: лимит " + AutoResumeLimit + " за " + AutoResumeWindow.TotalMinutes
                    + " мин исчерпан — остаюсь выключенным до F11. Последняя причина: " + _disabledReason);
                return false;
            }
            string why = _disabledReason;
            if (!TryEnable(Mode.Apply, out string reason))
            {
                _resumeArmed = false;
                AutopilotLog.Write("АВТОВОЗВРАТ: включиться не удалось: " + reason);
                return false;
            }
            _resumes.Enqueue(now);
            StreamStatus.Note("Автопилот снова в строю после сбоя");
            AutopilotLog.Write("АВТОВОЗВРАТ: включился сам после «" + why + "» (" + _resumes.Count + " из "
                + AutoResumeLimit + " за " + AutoResumeWindow.TotalMinutes + " мин)");
            return true;
        }
    }
}
