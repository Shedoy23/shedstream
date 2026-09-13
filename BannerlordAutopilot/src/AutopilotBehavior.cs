using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using Helpers;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.GameState;
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
    /// ПОСЕЛЕНИЕ — КАК У NPC: вошёл, остался, ушёл по решению. NPC остаётся в
    /// поселении, пока лучшая цель — само это поселение
    /// (CheckExitingSettlementParallel), и уходит, когда пересчёт выбрал другое.
    /// Автопилот делает то же пунктами меню игрока: «Подождать» (время идёт,
    /// партия внутри), а когда пересчёт выбрал другую цель — «Перестать ждать»
    /// и выход. Прототип выходил сразу после входа, и 13.09 это дало 89 входов
    /// и выходов в одном городе.
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
    /// ВРЕМЯ НЕ СТОИТ. Человека за компьютером нет, поэтому в режиме применения
    /// пауза на свободной карте снимается, а простой дольше 10 секунд
    /// записывается в журнал с описанием того, что держит игру.
    ///
    /// ЧЕГО ЗДЕСЬ НЕТ: осада, штурм, рейд, оборона, преследование, армия,
    /// боевой автопилот. Такие решения штатного AI пропускаются — берётся
    /// лучшее из выполнимых; бой и встреча с чужой партией пока выключают
    /// автопилот с названной причиной.
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

        // Поселения, где подождать нельзя (у ворот замка, пункт недоступен). NPC
        // бы вошёл и остался, партия игрока — нет. Поэтому решение штатного AI
        // снова ехать туда заменяется следующим: иначе вход и выход по кругу,
        // как 13.09.
        private readonly HashSet<Settlement> _cannotStay = new HashSet<Settlement>();

        // Решение, ради которого надо уйти из поселения. Принимается часовым
        // тиком, выполняется опросом по кадрам: пункты меню нажимаются там же,
        // где их нажал бы игрок, а приказ выдаётся сразу после выхода — иначе
        // партия час простояла бы у ворот.
        private bool _hasPendingDecision;
        private AIBehaviorData _pendingDecision;
        private float _pendingScore;

        // Пересчёт как у NPC: раз в шесть часов (AiPartyThinkBehavior.
        // PartyHourlyAiTick, num = 6), стоящая партия — каждый час. Каждый час
        // пересчитывать нельзя: при близких оценках партия разворачивалась бы
        // на полпути.
        private const int ThinkPeriodHours = 6;
        private int _hoursSinceThink;

        // Сторож простоя: время кампании не идёт дольше StallSeconds реального
        // времени — значит, игру что-то держит (окно, меню, пауза), и без
        // человека она так и простоит. Часы подменяются в проверках.
        internal static Func<DateTime> Clock = () => DateTime.UtcNow;
        private const double StallSeconds = 10;
        private double _lastCampaignHours = -1;
        private DateTime _lastProgressAt;
        private bool _stallReported;
        private int _stallsThisSession;
        private double _longestStallSeconds;
        private int _timeStartsThisSession;

        /// <summary>Что выключение реально сделало с партией — для сообщения на
        /// экране. Раньше F12 всегда писал «движение остановлено, состояние AI
        /// восстановлено», даже когда не было ни того, ни другого.</summary>
        internal string LastDisableSummary { get; private set; }

        internal Mode CurrentMode => _mode;

        /// <summary>Работать ли в мирном поселении самостоятельно — ждать и
        /// уходить (только в режиме применения). Без этого цикл обрывается на
        /// первой же цели «съездить в город»: движок партию игрока из поселения
        /// не выводит.</summary>
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
            _cannotStay.Clear();
            _hasPendingDecision = false;
            _hoursSinceThink = 0;
            _lastCampaignHours = -1;
            _stallReported = false;
            _stallsThisSession = 0;
            _longestStallSeconds = 0;
            _timeStartsThisSession = 0;
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
                               + "; подтверждённых выходов " + _settlementExitsThisSession
                               + "; простоев " + _stallsThisSession
                               + " (самый долгий " + _longestStallSeconds.ToString("F0", CultureInfo.InvariantCulture) + " с)"
                               + "; снятий с паузы " + _timeStartsThisSession);
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

            if (_mode == Mode.Apply)
            {
                WatchTime(party);
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
                if (_mode == Mode.Apply)
                {
                    KeepTimeRunning(party);
                }
                return true;
            }

            if (_mode == Mode.Observe)
            {
                if (peaceful != _handledSettlement)
                {
                    _handledSettlement = peaceful;
                    AutopilotLog.Write("наблюдение: партия в «" + peaceful.Name
                                       + "», в режиме наблюдения автопилот ничего не нажимает");
                }
                return false;
            }

            if (peaceful != _handledSettlement)
            {
                _handledSettlement = peaceful;
                if (peaceful != _startedIn)
                {
                    _settlementVisitsThisSession++;
                    AutopilotLog.Write("ПРИБЫЛИ в «" + peaceful.Name + "» (прибытие #"
                                       + _settlementVisitsThisSession + ")");
                }
            }

            if (!AutoLeaveSettlement)
            {
                Disable("вошли в «" + peaceful.Name + "», работа в поселениях выключена — дальше руками");
                return false;
            }

            string menuId = MenuDriver.CurrentMenuId;
            if (IsWaiting(menuId))
            {
                if (_hasPendingDecision)
                {
                    StopWaitingAndLeave(party, peaceful);
                }
                return false;
            }

            switch (menuId)
            {
                case null:
                    // Встреча уже есть, меню ещё нет — движок открывает его в том же
                    // переходе; решать нечего до следующего опроса.
                    return false;

                case "town":
                case "castle":
                case "village":
                    if (_hasPendingDecision || _cannotStay.Contains(peaceful))
                    {
                        LeaveAndApplyPending(party, peaceful);
                    }
                    else
                    {
                        StartWaiting(party, peaceful, menuId);
                    }
                    return false;

                case "town_outside":
                case "castle_outside":
                case "village_looted":
                    // У ворот, куда не пускают, и в разграбленной деревне подождать
                    // нельзя — остаётся уйти (village_looted_leave_on_consequence
                    // тоже LeaveSettlement → Finish → Hold).
                    if (_cannotStay.Add(peaceful))
                    {
                        AutopilotLog.Write("  у «" + peaceful.Name + "» подождать нельзя (меню " + menuId
                                           + "): уходим; в этом сеансе автопилот туда не вернётся");
                    }
                    LeaveAndApplyPending(party, peaceful);
                    return false;

                default:
                    Disable("в «" + peaceful.Name + "» открыто меню, которое автопилот не знает: "
                            + MenuDriver.Describe());
                    return false;
            }
        }

        private static bool IsWaiting(string menuId)
        {
            return (menuId == "town_wait_menus" || menuId == "village_wait_menus")
                   && PlayerEncounter.Current != null
                   && PlayerEncounter.Current.IsPlayerWaiting;
        }

        /// <summary>Остаться в поселении, как NPC: пункт «Подождать». В городе и
        /// замке партия остаётся внутри, в деревне движок сам выводит её за
        /// околицу (game_menu_wait_village_on_consequence) — так и у игрока.</summary>
        private void StartWaiting(MobileParty party, Settlement settlement, string menuId)
        {
            string option = menuId == "village" ? "village_wait" : "town_wait";
            if (!MenuDriver.TryInvoke(option, out string why))
            {
                _cannotStay.Add(settlement);
                AutopilotLog.Write("  подождать в «" + settlement.Name + "» нельзя (" + why
                                   + "): уходим; в этом сеансе автопилот туда не вернётся");
                LeaveAndApplyPending(party, settlement);
                return;
            }

            if (PlayerEncounter.Current != null && PlayerEncounter.Current.IsPlayerWaiting)
            {
                AutopilotLog.Write("  ЖДЁМ в «" + settlement.Name + "»: пункт «Подождать», время "
                                   + Campaign.Current.TimeControlMode
                                   + "; уйдём, когда пересчёт штатного AI выберет другую цель");
            }
            else
            {
                Disable("пункт «Подождать» в «" + settlement.Name + "» нажат, но ожидание не началось: "
                        + MenuDriver.Describe());
            }
        }

        /// <summary>Пересчёт выбрал другую цель: «Перестать ждать», затем выход.</summary>
        private void StopWaitingAndLeave(MobileParty party, Settlement settlement)
        {
            if (!MenuDriver.TryInvoke("wait_leave", out string why))
            {
                Disable("не удалось перестать ждать в «" + settlement.Name + "»: " + why);
                return;
            }
            if (PlayerEncounter.Current != null && PlayerEncounter.Current.IsPlayerWaiting)
            {
                Disable("«Перестать ждать» в «" + settlement.Name + "» нажат, но ожидание продолжается");
                return;
            }
            AutopilotLog.Write("  ожидание в «" + settlement.Name + "» закончено пунктом «Перестать ждать»");
            LeaveAndApplyPending(party, settlement);
        }

        /// <summary>Выйти и сразу выполнить решение, ради которого вышли.</summary>
        private void LeaveAndApplyPending(MobileParty party, Settlement settlement)
        {
            if (!LeavePeacefulSettlement(party, settlement) || !_hasPendingDecision)
            {
                return;
            }
            _hasPendingDecision = false;
            ApplyDecision(party, _pendingDecision, _pendingScore);
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

        /// <summary>Выход тем же путём, что кнопка «Уйти», и только с подтверждением.
        /// true — выход наблюдается (партия вне поселения и встречи).</summary>
        private bool LeavePeacefulSettlement(MobileParty party, Settlement settlement)
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
                return false;
            }

            // Засчитываем только наблюдаемый результат, а не сам запрос.
            if (party.CurrentSettlement == null && PlayerEncounter.Current == null)
            {
                _settlementExitsThisSession++;
                _lastTargetKey = null;
                _handledSettlement = null;
                AutopilotLog.Write("  ВЫШЛИ из «" + settlement.Name + "» (подтверждённый выход #"
                                   + _settlementExitsThisSession + ")");
                ResumeTimeAfterLeave();
                return true;
            }
            Disable("выход из «" + settlement.Name + "» не подтвердился: партия всё ещё в поселении или встрече");
            return false;
        }

        /// <summary>Снять паузу на свободной карте.
        ///
        /// Человек за компьютером ставит паузу сам и сам же её снимает; автопилоту
        /// без человека пауза — остановка всей игры. Режимы «Stoppable» к тому же
        /// не двигают время, пока партия стоит (Campaign.TickMapTime при
        /// IsMainPartyWaiting), поэтому ставится неостанавливаемый режим той
        /// скорости, на которой автопилот ехал. Поверх карты открыто окно, меню
        /// или разговор — не трогаем: их закрывает не пауза.</summary>
        private void KeepTimeRunning(MobileParty party)
        {
            Campaign campaign = Campaign.Current;
            if (campaign.CurrentMenuContext != null
                || (campaign.ConversationManager != null && campaign.ConversationManager.IsConversationInProgress)
                || !(Game.Current?.GameStateManager?.ActiveState is MapState))
            {
                return;
            }

            CampaignTimeControlMode mode = campaign.TimeControlMode;
            if (TimeAdvances(mode))
            {
                return;
            }

            CampaignTimeControlMode wanted = _resumeSpeed == 2
                ? CampaignTimeControlMode.UnstoppableFastForward
                : CampaignTimeControlMode.UnstoppablePlay;
            campaign.TimeControlMode = wanted;
            if (campaign.TimeControlMode == wanted)
            {
                _timeStartsThisSession++;
                AutopilotLog.Write("время запущено: было " + mode + ", партия " + party.DefaultBehavior
                                   + ", стало " + wanted);
            }
        }

        private static bool TimeAdvances(CampaignTimeControlMode mode)
        {
            switch (mode)
            {
                case CampaignTimeControlMode.UnstoppablePlay:
                case CampaignTimeControlMode.UnstoppableFastForward:
                case CampaignTimeControlMode.UnstoppableFastForwardForPartyWaitTime:
                    return true;
                case CampaignTimeControlMode.StoppablePlay:
                case CampaignTimeControlMode.StoppableFastForward:
                    return !Campaign.Current.IsMainPartyWaiting;
                default:
                    return false;
            }
        }

        /// <summary>Сторож простоя: время кампании не идёт дольше StallSeconds —
        /// одна запись с описанием того, что держит игру, и одна — когда пошло.</summary>
        private void WatchTime(MobileParty party)
        {
            double hours = CampaignTime.Now.ToHours;
            DateTime now = Clock();
            if (_lastCampaignHours < 0 || hours > _lastCampaignHours)
            {
                if (_stallReported)
                {
                    double stalled = (now - _lastProgressAt).TotalSeconds;
                    _longestStallSeconds = Math.Max(_longestStallSeconds, stalled);
                    AutopilotLog.Write("время снова идёт после простоя "
                                       + stalled.ToString("F0", CultureInfo.InvariantCulture) + " с");
                }
                _lastCampaignHours = hours;
                _lastProgressAt = now;
                _stallReported = false;
                return;
            }

            double seconds = (now - _lastProgressAt).TotalSeconds;
            if (!_stallReported && seconds >= StallSeconds)
            {
                _stallReported = true;
                _stallsThisSession++;
                AutopilotLog.Write("ПРОСТОЙ: время кампании не идёт уже "
                                   + seconds.ToString("F0", CultureInfo.InvariantCulture) + " с. "
                                   + DescribeGame(party));
            }
        }

        /// <summary>Что держит игру — для записи о простое.</summary>
        private static string DescribeGame(MobileParty party)
        {
            var sb = new StringBuilder();
            try
            {
                GameStateManager states = Game.Current?.GameStateManager;
                sb.Append("экран ").Append(states?.ActiveState?.GetType().Name ?? "нет");
                if (states != null && states.ActiveStateDisabledByUser)
                {
                    sb.Append(" (приостановлен окном)");
                }
                Campaign campaign = Campaign.Current;
                sb.Append("; режим времени ").Append(campaign.TimeControlMode);
                if (campaign.TimeControlModeLock)
                {
                    sb.Append(" (заблокирован)");
                }
                if (campaign.IsMainPartyWaiting)
                {
                    sb.Append("; партия стоит");
                }
                sb.Append("; меню ").Append(MenuDriver.Describe());
                if (campaign.ConversationManager != null && campaign.ConversationManager.IsConversationInProgress)
                {
                    sb.Append("; идёт разговор");
                }
                if (PlayerEncounter.Current != null)
                {
                    sb.Append("; встреча: поселение ").Append(PlayerEncounter.EncounterSettlement?.Name?.ToString() ?? "нет")
                      .Append(", партия ").Append(PlayerEncounter.EncounteredMobileParty?.Name?.ToString() ?? "нет")
                      .Append(", бой ").Append(PlayerEncounter.Battle != null ? "да" : "нет")
                      .Append(", ожидание ").Append(PlayerEncounter.Current.IsPlayerWaiting ? "да" : "нет");
                }
                sb.Append("; партия ").Append(Where(party))
                  .Append(", поведение ").Append(party.DefaultBehavior)
                  .Append(", движется ").Append(party.IsMoving);
                if (Hero.MainHero != null && Hero.MainHero.IsPrisoner)
                {
                    sb.Append("; герой в плену");
                }
                if (Hero.MainHero != null && Hero.MainHero.IsWounded)
                {
                    sb.Append("; герой ранен");
                }
            }
            catch (Exception ex)
            {
                sb.Append("; описание оборвалось: ").Append(ex.GetType().Name).Append(": ").Append(ex.Message);
            }
            return sb.ToString();
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
            if (_mode == Mode.Off || Campaign.Current == null)
            {
                return;
            }

            MobileParty party = MobileParty.MainParty;
            if (party == null || !party.IsActive || UnsupportedState(party) != null)
            {
                return; // выключит ближайший опрос по кадрам — с причиной
            }

            // Думать можно на свободной карте и во время ожидания в поселении.
            // Всё прочее — переходы меню, в них решать нечего.
            Settlement waitingIn = null;
            if (!IsOnFreeMap(party))
            {
                waitingIn = PeacefulSettlement(party);
                if (waitingIn == null || !IsWaiting(MenuDriver.CurrentMenuId))
                {
                    return;
                }
            }

            _hoursSinceThink++;
            bool idle = waitingIn == null && party.DefaultBehavior == AiBehavior.Hold;
            if (_ticksThisSession > 0 && !idle && _hoursSinceThink < ThinkPeriodHours)
            {
                return;
            }
            _hoursSinceThink = 0;

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

            // Лучшее из того, что автопилот умеет выполнить. Осада, рейд и армия
            // партии игрока пока не по силам, но выключаться из-за них нельзя —
            // игра должна идти дальше, поэтому берётся следующее решение того же
            // штатного пересчёта, а пропуск пишется в журнал.
            AIBehaviorData chosen = AIBehaviorData.Invalid;
            float chosenScore = -1f;
            string skipped = null;
            foreach (var pair in think.AIBehaviorScores.OrderByDescending(p => p.Item2))
            {
                string reason = WhyNotApplicable(pair.Item1);
                if (reason == null)
                {
                    chosen = pair.Item1;
                    chosenScore = pair.Item2;
                    break;
                }
                skipped = skipped ?? Describe(pair.Item1) + " — " + reason;
            }

            if (chosen.AiBehavior == AiBehavior.None)
            {
                AutopilotLog.Write("  выполнимых решений нет (" + skipped + ") — партия продолжает текущее");
                return;
            }
            if (skipped != null)
            {
                AutopilotLog.Write("  пропущено: " + skipped + "; берём: " + Describe(chosen) + " = "
                                   + chosenScore.ToString("F3", CultureInfo.InvariantCulture));
            }

            if (waitingIn != null)
            {
                if (chosen.AiBehavior == AiBehavior.GoToSettlement && chosen.Party == waitingIn)
                {
                    AutopilotLog.Write("  остаёмся в «" + waitingIn.Name + "»: лучшая цель — само это поселение, как у NPC");
                    return;
                }
                _pendingDecision = chosen;
                _pendingScore = chosenScore;
                _hasPendingDecision = true;
                AutopilotLog.Write("  решено уйти из «" + waitingIn.Name + "»: " + Describe(chosen));
                return;
            }

            ApplyDecision(party, chosen, chosenScore);
        }

        /// <summary>Почему решение штатного AI автопилот не выполняет. null — выполняет.</summary>
        private string WhyNotApplicable(AIBehaviorData data)
        {
            if (data.WillGatherArmy)
            {
                return "со сбором армии — армии вне области автопилота";
            }
            switch (data.AiBehavior)
            {
                case AiBehavior.GoToSettlement:
                    if (!(data.Party is Settlement settlement))
                    {
                        return "без поселения";
                    }
                    return _cannotStay.Contains(settlement)
                        ? "в «" + settlement.Name + "» подождать нельзя, по кругу туда не ездим"
                        : null;
                case AiBehavior.PatrolAroundPoint:
                    return null;
                case AiBehavior.EscortParty:
                    return data.Party is MobileParty ? null : "без партии";
                default:
                    return "вне области автопилота";
            }
        }

        // ── Применение ───────────────────────────────────────────────────────

        /// <summary>Выдать приказ. Сюда приходят только решения, которые прошли
        /// WhyNotApplicable: поселение, партия и поведение уже проверены.</summary>
        private void ApplyDecision(MobileParty party, AIBehaviorData data, float score)
        {
            var settlement = data.Party as Settlement;

            try
            {
                switch (data.AiBehavior)
                {
                    case AiBehavior.GoToSettlement:
                        if (MobilePartyHelper.GetCurrentSettlementOfMobilePartyForAICalculation(party) == settlement)
                        {
                            // Движок для NPC приказ посетить поселение, в котором
                            // (или вплотную к центру которого) партия уже стоит, НЕ
                            // выдаёт — та же проверка в PartyHourlyAiTick. От
                            // пинг-понга она НЕ спасала: выход ставит партию к
                            // воротам, а хелпер считает «при поселении» ближе единицы
                            // к центру (прогон 13.09: 89 кругов). Пинг-понг снят
                            // пребыванием: из поселения теперь уходят по решению.
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
                        SetPartyAiAction.GetActionForEscortingParty(
                            party, (MobileParty)data.Party, data.NavigationType, data.IsFromPort, data.IsTargetingPort);
                        break;

                    default:
                        AutopilotLog.Write("  «" + data.AiBehavior + "» автопилот не выполняет — приказ не выдан");
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
