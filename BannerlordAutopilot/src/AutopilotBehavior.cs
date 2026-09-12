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
    ///   * боевой автопилот — отдельная задача.
    ///
    /// ВЫХОД ИЗ ПОСЕЛЕНИЯ мы делаем сами. Движок для партии игрока его не
    /// делает (`CheckExitingSettlementParallel` пропускает MainParty), а без
    /// выхода цикл обрывается на первой же цели «съездить в город» — это и
    /// был главный барьер. Механизм тот же, которым пользуется кнопка «Уйти»:
    /// `PlayerEncounter.LeaveEncounter`, иначе `LeaveSettlementAction`.
    /// Проверено прогоном 12.09: три поселения посещены и покинуты подряд, с
    /// новой целью после каждого.
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

        // Учёт намеренно раздельный. В первом прогоне 12.09 в журнале стояло
        // «самостоятельных решений 9», хотя на деле это был ОДИН выбранный
        // маршрут (Карбур), переприменённый девять раз подряд — внешний обзор
        // справедливо указал, что такая строка вводит в заблуждение.
        private int _ticksThisSession;          // сколько раз пересчитали оценки
        private int _targetChangesThisSession;  // сколько раз сменилась цель
        private int _reappliesThisSession;      // сколько раз повторили ту же цель
        private int _settlementVisitsThisSession;
        private int _settlementExitsThisSession;
        private string _lastAppliedDescription = "—";
        private bool _leaveRequested;      // выход из поселения уже запрошен
        private string _lastTargetKey;          // чем отличается «та же цель» от новой

        internal Mode CurrentMode => _mode;

        /// <summary>Выходить ли из поселения самостоятельно.
        ///
        /// Это ЯВНОЕ решение спецификации, а не побочный эффект: без выхода
        /// цикл обрывается на первой же цели «съездить в город», потому что
        /// движок партию игрока из поселения не выводит. Выключается на время
        /// отладки — тогда прибытие просто останавливает автопилот.</summary>
        internal static bool AutoLeaveSettlement = true;

        private void ResetCounters()
        {
            _ticksThisSession = 0;
            _targetChangesThisSession = 0;
            _reappliesThisSession = 0;
            _settlementVisitsThisSession = 0;
            _settlementExitsThisSession = 0;
            _lastAppliedDescription = "—";
            _lastTargetKey = null;
        }

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
            ResetCounters();

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
            // Включение ИЗ поселения разрешено: штатный выход у нас есть и
            // проверен прогоном 12.09 (21 выход подряд), поэтому запрещать
            // старт из города больше незачем — автопилот выведет партию сам
            // на ближайшем опросе состояния.
            if (party.CurrentSettlement != null && !AutoLeaveSettlement)
            {
                reason = "партия внутри поселения, а автоматический выход выключен";
                return false;
            }
            if (party.MapEvent != null)
            {
                reason = "идёт бой";
                return false;
            }
            if (PlayerEncounter.Current != null && PlayerEncounter.EncounterSettlement == null)
            {
                // Встреча с поселением — это и есть «мы в городе», её мы умеем
                // закрывать. А вот встреча с чужой ПАРТИЕЙ ведёт в переговоры
                // или бой, и это вне области прототипа.
                reason = "идёт встреча с другой партией";
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

            // Снимок ДО первого изменения — и только если его ещё нет.
            //
            // Иначе повторное включение (F11 второй раз, без выключения)
            // снимает снимок уже с НАШЕГО значения и затирает настоящее. Так
            // и вышло 12.09: при первом включении флаг был взведён, мы его
            // сняли, второе включение записало в снимок False, и при
            // выключении игроку вернули False вместо True.
            if (!_snapshotTaken)
            {
                _savedDoNotMakeNewDecisions = party.Ai.DoNotMakeNewDecisions;
                _snapshotTaken = true;
            }
            else
            {
                AutopilotLog.Write("снимок уже взят раньше, не перезаписываю: DoNotMakeNewDecisions="
                                   + _savedDoNotMakeNewDecisions);
            }

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
            ResetCounters();

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
            AutopilotLog.Write("итог сеанса: пересчётов " + _ticksThisSession
                               + "; смен цели " + _targetChangesThisSession
                               + "; повторов того же приказа " + _reappliesThisSession
                               + "; посещений поселений " + _settlementVisitsThisSession
                               + "; штатных выходов " + _settlementExitsThisSession);
        }

        // ── Часовой цикл ─────────────────────────────────────────────────────

        /// <summary>Проверка границ, НЕ привязанная к часовому тику.
        ///
        /// Зачем отдельно. В первом прогоне 12.09 автопилот заметил прибытие в
        /// деревню только после того, как человек вручную выбрал «подождать» —
        /// потому что меню поселения ставит время на паузу, а часовых тиков на
        /// паузе не бывает. Реакция на меню, встречу и выключение обязана
        /// работать независимо от хода времени, иначе пауза делает автопилот
        /// слепым (замечание внешнего обзора 12.09).
        ///
        /// Вызывается из AutopilotSubModule.OnApplicationTick с троттлингом.
        /// Возвращает true, если состояние в порядке и цикл может продолжаться.</summary>
        internal bool PollState()
        {
            if (_mode == Mode.Off || Campaign.Current == null)
            {
                return false;
            }

            MobileParty party = MobileParty.MainParty;
            if (party == null || !party.IsActive)
            {
                Disable("партия игрока пропала или неактивна");
                return false;
            }

            // Вход в поселение — не «встреча вообще», а именно прибытие.
            // Раньше это записывалось как «началась встреча или бой», и по
            // журналу нельзя было понять, что произошло.
            Settlement inside = party.CurrentSettlement
                                ?? (PlayerEncounter.Current != null ? PlayerEncounter.EncounterSettlement : null);
            if (inside != null)
            {
                // Выход из поселения не мгновенный: движок закрывает встречу
                // через свой цикл, а опрос идёт каждые полсекунды. Без этой
                // защиты прибытие засчитывалось ПОВТОРНО всё время, пока
                // партия выходит — в прогоне 12.09 одно прибытие давало от 5
                // до 13 записей и столько же лишних запросов на выход, а
                // счётчик посещений показал 21 вместо четырёх настоящих.
                if (!_leaveRequested)
                {
                    _leaveRequested = true;
                    OnArrivedAtSettlement(inside);
                }
                return false;
            }
            // Партия снова на карте — прибытие можно считать заново.
            _leaveRequested = false;
            if (party.MapEvent != null)
            {
                Disable("начался бой (MapEvent) — вне области первого прототипа");
                return false;
            }
            if (PlayerEncounter.Current != null)
            {
                Disable("началась встреча с партией — вне области первого прототипа");
                return false;
            }
            if (party.Army != null)
            {
                Disable("партия оказалась в армии — вне области первого прототипа");
                return false;
            }
            if (party.BesiegedSettlement != null || party.SiegeEvent != null)
            {
                Disable("партия в осаде — вне области первого прототипа");
                return false;
            }
            if (party.Ai == null || party.Ai.IsDisabled)
            {
                Disable("AI партии ограничен игрой (IsDisabled) — прототип уступает");
                return false;
            }
            return true;
        }

        /// <summary>Прибытие в поселение — ключевая точка цикла.
        ///
        /// Движок не выводит партию игрока из поселения сам
        /// (`CheckExitingSettlementParallel` пропускает MainParty), поэтому
        /// без нас цикл здесь и кончается. Штатный выход — тот же, которым
        /// пользуется игра по кнопке «Уйти»: `PlayerEncounter.LeaveEncounter`,
        /// а если встречи нет — `LeaveSettlementAction`.</summary>
        private void OnArrivedAtSettlement(Settlement settlement)
        {
            _settlementVisitsThisSession++;
            AutopilotLog.Write("ПРИБЫЛИ в «" + settlement.Name + "» (посещение #"
                               + _settlementVisitsThisSession + ")");

            if (!AutoLeaveSettlement)
            {
                Disable("вошли в поселение «" + settlement.Name
                        + "», автоматический выход выключен — дальше руками");
                return;
            }

            try
            {
                if (PlayerEncounter.Current != null)
                {
                    // Мягкий штатный выход: движок сам закроет меню и выведет
                    // партию на карту, как при нажатии «Уйти».
                    PlayerEncounter.LeaveEncounter = true;
                    AutopilotLog.Write("  выход: PlayerEncounter.LeaveEncounter = true");
                }
                else if (MobileParty.MainParty.CurrentSettlement != null)
                {
                    LeaveSettlementAction.ApplyForParty(MobileParty.MainParty);
                    AutopilotLog.Write("  выход: LeaveSettlementAction.ApplyForParty");
                }
                _settlementExitsThisSession++;
                // Следующий час пусть решает заново, а не продолжает старую цель.
                if (MobileParty.MainParty.Ai != null)
                {
                    MobileParty.MainParty.Ai.RethinkAtNextHourlyTick = true;
                }
                _lastTargetKey = null;
            }
            catch (Exception ex)
            {
                Disable("штатный выход из поселения упал: " + ex.GetType().Name + ": " + ex.Message);
            }
        }

        private void OnHourlyTick()
        {
            if (_mode == Mode.Off)
            {
                return;
            }
            if (!PollState())
            {
                return;
            }

            MobileParty party = MobileParty.MainParty;

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

            _ticksThisSession++;
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

            string key = data.AiBehavior + "|" + (data.Party != null ? data.Party.ToString() : data.Position.ToString());
            bool changed = key != _lastTargetKey;
            _lastTargetKey = key;
            _lastAppliedDescription = Describe(data);
            if (changed)
            {
                _targetChangesThisSession++;
                AutopilotLog.Write("  НОВАЯ ЦЕЛЬ #" + _targetChangesThisSession + ": " + _lastAppliedDescription
                                   + " (оценка " + score.ToString("F3", CultureInfo.InvariantCulture) + ")");
            }
            else
            {
                _reappliesThisSession++;
                AutopilotLog.Write("  та же цель, приказ повторён (" + _reappliesThisSession
                                   + "-й раз): " + _lastAppliedDescription
                                   + " (оценка " + score.ToString("F3", CultureInfo.InvariantCulture) + ")");
            }
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
            sb.Append("; пересчётов: ").Append(_ticksThisSession);
            sb.Append("; смен цели: ").Append(_targetChangesThisSession);
            sb.Append("; повторов: ").Append(_reappliesThisSession);
            sb.Append("; посещений: ").Append(_settlementVisitsThisSession);
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
