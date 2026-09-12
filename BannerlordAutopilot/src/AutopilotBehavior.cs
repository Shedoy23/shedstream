using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Core;
using TaleWorlds.Library;

namespace BannerlordAutopilot
{
    /// <summary>Прототип автопилота партии игрока.
    ///
    /// ЧТО ОН ДОКАЗЫВАЕТ. Что цель партии игрока может выбрать ШТАТНЫЙ мозг
    /// движка, а не мод. Поэтому здесь нет ни одной собственной оценки целей:
    /// мод только вызывает для MainParty тот же сбор оценок, который игра
    /// каждый час делает для партий лордов, и применяет его результат.
    ///
    /// ПОЧЕМУ БЕЗ HARMONY. Штатный выбор целей закрыт для партии игрока
    /// сравнением `mobileParty != MobileParty.MainParty` внутри
    /// AiPartyThinkBehavior.PartyHourlyAiTick (1.4.8, подтверждено
    /// декомпиляцией). Патчить чужой метод не понадобилось: все нужные вызовы
    /// публичны, поэтому мод делает ту же работу сам и ровно для одной партии.
    /// Ни одна другая партия в игре не затронута — это главное отличие от
    /// правки общего метода.
    ///
    /// ЧЕГО ЗДЕСЬ НАМЕРЕННО НЕТ (вне области первого прототипа):
    ///   * осада и штурм — у партии игрока не исполняется переход «доехал →
    ///     сажусь в осаду» (`GetBesiegeBehavior` закрыт условием
    ///     `!IsMainParty`), поэтому такие решения прототип не применяет;
    ///   * рейд, оборона поселения, преследование — те же причины плюс
    ///     отключённая для игрока инициатива;
    ///   * боевой автопилот — отдельная задача;
    ///   * автоматический выход из поселения — движок для партии игрока его
    ///     не делает (`CheckExitingSettlementParallel` пропускает MainParty),
    ///     поэтому вход в поселение прототип считает ОСТАНОВКОЙ, а не
    ///     проблемой, которую надо обойти.
    ///
    /// Полный разбор: docs/BANNERLORD_AUTOPILOT_RESEARCH_2026-09-12.md</summary>
    public class AutopilotBehavior : CampaignBehaviorBase
    {
        internal enum Mode
        {
            /// <summary>Выключен. Единственное состояние после загрузки сейва.</summary>
            Off,
            /// <summary>Только смотрим, что предлагает штатный AI. Ничего не применяем.</summary>
            Observe,
            /// <summary>Применяем выбранное решение.</summary>
            Apply
        }

        internal static AutopilotBehavior Instance { get; private set; }

        private Mode _mode = Mode.Off;

        // ── Снимок чужого состояния ──────────────────────────────────────────
        // Флаги AI сохраняемые: если оставить их изменёнными, они переживут
        // сейв и будут выглядеть как «так было всегда». Поэтому снимок живёт в
        // нашем сейв-блоке и восстанавливается даже после перезапуска игры.
        private bool _snapshotTaken;
        private bool _savedDoNotMakeNewDecisions;

        private int _decisionsThisSession;
        private int _settlementVisitsThisSession;
        private string _lastAppliedDescription = "—";

        internal Mode CurrentMode => _mode;

        public override void RegisterEvents()
        {
            Instance = this;
            CampaignEvents.HourlyTickEvent.AddNonSerializedListener(this, OnHourlyTick);
            CampaignEvents.OnGameLoadFinishedEvent.AddNonSerializedListener(this, OnGameLoadFinished);
        }

        public override void SyncData(IDataStore dataStore)
        {
            dataStore.SyncData("shedautopilot_snapshotTaken", ref _snapshotTaken);
            dataStore.SyncData("shedautopilot_savedDoNotMakeNewDecisions", ref _savedDoNotMakeNewDecisions);
        }

        /// <summary>После загрузки автопилот ВСЕГДА выключен — требование
        /// спецификации. Заодно чиним то, что могло остаться от прошлого
        /// сеанса: если игрок сохранился при включённом автопилоте, флаг
        /// «не принимать решения» лежит в сейве уже нашим значением.</summary>
        private void OnGameLoadFinished()
        {
            _mode = Mode.Off;
            _decisionsThisSession = 0;
            _settlementVisitsThisSession = 0;

            AutopilotLog.Session("загрузка сохранения; автопилот выключен");
            LogCurrentFlags("после загрузки");

            if (_snapshotTaken)
            {
                MobileParty party = MobileParty.MainParty;
                if (party?.Ai != null)
                {
                    party.Ai.SetDoNotMakeNewDecisions(_savedDoNotMakeNewDecisions);
                    AutopilotLog.Write("восстановлен снимок прошлого сеанса: DoNotMakeNewDecisions="
                                       + _savedDoNotMakeNewDecisions);
                }
                _snapshotTaken = false;
            }
        }

        // ── Включение ────────────────────────────────────────────────────────

        /// <summary>Предусловия первого прототипа. Узко намеренно: всё, что
        /// сложнее свободной карты, в этом заходе не проверяется и потому не
        /// разрешается.</summary>
        internal bool TryEnable(Mode mode, out string reason)
        {
            reason = null;

            if (!EngineContract.Ok)
            {
                reason = "структура движка не совпала с ожидаемой: " + EngineContract.Report;
                return false;
            }
            if (Campaign.Current == null)
            {
                reason = "кампания не запущена";
                return false;
            }

            MobileParty party = MobileParty.MainParty;
            if (party == null || !party.IsActive)
            {
                reason = "партии игрока нет или она неактивна";
                return false;
            }
            if (Hero.MainHero == null || Hero.MainHero.IsPrisoner)
            {
                reason = "герой в плену";
                return false;
            }
            if (party.CurrentSettlement != null)
            {
                reason = "партия внутри поселения — первый прототип работает только на карте";
                return false;
            }
            if (party.MapEvent != null || PlayerEncounter.Current != null)
            {
                reason = "идёт встреча или бой";
                return false;
            }
            if (party.Army != null)
            {
                reason = "партия в армии — вне области первого прототипа";
                return false;
            }
            if (party.BesiegedSettlement != null || party.SiegeEvent != null)
            {
                reason = "партия в осаде — вне области первого прототипа";
                return false;
            }
            if (party.Ai == null)
            {
                reason = "у партии нет объекта AI";
                return false;
            }
            if (party.Ai.IsDisabled)
            {
                // Осознанный отказ вместо «починим». Срок ограничения лежит в
                // приватном поле, снаружи его не прочитать, и по одному флагу
                // нельзя понять, кто его поставил. Известный штатный случай —
                // морской плот после боя без кораблей.
                reason = "AI партии уже ограничен игрой (IsDisabled). Кто и насколько — снаружи не видно, "
                         + "поэтому автопилот не включается";
                return false;
            }

            // Снимок ДО первого изменения.
            _savedDoNotMakeNewDecisions = party.Ai.DoNotMakeNewDecisions;
            _snapshotTaken = true;

            AutopilotLog.Session("включение, режим " + ModeName(mode));
            LogCurrentFlags("до включения");

            // Допуск к штатному выбору: флаг «не принимать решения» читается в
            // том числе ранним выходом из PartyHourlyAiTick, поэтому он обязан
            // быть снят, иначе оценки не соберутся.
            if (party.Ai.DoNotMakeNewDecisions)
            {
                party.Ai.SetDoNotMakeNewDecisions(false);
                AutopilotLog.Write("снят DoNotMakeNewDecisions (был взведён)");
            }
            party.Ai.RethinkAtNextHourlyTick = true;

            _mode = mode;
            _decisionsThisSession = 0;
            _settlementVisitsThisSession = 0;
            _lastAppliedDescription = "—";

            AutopilotLog.Write("ВКЛЮЧЕН, режим " + ModeName(mode)
                               + "; позиция " + Where(party)
                               + "; поведение " + party.DefaultBehavior);
            return true;
        }

        // ── Выключение ───────────────────────────────────────────────────────

        internal void Disable(string reason)
        {
            if (_mode == Mode.Off)
            {
                return;
            }

            MobileParty party = MobileParty.MainParty;
            _mode = Mode.Off;

            AutopilotLog.Write("ВЫКЛЮЧЕНИЕ: " + reason);

            if (party?.Ai != null)
            {
                // 1. Остановить движение. Исполнение живёт своей жизнью и
                //    повезёт партию к последней цели AI, даже когда автопилот
                //    уже выключен — для человека это выглядит как «оно само».
                if (party.CurrentSettlement == null && party.MapEvent == null && party.Army == null)
                {
                    party.SetMoveModeHold();
                    AutopilotLog.Write("движение остановлено (SetMoveModeHold)");
                }
                else
                {
                    AutopilotLog.Write("движение НЕ останавливаю: партия в поселении/бою/армии, "
                                       + "приказ там уже не наш");
                }

                // 2. Вернуть чужое состояние.
                if (_snapshotTaken)
                {
                    party.Ai.SetDoNotMakeNewDecisions(_savedDoNotMakeNewDecisions);
                    AutopilotLog.Write("восстановлено: DoNotMakeNewDecisions=" + _savedDoNotMakeNewDecisions);
                    _snapshotTaken = false;
                }
            }

            LogCurrentFlags("после выключения");
            AutopilotLog.Write("итог сеанса: самостоятельных решений " + _decisionsThisSession
                               + ", посещений поселений " + _settlementVisitsThisSession);
        }

        // ── Часовой цикл ─────────────────────────────────────────────────────

        private void OnHourlyTick()
        {
            if (_mode == Mode.Off)
            {
                return;
            }

            MobileParty party = MobileParty.MainParty;
            if (party == null || !party.IsActive)
            {
                Disable("партия игрока пропала или неактивна");
                return;
            }

            // Остановки по состоянию. Это не ошибки прототипа, а заранее
            // названные границы: так и написано в спецификации.
            if (party.CurrentSettlement != null)
            {
                _settlementVisitsThisSession++;
                Disable("партия вошла в поселение «" + party.CurrentSettlement.Name
                        + "». Движок не выводит партию игрока из поселения автоматически "
                        + "(CheckExitingSettlementParallel пропускает MainParty), поэтому "
                        + "дальше — руками. Это ожидаемая остановка, а не сбой");
                return;
            }
            if (party.MapEvent != null || PlayerEncounter.Current != null)
            {
                Disable("началась встреча или бой — вне области первого прототипа");
                return;
            }
            if (party.Army != null)
            {
                Disable("партия оказалась в армии — вне области первого прототипа");
                return;
            }
            if (party.Ai == null || party.Ai.IsDisabled)
            {
                Disable("AI партии ограничен игрой (IsDisabled) — прототип уступает");
                return;
            }

            // ── Сбор оценок штатным способом ─────────────────────────────────
            PartyThinkParams think;
            try
            {
                think = party.ThinkParamsCache;
                think.Reset(party);
                // Ровно тот же вызов, который PartyHourlyAiTick делает для NPC:
                // все AI-поведения складывают сюда свои оценки.
                CampaignEventDispatcher.Instance.AiHourlyTick(party, think);
            }
            catch (Exception ex)
            {
                Disable("сбор оценок упал: " + ex.GetType().Name + ": " + ex.Message);
                return;
            }

            AIBehaviorData best = AIBehaviorData.Invalid;
            float bestScore = -1f;
            var lines = new List<string>();
            foreach (var pair in think.AIBehaviorScores)
            {
                AIBehaviorData data = pair.Item1;
                float score = pair.Item2;
                lines.Add(Describe(data) + " = " + score.ToString("F3", CultureInfo.InvariantCulture));
                if (score > bestScore)
                {
                    bestScore = score;
                    best = data;
                }
            }

            AutopilotLog.Write("час: оценок " + lines.Count + "; позиция " + Where(party)
                               + "; текущее поведение " + party.DefaultBehavior);
            if (lines.Count == 0)
            {
                AutopilotLog.Write("  оценок НЕТ — штатный AI ничего не предложил для этой партии");
                return;
            }
            foreach (string line in Top(lines, 8))
            {
                AutopilotLog.Write("    " + line);
            }
            AutopilotLog.Write("  лучшее: " + Describe(best) + " = "
                               + bestScore.ToString("F3", CultureInfo.InvariantCulture));

            if (_mode == Mode.Observe)
            {
                // Наблюдение обязано ничего не менять. Единственный побочный
                // эффект сбора оценок — SetInitiative в военном поведении, и он
                // для партии игрока не действует (движок сам его игнорирует),
                // поэтому здесь просто выходим, не трогая решение.
                return;
            }

            ApplyDecision(party, best, bestScore);
        }

        // ── Применение ───────────────────────────────────────────────────────

        private void ApplyDecision(MobileParty party, AIBehaviorData data, float score)
        {
            if (data.AiBehavior == AiBehavior.None)
            {
                AutopilotLog.Write("  решение пустое — ничего не применяю");
                return;
            }

            var settlement = data.Party as Settlement;
            var targetParty = data.Party as MobileParty;

            try
            {
                switch (data.AiBehavior)
                {
                    case AiBehavior.GoToSettlement:
                        if (settlement == null)
                        {
                            Disable("решение «ехать в поселение» без поселения — не применяю");
                            return;
                        }
                        SetPartyAiAction.GetActionForVisitingSettlement(
                            party, settlement, data.NavigationType, data.IsFromPort, data.IsTargetingPort);
                        break;

                    case AiBehavior.PatrolAroundPoint:
                        if (settlement != null)
                        {
                            SetPartyAiAction.GetActionForPatrollingAroundSettlement(
                                party, settlement, data.NavigationType, data.IsFromPort, data.IsTargetingPort);
                        }
                        else
                        {
                            SetPartyAiAction.GetActionForPatrollingAroundPoint(
                                party, data.Position, data.NavigationType, data.IsFromPort);
                        }
                        break;

                    case AiBehavior.EscortParty:
                        if (targetParty == null)
                        {
                            Disable("решение «сопровождать» без партии — не применяю");
                            return;
                        }
                        SetPartyAiAction.GetActionForEscortingParty(
                            party, targetParty, data.NavigationType, data.IsFromPort, data.IsTargetingPort);
                        break;

                    default:
                        // Всё остальное — осада, штурм, рейд, оборона,
                        // преследование — вне области первого прототипа.
                        // Останавливаемся с названной причиной, а не пытаемся
                        // выполнить то, что движок для партии игрока не
                        // доводит до конца.
                        Disable("штатный AI выбрал «" + data.AiBehavior + "» ("
                                + Describe(data) + "). Это вне области первого прототипа: "
                                + "осадные и боевые переходы у партии игрока движком не исполняются");
                        return;
                }
            }
            catch (Exception ex)
            {
                Disable("применение решения упало: " + ex.GetType().Name + ": " + ex.Message);
                return;
            }

            _decisionsThisSession++;
            _lastAppliedDescription = Describe(data);
            AutopilotLog.Write("  ПРИМЕНЕНО #" + _decisionsThisSession + ": " + _lastAppliedDescription
                               + " (оценка " + score.ToString("F3", CultureInfo.InvariantCulture) + ")");
            AutopilotLog.Write("  после применения: поведение " + party.DefaultBehavior
                               + "; цель " + (party.TargetSettlement != null
                                   ? party.TargetSettlement.Name.ToString()
                                   : "нет")
                               + "; движется " + party.IsMoving);
        }

        // ── Вспомогательное ──────────────────────────────────────────────────

        private static IEnumerable<string> Top(List<string> lines, int count)
        {
            int taken = 0;
            foreach (string line in lines)
            {
                if (taken++ >= count)
                {
                    yield break;
                }
                yield return line;
            }
        }

        private static string Describe(AIBehaviorData data)
        {
            var sb = new StringBuilder();
            sb.Append(data.AiBehavior.ToString());
            if (data.Party is Settlement settlement)
            {
                sb.Append(" → ").Append(settlement.Name);
            }
            else if (data.Party is MobileParty party)
            {
                sb.Append(" → ").Append(party.Name);
            }
            if (data.WillGatherArmy)
            {
                sb.Append(" [+армия]");
            }
            return sb.ToString();
        }

        private static string Where(MobileParty party)
        {
            // Ориентир для чтения лога человеком: одни координаты ничего не
            // говорят, а последнее посещённое поселение сразу привязывает
            // строку к месту на карте.
            Settlement near = party.CurrentSettlement ?? party.LastVisitedSettlement;
            string position = party.Position.ToString();
            return near != null ? "у " + near.Name + " (" + position + ")" : position;
        }

        private void LogCurrentFlags(string when)
        {
            MobileParty party = MobileParty.MainParty;
            if (party?.Ai == null)
            {
                AutopilotLog.Write("флаги " + when + ": партии/AI нет");
                return;
            }
            AutopilotLog.Write("флаги " + when + ": IsDisabled=" + party.Ai.IsDisabled
                               + "; DoNotMakeNewDecisions=" + party.Ai.DoNotMakeNewDecisions
                               + "; RethinkAtNextHourlyTick=" + party.Ai.RethinkAtNextHourlyTick
                               + "; DefaultBehavior=" + party.DefaultBehavior
                               + "; Army=" + (party.Army != null)
                               + "; Settlement=" + (party.CurrentSettlement != null
                                   ? party.CurrentSettlement.Name.ToString() : "нет"));
        }

        internal static string ModeName(Mode mode)
        {
            switch (mode)
            {
                case Mode.Observe: return "наблюдение";
                case Mode.Apply: return "применение";
                default: return "выключен";
            }
        }

        internal string StatusLine()
        {
            MobileParty party = MobileParty.MainParty;
            var sb = new StringBuilder();
            sb.Append("режим: ").Append(ModeName(_mode));
            sb.Append("; контракт движка: ").Append(EngineContract.Ok ? "совпал" : "НЕ совпал");
            sb.Append("; решений за сеанс: ").Append(_decisionsThisSession);
            sb.Append("; последнее: ").Append(_lastAppliedDescription);
            if (party?.Ai != null)
            {
                sb.Append("; IsDisabled=").Append(party.Ai.IsDisabled);
                sb.Append("; DoNotMakeNewDecisions=").Append(party.Ai.DoNotMakeNewDecisions);
            }
            sb.Append("; лог: ").Append(AutopilotLog.Path);
            return sb.ToString();
        }
    }
}
