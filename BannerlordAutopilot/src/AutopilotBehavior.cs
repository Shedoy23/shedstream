using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Text;
using Helpers;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.GameState;
using TaleWorlds.CampaignSystem.Incidents;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Core;
using TaleWorlds.Library;

namespace BannerlordAutopilot
{
    /// <summary>Прототип автопилота партии игрока.
    ///
    /// ЧТО ОН ДОКАЗЫВАЕТ. Что цель партии игрока может выбрать ШТАТНЫЙ мозг
    /// движка, а не мод. Мод вызывает для MainParty тот же сбор оценок, который
    /// игра делает для партий лордов. После прогона 14.09 поверх штатных оценок
    /// добавлены две узкие поправки для игры без человека: убывание долгого
    /// патруля одной точки и порог смены близких по оценке маршрутов.
    ///
    /// НО ВЫБОР — НЕ КОПИЯ РЕШЕНИЯ NPC (итоговая независимая проверка 13.09).
    /// Оценки штатные, набор действий ограничен, а правило выбора своё: лучшее
    /// из выполнимых — осада, рейд, армия и поселение, где недавно нельзя было
    /// подождать, пропускаются. При устойчивом максимуме «осада» партия будет
    /// раз за разом делать следующее мирное решение, чего NPC не делает. Нет и
    /// штатного вероятностного допуска смены решения: у NPC он срабатывает,
    /// только когда CurrentObjectiveValue ≥ 0.05 (враг рядом). Вместо него мод
    /// использует проверяемый порог 0.15, чтобы не разворачиваться на полпути.
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
    /// ПОСЕЛЕНИЕ — ПО МОДЕЛИ NPC: вошёл, остался, ушёл по решению. NPC остаётся в
    /// поселении, пока лучшая цель — само это поселение
    /// (CheckExitingSettlementParallel), и уходит, когда пересчёт выбрал другое.
    /// Автопилот делает то же пунктами меню игрока: «Подождать» (время идёт,
    /// партия внутри), а когда пересчёт выбрал другую цель — «Перестать ждать»
    /// и выход. Прототип выходил сразу после входа, и 13.09 это дало 89 входов
    /// и выходов в одном городе. ГЛАВНОЕ ОГРАНИЧЕНИЕ: NPC в поселении движок
    /// кормит, пополняет и избавляет от пленных, партию игрока — нет. Её
    /// потребности не закрываются, оценка «побыть здесь» может не падать, а
    /// еда при этом тратится — до голода и падения морали.
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
    /// Текущая реализация также ведёт осады, рейды, оборону и армию;
    /// при отсутствии осадной цели от штатного AI ищет посильную крепость сама.
    ///
    /// Разбор: docs/BANNERLORD_AUTOPILOT_RESEARCH_2026-09-12.md,
    /// независимая проверка: dist/audit/autopilot-review/REVIEW_RU.md.</summary>
    public partial class AutopilotBehavior : CampaignBehaviorBase
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
        /// Одно из двух, что мод пишет в сейв (второе — отметки проходов
        /// обслуживания, SyncData). Нужен, чтобы после загрузки
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
        private MobileParty _combatTarget;
        // Участники чужого боя, из которого ушли, → тот самый MapEvent (см. InLeftForeignBattle).
        // object, а не MapEvent: тип живёт в TaleWorlds.CampaignSystem.MapEvents, и как
        // везде в этом файле его не называем, чтобы исходник собирался и со стендом.
        private readonly Dictionary<MobileParty, object> _leftForeignBattles = new Dictionary<MobileParty, object>();
        private int _lastProgressWeek = -1;
        internal bool RandomDialogsEnabled { get; set; } = true;
        private readonly Random _dialogRandom = new Random();
        private int _randomDialogSteps;
        private DateTime _nextRandomDialogAt;
        private DateTime _nextLiberationDialogAt;
        private DateTime _nextScriptedDialogAt;

        // Штатная оценка сухопутного патруля не убывает от времени у цели и
        // почти не зависит от расстояния партии до неё. В прогоне 14.09 это
        // дало серии до 72 пересчётов одной деревни. Сохраняем штатные оценки,
        // но постепенно уменьшаем ценность непрерывного патруля и на сутки
        // охлаждаем точку после долгого обхода.
        private Settlement _continuousPatrolSettlement;
        private double _continuousPatrolSinceHours = -1;
        private readonly Dictionary<Settlement, double> _patrolCooldownUntil = new Dictionary<Settlement, double>();
        private const double PatrolGraceHours = 6;
        private const double LongPatrolHours = 12;
        private const double PatrolCooldownHours = 24;
        private const float PatrolPenaltyPerHour = 0.05f;
        private const float MaximumPatrolPenalty = 0.8f;
        private const float PatrolCooldownPenalty = 0.5f;
        private const float DecisionChangeMargin = 0.15f;
        private const double TravelAfterPatrolHours = 24;
        private const double ReturnToPatrolHours = 48;
        private const double RecentTownHours = 30 * 24;
        private readonly Dictionary<Settlement, double> _recentTownVisits = new Dictionary<Settlement, double>();
        private const double RecruitmentVisitCooldownHours = 30 * 24;
        private Settlement _travelTown;
        private Settlement _travelOrigin;
        private Settlement _avoidAfterTravel;
        private double _avoidAfterTravelUntil;

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

        // Поселения, где подождать нельзя (у ворот замка, пункт недоступен), и час
        // кампании, до которого туда не ездим. NPC бы вошёл и остался, партия
        // игрока — нет, поэтому решение штатного AI снова ехать туда заменяется
        // следующим: иначе вход и выход по кругу, как 13.09. Срок — сутки, а не
        // сеанс: причина бывает временной (проверка 13.09), а сеанс длится часами.
        private readonly Dictionary<Settlement, double> _cannotStayUntil = new Dictionary<Settlement, double>();
        private const double CannotStayHours = 24;

        // Обслуживание партии в поселении (еда, найм, пленные). Объект живёт дольше
        // сеанса: повторный F11 не должен повторять проход того же часа. Отметки
        // проходов, кроме того, пишутся в сейв — см. SyncData.
        private readonly SettlementServices _services = new SettlementServices();

        // Почему обслуживание сейчас не идёт — пишется в журнал, только когда меняется.
        private readonly Dictionary<Settlement, string> _serviceBlocked = new Dictionary<Settlement, string>();

        // Час кампании, когда партия начала ждать, и было ли уже предупреждение о
        // долгом пребывании. Сторож простоя такое не видит — время-то идёт, — а
        // пребывание может не кончиться никогда: движок не обслуживает партию
        // игрока в поселении, и оценка «побыть здесь» не падает.
        private double _waitingSinceHours = -1;
        private bool _longStayWarned;
        private const double LongStayHours = 120;

        // Решение, ради которого надо уйти из поселения. Принимается часовым
        // тиком, выполняется опросом по кадрам: пункты меню нажимаются там же,
        // где их нажал бы игрок, а приказ выдаётся сразу после выхода — иначе
        // партия час простояла бы у ворот.
        private bool _hasPendingDecision;
        private AIBehaviorData _pendingDecision;
        private float _pendingScore;

        // Пересчёт с обычным периодом NPC: раз в шесть часов (AiPartyThinkBehavior.
        // PartyHourlyAiTick, num = 6). Сокращений периода NPC (Rethink, армия,
        // переход) нет, а стоящая партия пересчитывается каждый час — это своё
        // правило, чтобы игрок не стоял до шести часов. Каждый час пересчитывать
        // едущую партию нельзя: при близких оценках она разворачивалась бы на полпути.
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
        private int _incidentsResolvedThisSession;
        private int _kingdomDecisionsResolvedThisSession;
        private object _lastIncidentLogged;
        private int _incidentHoldPolls;
        private string _moveWatchKey;
        private CampaignVec2 _moveWatchPosition;
        private int _moveWatchHours;
        private int _moveWatchNudges;
        private Settlement _stuckTarget;
        private double _stuckTargetUntil;

        /// <summary>Сколько игровых часов партия может простоять под приказом
        /// «ехать», прежде чем это считается застреванием, сколько раз приказ
        /// перевыдаётся и на сколько часов снимается недостижимая цель.</summary>
        private const int StuckHours = 6;
        private const int StuckNudges = 2;
        private const double StuckTargetAvoidHours = 24;
        private const float MovedEpsilon = 0.01f;

        /// <summary>Сколько опросов (по 0.5 с) ждём показа выпавшего события.
        /// Движок показывает его на ближайшем Campaign.Tick, то есть обычно
        /// хватает одного; предел — на случай, если показа не будет вовсе.</summary>
        private const int IncidentHoldPolls = 20;

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
            _postBattleRestPending = false;
            _postBattleRestSettlement = null;
            _postBattleRestUntil = -1;
            ResetPrisonerScreen();
            _lootEncounter = null;
            ResetOperations();
            _banditGatheredBattle = null;
            _banditGatherPreviewFault = false;
            _ticksThisSession = 0;
            _targetChangesThisSession = 0;
            _reappliesThisSession = 0;
            _settlementVisitsThisSession = 0;
            _settlementExitsThisSession = 0;
            _lastAppliedDescription = "—";
            _lastTargetKey = null;
            _combatTarget = null;
            _nextLiberationDialogAt = DateTime.MinValue;
            _nextScriptedDialogAt = DateTime.MinValue;
            _leftForeignBattles.Clear();
            _lastProgressWeek = -1;
            _continuousPatrolSettlement = null;
            _continuousPatrolSinceHours = -1;
            _travelTown = null;
            _travelOrigin = null;
            _avoidAfterTravel = null;
            _avoidAfterTravelUntil = 0;
            _recentTownVisits.Clear();
            _startedIn = null;
            _handledSettlement = null;
            _resumeSpeed = 0;
            _cannotStayUntil.Clear();
            _serviceBlocked.Clear();
            _waitingSinceHours = -1;
            _longStayWarned = false;
            _incidentHoldPolls = 0;
            _moveWatchKey = null;
            _moveWatchHours = 0;
            _moveWatchNudges = 0;
            _stuckTarget = null;
            _stuckTargetUntil = 0;
            _hasPendingDecision = false;
            _hoursSinceThink = 0;
            _lastCampaignHours = -1;
            _stallReported = false;
            _stallsThisSession = 0;
            _longestStallSeconds = 0;
            _timeStartsThisSession = 0;
            _incidentsResolvedThisSession = 0;
            _kingdomDecisionsResolvedThisSession = 0;
            _lastIncidentLogged = null;
        }

        public override void RegisterEvents()
        {
            Instance = this;
            CampaignEvents.HourlyTickEvent.AddNonSerializedListener(this, OnHourlyTick);
            CampaignEvents.OnGameLoadFinishedEvent.AddNonSerializedListener(this, OnGameLoadFinished);
            CampaignEvents.OnSessionLaunchedEvent.AddNonSerializedListener(this, RegisterBanditGatherDialog);
        }

        public override void SyncData(IDataStore dataStore)
        {
            // При сохранении здесь записывается факт; при загрузке присвоенное
            // значение тут же перезаписывается прочитанным из сейва.
            _activeAtSave = _mode == Mode.Apply;
            dataStore.SyncData("shedautopilot_activeAtSave", ref _activeAtSave);

            // Отметки проходов обслуживания: без них загрузка сейва обнуляла предел
            // «проход раз в шесть часов» (проверка 14.09). В сейве старой версии
            // ключа нет — SyncData значение не трогает, отметок нет, проход разрешён.
            string passes = _services.SavePasses();
            dataStore.SyncData("shedautopilot_servicePasses", ref passes);
            if (dataStore.IsLoading)
            {
                _services.LoadPasses(passes);
            }
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

            bool operation = IsArmyDispersedMenu(party) || CanStartOperation(party) || (party.Army?.LeaderParty != null && !ControlsParty(party));
            string unsupported = operation || IsSupportedFieldBattleEncounter(party) || IsForeignFieldBattle(party) ? null : UnsupportedState(party);
            if (unsupported != null)
            {
                reason = unsupported;
                return false;
            }

            Settlement peaceful = PeacefulSettlement(party);
            if (!operation && peaceful == null && PlayerEncounter.Current != null && !IsSupportedFieldBattleEncounter(party) && !IsForeignFieldBattle(party))
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
            StreamStatus.SetActive(mode == Mode.Apply);
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
            StreamStatus.SetActive(false);
            ArmAutoResume(reason, wasApply);

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
            // Простой, который ещё идёт, в _longestStallSeconds не попал: тот
            // обновляется, только когда время снова пошло.
            double longest = _stallReported
                ? Math.Max(_longestStallSeconds, (Clock() - _lastProgressAt).TotalSeconds)
                : _longestStallSeconds;
            AutopilotLog.Write("итог сеанса: пересчётов " + _ticksThisSession
                               + "; смен цели " + _targetChangesThisSession
                               + "; повторов того же приказа " + _reappliesThisSession
                               + "; прибытий во время сеанса " + _settlementVisitsThisSession
                               + "; подтверждённых выходов " + _settlementExitsThisSession
                               + "; простоев " + _stallsThisSession
                               + " (самый долгий " + longest.ToString("F0", CultureInfo.InvariantCulture) + " с"
                               + (_stallReported ? ", последний ещё идёт" : "") + ")"
                               + "; снятий с паузы " + _timeStartsThisSession);
            AutopilotLog.Write("итог событий: случайных " + _incidentsResolvedThisSession
                               + "; решений королевства " + _kingdomDecisionsResolvedThisSession);
        }

        // ── Проверка состояния (каждые полсекунды, независимо от хода времени) ──

        /// <summary>Меню поселения и встреча держат время на паузе, часовых
        /// тиков в этот момент нет — поэтому реакция идёт по кадрам.
        /// Возвращает true, если партия на свободной карте и цикл может идти.</summary>
        internal bool PollState() => Guarded("опрос", PollStateCore);

        /// <summary>Общая страховка кадрового опроса (23.09). Опрос идёт из
        /// OnApplicationTick, и исключение отсюда роняет игру. Части опроса
        /// ловят свои ошибки сами, но не все — поэтому последний рубеж здесь:
        /// выключиться с причиной в логе, как при любом другом отказе.</summary>
        internal bool Guarded(string what, Func<bool> poll)
        {
            if (_mode == Mode.Off) return false;
            try { return poll(); }
            catch (Exception ex)
            {
                Exception cause = ex is TargetInvocationException && ex.InnerException != null ? ex.InnerException : ex;
                Disable(what + " упал: " + cause.GetType().Name + ": " + cause.Message);
                return false;
            }
        }

        private bool PollStateCore()
        {
            if (_mode == Mode.Off || Campaign.Current == null)
            {
                return false;
            }

            MobileParty party = MobileParty.MainParty;
            if (Hero.MainHero?.IsPrisoner == true)
            {
                PollCaptivity();
                return false;
            }
            if (party == null || !party.IsActive)
            {
                Disable("партия игрока пропала или неактивна");
                return false;
            }

            // Сторож простоя — до всех обработчиков: любой из них, взяв опрос себе,
            // иначе глушит и запись о простое (16.09 19:44 — 24 с тишины на встрече).
            if (_mode == Mode.Apply)
            {
                WatchTime(party);
            }

            if (PollLootScreen()) return false;
            if (PollOwnedSimulation()) return false;
            if (PollPrisonerScreen()) return false;
            if (PollDialogs()) return false;

            // Окна поверх карты закрываем ДО всего, что умеет ответить «занято».
            // Осадный обработчик при окне возвращает «занято» и съедает опрос, и
            // 18.09 в 19:54:27 событие «Подкоп» во время осады так и провисело 22
            // секунды, пока владелец не нажал сам: до разбора события очередь не
            // доходила. Экраны добычи, пленных и разговоры разбираются раньше —
            // они не слои карты, а другие состояния игры.
            if (_mode == Mode.Apply)
            {
                if (TryHandleKingdomDecision())
                {
                    return false;
                }
                if (TryHandleMapIncident())
                {
                    return false;
                }
            }
            if (PollArmyDispersed(party)) return false;
            if (PollUnavoidableSurrender(party)) return false;
            if (PollRaidWarning()) return false;
            if (PollFlee(party)) return false;
            if (PollEmergencyDefense(party)) return false;
            if (PollOffensiveSiege(party)) return false;
            if (PollRaid(party)) return false;
            if (PollOperations(party)) return false;
            if (PollArmy(party)) return false;

            // СНАЧАЛА опасные состояния — до любых рассуждений о поселении.
            if (IsForeignFieldBattle(party))
            {
                if (_mode == Mode.Apply && MapIsActiveScreen() && !InformationManager.IsAnyInquiryActive())
                {
                    JoinOrLeaveForeignBattle(party);
                }
                return false;
            }
            if (IsSupportedFieldBattleEncounter(party))
            {
                if (_mode == Mode.Observe || !MapIsActiveScreen() || InformationManager.IsAnyInquiryActive())
                {
                    return false;
                }
                string menu = MenuDriver.CurrentMenuId;
                if (menu == null)
                {
                    return false;
                }
                if (menu != "encounter")
                {
                    Disable("перед полевым боем открыто неподдерживаемое меню: " + MenuDriver.Describe());
                    return false;
                }
                if (TrySendTroopsWhenWounded()) return false;
                if (!MenuDriver.CanInvoke("attack", out string attackWhy))
                {
                    Disable("полноценный бой нельзя начать: " + attackWhy);
                    return false;
                }
                if (!GatherBanditsForBattle(party)) return false;
                if (MenuDriver.TryInvoke("attack", out attackWhy))
                {
                    AutopilotLog.Write("БОЙ: нажата штатная кнопка «В атаку»; открывается полноценная боевая сцена");
                }
                else
                {
                    Disable("полноценный бой нельзя начать: " + attackWhy);
                }
                return false;
            }

            string unsupported = UnsupportedState(party);
            if (unsupported != null)
            {
                Disable(unsupported);
                return false;
            }

            Settlement peaceful = PeacefulSettlement(party);
            if (peaceful == null)
            {
                _postBattleRestSettlement = null;
                _postBattleRestUntil = -1;
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
                if (peaceful.IsTown) _recentTownVisits[peaceful] = CampaignTime.Now.ToHours;
            }

            if (!AutoLeaveSettlement)
            {
                Disable("вошли в «" + peaceful.Name + "», работа в поселениях выключена — дальше руками");
                return false;
            }

            if (!MapIsActiveScreen())
            {
                return false; // под экраном или окном меню не трогаем; затянется — запишет сторож
            }

            if (HoldExitForQueuedIncident(party, peaceful))
            {
                return false;
            }

            string menuId = MenuDriver.CurrentMenuId;
            if (IsWaiting(menuId))
            {
                NoteWaiting();
                if (HoldShelter(party, peaceful)) return false;
                TryEmergencyDefense(party, peaceful);
                if (HoldPostBattleRest(party, peaceful, true))
                {
                    TryServe(party, peaceful, menuId, "отдых после боя");
                    return false;
                }
                if (_hasPendingDecision)
                {
                    StopWaitingAndLeave(party, peaceful);
                }
                else
                {
                    TryServe(party, peaceful, menuId, "ожидание");
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
                    if (HoldPostBattleRest(party, peaceful, false) || HoldShelter(party, peaceful)) _hasPendingDecision = false;
                    if (_hasPendingDecision || CannotStay(peaceful))
                    {
                        LeaveAndApplyPending(party, peaceful);
                    }
                    else
                    {
                        // Сначала потребности, потом ожидание: следующий пересчёт AI
                        // увидит купленную еду и нанятых.
                        TryServe(party, peaceful, menuId, "прибытие");
                        if (_mode == Mode.Apply)
                        {
                            StartWaiting(party, peaceful, menuId);
                        }
                    }
                    return false;

                case "town_outside":
                case "castle_outside":
                case "village_looted":
                    // У ворот, куда не пускают, и в разграбленной деревне подождать
                    // нельзя — остаётся уйти (village_looted_leave_on_consequence
                    // тоже LeaveSettlement → Finish → Hold).
                    if (!CannotStay(peaceful))
                    {
                        MarkCannotStay(peaceful, "меню " + menuId);
                    }
                    LeaveAndApplyPending(party, peaceful);
                    return false;

                default:
                    Disable("в «" + peaceful.Name + "» открыто меню, которое автопилот не знает: "
                            + MenuDriver.Describe());
                    return false;
            }
        }

        /// <summary>true — ничего в поселении не делаем: движок ещё не показал
        /// выпавшее событие, а выйти до показа — уронить игру.
        ///
        /// Выпавшее на входе событие движок кладёт в MapState.NextIncident
        /// (IncidentsCampaignBehaviour.InvokeIncident, 190449-190456), а условия
        /// проверяет на СЛЕДУЮЩЕМ Campaign.Tick (10136-10143). Условия пяти
        /// ванильных событий с триггером «вход» читают MainParty.CurrentSettlement
        /// без проверки на null — incident_hammer_of_the_sun (193255),
        /// through_proper_channels (192377), the_quiet_life (192768),
        /// occupational_safety (192852), jobs_for_the_lads (192925). Человек так не
        /// успевает, автопилот выходит за ту же секунду: 18.09 14:34:34 игра
        /// закрылась с 0xC0000005 внутри условия hammer_of_the_sun
        /// (evidence/crash-20260918-143427-stack.txt).
        ///
        /// Держим выход, пока очередь не опустеет: событие покажется, и его
        /// разберёт TryHandleMapIncident, как любое другое. Показа нет за предел
        /// опросов — снимаем очередь сами: потерять одно случайное событие лучше,
        /// чем встать в поселении навсегда.</summary>
        private bool HoldExitForQueuedIncident(MobileParty party, Settlement settlement)
        {
            MapState map = Game.Current?.GameStateManager?.ActiveState as MapState;
            if (party.CurrentSettlement == null || map == null || map.NextIncident == null)
            {
                _incidentHoldPolls = 0;
                return false;
            }

            _incidentHoldPolls++;
            if (_incidentHoldPolls == 1)
            {
                AutopilotLog.Write("  СОБЫТИЕ в очереди: выход из «" + settlement.Name
                                   + "» придержан до показа");
            }
            if (_incidentHoldPolls <= IncidentHoldPolls)
            {
                return true;
            }

            map.NextIncident = null;
            AutopilotLog.Write("  СОБЫТИЕ не показано за " + IncidentHoldPolls
                               + " опросов — снято из очереди, выходим из «" + settlement.Name + "»");
            _incidentHoldPolls = 0;
            return false;
        }

        private static bool IsWaiting(string menuId)
        {
            return (menuId == "town_wait_menus" || menuId == "village_wait_menus")
                   && PlayerEncounter.Current != null
                   && PlayerEncounter.Current.IsPlayerWaiting;
        }

        /// <summary>Карта — активный экран, и её не держит окно. Иначе
        /// Campaign.CurrentMenuContext отдаёт меню карты ПОД другим экраном
        /// (1.4.8, строка 9568), и нажатие пункта было бы кнопкой, которую игрок
        /// не видит (проверка 13.09). Окна поверх карты ActiveState не меняют —
        /// их видно только по экрану карты (WindowOverMap, прогон 14.09).</summary>
        private static bool MapIsActiveScreen()
        {
            GameStateManager states = Game.Current?.GameStateManager;
            return states != null && states.ActiveState is MapState && !states.ActiveStateDisabledByUser
                   && WindowOverMap() == null;
        }

        /// <summary>Какое окно открыто поверх карты; null — ни одного.
        ///
        /// Окна — слои экрана карты (MapState.Handler), флаги которых движок сам
        /// сверяет перед действиями на карте. Прогон 14.09: окно случайного события
        /// заперло время, а автопилот под ним обслужил партию и нажал «Подождать».
        /// SandBox.View мод не подключает — флаги читаются по имени из
        /// EngineContract.MapWindows, их наличие проверяет контракт.</summary>
        private static string WindowOverMap()
        {
            object screen = (Game.Current?.GameStateManager?.ActiveState as MapState)?.Handler;
            if (screen == null)
            {
                return null;
            }
            Type type = screen.GetType();
            foreach ((string property, string name) in EngineContract.MapWindows)
            {
                if (type.GetProperty(property)?.GetValue(screen) is true)
                {
                    return name;
                }
            }
            object encyclopedia = type.GetProperty("EncyclopediaScreenManager")?.GetValue(screen);
            return encyclopedia?.GetType().GetProperty("IsEncyclopediaOpen")?.GetValue(encyclopedia) is true
                ? "энциклопедия"
                : null;
        }

        /// <summary>Решает обязательные голосования королевства через их VM.
        /// Проценты, доступность и последствия остаются расчётом игры; мод лишь
        /// выбирает доступный вариант с максимальной уже набранной поддержкой.
        /// За один опрос выполняется один шаг, поэтому последовательность
        /// запрос → голосование → итог → следующее решение не теряет модалки.</summary>
        private bool TryHandleKingdomDecision()
        {
            object state = Game.Current?.GameStateManager?.ActiveState;
            if (state == null || state.GetType().FullName != "TaleWorlds.CampaignSystem.GameState.KingdomState")
            {
                return false;
            }

            try
            {
                Type screenManager = AppDomain.CurrentDomain.GetAssemblies()
                    .Select(a => a.GetType("TaleWorlds.ScreenSystem.ScreenManager", false))
                    .FirstOrDefault(t => t != null);
                object screen = screenManager?.GetProperty("TopScreen", BindingFlags.Public | BindingFlags.Static)
                    ?.GetValue(null);
                object source = screen?.GetType().GetProperty("DataSource", BindingFlags.Public | BindingFlags.Instance)
                    ?.GetValue(screen);
                object decisions = source?.GetType().GetProperty("Decision", BindingFlags.Public | BindingFlags.Instance)
                    ?.GetValue(source);
                if (decisions == null)
                {
                    Disable("экран решений королевства открыт, но его модель недоступна");
                    return true;
                }

                object current = decisions.GetType().GetProperty("CurrentDecision")?.GetValue(decisions);
                bool inquiry = InformationManager.IsAnyInquiryActive();
                FieldInfo queryField = decisions.GetType().GetField("_queryData", BindingFlags.NonPublic | BindingFlags.Instance);
                InquiryData query = queryField?.GetValue(decisions) as InquiryData;

                // Первый запрос «принять решение?» хранится в самой VM.
                if (inquiry && query != null && query.IsAffirmativeOptionShown && query.AffirmativeAction != null)
                {
                    string title = query.TitleText;
                    InformationManager.HideInquiry();
                    queryField.SetValue(decisions, null);
                    query.AffirmativeAction();
                    AutopilotLog.Write("РЕШЕНИЕ КОРОЛЕВСТВА: подтверждён запрос «" + title + "»");
                    return true;
                }

                if (current != null)
                {
                    Type itemType = current.GetType();
                    bool concluded = itemType.GetProperty("IsKingsDecisionOver")?.GetValue(current) is true;
                    if (!concluded)
                    {
                        object list = itemType.GetProperty("DecisionOptionsList")?.GetValue(current);
                        var options = (list as System.Collections.IEnumerable)?.Cast<object>().ToList()
                                      ?? new List<object>();
                        var available = options.Where(o => o.GetType().GetProperty("CanBeChosen")?.GetValue(o) is true).ToList();
                        object chosen = available.Where(o => !(o.GetType().GetProperty("IsOptionForAbstain")?.GetValue(o) is true))
                            .OrderByDescending(o => (int)(o.GetType().GetProperty("WinPercentage")?.GetValue(o) ?? -1))
                            .FirstOrDefault()
                            ?? available.FirstOrDefault(o => o.GetType().GetProperty("IsOptionForAbstain")?.GetValue(o) is true);
                        if (chosen == null)
                        {
                            Disable("в решении королевства нет доступного варианта");
                            return true;
                        }

                        Type optionType = chosen.GetType();
                        optionType.GetMethod("ExecuteSelection", BindingFlags.NonPublic | BindingFlags.Instance)
                            ?.Invoke(chosen, null);
                        bool supporter = itemType.GetProperty("IsPlayerSupporter")?.GetValue(current) is true;
                        bool abstain = optionType.GetProperty("IsOptionForAbstain")?.GetValue(chosen) is true;
                        if (supporter && !abstain)
                        {
                            optionType.GetMethod("OnSupportStrengthChange", BindingFlags.NonPublic | BindingFlags.Instance)
                                ?.Invoke(chosen, new object[] { 0 });
                        }
                        if (!(itemType.GetProperty("CanEndDecision")?.GetValue(current) is true))
                        {
                            Disable("самый популярный вариант выбран, но игра не разрешила завершить решение");
                            return true;
                        }
                        itemType.GetMethod("ExecuteFinalSelection", BindingFlags.Public | BindingFlags.Instance)
                            ?.Invoke(current, null);
                        _kingdomDecisionsResolvedThisSession++;
                        string name = optionType.GetProperty("Name")?.GetValue(chosen)?.ToString() ?? "вариант";
                        int percent = (int)(optionType.GetProperty("WinPercentage")?.GetValue(chosen) ?? -1);
                        AutopilotLog.Write("РЕШЕНИЕ КОРОЛЕВСТВА: выбран самый популярный вариант «" + name
                                           + "» (" + percent + "%)" + (supporter && !abstain ? ", минимальная поддержка" : ""));
                        return true;
                    }

                    // На следующем кадре запускаем штатное итоговое окно.
                    if (!inquiry)
                    {
                        itemType.GetMethod("ExecuteDone", BindingFlags.NonPublic | BindingFlags.Instance)
                            ?.Invoke(current, null);
                        return true;
                    }

                    // Кнопка OK итогового окна вызывает именно OnDecisionOver.
                    InformationManager.HideInquiry();
                    decisions.GetType().GetMethod("OnDecisionOver", BindingFlags.NonPublic | BindingFlags.Instance)
                        ?.Invoke(decisions, null);
                    AutopilotLog.Write("РЕШЕНИЕ КОРОЛЕВСТВА: итог подтверждён");
                    return true;
                }

                // Единоличное решение показывает итог без CurrentDecision.
                if (inquiry)
                {
                    InformationManager.HideInquiry();
                    decisions.GetType().GetMethod("OnSingleDecisionOver", BindingFlags.NonPublic | BindingFlags.Instance)
                        ?.Invoke(decisions, null);
                    AutopilotLog.Write("РЕШЕНИЕ КОРОЛЕВСТВА: итог единоличного решения подтверждён");
                    return true;
                }

                // VM успевает открыть следующее неразрешённое решение своим
                // OnFrameTick. Если их больше нет, возвращаемся на карту.
                bool any = Clan.PlayerClan?.Kingdom?.UnresolvedDecisions
                    .Any(d => !d.ShouldBeCancelled()) is true;
                if (!any)
                {
                    Game.Current.GameStateManager.PopState(0);
                    AutopilotLog.Write("РЕШЕНИЯ КОРОЛЕВСТВА: цепочка закончена, возвращаемся на карту");
                }
                return true;
            }
            catch (Exception ex)
            {
                Exception cause = ex is TargetInvocationException && ex.InnerException != null ? ex.InnerException : ex;
                Disable("обработка решения королевства упала: " + cause.GetType().Name + ": " + cause.Message);
                return true;
            }
        }

        /// <summary>По запросу владельца случайно выбирать вариант показанного
        /// события. Варианты и последствия берутся из публичного Incident API;
        /// само окно закрывается тем же MapScreen.RemoveMapView, что вызывает UI.</summary>
        private bool TryHandleMapIncident()
        {
            object screen = (Game.Current?.GameStateManager?.ActiveState as MapState)?.Handler;
            if (screen == null || !(screen.GetType().GetProperty("IsMapIncidentActive")?.GetValue(screen) is true))
            {
                _lastIncidentLogged = null;
                return false;
            }

            try
            {
                Type viewType = AppDomain.CurrentDomain.GetAssemblies()
                    .Select(a => a.GetType("SandBox.View.Map.MapIncidentView", false))
                    .FirstOrDefault(t => t != null);
                MethodInfo getView = screen.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance)
                    .FirstOrDefault(m => m.Name == "GetMapView" && m.IsGenericMethodDefinition && m.GetParameters().Length == 0);
                object view = viewType != null && getView != null
                    ? getView.MakeGenericMethod(viewType).Invoke(screen, null)
                    : null;
                FieldInfo incidentField = viewType?.GetField("Incident", BindingFlags.Public | BindingFlags.Instance);
                Incident incident = view != null && incidentField != null ? incidentField.GetValue(view) as Incident : null;
                if (view == null || incident == null)
                {
                    if (_lastIncidentLogged == null)
                    {
                        _lastIncidentLogged = screen;
                        AutopilotLog.Write("СОБЫТИЕ: окно найдено, но активный Incident прочитать нельзя — оставлено человеку");
                    }
                    return true;
                }

                int option = incident.NumOfOptions > 0 ? _dialogRandom.Next(incident.NumOfOptions) : -1;
                bool firstLog = _lastIncidentLogged != incident;
                if (firstLog)
                {
                    _lastIncidentLogged = incident;
                    AutopilotLog.Write("СОБЫТИЕ: «" + incident.Title + "» [" + incident.StringId + "], вариантов "
                                       + incident.NumOfOptions);
                    for (int i = 0; i < incident.NumOfOptions; i++)
                    {
                        string hints = string.Join("; ", incident.GetOptionHint(i).Select(x => x.ToString()).ToArray());
                        AutopilotLog.Write("  вариант " + i + ": " + incident.GetOptionText(i) + " => " + hints);
                    }
                }
                if (option < 0)
                {
                    if (firstLog)
                    {
                        AutopilotLog.Write("  нет доступных вариантов события — требуется игрок");
                    }
                    return true;
                }

                string selected = incident.GetOptionText(option).ToString();
                List<string> results = incident.InvokeOption(option).Select(x => x.ToString()).ToList();
                MethodInfo remove = screen.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance)
                    .FirstOrDefault(m => m.Name == "RemoveMapView" && m.GetParameters().Length == 1
                                         && m.GetParameters()[0].ParameterType.IsAssignableFrom(view.GetType()));
                if (remove == null)
                {
                    Disable("событие выполнено, но его окно нельзя закрыть: MapScreen.RemoveMapView не найден");
                    return true;
                }
                remove.Invoke(screen, new[] { view });
                _incidentsResolvedThisSession++;
                _lastIncidentLogged = null;
                AutopilotLog.Write("  СОБЫТИЕ РЕШЕНО автоматически: вариант " + option + " «" + selected + "»"
                                   + (results.Count > 0 ? "; результат: " + string.Join("; ", results.ToArray()) : ""));
                return true;
            }
            catch (Exception ex)
            {
                Exception cause = ex is TargetInvocationException && ex.InnerException != null ? ex.InnerException : ex;
                Disable("обработка случайного события упала: " + cause.GetType().Name + ": " + cause.Message);
                return true;
            }
        }

        /// <summary>Завести отсчёт пребывания при первом наблюдении ожидания в сеансе.
        /// Семантика: отсчёт — с момента, когда ожидание увидел ЭТОТ сеанс
        /// автопилота, а не с нажатия «Подождать». Ожидание, начатое человеком до
        /// F11, раньше не заводило отсчёт вовсе (проверка 13.09); повторный F11 —
        /// новый сеанс, и отсчёт начинается заново, как и все счётчики сеанса.</summary>
        private void NoteWaiting()
        {
            if (_waitingSinceHours < 0)
            {
                _waitingSinceHours = CampaignTime.Now.ToHours;
                _longStayWarned = false;
            }
        }

        /// <summary>Обслуживание партии в поселении, если пора и можно. Проход не
        /// чаще раза в ServiceLimits.PassIntervalHours; причина, по которой сейчас
        /// нельзя, пишется в журнал один раз, пока не сменится.</summary>
        private static bool NeedsRecruitment(MobileParty party) => party?.Party != null
            && party.Party.PartySizeLimit > 0
            && party.Party.NumberOfAllMembers < (int)Math.Ceiling(party.Party.PartySizeLimit * .9);

        private Settlement FindRecruitmentTarget(MobileParty party)
        {
            var candidates = Settlement.All.Where(s => s != null && (s.IsTown || s.IsVillage)
                && s.MapFaction != null && party.MapFaction != null
                && !party.MapFaction.IsAtWarWith(s.MapFaction)
                && !s.IsUnderSiege && !s.IsUnderRaid && !s.IsRaided
                && !CannotStay(s) && _services.IsDue(s)
                && !_services.WasServicedRecently(s, RecruitmentVisitCooldownHours)
                && (!s.IsTown || !_recentTownVisits.TryGetValue(s, out double townVisit)
                    || CampaignTime.Now.ToHours - townVisit >= RecruitmentVisitCooldownHours)
                && SettlementServices.HasAffordableRecruits(party, s)).ToList();
            if (party.DefaultBehavior == AiBehavior.GoToSettlement
                && candidates.Contains(party.TargetSettlement)) return party.TargetSettlement;
            return candidates.OrderBy(s => party.Position.DistanceSquared(s.Position)).FirstOrDefault();
        }

        private void TryServe(MobileParty party, Settlement settlement, string menuId, string trigger)
        {
            if (_mode != Mode.Apply || !_services.IsDue(settlement))
            {
                return;
            }
            string blocked = ServiceBlocked(party, settlement, menuId);
            if (blocked != null)
            {
                if (!_serviceBlocked.TryGetValue(settlement, out string last) || last != blocked)
                {
                    _serviceBlocked[settlement] = blocked;
                    AutopilotLog.Write("  обслуживание «" + settlement.Name + "» не сейчас: " + blocked);
                }
                return;
            }
            _serviceBlocked.Remove(settlement);
            try
            {
                _services.Run(party, settlement, trigger);
            }
            catch (Exception ex)
            {
                Disable("обслуживание в «" + settlement.Name + "» упало: " + ex.GetType().Name + ": " + ex.Message);
            }
        }

        /// <summary>Почему обслуживание сейчас не идёт. null — можно. Признак
        /// состояния — открытое меню поселения, а не CurrentSettlement или
        /// IsPlayerWaiting: в деревенском ожидании CurrentSettlement пуст, а флаг
        /// ожидания остаётся включённым и после «Перестать ждать».</summary>
        private static string ServiceBlocked(MobileParty party, Settlement settlement, string menuId)
        {
            if (!MapIsActiveScreen())
            {
                return "поверх карты " + (WindowOverMap() ?? "другой экран или окно");
            }
            if (InformationManager.IsAnyInquiryActive())
            {
                return "открыто окно с вопросом";
            }
            if (Campaign.Current.ConversationManager != null && Campaign.Current.ConversationManager.IsConversationInProgress)
            {
                return "идёт разговор";
            }
            if (party.MapEvent != null || party.SiegeEvent != null || settlement.IsUnderSiege)
            {
                return "бой или осада";
            }
            if (settlement.IsVillage && (settlement.IsRaided || settlement.IsUnderRaid))
            {
                return "деревня разграблена или под налётом";
            }
            switch (menuId)
            {
                case "town":
                case "village":
                case "town_wait_menus":
                    return null;
                case "castle":
                    return "в замке у игрока нет ни рынка, ни добровольцев";
                case "village_wait_menus":
                    return "в деревенском ожидании партия за околицей — торговать и нанимать игрок там не может; обслуживание при следующем входе";
                default:
                    return "открыто меню «" + menuId + "», а не меню поселения";
            }
        }

        private bool CannotStay(Settlement settlement)
        {
            return _cannotStayUntil.TryGetValue(settlement, out double until) && CampaignTime.Now.ToHours < until;
        }

        private void MarkCannotStay(Settlement settlement, string why)
        {
            _cannotStayUntil[settlement] = CampaignTime.Now.ToHours + CannotStayHours;
            AutopilotLog.Write("  подождать в «" + settlement.Name + "» нельзя (" + why
                               + "): уходим; сутки автопилот туда не поедет");
        }

        /// <summary>Остаться в поселении, как NPC: пункт «Подождать». В городе и
        /// замке партия остаётся внутри, в деревне движок сам выводит её за
        /// околицу (game_menu_wait_village_on_consequence) — так и у игрока.</summary>
        private void StartWaiting(MobileParty party, Settlement settlement, string menuId)
        {
            string option = menuId == "village" ? "village_wait" : "town_wait";
            if (!MenuDriver.TryInvoke(option, out string why))
            {
                MarkCannotStay(settlement, why);
                LeaveAndApplyPending(party, settlement);
                return;
            }

            if (IsWaiting(MenuDriver.CurrentMenuId))
            {
                _waitingSinceHours = CampaignTime.Now.ToHours;
                _longStayWarned = false;
                HoldPostBattleRest(party, settlement, true);
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

        /// <summary>Пересчёт выбрал другую цель: «Перестать ждать», затем выход.
        /// Конец ожидания подтверждается меню, а не флагом: в деревне движок
        /// оставляет IsPlayerWaiting включённым (game_menu_stop_waiting_at_village_on_consequence
        /// его не сбрасывает), и проверка по флагу выключала автопилот (проверка 13.09).</summary>
        private void StopWaitingAndLeave(MobileParty party, Settlement settlement)
        {
            if (!MenuDriver.TryInvoke("wait_leave", out string why))
            {
                Disable("не удалось перестать ждать в «" + settlement.Name + "»: " + why);
                return;
            }
            if (IsWaiting(MenuDriver.CurrentMenuId))
            {
                Disable("«Перестать ждать» в «" + settlement.Name + "» нажат, но меню ожидания осталось: "
                        + MenuDriver.Describe());
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
                var battle = party.MapEvent ?? PlayerEncounter.Battle;
                return "идёт бой — вне области прототипа; menu=" + MenuDriver.CurrentMenuId
                    + "; field=" + battle.IsFieldBattle + "; outside=" + battle.IsSiegeOutside
                    + "; sally=" + battle.IsSallyOut + "; assault=" + battle.IsSiegeAssault
                    + "; settlement=" + battle.MapEventSettlement?.StringId
                    + "; siege=" + party.SiegeEvent?.BesiegedSettlement?.StringId;
            }
            if (party.SiegeEvent != null || party.BesiegedSettlement != null)
            {
                return "партия в осаде — вне области прототипа";
            }
            if (!ControlsParty(party))
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

        /// <summary>Меню чужого полевого боя: партия наткнулась на бой, в котором не
        /// участвует. Бои у поселений и в осаде сюда не входят — их ведёт PollOperations
        /// или они вне области автопилота.</summary>
        private static bool IsForeignFieldBattle(MobileParty party)
        {
            string menu = MenuDriver.CurrentMenuId;
            if (PlayerEncounter.Current == null || party == null
                || (menu != "join_encounter" && menu != "encounter_interrupted"))
            {
                return false;
            }
            var battle = PlayerEncounter.EncounteredBattle;
            // Бой У ПОСЕЛЕНИЯ тоже наш случай: 18.09 в «Сестадайм» штатная кнопка
            // прерванного рейда открыла join_encounter у деревни, прежнее условие
            // «бой вне поселения» сюда не пускало, и автопилот выключался на
            // «неизвестном меню». Свои осады и рейды разбираются раньше, в
            // PollOffensiveSiege/PollRaid/PollOperations.
            return battle != null && party.MapEvent == null && party.Army == null
                   && party.SiegeEvent == null && party.BesiegedSettlement == null
                   && party.CurrentSettlement == null;
        }

        /// <summary>Встреча не останавливает автопилот. Помощь защитникам — решение
        /// владельца 14.09, и доступность кнопки решает сама игра. Иначе штатный уход:
        /// в драку нейтралов и в бой двух наших врагов игра не пускает ни на одну
        /// сторону (MapEvent.CanPartyJoinBattle, 1.4.8 строка 112256).</summary>
        private void JoinOrLeaveForeignBattle(MobileParty party)
        {
            string menu = MenuDriver.CurrentMenuId;
            string refused = "нападающие нам не враги или защитники нам враги";
            if (CanHelpDefenders(party))
            {
                if (MenuDriver.TryInvoke(menu + "_help_defenders", out string helpWhy))
                {
                    AutopilotLog.Write("БОЙ: нажата помощь защитникам; ждём меню «В атаку»");
                    return;
                }
                refused = helpWhy;
            }

            // Всё — до нажатия: Finish обнуляет встречу.
            var battle = PlayerEncounter.EncounteredBattle;
            MobileParty[] involved =
            {
                PlayerEncounter.EncounteredMobileParty,
                battle.AttackerSide?.LeaderParty?.MobileParty,
                battle.DefenderSide?.LeaderParty?.MobileParty,
            };
            string sides = PartyName(battle.AttackerSide?.LeaderParty) + " против " + PartyName(battle.DefenderSide?.LeaderParty);
            string leave = menu == "join_encounter" ? "join_encounter_leave" : "leave";
            if (!MenuDriver.TryInvoke(leave, out string leaveWhy))
            {
                Disable("из чужого боя «" + sides + "» нельзя ни помочь, ни уйти: " + leaveWhy);
                return;
            }
            foreach (MobileParty other in involved)
            {
                if (other != null && other != party)
                {
                    _leftForeignBattles[other] = battle;
                }
            }
            AutopilotLog.Write("ВСТРЕЧА: чужой бой «" + sides + "» — не вступаемся (" + refused
                               + "); ушли штатной кнопкой «" + leave + "»");
        }

        /// <summary>Отряд всё ещё в том чужом бою, из которого автопилот ушёл. Погоня
        /// за ним дала бы круг «догнал — ушёл»: штатная модель снова назовёт его целью.</summary>
        private bool InLeftForeignBattle(MobileParty target)
        {
            if (target == null || !_leftForeignBattles.TryGetValue(target, out object battle))
            {
                return false;
            }
            if (ReferenceEquals(target.MapEvent, battle))
            {
                return true;
            }
            _leftForeignBattles.Remove(target);
            return false;
        }

        private static string PartyName(PartyBase party)
        {
            if (party?.MobileParty != null) return party.MobileParty.Name.ToString();
            if (party?.Settlement != null) return party.Settlement.Name.ToString();
            return "?";
        }

        private static bool CanHelpDefenders(MobileParty party)
        {
            string menu = MenuDriver.CurrentMenuId;
            // The engine getter dereferences PlayerEncounter.Current internally.
            // Enabling on the ordinary map has no encounter yet (F11 crash).
            if (PlayerEncounter.Current == null || party == null
                || (menu != "join_encounter" && menu != "encounter_interrupted"))
            {
                return false;
            }
            var battle = PlayerEncounter.EncounteredBattle;
            return (menu == "join_encounter" || menu == "encounter_interrupted")
                   && PlayerEncounter.Current != null && battle != null
                   && party != null && party.Army == null && party.SiegeEvent == null
                   && party.BesiegedSettlement == null && party.Ai != null && !party.Ai.IsDisabled
                   && !battle.IsNavalMapEvent
                   && battle.AttackerSide?.LeaderParty?.MapFaction != null
                   && battle.DefenderSide?.LeaderParty?.MapFaction != null
                   && party.MapFaction != null
                   && party.MapFaction.IsAtWarWith(battle.AttackerSide.LeaderParty.MapFaction)
                   && !party.MapFaction.IsAtWarWith(battle.DefenderSide.LeaderParty.MapFaction);
        }

        // Only the enemy party deliberately pursued by this Apply session.
        // Calling from the application tick also covers conversation missions.
        internal bool PollCombatConversation()
        {
            var party = MobileParty.MainParty;
            var target = _combatTarget ?? (party?.DefaultBehavior == AiBehavior.EngageParty ? party.TargetParty : null);
            if (PlayerEncounter.Current != null && PlayerEncounter.PlayerIsDefender)
                target = PlayerEncounter.EncounteredMobileParty;
            bool villageFieldBattle = IsSupportedFieldBattleEncounter(party)
                && party.MapEvent.MapEventSettlement?.IsVillage == true;
            if (_mode != Mode.Apply || PlayerEncounter.Current == null || party == null
                || target == null || PlayerEncounter.EncounteredMobileParty != target
                || !ControlsParty(party) || party.SiegeEvent != null || party.BesiegedSettlement != null
                || target.SiegeEvent != null || (PlayerEncounter.EncounterSettlement != null && !villageFieldBattle)
                || party.MapFaction == null || target.MapFaction == null
                || !party.MapFaction.IsAtWarWith(target.MapFaction)) return false;
            // The pursued bandits already fight someone else (EncounteredBattle is the
            // encountered party's MapEvent): join_encounter waits for a side, and no
            // conversation will come. Claiming it hid the help option and the watchdog (16.09 19:44).
            if (party.MapEvent == null && PlayerEncounter.EncounteredBattle != null) return false;
            var conversation = Campaign.Current?.ConversationManager;
            if (conversation?.IsConversationInProgress != true)
                return party.MapEvent == null && PlayerEncounter.Battle == null;
            if (conversation.ConversationParty != target || InformationManager.IsAnyInquiryActive()) return true;
            try
            {
                if (TrySelectBanditGatherDialog()) return true;
                var options = conversation.CurOptions;
                for (int i=0; options != null && i<options.Count; i++)
                {
                    string id = options[i].Id;
                    // Both the normal caravan conversation and escort-quest
                    // DialogFlow use these native lines. DialogFlow generates
                    // adg:* option IDs, so its text's localization key is needed.
                    string line = options[i].Text?.Value ?? "";
                    bool caravanFight = (target.IsCaravan && (id == "caravan_loot"
                        || id == "player_decided_to_fight"
                        || id == "player_decided_to_take_everything"
                        || id == "player_decided_to_force_fight"))
                        || line.Contains("WOBy5UfY") || line.Contains("EhxS7NQ4")
                        || line.Contains("QZ6IcCIm") || line.Contains("ha53qb7v");
                    bool allowed = target.IsBandit
                        ? id == "common_encounter_ultimatum" || id == "common_bandit_surrender_accepted"
                          || id == "bandit_start_defender_1" || id == "bandit_start_defender_3"
                        : IsTravelIntroduction(id) || id == "main_option_hostile_1_2"
                          || id == "player_verify_attack_on_enemy_lord" || id == "545"
                          || caravanFight;
                    if (allowed && options[i].IsClickable)
                    {
                        string selected = options[i].Id;
                        if (selected == "common_bandit_surrender_accepted") AuthorizePrisonerScreen();
                        conversation.DoOption(i);
                        AutopilotLog.Write(selected == "common_bandit_surrender_accepted"
                            ? "БОЙ: принята сдача бандитов — берём в плен штатной репликой"
                            : "БОЙ: штатная реплика преследуемой вражеской партии «" + selected + "»; ждём ответа");
                        return true;
                    }
                }
                if ((options == null || options.Count == 0) && conversation.IsConversationEnded())
                {
                    conversation.ContinueConversation();
                    AutopilotLog.Write("БОЙ: завершена последняя реплика; ждём штатное меню боя");
                }
            }
            catch (Exception ex)
            {
                Disable("разговор с преследуемой партией остановлен: " + ex.GetType().Name + ": " + ex.Message);
            }
            return true;
        }

        private bool PollUnavoidableSurrender(MobileParty party)
        {
            if (_mode != Mode.Apply || Hero.MainHero?.IsWounded != true || PlayerEncounter.Current == null
                || party.Party.NumberOfHealthyMembers > 0 || MenuDriver.CurrentMenuId != "encounter") return false;
            if (!MapIsActiveScreen() || InformationManager.IsAnyInquiryActive()) return true;
            foreach (string option in new[] { "attack", "str_order_attack", "leave_soldiers_behind", "leave", "go_back_to_settlement", "abandon_army", "capture_the_enemy" })
                if (MenuDriver.CanInvoke(option, out _)) return false;
            if (!MenuDriver.CanInvoke("surrender", out _)) return false;
            try
            {
                OperationClick("surrender");
                if (_mode == Mode.Apply) AutopilotLog.Write("ПЛЕН: герой ранен, боеспособных нет, бой и отход недоступны; штатная сдача, ждём освобождения без выкупа");
            }
            catch (Exception ex) { Disable("вынужденная сдача: " + ex.GetType().Name + ": " + ex.Message); }
            return true;
        }

        private bool PollRaidWarning()
        {
            if (_mode != Mode.Apply || MenuDriver.CurrentMenuId != "encounter_interrupted_raid_started") return false;
            if (!MapIsActiveScreen() || InformationManager.IsAnyInquiryActive()) return true;
            try
            {
                // Native EncounterGameMenuBehavior only switches to join_encounter here.
                // This notification does not select a side or initiate an attack.
                OperationClick("encounter_interrupted_raid_started_leave");
            }
            catch (Exception ex) { Disable("предупреждение о рейде: " + ex.GetType().Name + ": " + ex.Message); }
            return true;
        }

        private void PollCaptivity()
        {
            if (_mode != Mode.Apply || !MapIsActiveScreen() || InformationManager.IsAnyInquiryActive()) return;
            string menu = MenuDriver.CurrentMenuId;
            try
            {
                switch (menu)
                {
                    case "menu_captivity_end_propose_ransom_wilderness":
                    case "menu_captivity_end_propose_ransom_in_prison":
                        OperationClick("captivity_end_ransom_deny"); return;
                    case "prisoner_wait":
                    case "settlement_wait": ResumeOperationWait(); return;
                    case "menu_captivity_end_no_more_enemies":
                    case "menu_captivity_end_by_ally_party_saved":
                    case "menu_captivity_end_by_party_removed":
                    case "menu_captivity_end_wilderness_escape":
                    case "menu_escape_captivity_during_battle":
                    case "menu_captivity_end_exchanged_with_prisoner":
                    case "menu_captivity_end_prison_escape":
                    case "menu_captivity_transfer_to_town":
                    case "menu_captivity_castle_remain":
                        OperationClick("mno_continue"); return;
                    case "taken_prisoner":
                    case "defeated_and_taken_prisoner":
                        OperationClick("taken_prisoner_continue"); return;
                }
            }
            catch (Exception ex) { Disable("плен: " + ex.GetType().Name + ": " + ex.Message); }
        }

        private static bool IsTravelIntroduction(string id)
        {
            return id == "lord_meet_player_response1" || id == "lord_meet_player_response2"
                || id == "lord_meet_player_response3" || id == "lord_meet_player_as_liege_response"
                || id == "ally_thanks_meet";
        }

        // A map encounter can exist for several ticks before its conversation starts.
        // Own this transition, but never Finish an encounter or choose diplomacy at random.
        private bool PollPeacefulTravelConversation()
        {
            var party = MobileParty.MainParty;
            var target = PlayerEncounter.Current == null ? null : PlayerEncounter.EncounteredMobileParty;
            if (party == null || target == null || Hero.MainHero?.IsPrisoner == true
                || party.MapEvent != null || PlayerEncounter.Battle != null
                || !ControlsParty(party) || party.SiegeEvent != null || party.BesiegedSettlement != null
                || PlayerEncounter.EncounterSettlement != null || target.SiegeEvent != null
                || party.MapFaction == null || target.MapFaction == null
                || party.MapFaction.IsAtWarWith(target.MapFaction)) return false;
            if (PlayerEncounter.EncounteredBattle != null) return false;
            var c = Campaign.Current?.ConversationManager;
            if (c?.IsConversationInProgress != true) return true;
            if (c.ConversationParty != target || InformationManager.IsAnyInquiryActive()) return true;
            try
            {
                var options = c.CurOptions;
                for (int i = 0; options != null && i < options.Count; i++)
                {
                    string id = options[i].Id;
                    if (!options[i].IsClickable || !(IsTravelIntroduction(id)
                        || id == "player_is_leaving_neutral_or_friendly" || id == "caravan_talk_leave"
                        || id == "player_caravan_nevermind" || id == "player_caravan_talk_leave"
                        || id == "caravan_companion_talk_leave" || id == "village_farmer_leave")) continue;
                    c.DoOption(i);
                    AutopilotLog.Write("ВСТРЕЧА: мирная партия, штатная реплика «" + id + "»");
                    return true;
                }
                if ((options == null || options.Count == 0) && c.IsConversationEnded()) c.ContinueConversation();
            }
            catch (Exception ex) { Disable("мирный разговор остановлен: " + ex.GetType().Name + ": " + ex.Message); }
            return true;
        }

        internal bool PollDialogs()
        {
            if (_mode != Mode.Apply) return false;
            if (PollLiberatedHeroConversation()) return true;
            if (PollScriptedEncounterConversation()) return true;
            try { if (PollHideoutConversation()) return true; }
            catch (Exception ex) { Disable("диалог убежища остановлен: " + ex); return true; }
            if (PollPeacefulTravelConversation()) return true;
            if (PollCombatConversation()) return true; // Fixed combat rules always win.
            var conversation = Campaign.Current?.ConversationManager;
            if (conversation?.IsConversationInProgress != true)
            {
                _randomDialogSteps = 0;
                _nextRandomDialogAt = DateTime.MinValue;
                return false;
            }
            if (!RandomDialogsEnabled) return false;
            if (InformationManager.IsAnyInquiryActive() || Clock() < _nextRandomDialogAt) return true;
            if (_randomDialogSteps >= 16)
            {
                RandomDialogsEnabled = false;
                AutopilotLog.Write("ДИАЛОГ: случайный режим остановлен после 16 шагов одного разговора; требуется выбор игрока");
                return true;
            }
            try
            {
                var options = conversation.CurOptions;
                var available = new List<int>();
                for (int i=0; options != null && i<options.Count; i++)
                    if (options[i].IsClickable) available.Add(i);
                if (available.Count > 0)
                {
                    int index = available[_dialogRandom.Next(available.Count)];
                    string id = options[index].Id;
                    if (id == "common_bandit_surrender_accepted") AuthorizePrisonerScreen();
                    conversation.DoOption(index);
                    _randomDialogSteps++;
                    _nextRandomDialogAt = Clock().AddSeconds(2);
                    AutopilotLog.Write("ДИАЛОГ: случайно выбрана доступная реплика «" + id + "»");
                }
                else if (options == null || options.Count == 0)
                {
                    conversation.ContinueConversation();
                    _randomDialogSteps++;
                    _nextRandomDialogAt = Clock().AddSeconds(2);
                }
            }
            catch (Exception ex)
            {
                RandomDialogsEnabled = false;
                Disable("случайный диалог остановлен: " + ex.GetType().Name + ": " + ex.Message);
            }
            return true;
        }

        private bool PollScriptedEncounterConversation()
        {
            var campaign = Campaign.Current;
            var conversation = campaign?.ConversationManager;
            if (conversation?.IsConversationInProgress != true || InformationManager.IsAnyInquiryActive()) return false;
            var context = campaign.CurrentConversationContext;
            if (context != ConversationContext.CapturedLord
                && context != ConversationContext.FreeOrCapturePrisonerHero
                && context != ConversationContext.PartyEncounter) return false;
            var options = conversation.CurOptions;
            if (options == null || options.Count == 0)
            {
                if (Clock() < _nextScriptedDialogAt) return true;
                try
                {
                    _nextScriptedDialogAt = Clock().AddSeconds(2);
                    conversation.ContinueConversation();
                    AutopilotLog.Write("ДИАЛОГ: продолжена штатная реплика встречи без вариантов");
                }
                catch (Exception ex) { Disable("продолжение встречи остановлено: " + ex.GetType().Name + ": " + ex.Message); }
                return true;
            }
            // A defending player can meet a hostile settlement patrol without an
            // EngageParty order. Its one fight reply must not fall through to the
            // peaceful-travel handler, which deliberately ignores hostile choices.
            if (context == ConversationContext.PartyEncounter && PlayerEncounter.Current != null
                && PlayerEncounter.PlayerIsDefender
                && conversation.ConversationParty == PlayerEncounter.EncounteredMobileParty)
            {
                for (int i = 0; i < options.Count; i++)
                {
                    var option = options[i];
                    string reply = option.Text?.ToString() ?? "";
                    bool fightReply = option.Id == "545"
                        || option.Text?.Value?.Contains("5KGuQb5C") == true
                        || reply.IndexOf("кто кого уб", StringComparison.OrdinalIgnoreCase) >= 0
                        || reply.IndexOf("who slays whom", StringComparison.OrdinalIgnoreCase) >= 0;
                    if (!option.IsClickable || !fightReply) continue;
                    if (Clock() < _nextScriptedDialogAt) return true;
                    try
                    {
                        _nextScriptedDialogAt = Clock().AddSeconds(2);
                        conversation.DoOption(i);
                        AutopilotLog.Write("БОЙ: принят штатный ответ атакующему патрулю «" + option.Id + "»");
                    }
                    catch (Exception ex) { Disable("ответ атакующему патрулю остановлен: " + ex.GetType().Name + ": " + ex.Message); }
                    return true;
                }
            }
            if (context != ConversationContext.CapturedLord) return false;
            for (int i = 0; i < options.Count; i++)
            {
                if (options[i].Id != "talk_lord_defeat_to_lord_capture" || !options[i].IsClickable) continue;
                if (Clock() < _nextScriptedDialogAt) return true;
                try
                {
                    _nextScriptedDialogAt = Clock().AddSeconds(2);
                    conversation.DoOption(i);
                    AutopilotLog.Write("ДИАЛОГ: побеждённый лорд взят в плен штатной репликой");
                }
                catch (Exception ex) { Disable("пленение лорда остановлено: " + ex.GetType().Name + ": " + ex.Message); }
                return true;
            }
            return true; // Never select execution or release as a fallback.
        }

        // After a battle, the encounter can still point at the defeated party while
        // the speaker is a rescued lord. Combat/hideout handlers otherwise claim the
        // conversation and never let the two liberation replies through.
        private bool PollLiberatedHeroConversation()
        {
            var conversation = Campaign.Current?.ConversationManager;
            if (conversation?.IsConversationInProgress != true || InformationManager.IsAnyInquiryActive()) return false;
            var options = conversation.CurOptions;
            int selected = -1;
            for (int i = 0; options != null && i < options.Count; i++)
            {
                if (!options[i].IsClickable) continue;
                // Native ally gratitude opens while the encounter still points
                // at defeated enemies. Introduction must precede combat routing.
                if (options[i].Id == "ally_thanks_meet") { selected = i; break; }
                if (options[i].Id == "liberate_hero_3") { selected = i; break; }
                if (options[i].Id == "liberate_hero_7") selected = i;
            }
            if (selected < 0) return false;
            if (Clock() < _nextLiberationDialogAt) return true;
            try
            {
                string id = options[selected].Id;
                _nextLiberationDialogAt = Clock().AddSeconds(2);
                conversation.DoOption(selected);
                AutopilotLog.Write("ДИАЛОГ: послебоевая встреча, штатная реплика «" + id + "»");
            }
            catch (Exception ex) { Disable("освобождение героя остановлено: " + ex.GetType().Name + ": " + ex.Message); }
            return true;
        }

        /// <summary>Первый поддержанный боевой сценарий: уже созданный обычный
        /// сухопутный MapEvent и его меню encounter. Движок может привязать
        /// полевой бой к ближайшей деревне; это не превращает его в рейд.
        /// Осады, налёты, убежища и морские бои проверяются отдельно.</summary>
        internal static bool IsSupportedFieldBattleEncounter(MobileParty party)
        {
            var battle = party?.MapEvent;
            return battle != null
                   && PlayerEncounter.Current != null
                   && PlayerEncounter.Battle != null
                   && party.SiegeEvent == null
                   && party.BesiegedSettlement == null
                   && (battle.MapEventSettlement == null
                       || (battle.IsFieldBattle && battle.MapEventSettlement.IsVillage))
                   && !battle.IsNavalMapEvent;
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
                   && ControlsParty(party)
                   && PlayerEncounter.Current == null;
        }

        /// <summary>Выход тем же путём, что кнопка «Уйти», и только с подтверждением.
        /// true — выход наблюдается (партия вне поселения и встречи).</summary>
        private bool LeavePeacefulSettlement(MobileParty party, Settlement settlement)
        {
            // A menu callback can enqueue an incident after PollState checked it.
            // Recheck at the mutation boundary: native incident conditions still
            // need CurrentSettlement on the next Campaign.Tick.
            if (HoldExitForQueuedIncident(party, settlement)) return false;
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
                _waitingSinceHours = -1;
                _longStayWarned = false;
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
        /// скорости, на которой автопилот ехал. Поверх карты открыт экран, окно,
        /// меню или разговор — не трогаем: их закрывает не пауза, а режим,
        /// переписанный под окном, сработал бы потом без чьего-либо решения.</summary>
        private void KeepTimeRunning(MobileParty party)
        {
            Campaign campaign = Campaign.Current;
            if (campaign.CurrentMenuContext != null
                || (campaign.ConversationManager != null && campaign.ConversationManager.IsConversationInProgress)
                || !MapIsActiveScreen())
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

        /// <summary>Идёт сцена (бой, убежище): время карты стоит штатно, а PollState
        /// не вызывается. Без отметки вся длина боя попадала в простой сразу после
        /// выхода — «96 с» в 17:50:11 16.09 ровно по длине боя, и зависание было
        /// не отличить от долгого боя. Отсчёт простоя идёт от последней отметки.</summary>
        internal void WatchMission()
        {
            if (_mode != Mode.Apply)
            {
                return;
            }
            DateTime now = Clock();
            if (_stallReported)
            {
                double stalled = (now - _lastProgressAt).TotalSeconds;
                _longestStallSeconds = Math.Max(_longestStallSeconds, stalled);
                _stallReported = false;
                AutopilotLog.Write("простой закончился входом в сцену через "
                                   + stalled.ToString("F0", CultureInfo.InvariantCulture) + " с");
            }
            _lastProgressAt = now;
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
                string window = WindowOverMap();
                if (window != null)
                {
                    sb.Append("; открыто: ").Append(window);
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

        partial void DailyPoliticsHook();

        private void OnHourlyTick()
        {
            if (_mode == Mode.Off || Campaign.Current == null)
            {
                return;
            }

            MobileParty party = MobileParty.MainParty;
            MaintainArmy(party);
            if (_mode == Mode.Off) return;
            if (party == null || !party.IsActive || UnsupportedState(party) != null)
            {
                return; // выключит ближайший опрос по кадрам — с причиной
            }
            WriteWeeklyProgress(party);
            // Политика раз в игровой день (AutopilotPolitics.cs). Частичный метод:
            // стенд AuditRegression его не собирает — там это пустышка.
            DailyPoliticsHook();
            WatchMovement(party);

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
                NoteWaiting();
            }

            // Отход от армии «в разы» сильнее важнее всего остального (23.09).
            if (waitingIn == null && _fleeFrom != null) return;
            if (waitingIn != null && HoldShelter(party, waitingIn)) return;
            if (TryEmergencyDefense(party, waitingIn)) return;
            if (waitingIn != null && HoldPostBattleRest(party, waitingIn, true)) return;
            if (_gatheringArmy != null && _gatheringArmy == party.Army) return;

            if (_mode == Mode.Apply && ControlsParty(party) && !party.IsCurrentlyAtSea
                && MapIsActiveScreen() && !InformationManager.IsAnyInquiryActive())
            {
                try
                {
                    TroopUpgrades.Run(party);
                    // Охота раньше набора и разгрузки: бой рядом по силам важнее
                    // похода за добровольцами (владелец 23.09: «если есть
                    // возможность рядом дать — дать»). Оборона и отдых — выше.
                    if (waitingIn == null && TryHunt(party)) return;
                    if (NeedsRecruitment(party) && !SiegeBeforeRecruitment(party))
                    {
                        Settlement recruitAt = FindRecruitmentTarget(party);
                        if (recruitAt != null)
                        {
                            var recruitDecision = new AIBehaviorData(recruitAt, AiBehavior.GoToSettlement,
                                MobileParty.NavigationType.Default, false, false, false);
                            if (!IsSameDecision(recruitDecision, party))
                                AutopilotLog.Write("ПОПОЛНЕНИЕ: " + party.Party.NumberOfAllMembers + "/"
                                    + party.Party.PartySizeLimit + " (цель 90%); доступные добровольцы в «"
                                    + recruitAt.Name + "»; едем набирать");
                            if (waitingIn != null)
                            {
                                if (waitingIn == recruitAt) TryServe(party, recruitAt, MenuDriver.CurrentMenuId, "пополнение");
                                else { _pendingDecision = recruitDecision; _pendingScore = 1f; _hasPendingDecision = true; }
                            }
                            else ApplyDecision(party, recruitDecision, 1f);
                            return;
                        }
                    }
                    Settlement market = EquipmentAndTrade.FindUnloadingTown(party,
                        s => _services.IsDue(s) && !CannotStay(s));
                    if (market != null)
                    {
                        var saleDecision = new AIBehaviorData(market, AiBehavior.GoToSettlement,
                            MobileParty.NavigationType.Default, false, false, false);
                        if (!IsSameDecision(saleDecision, party))
                            AutopilotLog.Write("РАЗГРУЗКА: вес " + party.TotalWeightCarried.ToString("F1", CultureInfo.InvariantCulture)
                                + "/" + party.InventoryCapacity + "; идём продавать в «" + market.Name + "»");
                        if (waitingIn != null)
                        {
                            if (waitingIn == market) TryServe(party, market, MenuDriver.CurrentMenuId, "разгрузка");
                            else { _pendingDecision = saleDecision; _pendingScore = 1f; _hasPendingDecision = true; }
                        }
                        else ApplyDecision(party, saleDecision, 1f);
                        return;
                    }
                }
                catch (Exception ex) { Disable("маршрут продажи: " + ex.GetType().Name + ": " + ex.Message); return; }
            }

            // MobilePartyAi.GetBehaviors вызывает этот штатный расчёт для NPC,
            // но DefaultMobilePartyAIModel.ShouldPartyCheckInitiativeBehavior
            // намеренно возвращает false для MainParty. Без него партия игрока
            // видит дальние маршруты, но не замечает даже слабых бандитов рядом.
            // Повторяем ровно NPC-порог (> 1) и его готовый выбор цели; свою
            // оценку силы, войны, скорости или дистанции здесь не изобретаем.
            _hoursSinceThink++;
            bool idle = waitingIn == null && party.DefaultBehavior == AiBehavior.Hold;
            if (_ticksThisSession > 0 && !idle && _hoursSinceThink < ThinkPeriodHours)
            {
                if (!_preparingCampaign && waitingIn == null && !HeadingToSiegeTarget(party)
                    && party.DefaultBehavior != AiBehavior.RaidSettlement) TryApplyNearbyAttack(party);
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

            var proposals = think.AIBehaviorScores.ToList();
            if (TryFindSiegeTarget(party, out AIBehaviorData siegeTarget, out float siegeScore))
            {
                proposals.Add((siegeTarget, siegeScore));
                AutopilotLog.Write("ПОХОД: найдена крепость самостоятельно: " + Describe(siegeTarget)
                    + "; оценка " + siegeScore.ToString("F3", CultureInfo.InvariantCulture)
                    + (siegeTarget.WillGatherArmy ? "; сначала собираем армию" : "; сил отряда достаточно"));
            }
            AIBehaviorData best = AIBehaviorData.Invalid;
            float bestScore = -1f;
            var lines = new List<string>();
            foreach (var pair in proposals)
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
                if (HeadingToSiegeTarget(party))
                    AutopilotLog.Write("ПОХОД: цель «" + party.TargetSettlement.Name + "» больше не предложена: "
                        + (SiegeTargetRejection(party, party.TargetSettlement) ?? "нет оценок от движка и нового кандидата"));
                if (_mode == Mode.Apply && waitingIn == null && !HeadingToSiegeTarget(party)
                    && TryApplyNearbyAttack(party)) return;
                if (waitingIn == null && TryChooseHideout(party)) return;
                AutopilotLog.Write("  оценок НЕТ — штатный AI ничего не предложил для этой партии");
                return;
            }
            foreach (string line in Top(lines, 8))
            {
                AutopilotLog.Write("    " + line);
            }
            AutopilotLog.Write("  лучшее: " + Describe(best) + " = "
                               + bestScore.ToString("F3", CultureInfo.InvariantCulture));
            try { LogStrategicAudit(party, proposals); }
            catch (Exception ex) { AutopilotLog.Write("СТРАТЕГИЯ: оценку записать не удалось: " + ex.GetType().Name + ": " + ex.Message); }

            if (_mode == Mode.Observe)
            {
                return;
            }

            // Use native proposals, with the owner's conquest/preparation priority.
            AIBehaviorData chosen = AIBehaviorData.Invalid;
            float chosenScore = -1f;
            // Все пропуски, а не первый: иначе рейд, лучший 91 раз за прогон 16.09,
            // не попал в журнал ни разу — его заслоняла осада выше в списке.
            var skipped = new List<string>();
            var applicable = new List<Tuple<AIBehaviorData, float, float>>();
            foreach (var pair in proposals)
            {
                string reason = WhyNotApplicable(pair.Item1);
                if (reason == null)
                {
                    applicable.Add(Tuple.Create(pair.Item1, pair.Item2, AdjustedDecisionScore(pair.Item1, pair.Item2)));
                }
                else
                {
                    skipped.Add(Describe(pair.Item1) + " = " + pair.Item2.ToString("F3", CultureInfo.InvariantCulture)
                                + " — " + reason);
                }
            }
            string preparation = PreparationNeeded(party);
            bool preparing = preparation != null && proposals.Any(p =>
                p.Item1.AiBehavior == AiBehavior.BesiegeSettlement || p.Item1.AiBehavior == AiBehavior.RaidSettlement);
            _preparingCampaign = preparing;
            if (_travelTown != null && waitingIn == _travelTown)
            {
                _avoidAfterTravel = _travelOrigin;
                _avoidAfterTravelUntil = CampaignTime.Now.ToHours + ReturnToPatrolHours;
                AutopilotLog.Write("ПОЕЗДКА: прибыли в «" + _travelTown.Name
                                   + "»; прежнюю точку патруля временно не выбираем");
                _travelTown = null;
                _travelOrigin = null;
            }
            var priority = preparing
                ? applicable.Where(p => p.Item1.AiBehavior == AiBehavior.GoToSettlement
                    && p.Item1.Party is Settlement s && s.MapFaction != null && party.MapFaction != null
                    && !party.MapFaction.IsAtWarWith(s.MapFaction) && !s.IsUnderSiege && !s.IsUnderRaid && !s.IsRaided).ToList()
                : applicable.Where(p => p.Item1.AiBehavior == AiBehavior.BesiegeSettlement && p.Item2 > 0).ToList();
            bool hasPriority = priority.Count > 0;
            if (hasPriority) AutopilotLog.Write(preparing ? "ПОХОД: снабжение/восстановление — " + preparation : "ПОХОД: готовы, приоритет захвату крепости");
            if (applicable.Count > 0)
            {
                var ordinary = applicable;
                if (_avoidAfterTravel != null && CampaignTime.Now.ToHours < _avoidAfterTravelUntil)
                {
                    var elsewhere = applicable.Where(p => p.Item1.Party != _avoidAfterTravel
                        || (p.Item1.AiBehavior != AiBehavior.PatrolAroundPoint
                            && p.Item1.AiBehavior != AiBehavior.GoToSettlement)).ToList();
                    if (elsewhere.Count > 0) ordinary = elsewhere;
                }
                // A high native settlement/patrol score can pull the party back to
                // the same town after every trip. Only ordinary peaceful movement is
                // diversified; preparation, siege and defence retain their priority.
                if (!hasPriority && !preparing)
                {
                    var fresh = ordinary.Where(p => !(p.Item1.Party is Settlement s && s.IsTown
                        && (p.Item1.AiBehavior == AiBehavior.GoToSettlement
                            || p.Item1.AiBehavior == AiBehavior.PatrolAroundPoint)
                        && _recentTownVisits.TryGetValue(s, out double visit)
                        && CampaignTime.Now.ToHours - visit < RecentTownHours)).ToList();
                    if (fresh.Count > 0 && fresh.Count < ordinary.Count)
                    {
                        AutopilotLog.Write("ПОЕЗДКА: недавние города отложены; доступны другие обычные цели");
                        ordinary = fresh;
                    }
                }
                var selected = (hasPriority ? priority : ordinary).OrderByDescending(p => p.Item3).First();
                chosen = selected.Item1;
                chosenScore = selected.Item3;

                if (selected.Item2 != selected.Item3)
                {
                    AutopilotLog.Write("  " + Describe(selected.Item1) + ": штатная оценка "
                                       + selected.Item2.ToString("F3", CultureInfo.InvariantCulture)
                                       + ", после поправки " + selected.Item3.ToString("F3", CultureInfo.InvariantCulture));
                }

                // Близкие оценки меняются каждый пересчёт и разворачивали
                // партию на полпути. Пока текущий приказ действителен, новая
                // обычная цель должна выиграть с небольшим явным запасом.
                if (!hasPriority && waitingIn == null && !IsSameDecision(chosen, party))
                {
                    var current = ordinary.FirstOrDefault(p => IsSameDecision(p.Item1, party));
                    if (current != null && chosenScore < current.Item3 + DecisionChangeMargin)
                    {
                        AutopilotLog.Write("  текущая цель сохранена: новая лучше только на "
                                           + (chosenScore - current.Item3).ToString("F3", CultureInfo.InvariantCulture)
                                           + ", порог смены " + DecisionChangeMargin.ToString("F2", CultureInfo.InvariantCulture));
                        chosen = current.Item1;
                        chosenScore = current.Item3;
                    }
                }

                // A very high native patrol score can beat every other town forever.
                // Use only safe towns already proposed by the engine, and keep the trip
                // until arrival instead of turning back at the next six-hour rethink.
                if (!hasPriority && !preparing && waitingIn == null
                    && (chosen.AiBehavior == AiBehavior.PatrolAroundPoint
                        || chosen.AiBehavior == AiBehavior.GoToSettlement))
                {
                    var towns = applicable.Where(p => p.Item1.AiBehavior == AiBehavior.GoToSettlement
                        && p.Item1.Party is Settlement s && s.IsTown && s != _continuousPatrolSettlement
                        && s != _avoidAfterTravel && p.Item2 > 0
                        && !s.IsUnderSiege && !s.IsUnderRaid && !s.IsRaided
                        && s.MapFaction != null && party.MapFaction != null
                        && !party.MapFaction.IsAtWarWith(s.MapFaction)).ToList();
                    var trip = _travelTown != null
                        ? towns.FirstOrDefault(p => p.Item1.Party == _travelTown)
                        : null;
                    if (trip == null && _travelTown != null) { _travelTown = null; _travelOrigin = null; }
                    if (trip == null && chosen.AiBehavior == AiBehavior.PatrolAroundPoint
                        && party.DefaultBehavior == AiBehavior.PatrolAroundPoint
                        && _continuousPatrolSettlement != null
                        && _continuousPatrolSinceHours >= 0
                        && CampaignTime.Now.ToHours - _continuousPatrolSinceHours >= TravelAfterPatrolHours)
                    {
                        var freshTowns = towns.Where(p => !(_recentTownVisits.TryGetValue((Settlement)p.Item1.Party, out double visit)
                            && CampaignTime.Now.ToHours - visit < RecentTownHours)).ToList();
                        trip = freshTowns.Count > 0
                            ? freshTowns.OrderByDescending(p => p.Item2).FirstOrDefault()
                            : towns.OrderBy(p => _recentTownVisits.TryGetValue((Settlement)p.Item1.Party, out double visit)
                                    ? visit : double.MinValue)
                                .ThenByDescending(p => p.Item2).FirstOrDefault();
                        if (trip != null)
                        {
                            _travelOrigin = _continuousPatrolSettlement;
                            _travelTown = (Settlement)trip.Item1.Party;
                            _avoidAfterTravel = _travelOrigin;
                            _avoidAfterTravelUntil = CampaignTime.Now.ToHours + ReturnToPatrolHours;
                            AutopilotLog.Write("ПОЕЗДКА: после долгого патруля «" + _travelOrigin.Name
                                               + "» едем в другой город «" + _travelTown.Name + "»");
                        }
                    }
                    if (trip != null) { chosen = trip.Item1; chosenScore = trip.Item3; }
                }
            }

            if (!preparing && waitingIn == null && chosen.AiBehavior != AiBehavior.BesiegeSettlement
                && chosen.AiBehavior != AiBehavior.RaidSettlement && TryApplyNearbyAttack(party)) return;

            if (waitingIn == null && (chosen.AiBehavior == AiBehavior.None || chosen.AiBehavior == AiBehavior.PatrolAroundPoint)
                && TryChooseHideout(party)) return;

            if (chosen.AiBehavior == AiBehavior.None)
            {
                if (HeadingToSiegeTarget(party))
                    AutopilotLog.Write("ПОХОД: цель «" + party.TargetSettlement.Name + "» больше не предложена: "
                        + (SiegeTargetRejection(party, party.TargetSettlement) ?? "нет выполнимых решений"));
                AutopilotLog.Write("  выполнимых решений нет (" + string.Join("; ", skipped) + ") — партия продолжает текущее");
                return;
            }
            if (HeadingToSiegeTarget(party) && !IsSameDecision(chosen, party))
            {
                string rejection = SiegeTargetRejection(party, party.TargetSettlement);
                AutopilotLog.Write("ПОХОД: прекращаем цель «" + party.TargetSettlement.Name + "»: "
                    + (rejection ?? "другая цель получила приоритет") + "; далее " + Describe(chosen));
            }
            if (skipped.Count > 0)
            {
                AutopilotLog.Write("  пропущено: " + string.Join("; ", skipped) + "; берём: " + Describe(chosen) + " = "
                                   + chosenScore.ToString("F3", CultureInfo.InvariantCulture));
            }
            if (DecisionKey(chosen) != DecisionKey(best) || Math.Abs(chosenScore - bestScore) > 0.0001f)
            {
                AutopilotLog.Write("  выбрано автопилотом после ограничений: " + Describe(chosen) + " = "
                                   + chosenScore.ToString("F3", CultureInfo.InvariantCulture));
            }

            if (waitingIn != null)
            {
                if (chosen.AiBehavior == AiBehavior.GoToSettlement && chosen.Party == waitingIn)
                {
                    AutopilotLog.Write("  остаёмся в «" + waitingIn.Name + "»: лучшая цель — само это поселение, как у NPC");
                    double stayed = CampaignTime.Now.ToHours - _waitingSinceHours;
                    if (!_longStayWarned && stayed >= LongStayHours)
                    {
                        _longStayWarned = true;
                        AutopilotLog.Write("ДОЛГОЕ ПРЕБЫВАНИЕ: " + (stayed / 24).ToString("F1", CultureInfo.InvariantCulture)
                                           + " сут. под автопилотом в «" + waitingIn.Name + "», штатный AI не уводит. Вероятная причина — "
                                           + "движок не кормит, не нанимает и не продаёт пленных за партию игрока, и "
                                           + "оценка «побыть здесь» не падает (review/unattended-play-engine-notes.md)");
                    }
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

        /// <summary>Мера прогресса для долгого прогона: в первый час сеанса и раз в
        /// игровую неделю — феоды клана, бойцы, золото, с кем война. Без неё «стало
        /// лучше» нечем доказать. Сбой сводки — строка в журнале, не выключение.</summary>
        private void WriteWeeklyProgress(MobileParty party)
        {
            int week = (int)(CampaignTime.Now.ToHours / (24 * 7));
            if (week == _lastProgressWeek)
            {
                return;
            }
            _lastProgressWeek = week;
            try
            {
                Clan clan = Clan.PlayerClan;
                int castles = clan.Fiefs.Count(f => f.Settlement.IsCastle);
                int totalFiefs = Settlement.All.Count(s => s.IsTown || s.IsCastle);
                int heldFiefs = clan.Kingdom != null ? clan.Kingdom.Fiefs.Count : clan.Fiefs.Count;
                string foodDays = party.FoodChange < 0
                    ? (party.TotalFoodAtInventory / -party.FoodChange).ToString("F1", CultureInfo.InvariantCulture) : "без расхода";
                string wars = string.Join(", ", FactionHelper.GetEnemyKingdoms(clan.MapFaction).Select(k => k.Name.ToString()));
                AutopilotLog.Write("НЕДЕЛЯ " + week + ": феодов " + clan.Fiefs.Count
                                   + " (замков " + castles + ", городов " + (clan.Fiefs.Count - castles) + ")"
                                   + ", деревень " + clan.Villages.Count
                                   + "; бойцов " + party.MemberRoster.TotalManCount
                                   + " (раненых " + party.MemberRoster.TotalWounded + ")"
                                   + "; золото " + Hero.MainHero.Gold
                                   + "; войны: " + (wars.Length > 0 ? wars : "нет")
                                   + "; карта " + heldFiefs + "/" + totalFiefs
                                   + "; еда " + foodDays + " дней; жалование " + party.TotalWage + " в день"
                                   + (party.Army == null ? "; без армии" : "; сплочённость " + party.Army.Cohesion.ToString("F0", CultureInfo.InvariantCulture)));
                if (totalFiefs > 0 && heldFiefs >= totalFiefs)
                    AutopilotLog.Write("ЦЕЛЬ: все города и замки карты принадлежат нашему королевству/клану");
            }
            catch (Exception ex)
            {
                AutopilotLog.Write("НЕДЕЛЯ " + week + ": сводку собрать не удалось: " + ex.GetType().Name + ": " + ex.Message);
            }
        }

        /// <summary>Наблюдение для будущего стратега. Не меняет оценки и приказы.
        /// Видимые подвижные враги в радиусе 35 — лишь локальная разведка;
        /// гарнизон и ополчение записываются отдельно, без ложного «шанса победы».</summary>
        private void LogStrategicAudit(MobileParty party, IEnumerable<(AIBehaviorData, float)> proposals)
        {
            var candidates = proposals
                .Where(p => (p.Item1.AiBehavior == AiBehavior.BesiegeSettlement
                          || p.Item1.AiBehavior == AiBehavior.DefendSettlement)
                          && p.Item1.Party is Settlement && p.Item2 > 0)
                .OrderByDescending(p => p.Item2).Take(3).ToList();
            if (candidates.Count == 0) return;
            float ownStrength = party.Party.EstimatedStrength;
            if (party.Army?.LeaderParty == party)
                foreach (var attached in party.AttachedParties)
                    if (attached != null && attached != party && attached.Army == party.Army)
                        ownStrength += attached.Party.EstimatedStrength;
            string preparation = PreparationNeeded(party);
            foreach (var candidate in candidates)
            {
                var data = candidate.Item1;
                var place = (Settlement)data.Party;
                float distance = (float)Math.Sqrt(Math.Max(0, party.Position.DistanceSquared(place.Position)));
                float garrison = place.Town?.GarrisonParty?.Party.EstimatedStrength ?? 0f;
                float nearbyEnemy = 0f;
                int nearbyCount = 0;
                foreach (var enemy in MobileParty.All)
                {
                    if (enemy == null || enemy == party || enemy == place.Town?.GarrisonParty
                        || !enemy.IsActive || !enemy.IsVisible || enemy.IsMilitia
                        || enemy.CurrentSettlement != null || enemy.MapFaction == null || party.MapFaction == null
                        || !party.MapFaction.IsAtWarWith(enemy.MapFaction)
                        || enemy.Position.DistanceSquared(place.Position) > 35f * 35f) continue;
                    nearbyEnemy += enemy.Party.EstimatedStrength;
                    nearbyCount++;
                }
                AutopilotLog.Write("СТРАТЕГИЯ [только наблюдение]: " + Describe(data)
                    + "; оценка цели " + candidate.Item2.ToString("F2", CultureInfo.InvariantCulture)
                    + "; расстояние по прямой " + distance.ToString("F1", CultureInfo.InvariantCulture)
                    + "; своя сила " + ownStrength.ToString("F0", CultureInfo.InvariantCulture)
                    + "; гарнизон " + garrison.ToString("F0", CultureInfo.InvariantCulture)
                    + "; ополчение " + place.Militia.ToString("F0", CultureInfo.InvariantCulture) + " бойцов"
                    + "; видимых вражеских партий рядом " + nearbyCount + " (сила "
                    + nearbyEnemy.ToString("F0", CultureInfo.InvariantCulture) + ")"
                    + "; снабжение " + (preparation ?? "достаточно")
                    + "; применимость " + (WhyNotApplicable(data) ?? "да")
                    + "; армия " + (data.WillGatherArmy ? "планируется" : party.Army == null ? "нет" : "есть"));
            }
        }

        private float AdjustedDecisionScore(AIBehaviorData data, float rawScore)
        {
            if (data.AiBehavior != AiBehavior.PatrolAroundPoint || !(data.Party is Settlement settlement))
            {
                return rawScore;
            }

            double now = CampaignTime.Now.ToHours;
            float penalty = 0f;
            if (settlement == _continuousPatrolSettlement && _continuousPatrolSinceHours >= 0)
            {
                double hours = Math.Max(0, now - _continuousPatrolSinceHours);
                penalty += Math.Min(MaximumPatrolPenalty,
                                    (float)Math.Max(0, hours - PatrolGraceHours) * PatrolPenaltyPerHour);
                if (penalty > 0f)
                {
                    AutopilotLog.Write("  штраф за " + hours.ToString("F0", CultureInfo.InvariantCulture)
                                       + " ч. патруля «" + settlement.Name + "»: -"
                                       + penalty.ToString("F3", CultureInfo.InvariantCulture));
                }
            }
            if (_patrolCooldownUntil.TryGetValue(settlement, out double until))
            {
                if (until > now)
                {
                    penalty += PatrolCooldownPenalty;
                    AutopilotLog.Write("  охлаждение патруля «" + settlement.Name + "»: ещё "
                                       + (until - now).ToString("F0", CultureInfo.InvariantCulture)
                                       + " ч., -" + PatrolCooldownPenalty.ToString("F3", CultureInfo.InvariantCulture));
                }
                else
                {
                    _patrolCooldownUntil.Remove(settlement);
                }
            }
            return rawScore - penalty;
        }

        /// <summary>Приказ принят, а партия стоит. Проверяется по НАБЛЮДАЕМОМУ
        /// эффекту — сдвинулась ли позиция за игровой час, — а не по тому, что
        /// движок принял вызов.
        ///
        /// Почему это вообще бывает. Движение задаёт не приказ, а сеттер
        /// MobileParty.DefaultBehavior, и только когда значение СМЕНИЛОСЬ
        /// (100715-100725 → RecalculateShortTermBehavior). При этом
        /// SetMoveBesiegeSettlement (104002-104012) сначала сбрасывает параметры
        /// движения и, в отличие от SetMoveGoToSettlement (103923-103931), не
        /// выставляет ни TargetPosition, ни MoveTargetPoint. Плюс сам
        /// SetPartyAiAction пропускает вызов, если поведение и цель уже те же
        /// (228351-228362). Итог: приказ «повторить» ничего не чинит, а мод,
        /// видя «цель та же», молчал часами — 18.09 партия так простояла
        /// у Фрактори и в 14:43, и в 18:38 при идущем времени.
        ///
        /// Что делаем. Три часа без движения — пишем полное состояние движка и
        /// перевыдаём приказ, СНАЧАЛА сбив поведение в Hold: только смена
        /// значения возвращает движение. Два раза не помогло — снимаем цель на
        /// сутки и берём следующую. Это не догадка о причине конкретного
        /// застревания: причина застревания записывается в журнал, а мод в
        /// любом случае перестаёт стоять.
        ///
        /// Порог в шесть часов взят не на глаз: это штатная длительность
        /// расстройства партии после боя (DefaultPartyImpairmentModel,
        /// 64569-64578), то есть самая долгая стоянка, которую движок считает
        /// нормальной. Само расстройство при этом исключено отдельно — партия в
        /// нём стоит по праву.</summary>
        private void WatchMovement(MobileParty party)
        {
            if (_mode != Mode.Apply || !IsTravelBehavior(party.DefaultBehavior)
                || party.CurrentSettlement != null || party.MapEvent != null
                || party.SiegeEvent != null || party.BesiegedSettlement != null
                || party.Army != null || PlayerEncounter.Current != null
                || party.IsDisorganized)
            {
                _moveWatchKey = null;
                _moveWatchHours = 0;
                _moveWatchNudges = 0;
                return;
            }

            string key = party.DefaultBehavior + "|"
                         + (party.TargetSettlement != null ? party.TargetSettlement.Name.ToString() : "точка");
            if (key != _moveWatchKey || party.Position.DistanceSquared(_moveWatchPosition) > MovedEpsilon)
            {
                _moveWatchKey = key;
                _moveWatchPosition = party.Position;
                _moveWatchHours = 0;
                _moveWatchNudges = 0;
                return;
            }

            if (++_moveWatchHours < StuckHours)
            {
                return;
            }
            _moveWatchHours = 0;

            if (_moveWatchNudges < StuckNudges)
            {
                _moveWatchNudges++;
                AutopilotLog.Write("ЗАСТРЯЛИ: приказ " + key + " принят, но за " + StuckHours
                                   + " ч. партия не сдвинулась (" + Where(party)
                                   + "); перевыдаю приказ, попытка " + _moveWatchNudges);
                LogCurrentState("при застревании");
                party.SetMoveModeHold();   // движение вернёт только СМЕНА поведения
                _lastTargetKey = null;     // и пересчёт должен выдать приказ заново
                return;
            }

            Settlement target = party.TargetSettlement;
            if (target != null)
            {
                _stuckTarget = target;
                _stuckTargetUntil = CampaignTime.Now.ToHours + StuckTargetAvoidHours;
                AutopilotLog.Write("ЗАСТРЯЛИ: до «" + target.Name + "» приказ партию не двигает — цель снята на "
                                   + StuckTargetAvoidHours.ToString("F0", CultureInfo.InvariantCulture)
                                   + " ч., беру следующую");
            }
            else
            {
                AutopilotLog.Write("ЗАСТРЯЛИ: приказ " + key + " партию не двигает, беру следующую цель");
            }
            party.SetMoveModeHold();
            _lastTargetKey = null;
            _moveWatchKey = null;
            _moveWatchNudges = 0;
        }

        /// <summary>Приказы, под которыми партия обязана ехать. Патруль и
        /// сопровождение сюда не входят: там стоянка бывает штатной.</summary>
        private static bool IsTravelBehavior(AiBehavior behavior)
        {
            return behavior == AiBehavior.GoToSettlement
                   || behavior == AiBehavior.BesiegeSettlement
                   || behavior == AiBehavior.RaidSettlement
                   || behavior == AiBehavior.DefendSettlement;
        }

        private static string DecisionKey(AIBehaviorData data)
        {
            return data.AiBehavior + "|" + (data.Party != null ? data.Party.ToString() : data.Position.ToString());
        }

        /// <summary>Идём брать эту крепость — ванильным осадным приказом или
        /// поездкой к ней: партию игрока двигает только вторая.</summary>
        private bool HeadingToSiegeTarget(MobileParty party)
        {
            return party.TargetSettlement != null
                   && (party.DefaultBehavior == AiBehavior.BesiegeSettlement
                       || (party.DefaultBehavior == AiBehavior.GoToSettlement
                           && party.TargetSettlement == _offensiveSiege));
        }

        private static bool IsSameDecision(AIBehaviorData data, MobileParty party)
        {
            // Решение «осадить» исполняется поездкой к крепости, поэтому поведение
            // партии при нём — GoToSettlement. Без этого приказ перевыдавался бы
            // каждый час, а каждая выдача сбрасывает путь.
            if ((data.AiBehavior == AiBehavior.BesiegeSettlement || data.AiBehavior == AiBehavior.DefendSettlement)
                && party.DefaultBehavior == AiBehavior.GoToSettlement
                && data.Party is Settlement heading)
            {
                return heading == party.TargetSettlement;
            }
            if (data.AiBehavior != party.DefaultBehavior)
            {
                return false;
            }
            var settlement = data.Party as Settlement;
            if (settlement != null)
            {
                return settlement == party.TargetSettlement;
            }
            var targetParty = data.Party as MobileParty;
            return targetParty != null && targetParty == party.TargetParty;
        }

        private bool TryApplyNearbyAttack(MobileParty party)
        {
            if (_mode != Mode.Apply) return false;
            try
            {
                Campaign.Current.Models.MobilePartyAIModel.GetBestInitiativeBehavior(
                    party, out AiBehavior behavior, out MobileParty target, out float score, out Vec2 _);
                if (behavior != AiBehavior.EngageParty || target == null || score <= 1f)
                {
                    return false;
                }
                if (InLeftForeignBattle(target))
                {
                    AutopilotLog.Write("ближняя угроза «" + target.Name + "» пропущена: она в чужом бою, из которого мы ушли");
                    return false;
                }

                var decision = new AIBehaviorData(target, AiBehavior.EngageParty,
                    MobileParty.NavigationType.Default, false, false, false);
                AutopilotLog.Write("ближняя угроза по штатной модели: атакуем «" + target.Name
                                   + "», оценка " + score.ToString("F3", CultureInfo.InvariantCulture));
                ApplyDecision(party, decision, score);
                return true;
            }
            catch (Exception ex)
            {
                Disable("расчёт ближайшего врага упал: " + ex.GetType().Name + ": " + ex.Message);
                return true;
            }
        }

        private void UpdatePatrolHistory(AIBehaviorData next)
        {
            var nextSettlement = next.AiBehavior == AiBehavior.PatrolAroundPoint ? next.Party as Settlement : null;
            if (_continuousPatrolSettlement != null && nextSettlement != _continuousPatrolSettlement)
            {
                double duration = Math.Max(0, CampaignTime.Now.ToHours - _continuousPatrolSinceHours);
                if (duration >= LongPatrolHours)
                {
                    _patrolCooldownUntil[_continuousPatrolSettlement] = CampaignTime.Now.ToHours + PatrolCooldownHours;
                    AutopilotLog.Write("  «" + _continuousPatrolSettlement.Name + "» отдыхает от патруля "
                                       + PatrolCooldownHours.ToString("F0", CultureInfo.InvariantCulture) + " ч.");
                }
                _continuousPatrolSettlement = null;
                _continuousPatrolSinceHours = -1;
            }
            if (nextSettlement != null && _continuousPatrolSettlement == null)
            {
                _continuousPatrolSettlement = nextSettlement;
                _continuousPatrolSinceHours = CampaignTime.Now.ToHours;
            }
        }

        /// <summary>Почему решение штатного AI автопилот не выполняет. null — выполняет.</summary>
        private string WhyNotApplicable(AIBehaviorData data)
        {
            if (ReliefUnavailable(data.Party as Settlement)) return "прорыв недавно запрещён игрой, ждём повторной попытки";
            // Цель, под приказ на которую партия не сдвинулась с места, временно
            // не предлагаем: иначе тот же приказ выдаётся снова и снова.
            if (_stuckTarget != null && CampaignTime.Now.ToHours < _stuckTargetUntil
                && ReferenceEquals(data.Party, _stuckTarget))
            {
                return "приказ туда не двигал партию, цель снята до " + _stuckTargetUntil.ToString("F0", CultureInfo.InvariantCulture) + " ч.";
            }
            if (data.WillGatherArmy)
            {
                if (!ControlsParty(MobileParty.MainParty)) return "следуем другой армии";
                if (MobileParty.MainParty.Army == null && AffordableArmyMembers(MobileParty.MainParty).Count == 0)
                    return "нет доступных приглашений в армию или ресурсов";
            }
            switch (data.AiBehavior)
            {
                case AiBehavior.RaidSettlement:
                    if (!EnemyVillage(data.Party as Settlement, MobileParty.MainParty)) return "нет вражеской деревни";
                    return PreparationNeeded(MobileParty.MainParty);
                case AiBehavior.BesiegeSettlement:
                    if (!EnemyFortress(data.Party as Settlement, MobileParty.MainParty)) return "нет вражеской крепости";
                    var siegeParty = MobileParty.MainParty;
                    string border = SiegeBorderRejection(siegeParty, data.Party as Settlement);
                    if (border != null) return border;
                    string siegePreparation = PreparationNeeded(siegeParty);
                    if (siegePreparation != null) return siegePreparation;
                    float defenders = SiegeDefenderStrength((Settlement)data.Party, siegeParty);
                    float attackers = SiegeAttackerStrength(siegeParty);
                    if (data.WillGatherArmy && siegeParty.Army == null)
                        attackers += AffordableArmyMembers(siegeParty).Sum(p => Math.Max(0f, p.Party.EstimatedStrength));
                    return defenders <= attackers * 1.5f ? null : "защитники сильнее 1.5x наших сил";
                case AiBehavior.DefendSettlement:
                    if (!FriendlySiege(data.Party as Settlement, MobileParty.MainParty)) return "нет дружественной осады";
                    if (data.Party == _defenseTarget && !OwnFort(data.Party as Settlement)) return "срочная цель обороны больше не принадлежит нашему клану";
                    return OwnFort(data.Party as Settlement) ? DefenseReadiness(MobileParty.MainParty) : null;
                case AiBehavior.GoToSettlement:
                    if (!(data.Party is Settlement settlement))
                    {
                        return "без поселения";
                    }
                    return CannotStay(settlement)
                        ? "в «" + settlement.Name + "» недавно нельзя было подождать, по кругу туда не ездим"
                        : null;
                case AiBehavior.PatrolAroundPoint:
                    return null;
                case AiBehavior.EscortParty:
                    return data.Party is MobileParty ? null : "без партии";
                case AiBehavior.GoAroundParty:
                    return data.Party is MobileParty ? null : "без партии";
                case AiBehavior.EngageParty:
                    if (!(data.Party is MobileParty target))
                    {
                        return "без партии";
                    }
                    return InLeftForeignBattle(target) ? "в чужом бою, из которого мы ушли" : null;
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
            if (data.AiBehavior == AiBehavior.DefendSettlement)
            {
                // A pending departure may execute later than the hourly selection.
                string invalid = !ControlsParty(party) ? "следуем другой армии" : WhyNotApplicable(data);
                if (invalid != null)
                {
                    AutopilotLog.Write("ОБОРОНА: отложенный приказ отменён: " + invalid);
                    return;
                }
            }
            string key = DecisionKey(data);

            if (key == _lastTargetKey && IsSameDecision(data, party))
            {
                _reappliesThisSession++;
                AutopilotLog.Write("  та же цель продолжается, приказ не перевыдаю ("
                                   + _reappliesThisSession + "-й пересчёт): " + Describe(data)
                                   + " (оценка " + score.ToString("F3", CultureInfo.InvariantCulture) + ")");
                return;
            }

            UpdatePatrolHistory(data);

            try
            {
                if (data.WillGatherArmy && party.Army == null)
                {
                    if (!StartArmy(party, data, score)) AutopilotLog.Write("АРМИЯ: сбор сейчас недоступен, нужен пересчёт цели");
                    return;
                }
                switch (data.AiBehavior)
                {
                    case AiBehavior.RaidSettlement:
                        _raidSettlement = settlement;
                        SetPartyAiAction.GetActionForRaidingSettlement(party, settlement, data.NavigationType, data.IsFromPort, data.IsTargetingPort);
                        break;
                    case AiBehavior.BesiegeSettlement:
                        // Ванильный SetMoveBesiegeSettlement (104002-104012) ставит цель и
                        // поведение, но НЕ ставит ни TargetPosition, ни MoveTargetPoint — в
                        // отличие от рейда (103994-103999) и поездки (103923-103931). NPC под
                        // этим приказом ведёт тик ИИ, а партия игрока просто стоит: 18.09
                        // сторож движения поймал шесть часов на месте при пустом состоянии
                        // движка (журнал 19:27:57). Поэтому к крепости едем приказом, который
                        // партию игрока действительно двигает, а осаду начинает штатный пункт
                        // меню у ворот — ровно как это делает человек.
                        _offensiveSiege = settlement;
                        SetPartyAiAction.GetActionForVisitingSettlement(
                            party, settlement, data.NavigationType, data.IsFromPort, data.IsTargetingPort);
                        break;
                    case AiBehavior.DefendSettlement:
                        // Native Defend resets MoveTargetPoint to our current position;
                        // only visiting sets the point that actually moves MainParty.
                        SetPartyAiAction.GetActionForVisitingSettlement(
                            party, settlement, data.NavigationType, data.IsFromPort, data.IsTargetingPort);
                        break;
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

                    case AiBehavior.GoAroundParty:
                        SetPartyAiAction.GetActionForGoingAroundParty(
                            party, (MobileParty)data.Party, data.NavigationType, data.IsFromPort);
                        break;

                    case AiBehavior.EngageParty:
                        SetPartyAiAction.GetActionForEngagingParty(
                            party, (MobileParty)data.Party, data.NavigationType, data.IsFromPort);
                        _combatTarget = (MobileParty)data.Party;
                        break;

                    default:
                        AutopilotLog.Write("  «" + data.AiBehavior + "» автопилот не выполняет — приказ не выдан");
                        return;
                }
                if (data.AiBehavior != AiBehavior.EngageParty) _combatTarget = null;
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
