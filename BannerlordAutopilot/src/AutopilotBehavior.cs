using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using Helpers;
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
    /// AiPartyThinkBehavior.PartyHourlyAiTick (1.4.8). Патчить чужой метод не
    /// понадобилось: все нужные вызовы публичны, поэтому мод делает ту же
    /// работу сам и ровно для одной партии.
    ///
    /// ФЛАГИ AI МОД НЕ ТРОГАЕТ. Раньше он снимал `DoNotMakeNewDecisions` и
    /// взводил `RethinkAtNextHourlyTick`, потом «восстанавливал» их — и
    /// независимая проверка 12.09 показала, что это ломается тремя способами:
    /// Rethink не возвращался, старый снимок затирал более новое чужое
    /// значение, и всё это жило в сейве. Причина снимать флаги была ошибочной:
    /// оба читаются ранним выходом из PartyHourlyAiTick, а этот метод мы не
    /// вызываем — сбор оценок и SetPartyAiAction их не читают. Зато
    /// `DoNotMakeNewDecisions` читают торговля партии (HourlyTickParty) и
    /// телепорт героя (TeleportHeroAction), так что снятие меняло поведение
    /// там, где мы его не видели. Не трогаем — нечего и восстанавливать.
    ///
    /// НАБЛЮДЕНИЕ НИЧЕГО НЕ МЕНЯЕТ: ни выхода из поселения, ни остановки
    /// маршрута при выключении. Раньше F10 в городе выводил партию, а F12
    /// после F10 затирал маршрут, который задал человек.
    ///
    /// ВЫХОД ИЗ ПОСЕЛЕНИЯ — только из МИРНОГО поселения и ровно так, как это
    /// делает кнопка «Уйти» (PlayerTownVisitCampaignBehavior.
    /// game_menu_settlement_leave_on_consequence): к воротам → LeaveSettlement
    /// → Finish → Hold. Снаружи у ворот (castle_outside) — Finish → Hold.
    /// Сознательно НЕ повторяем `SignalAutoSave`: это перезаписало бы
    /// автосохранения игрока на каждом городе. Бой, осада, армия и встреча с
    /// чужой партией проверяются РАНЬШЕ поселения: прежний порядок принимал
    /// встречу с осаждающим лордом за прибытие и закрывал её вместе с боем.
    ///
    /// ЧЕГО ЗДЕСЬ НЕТ: осада, штурм, рейд, оборона, преследование, армия,
    /// боевой автопилот. Решения такого рода автопилот не применяет и
    /// останавливается с названной причиной.
    ///
    /// Разбор: docs/BANNERLORD_AUTOPILOT_RESEARCH_2026-09-12.md,
    /// независимая проверка: dist/audit/autopilot-review/REVIEW_RU.md.</summary>
    public class AutopilotBehavior : CampaignBehaviorBase
    {
        internal enum Mode
        {
            /// <summary>Выключен. Единственное состояние после загрузки сейва.</summary>
            Off,
            /// <summary>Только смотрим, что предлагает штатный AI. Ничего не меняем.</summary>
            Observe,
            /// <summary>Применяем выбранное решение.</summary>
            Apply
        }

        internal static AutopilotBehavior Instance { get; private set; }

        private Mode _mode = Mode.Off;

        /// <summary>Был ли автопилот в режиме применения на момент сохранения.
        ///
        /// Единственное, что мод пишет в сейв. Нужен, чтобы после загрузки
        /// отменить маршрут, выданный автопилотом до сохранения: иначе партия
        /// продолжала бы ехать по нашему приказу при выключенном автопилоте.
        /// Удаление мода безопасно — ключ просто не прочитается, а маршрут
        /// останется обычным приказом движения.</summary>
        private bool _activeAtSave;

        // Учёт раздельный и только по подтверждённым событиям. Прежний журнал
        // считал запрос выхода состоявшимся выходом, а старт в городе —
        // прибытием; внешняя проверка 12.09 показала оба случая.
        private int _ticksThisSession;          // пересчёты оценок
        private int _targetChangesThisSession;  // смены цели
        private int _reappliesThisSession;      // повторы того же приказа
        private int _settlementVisitsThisSession;  // прибытия ВО ВРЕМЯ сеанса
        private int _settlementExitsThisSession;   // ПОДТВЕРЖДЁННЫЕ выходы
        private string _lastAppliedDescription = "—";
        private string _lastTargetKey;

        // Состояние одного сеанса. Раньше флаг «выход уже запрошен» переживал
        // выключение и глушил первое прибытие следующего сеанса. Теперь всё
        // сбрасывается на каждой границе сеанса (включение, выключение,
        // загрузка) и привязано к конкретному поселению, а не к «вообще».
        private Settlement _startedIn;       // поселение, в котором сеанс начался
        private Settlement _handledSettlement; // поселение, которое уже обработано

        // Скорость времени, на которой автопилот ехал по свободной карте: 1 —
        // обычная, 2 — ускоренная, 0 — неизвестна. Нужна, чтобы вернуть ход
        // времени после выхода из поселения: PlayerEncounter.Finish ставит
        // паузу, и 13.09 цикл застывал после каждого выхода.
        private int _resumeSpeed;

        /// <summary>Что выключение реально сделало с партией — для сообщения на
        /// экране. Раньше F12 всегда писал «движение остановлено, состояние AI
        /// восстановлено», даже когда не было ни того, ни другого.</summary>
        internal string LastDisableSummary { get; private set; }

        internal Mode CurrentMode => _mode;

        /// <summary>Выходить ли из мирного поселения самостоятельно (только в
        /// режиме применения). Без выхода цикл обрывается на первой же цели
        /// «съездить в город»: движок партию игрока из поселения не выводит.</summary>
        internal static bool AutoLeaveSettlement = true;

        private void ResetSession()
        {
            _ticksThisSession = 0;
            _targetChangesThisSession = 0;
            _reappliesThisSession = 0;
            _settlementVisitsThisSession = 0;
            _settlementExitsThisSession = 0;
            _lastAppliedDescription = "—";
            _lastTargetKey = null;
            _startedIn = null;
            _handledSettlement = null;
            _resumeSpeed = 0;
        }

        public override void RegisterEvents()
        {
            Instance = this;
            CampaignEvents.HourlyTickEvent.AddNonSerializedListener(this, OnHourlyTick);
            CampaignEvents.OnGameLoadFinishedEvent.AddNonSerializedListener(this, OnGameLoadFinished);
        }

        public override void SyncData(IDataStore dataStore)
        {
            // При сохранении здесь записывается факт; при загрузке присвоенное
            // значение тут же перезаписывается прочитанным из сейва.
            _activeAtSave = _mode == Mode.Apply;
            dataStore.SyncData("shedautopilot_activeAtSave", ref _activeAtSave);
        }

        /// <summary>После загрузки автопилот ВСЕГДА выключен. Если сейв сделан
        /// во время применения — отменяем маршрут, который выдал автопилот:
        /// это наше изменение, и владеем им мы.</summary>
        private void OnGameLoadFinished()
        {
            _mode = Mode.Off;
            ResetSession();

            AutopilotLog.Session("загрузка сохранения; автопилот выключен");
            LogCurrentState("после загрузки");

            if (_activeAtSave)
            {
                MobileParty party = MobileParty.MainParty;
                if (party != null && IsOnFreeMap(party))
                {
                    party.SetMoveModeHold();
                    AutopilotLog.Write("сейв сделан при включённом автопилоте: его маршрут отменён (Hold)");
                }
                else
                {
                    AutopilotLog.Write("сейв сделан при включённом автопилоте, но партия не на свободной карте — "
                                       + "маршрут не трогаю, там уже не наш приказ");
                }
            }
            _activeAtSave = false;
        }

        // ── Включение ────────────────────────────────────────────────────────

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

            string unsupported = UnsupportedState(party);
            if (unsupported != null)
            {
                reason = unsupported;
                return false;
            }

            Settlement peaceful = PeacefulSettlement(party);
            if (peaceful == null && PlayerEncounter.Current != null)
            {
                reason = "идёт встреча, которую автопилот не поддерживает";
                return false;
            }
            if (peaceful != null && mode == Mode.Apply && !AutoLeaveSettlement)
            {
                reason = "партия в поселении, а автоматический выход выключен";
                return false;
            }

            // Повторное включение без выключения: закрыть старый сеанс итогом,
            // иначе его счётчики пропадают молча.
            if (_mode != Mode.Off)
            {
                AutopilotLog.Write("повторное включение: предыдущий сеанс закрыт");
                WriteSummary();
            }

            _mode = mode;
            ResetSession();
            _startedIn = peaceful;
            RememberSpeed();

            AutopilotLog.Session("включение, режим " + ModeName(mode));
            LogCurrentState("до включения");
            AutopilotLog.Write("ВКЛЮЧЕН, режим " + ModeName(mode)
                               + "; позиция " + Where(party)
                               + "; поведение " + party.DefaultBehavior
                               + (peaceful != null ? "; сеанс начат в «" + peaceful.Name + "»" : ""));
            return true;
        }

        // ── Выключение ───────────────────────────────────────────────────────

        internal void Disable(string reason)
        {
            if (_mode == Mode.Off)
            {
                return;
            }

            bool wasApply = _mode == Mode.Apply;
            _mode = Mode.Off;
            AutopilotLog.Write("ВЫКЛЮЧЕНИЕ: " + reason);

            MobileParty party = MobileParty.MainParty;
            if (wasApply && party != null && IsOnFreeMap(party))
            {
                // Маршрут выдал автопилот — его и отменяем. Исполнение живёт
                // своей жизнью и без этого довезло бы партию до последней цели.
                party.SetMoveModeHold();
                LastDisableSummary = "Автопилот выключен: маршрут автопилота остановлен.";
                AutopilotLog.Write("движение остановлено: маршрут выдавал автопилот");
            }
            else if (!wasApply)
            {
                LastDisableSummary = "Автопилот выключен: был режим наблюдения, партия не тронута.";
                AutopilotLog.Write("режим наблюдения: партию не трогаю, маршрут игрока сохранён");
            }
            else
            {
                LastDisableSummary = "Автопилот выключен: партия не на свободной карте, её приказ не трогаю.";
                AutopilotLog.Write("движение не останавливаю: партия не на свободной карте");
            }

            LogCurrentState("после выключения");
            WriteSummary();
            ResetSession();
        }

        private void WriteSummary()
        {
            AutopilotLog.Write("итог сеанса: пересчётов " + _ticksThisSession
                               + "; смен цели " + _targetChangesThisSession
                               + "; повторов того же приказа " + _reappliesThisSession
                               + "; прибытий во время сеанса " + _settlementVisitsThisSession
                               + "; подтверждённых выходов " + _settlementExitsThisSession);
        }

        // ── Проверка состояния (каждые полсекунды, независимо от хода времени) ──

        /// <summary>Меню поселения и встреча держат время на паузе, часовых
        /// тиков в этот момент нет — поэтому реакция идёт по кадрам.
        /// Возвращает true, если партия на свободной карте и цикл может идти.</summary>
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

            // СНАЧАЛА опасные состояния — до любых рассуждений о поселении.
            string unsupported = UnsupportedState(party);
            if (unsupported != null)
            {
                Disable(unsupported);
                return false;
            }

            Settlement peaceful = PeacefulSettlement(party);
            if (peaceful == null)
            {
                if (PlayerEncounter.Current != null)
                {
                    Disable("идёт встреча, которую автопилот не поддерживает");
                    return false;
                }
                // Свободная карта: всё, что относилось к прошлому поселению, закрыто.
                _handledSettlement = null;
                _startedIn = null;
                RememberSpeed();
                return true;
            }

            if (peaceful == _handledSettlement)
            {
                return false;
            }
            _handledSettlement = peaceful;

            if (_mode == Mode.Observe)
            {
                AutopilotLog.Write("наблюдение: партия в «" + peaceful.Name
                                   + "», в режиме наблюдения выход не выполняется");
                return false;
            }

            if (peaceful != _startedIn)
            {
                _settlementVisitsThisSession++;
                AutopilotLog.Write("ПРИБЫЛИ в «" + peaceful.Name + "» (прибытие #"
                                   + _settlementVisitsThisSession + ")");
            }

            if (!AutoLeaveSettlement)
            {
                Disable("вошли в «" + peaceful.Name + "», автоматический выход выключен — дальше руками");
                return false;
            }

            LeavePeacefulSettlement(party, peaceful);
            return false;
        }

        /// <summary>Состояние, в котором автопилот не работает. null — всё в порядке.
        /// Проверяется ДО поселения: встреча с осаждающим лордом тоже несёт
        /// EncounterSettlement, и прежний порядок принимал её за прибытие.</summary>
        private static string UnsupportedState(MobileParty party)
        {
            if (party.MapEvent != null || PlayerEncounter.Battle != null)
            {
                return "идёт бой — вне области прототипа";
            }
            if (party.SiegeEvent != null || party.BesiegedSettlement != null)
            {
                return "партия в осаде — вне области прототипа";
            }
            if (party.Army != null)
            {
                return "партия в армии — вне области прототипа";
            }
            if (party.Ai == null || party.Ai.IsDisabled)
            {
                // Отказ вместо починки: срок ограничения лежит в приватном поле,
                // и по флагу не понять, кто его поставил (штатно — морской плот).
                return "AI партии ограничен игрой (IsDisabled)";
            }
            if (PlayerEncounter.Current != null && PlayerEncounter.EncounteredMobileParty != null)
            {
                return "идёт встреча с другой партией — вне области прототипа";
            }
            return null;
        }

        /// <summary>Мирное поселение, в котором или у ворот которого стоит партия.
        /// null — такого нет. Поселение под осадой мирным не считается.</summary>
        private static Settlement PeacefulSettlement(MobileParty party)
        {
            Settlement inside = party.CurrentSettlement;
            if (inside != null)
            {
                return inside.IsUnderSiege ? null : inside;
            }
            Settlement atGate = PlayerEncounter.Current != null ? PlayerEncounter.EncounterSettlement : null;
            if (atGate != null
                && PlayerEncounter.EncounteredMobileParty == null
                && PlayerEncounter.Battle == null
                && !atGate.IsUnderSiege)
            {
                return atGate;
            }
            return null;
        }

        private static bool IsOnFreeMap(MobileParty party)
        {
            return party.CurrentSettlement == null
                   && party.MapEvent == null
                   && party.Army == null
                   && PlayerEncounter.Current == null;
        }

        /// <summary>Выход тем же путём, что кнопка «Уйти», и только с подтверждением.</summary>
        private void LeavePeacefulSettlement(MobileParty party, Settlement settlement)
        {
            try
            {
                if (party.CurrentSettlement == settlement)
                {
                    // Изнутри: game_menu_settlement_leave_on_consequence.
                    party.Position = settlement.GatePosition;
                    PlayerEncounter.LeaveSettlement();
                    PlayerEncounter.Finish();
                    party.SetMoveModeHold();
                    AutopilotLog.Write("  выход изнутри: к воротам → LeaveSettlement → Finish → Hold");
                }
                else
                {
                    // Снаружи у ворот: game_menu_castle_outside_leave_on_consequence.
                    PlayerEncounter.Finish();
                    party.SetMoveModeHold();
                    AutopilotLog.Write("  выход от ворот: Finish → Hold");
                }
            }
            catch (Exception ex)
            {
                Disable("выход из «" + settlement.Name + "» упал: " + ex.GetType().Name + ": " + ex.Message);
                return;
            }

            // Засчитываем только наблюдаемый результат, а не сам запрос.
            if (party.CurrentSettlement == null && PlayerEncounter.Current == null)
            {
                _settlementExitsThisSession++;
                _lastTargetKey = null;
                AutopilotLog.Write("  ВЫШЛИ из «" + settlement.Name + "» (подтверждённый выход #"
                                   + _settlementExitsThisSession + ")");
                ResumeTimeAfterLeave();
            }
            else
            {
                Disable("выход из «" + settlement.Name + "» не подтвердился: партия всё ещё в поселении или встрече");
            }
        }

        /// <summary>Запомнить скорость, на которой идёт время. Пауза не
        /// запоминается: вернуть надо ту скорость, на которой автопилот ехал.</summary>
        private void RememberSpeed()
        {
            int speed = SpeedOf(Campaign.Current.TimeControlMode);
            if (speed > 0)
            {
                _resumeSpeed = speed;
            }
        }

        private static int SpeedOf(CampaignTimeControlMode mode)
        {
            switch (mode)
            {
                case CampaignTimeControlMode.UnstoppablePlay:
                case CampaignTimeControlMode.StoppablePlay:
                    return 1;
                case CampaignTimeControlMode.UnstoppableFastForward:
                case CampaignTimeControlMode.StoppableFastForward:
                case CampaignTimeControlMode.UnstoppableFastForwardForPartyWaitTime:
                    return 2;
                default:
                    return 0;
            }
        }

        /// <summary>Вернуть ход времени после выхода.
        ///
        /// PlayerEncounter.Finish ставит TimeControlMode = Stop для партии вне
        /// армии. Для кнопки «Уйти» это правильно — игрок сам решает, что
        /// дальше; для автопилота это стопор: прогон 13.09 после выхода из
        /// Ревиля простоял восемь минут без единого пересчёта. Паузу поставил
        /// наш вызов — мы её и снимаем, но только если до поселения время шло.
        /// SetTimeSpeed — то же, что кнопка «▶»: при стопе и Hold он включает
        /// неостанавливаемое воспроизведение, иначе время не пошло бы, пока
        /// партия стоит у ворот.</summary>
        private void ResumeTimeAfterLeave()
        {
            CampaignTimeControlMode mode = Campaign.Current.TimeControlMode;
            bool paused = mode == CampaignTimeControlMode.Stop || mode == CampaignTimeControlMode.FastForwardStop;
            if (paused && _resumeSpeed > 0)
            {
                Campaign.Current.SetTimeSpeed(_resumeSpeed);
                AutopilotLog.Write("  время возобновлено (скорость " + _resumeSpeed
                                   + "): закрытие встречи ставит паузу");
            }
            else if (paused)
            {
                AutopilotLog.Write("  время на паузе, а скорость до поселения неизвестна — не трогаю");
            }
        }

        // ── Часовой цикл ─────────────────────────────────────────────────────

        private void OnHourlyTick()
        {
            if (_mode == Mode.Off || !PollState())
            {
                return;
            }

            MobileParty party = MobileParty.MainParty;

            PartyThinkParams think;
            try
            {
                think = party.ThinkParamsCache;
                think.Reset(party);
                // Тот же вызов, что PartyHourlyAiTick делает для NPC. Побочные
                // эффекты есть и они не наши: подписчики пишут кеши оценки силы
                // партий (PartyBase.EstimatedStrength) — это кеширование движка,
                // не приказ и не трата (разбор подписчиков — в независимой проверке).
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
                        if (MobilePartyHelper.GetCurrentSettlementOfMobilePartyForAICalculation(party) == settlement)
                        {
                            // Движок для NPC приказ посетить поселение, в котором
                            // (или вплотную к которому) партия уже стоит, НЕ выдаёт —
                            // та же проверка в AiPartyThinkBehavior.PartyHourlyAiTick.
                            // Без неё автопилот 13.09 заходил в Ревиль, выходил и
                            // заходил снова. Пишем один раз на цель, а не каждый час.
                            string idleKey = "idle|" + settlement;
                            if (idleKey != _lastTargetKey)
                            {
                                AutopilotLog.Write("  лучшее — «" + settlement.Name
                                                   + "», у которого партия уже стоит: приказ не выдаю, как движок для NPC");
                            }
                            _lastTargetKey = idleKey;
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
                        // Осада, штурм, рейд, оборона, преследование — вне области
                        // прототипа. Останавливаемся с причиной, а не пытаемся
                        // выполнить то, что движок для партии игрока не доводит до конца.
                        Disable("штатный AI выбрал «" + data.AiBehavior + "» ("
                                + Describe(data) + "). Это вне области прототипа");
                        return;
                }
            }
            catch (Exception ex)
            {
                Disable("применение решения упало: " + ex.GetType().Name + ": " + ex.Message);
                return;
            }

            // «Смена цели» здесь — новый приказ относительно предыдущего В ЭТОМ
            // сеансе. После выхода из поселения ключ сбрасывается, поэтому
            // повторная выдача той же цели после остановки считается новым
            // приказом — это число приказов, а не буквальное число смен цели.
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
            Settlement near = party.CurrentSettlement ?? party.LastVisitedSettlement;
            string position = party.Position.ToString();
            return near != null ? "у " + near.Name + " (" + position + ")" : position;
        }

        /// <summary>Только чтение: мод эти флаги не меняет, но их значение
        /// нужно видеть в журнале, чтобы отличать чужое ограничение от своего.</summary>
        private void LogCurrentState(string when)
        {
            MobileParty party = MobileParty.MainParty;
            if (party?.Ai == null)
            {
                AutopilotLog.Write("состояние " + when + ": партии/AI нет");
                return;
            }
            AutopilotLog.Write("состояние " + when + ": IsDisabled=" + party.Ai.IsDisabled
                               + "; DoNotMakeNewDecisions=" + party.Ai.DoNotMakeNewDecisions
                               + "; DefaultBehavior=" + party.DefaultBehavior
                               + "; Army=" + (party.Army != null)
                               + "; Settlement=" + (party.CurrentSettlement != null
                                   ? party.CurrentSettlement.Name.ToString() : "нет")
                               + "; Encounter=" + (PlayerEncounter.Current != null));
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
            sb.Append("; прибытий: ").Append(_settlementVisitsThisSession);
            sb.Append("; выходов: ").Append(_settlementExitsThisSession);
            sb.Append("; последнее: ").Append(_lastAppliedDescription);
            if (party?.Ai != null)
            {
                sb.Append("; IsDisabled=").Append(party.Ai.IsDisabled);
            }
            sb.Append("; лог: ").Append(AutopilotLog.Path);
            return sb.ToString();
        }
    }
}
