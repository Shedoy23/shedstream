using System;
using System.Collections.Generic;
using System.Linq;
using BannerlordLink.Util;
using Newtonsoft.Json;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.MapEvents;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// Sprint 5.33 PORDER — Sticky party orders с auto-completion detection.
    ///
    /// Зачем: engine SetMove* API одноразовое — выставляет goal, AI потом
    /// может drift'нуть (defend → engage enemies → forget original target).
    /// BLT pattern: behavior держит intent, re-issue'ит периодически, snimает
    /// при достижении цели.
    ///
    /// State:
    ///   _orders[username] = (orderType, targetSettlementId, expiresAt, lastReissuedAt)
    ///
    /// Tick model:
    ///   HourlyTickEvent (global, не per-party — дешевле) — iterate _orders:
    ///     1. Check expiry (CampaignTime > expiresAt) → release + push status
    ///     2. Check completion:
    ///         siege → target.OwnerClan changed (взяли settlement)
    ///         raid  → village.IsRaided → false after IsRaided=true cycle
    ///         garrison → party.CurrentSettlement == target за prev 2 hours
    ///         defend → enemy threat gone (no enemy parties в radius)
    ///         patrol → never auto-complete (continuous behavior)
    ///     3. Reissue SetMove* — engine no-op'ит если уже same target.
    ///
    /// Auto-release also fires on:
    ///   MapEventEnded (raid completed, siege ended)
    ///   OnSettlementOwnerChanged (siege resolved via capture)
    ///
    /// Persistence: SyncData сериализует dict (username, orderType, settlementId,
    /// expiresAt-numTicks) — restores на game load.
    ///
    /// Event push: hero.party_order_status с {owner, order, target, remaining_hours}
    /// при set/release/expire/complete → extension UI shows live state.
    /// </summary>
    public class PartyOrderBehavior : CampaignBehaviorBase
    {
        // ─── State ──────────────────────────────────────────────────────────

        private struct OrderState
        {
            public string OrderType;          // siege/defend/raid/garrison/patrol
            public string TargetSettlementId;
            public double ExpiresAtHours;     // CampaignTime.Now.ToHours at expiry
            public double LastReissuedHours;  // for dampening re-issue spam
        }

        // username-lowercased → OrderState
        private Dictionary<string, OrderState> _orders
            = new Dictionary<string, OrderState>();

        // Default order duration if не задано иначе (real-time ~30 min @ 1x speed,
        // ~12 game days). Matches backend bannerlord_party_orders.expires_at default.
        public const float DEFAULT_DURATION_HOURS = 168f;   // 7 game-days

        // Re-issue throttle — повторять SetMove* не чаще раза в N hours.
        // 2026-07-20 — было 4ч. Так как глушить AI нельзя (он же исполняет приказ, см.
        // LockPartyAi), единственный способ удержать цель — исправлять дрейф БЫСТРО.
        // 1ч = каждый часовой тик: движок успевает исполнять, но не успевает уехать.
        private const float REISSUE_THROTTLE_HOURS = 1f;

        // Singleton access — handlers вызывают SetOrder/ReleaseOrder через it.
        public static PartyOrderBehavior Instance { get; private set; }

        public PartyOrderBehavior() { Instance = this; }

        // ─── Lifecycle ─────────────────────────────────────────────────────

        public override void RegisterEvents()
        {
            CampaignEvents.HourlyTickEvent.AddNonSerializedListener(this, OnHourlyTick);
            CampaignEvents.MapEventEnded.AddNonSerializedListener(this, OnMapEventEnded);
            CampaignEvents.OnSettlementOwnerChangedEvent.AddNonSerializedListener(
                this, OnSettlementOwnerChanged);
            CampaignEvents.OnGameLoadFinishedEvent.AddNonSerializedListener(
                this, OnGameLoadFinished);
        }

        public override void SyncData(IDataStore dataStore)
        {
            try
            {
                // Encode as parallel lists — CampaignBehaviorBase SyncData
                // не любит generic struct dicts.
                List<string> keys = new List<string>(_orders.Keys);
                List<string> vals = new List<string>();
                foreach (var k in keys)
                {
                    var o = _orders[k];
                    vals.Add($"{o.OrderType}|{o.TargetSettlementId}|{o.ExpiresAtHours:R}|{o.LastReissuedHours:R}");
                }
                dataStore.SyncData("blink_porder_keys", ref keys);
                dataStore.SyncData("blink_porder_vals", ref vals);

                if (!dataStore.IsSaving && keys != null && vals != null)
                {
                    _orders.Clear();
                    int n = Math.Min(keys.Count, vals.Count);
                    for (int i = 0; i < n; i++)
                    {
                        var parts = vals[i].Split('|');
                        if (parts.Length < 3) continue;
                        double expiry = 0, lastReissued = 0;
                        double.TryParse(parts[2], System.Globalization.NumberStyles.Float,
                                        System.Globalization.CultureInfo.InvariantCulture, out expiry);
                        if (parts.Length >= 4)
                            double.TryParse(parts[3], System.Globalization.NumberStyles.Float,
                                            System.Globalization.CultureInfo.InvariantCulture, out lastReissued);
                        _orders[keys[i]] = new OrderState
                        {
                            OrderType = parts[0],
                            TargetSettlementId = parts[1],
                            ExpiresAtHours = expiry,
                            LastReissuedHours = lastReissued,
                        };
                    }
                    BannerlordLinkModule.Log(
                        $"[party_order] SyncData load: restored {_orders.Count} active orders");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[party_order] SyncData crash: {ex.Message}");
            }
        }

        private void OnGameLoadFinished()
        {
            // Force one immediate re-issue cycle so restored orders apply quickly.
            try
            {
                if (_orders.Count > 0)
                {
                    BannerlordLinkModule.Log(
                        $"[party_order] OnGameLoadFinished — kick-starting {_orders.Count} orders");
                    OnHourlyTick();
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[party_order] OnGameLoadFinished crash: {ex.Message}");
            }
        }

        // ─── Public API (used by SetPartyOrderHandler / ReleasePartyOrderHandler) ─

        /// <summary>Register sticky order. Behavior takes over re-issue + completion
        /// tracking. Returns true if persisted.</summary>
        public static bool SetOrder(string username, string orderType,
            Settlement target, float? customHours = null)
        {
            var inst = Instance;
            if (inst == null) return false;
            if (string.IsNullOrEmpty(username) || target == null) return false;
            string key = username.ToLowerInvariant();
            float hours = customHours ?? DEFAULT_DURATION_HOURS;
            try
            {
                double nowH = CampaignTime.Now.ToHours;
                inst._orders[key] = new OrderState
                {
                    OrderType = orderType,
                    TargetSettlementId = target.StringId,
                    ExpiresAtHours = nowH + hours,
                    LastReissuedHours = nowH,
                };
                BannerlordLinkModule.Log(
                    $"[party_order] SET @{key} order={orderType} target={target.StringId} " +
                    $"expires_hours={hours:F1}");
                PushStatusEvent(key, orderType, target, hours);
                return true;
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[party_order] SetOrder crash: {ex.Message}");
                return false;
            }
        }

        /// <summary>Remove sticky order. Engine AI resumes default behavior.</summary>
        public static void ReleaseOrder(string username, string reason = "manual")
        {
            var inst = Instance;
            if (inst == null) return;
            string key = (username ?? "").ToLowerInvariant();
            if (string.IsNullOrEmpty(key)) return;
            if (inst._orders.Remove(key))
            {
                BannerlordLinkModule.Log(
                    $"[party_order] RELEASE @{key} reason={reason}");
                PushStatusEvent(key, null, null, 0);
            }
        }

        /// <summary>Inspect current order для UI / diagnostics.</summary>
        public static (string orderType, string targetId, float remainingHours)? GetOrder(string username)
        {
            var inst = Instance;
            if (inst == null) return null;
            if (!inst._orders.TryGetValue((username ?? "").ToLowerInvariant(), out var o))
                return null;
            try
            {
                float remaining = (float)(o.ExpiresAtHours - CampaignTime.Now.ToHours);
                return (o.OrderType, o.TargetSettlementId, Math.Max(0, remaining));
            }
            catch { return null; }
        }

        /// <summary>2026-07-20 — немедленная переотдача приказа, в обход
        /// REISSUE_THROTTLE_HOURS. Нужна там, где ЧТО-ТО извне перетёрло цель партии и
        /// ждать до 4 игровых часов нельзя: создание армии (CreateArmy уводит партию к
        /// точке сбора → «армия садится в осаду и уходит»). Возвращает и замок AI.
        /// No-op если приказа нет / герой или партия не найдены.</summary>
        public static bool ReissueNow(string username)
        {
            var inst = Instance;
            if (inst == null) return false;
            string key = (username ?? "").ToLowerInvariant();
            if (!inst._orders.TryGetValue(key, out var o)) return false;
            try
            {
                var hero = BannerlordLink.Actions.HeroLookup.FindByUsername(key);
                var mp = hero?.PartyBelongedTo;
                if (mp == null) return false;
                var target = Settlement.Find(o.TargetSettlementId);
                if (target == null) return false;
                Reissue(o.OrderType, mp, target);      // сам ставит и SetDoNotMakeNewDecisions(true)
                o.LastReissuedHours = CampaignTime.Now.ToHours;
                inst._orders[key] = o;
                BannerlordLinkModule.Log(
                    $"[party_order] @{key} немедленная переотдача '{o.OrderType}' → {target.Name}");
                return true;
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[party_order] ReissueNow warn @{key}: {ex.Message}");
                return false;
            }
        }

        // ─── Tick — re-issue + completion check ────────────────────────────

        private void OnHourlyTick()
        {
            TopUpViewerArmyCohesion();
            if (_orders.Count == 0) return;
            try
            {
                // Snapshot keys чтобы mutation в loop'е была safe.
                var keys = new List<string>(_orders.Keys);
                double now = CampaignTime.Now.ToHours;
                int reissued = 0, expired = 0, completed = 0;

                foreach (var key in keys)
                {
                    if (!_orders.TryGetValue(key, out var o)) continue;

                    // 1) Expiry check.
                    if (now >= o.ExpiresAtHours)
                    {
                        _orders.Remove(key);
                        BannerlordLinkModule.Log(
                            $"[party_order] @{key} EXPIRED ({o.OrderType} → {o.TargetSettlementId})");
                        PushStatusEvent(key, null, null, 0);
                        expired++;
                        continue;
                    }

                    // 2) Resolve hero + party + target.
                    var hero = BannerlordLink.Actions.HeroLookup.FindByUsername(key);
                    if (hero == null || !hero.IsAlive)
                    {
                        _orders.Remove(key);
                        BannerlordLinkModule.Log(
                            $"[party_order] @{key} dropped — hero gone/dead");
                        PushStatusEvent(key, null, null, 0);
                        continue;
                    }
                    var mp = hero.PartyBelongedTo;
                    if (mp == null || mp != hero.PartyBelongedTo)
                    {
                        // No active party (in town, captured, etc.) — skip this tick,
                        // не release — может вернётся в party.
                        continue;
                    }
                    Settlement target = null;
                    try { target = MBObjectManager.Instance.GetObject<Settlement>(o.TargetSettlementId); }
                    catch { }
                    if (target == null)
                    {
                        _orders.Remove(key);
                        BannerlordLinkModule.Log(
                            $"[party_order] @{key} dropped — target settlement '{o.TargetSettlementId}' gone");
                        PushStatusEvent(key, null, null, 0);
                        continue;
                    }

                    // 3) Completion check (per order type).
                    if (IsCompleted(o.OrderType, mp, hero, target))
                    {
                        _orders.Remove(key);
                        BannerlordLinkModule.Log(
                            $"[party_order] @{key} COMPLETED ({o.OrderType} @ {target.Name})");
                        PushStatusEvent(key, null, null, 0);
                        completed++;
                        continue;
                    }

                    // 3b) 2026-07-20 — обновляем сильный замок AI КАЖДЫЙ час (не только на
                    // троттленной переотдаче): DisableForHours(8) + ежечасный refresh =
                    // замок непрерывен, пока приказ жив, и самоснимается, если нас не стало.
                    LockPartyAi(mp);

                    // 4) Throttled re-issue.
                    double hoursSinceReissue = now - o.LastReissuedHours;
                    if (hoursSinceReissue >= REISSUE_THROTTLE_HOURS)
                    {
                        try { Reissue(o.OrderType, mp, target); } catch (Exception rEx)
                        {
                            BannerlordLinkModule.Log(
                                $"[party_order] reissue @{key} crash: {rEx.Message}");
                        }
                        var updated = o;
                        updated.LastReissuedHours = now;
                        _orders[key] = updated;
                        reissued++;
                    }
                }
                if (reissued + expired + completed > 0)
                {
                    BannerlordLinkModule.Log(
                        $"[party_order] HourlyTick: reissued={reissued} expired={expired} completed={completed} " +
                        $"active={_orders.Count}");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[party_order] OnHourlyTick crash: {ex.Message}");
            }
        }

        // ─── Army MVP fast-follow (2026-07-19) — cohesion-долив ────────────
        // Армия зрителя (Kingdom.CreateArmy в ArmyHandlers) без долива
        // рассыпается движком за 1-2 игровых дня (cohesion → 0). Зритель
        // заплатил крустиками — держим cohesion=100 каждый час, пока армию
        // не распустят/разобьют. См. docs/ARMY_MVP_SPEC.md.
        private void TopUpViewerArmyCohesion()
        {
            try
            {
                if (Campaign.Current == null) return;
                int topped = 0;
                foreach (var kingdom in Campaign.Current.Kingdoms)
                {
                    var armies = kingdom?.Armies;
                    if (armies == null) continue;
                    foreach (var army in armies)
                    {
                        var leader = army?.LeaderParty?.LeaderHero;
                        if (leader == null) continue;
                        // Viewer-геройность: name prefix ИЛИ persistent dict
                        // (legacy saves могут иметь только одно из двух).
                        bool isViewer = HeroNaming.IsAdopted(leader)
                            || HeroIdentityBehavior.Instance?.GetUsername(leader) != null;
                        if (!isViewer) continue;
                        if (army.Cohesion < 100f)
                        {
                            army.Cohesion = 100f;
                            topped++;
                        }
                    }
                }
                if (topped > 0)
                    BannerlordLinkModule.Log(
                        $"[army] cohesion top-up: {topped} viewer army(ies) → 100");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[army] cohesion top-up crash: {ex.Message}");
            }
        }

        // ─── Completion heuristics ─────────────────────────────────────────

        private static bool IsCompleted(string orderType, MobileParty mp,
            Hero hero, Settlement target)
        {
            try
            {
                switch (orderType)
                {
                    case "siege":
                        // Done if hero faction owns target (siege succeeded by anyone)
                        // OR settlement не at war anymore (peace).
                        if (target.OwnerClan?.MapFaction == hero.MapFaction) return true;
                        if (hero.MapFaction != null && target.MapFaction != null
                            && !hero.MapFaction.IsAtWarWith(target.MapFaction)) return true;
                        return false;
                    case "raid":
                        // Village raided this cycle? Engine clears IsRaided after recovery —
                        // безопасно считать complete если хотя бы один цикл прошёл.
                        if (target.IsVillage && target.Village != null)
                        {
                            // Hearth dropped значительно VS pre-raid — упрощённый proxy.
                            // Здесь просто smell-test: если settlement не at war or hero
                            // не near target — auto-release.
                            if (hero.MapFaction != null && target.MapFaction != null
                                && !hero.MapFaction.IsAtWarWith(target.MapFaction)) return true;
                        }
                        return false;
                    case "garrison":
                        // Already inside garrisoned settlement >2 hours.
                        return mp.CurrentSettlement == target;
                    case "defend":
                        // No enemy threat около target settlement (1 day stable).
                        // Simpler: just keep order active — defends все время.
                        return false;
                    case "patrol":
                        // Patrol — never auto-complete.
                        return false;
                    default:
                        return false;
                }
            }
            catch { return false; }
        }

        // ─── Re-issue dispatch ─────────────────────────────────────────────

        private static void Reissue(string orderType, MobileParty mp, Settlement target)
        {
            var navType = MobileParty.NavigationType.Default;
            switch (orderType)
            {
                case "siege":    mp.SetMoveBesiegeSettlement(target, navType); break;
                case "defend":   mp.SetMoveDefendSettlement(target, false, navType); break;
                case "raid":
                    if (target.IsVillage) mp.SetMoveRaidSettlement(target, navType);
                    break;
                case "garrison": mp.SetMoveGoToSettlement(target, navType, false); break;
                case "patrol":   mp.SetMovePatrolAroundSettlement(target, navType, false); break;
            }
            // 2026-06-10 FIX — держим AI замороженным на каждом reissue (флаг могут
            // сбросить движковые события: вступление в армию, бой, плен).
            LockPartyAi(mp);

            // 2026-07-20 — синхронизируем цель АРМИИ. У армии свой AiBehaviorObject, и он
            // жил своей жизнью: расширение показывало «осада → Замок Укба», а в игре армия
            // писала «Цель — осада Кайяза» (скриншот владельца). Пока цели расходятся,
            // армейская логика (Army.HourlyTick / MoveLeaderToGatheringLocationIfNeeded)
            // тянет лидера к СВОЕЙ цели и наш приказ перебивается каждый час.
            // Ставим только если наш герой — лидер армии (иначе не наше дело).
            try
            {
                var army = mp.Army;
                if (army != null && army.LeaderParty == mp && !ReferenceEquals(army.AiBehaviorObject, target))
                {
                    army.AiBehaviorObject = target;
                    BannerlordLinkModule.Log(
                        $"[party_order] цель армии синхронизирована → {target.Name}");
                }
            }
            catch (Exception aEx)
            {
                BannerlordLinkModule.Log($"[party_order] army target sync warn: {aEx.Message}");
            }
        }

        /// <summary>Мягкий замок AI партии.
        ///
        /// ⚠️ ИСТОРИЯ ГРАБЕЛЬ (2026-07-20, два круга):
        /// 1) Сначала тут был только SetDoNotMakeNewDecisions(true). Декомпайл показал,
        ///    что флаг читается РОВНО в одном месте (GetBehaviors — «инициативные» решения
        ///    погнаться/сбежать) и не мешает движку пересчитывать DefaultBehavior → осада
        ///    сбивалась.
        /// 2) Тогда включили жёсткий DisableForHours() — ветку IsDisabled в TickInternal,
        ///    которая пропускает расчёт поведения ЦЕЛИКОМ. Приказ перестали сбивать...
        ///    и перестали ИСПОЛНЯТЬ: партия доезжала до замка и вставала. Причина —
        ///    MobilePartyAi.GetBesiegeBehavior (переход «доехал → сажусь в осаду») живёт
        ///    В ЭТОМ ЖЕ тике. AI партии одновременно и ломает наш приказ, и выполняет его.
        ///
        /// Вывод: глушить AI НЕЛЬЗЯ. Держим приказ иначе — частой переотдачей
        /// (REISSUE_THROTTLE_HOURS=1, см. OnHourlyTick): дрейф исправляется за игровой час,
        /// а исполнение приказа остаётся за движком.</summary>
        internal static void LockPartyAi(MobileParty mp)
        {
            if (mp == null) return;
            // Мягкий гейт: гасит «инициативу» (погоня/бегство за соседями), исполнение не трогает.
            try { mp.Ai.SetDoNotMakeNewDecisions(true); } catch { }
            // AI НЕ отключаем (DisableAi/DisableForHours) — он исполняет осаду. См. историю выше.
            try { mp.Ai.EnableAi(); } catch { }   // снять возможный замок от прошлой версии мода
        }

        /// <summary>Снять замок — партия возвращается к автономному AI.</summary>
        private static void UnlockPartyAi(MobileParty mp)
        {
            if (mp == null) return;
            try { mp.Ai.EnableAi(); } catch { }
            try { mp.Ai.SetDoNotMakeNewDecisions(false); } catch { }
        }

        // ─── Event-driven auto-release ─────────────────────────────────────

        private void OnMapEventEnded(MapEvent ev)
        {
            try
            {
                if (ev?.MapEventSettlement == null) return;
                Settlement s = ev.MapEventSettlement;
                // For each viewer raid/siege order targeting s, release.
                var keys = new List<string>(_orders.Keys);
                foreach (var k in keys)
                {
                    if (!_orders.TryGetValue(k, out var o)) continue;
                    if (o.TargetSettlementId != s.StringId) continue;
                    if (o.OrderType == "raid")
                    {
                        _orders.Remove(k);
                        BannerlordLinkModule.Log(
                            $"[party_order] @{k} auto-release — raid MapEvent ended at {s.Name}");
                        PushStatusEvent(k, null, null, 0);
                    }
                    else if (o.OrderType == "siege")
                    {
                        // Осада в движке — долгоживущий SiegeEvent, внутри которого идут
                        // отдельные MapEvent'ы: штурмы (IsSiegeAssault), вылазки гарнизона
                        // (IsSallyOut), SiegeOutside/Blockade — у ВСЕХ MapEventSettlement ==
                        // осаждаемое поселение. Раньше приказ снимался на завершении ЛЮБОГО из
                        // них → «осада сбрасывается» прямо во время осады (репорт #35; декомпайл
                        // MapEvent + Settlement подтвердил, движок держит SiegeEvent через
                        // суб-бои полем _keepSiegeEvent). Снимаем ТОЛЬКО когда осада реально
                        // кончилась: Settlement.IsUnderSiege==false (SiegeEvent обнулён = осада
                        // снята). Взятие поселения покрыто отдельно OnSettlementOwnerChanged.
                        if (!s.IsUnderSiege)
                        {
                            _orders.Remove(k);
                            BannerlordLinkModule.Log(
                                $"[party_order] @{k} auto-release — siege lifted at {s.Name}");
                            PushStatusEvent(k, null, null, 0);
                        }
                        // иначе осада продолжается → sticky-приказ держим (ничего не делаем)
                    }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[party_order] OnMapEventEnded crash: {ex.Message}");
            }
        }

        private void OnSettlementOwnerChanged(Settlement settlement, bool openToClaim,
            Hero newOwner, Hero oldOwner, Hero capturer,
            ChangeOwnerOfSettlementAction.ChangeOwnerOfSettlementDetail detail)
        {
            try
            {
                if (settlement == null) return;
                // Any active siege order для этого settlement'а auto-release'ится.
                var keys = new List<string>(_orders.Keys);
                foreach (var k in keys)
                {
                    if (!_orders.TryGetValue(k, out var o)) continue;
                    if (o.OrderType != "siege") continue;
                    if (o.TargetSettlementId != settlement.StringId) continue;
                    _orders.Remove(k);
                    BannerlordLinkModule.Log(
                        $"[party_order] @{k} auto-release — settlement {settlement.Name} " +
                        $"changed owner (new={newOwner?.Name})");
                    PushStatusEvent(k, null, null, 0);
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[party_order] OnSettlementOwnerChanged crash: {ex.Message}");
            }
        }

        // ─── Status event push (for extension UI) ──────────────────────────

        // 2026-06-10 FIX — снять заморозку AI у партии (по username), чтобы после
        // снятия/истечения/выполнения приказа партия вернулась к автономному AI,
        // а не осталась "замороженной" навсегда. No-op если героя/партии нет.
        private static void TryUnfreezeParty(string username)
        {
            try
            {
                var hero = BannerlordLink.Actions.HeroLookup.FindByUsername(username);
                var mp = hero?.PartyBelongedTo;
                // 2026-07-20 — снимаем СИЛЬНЫЙ замок (DisableAi), иначе партия осталась
                // бы с выключенным AI навсегда после снятия приказа.
                UnlockPartyAi(mp);
            }
            catch { }
        }

        private static void PushStatusEvent(string owner, string orderType,
            Settlement target, float remainingHours)
        {
            // orderType==null → приказ снят/истёк/выполнен: размораживаем AI партии.
            // Вызывается из ВСЕХ путей удаления приказа (release/expire/complete/
            // auto-release) — единая центральная точка разморозки.
            if (orderType == null) TryUnfreezeParty(owner);
            try
            {
                string evtData = JsonConvert.SerializeObject(new
                {
                    owner            = owner,
                    order_type       = orderType,           // null = released/expired/done
                    target_id        = target?.StringId,
                    target_name      = target?.Name?.ToString(),
                    remaining_hours  = remainingHours,
                });
                System.Threading.Tasks.Task.Run(async () =>
                    await BannerlordLinkModule.Backend.PostEventAsync(
                        "bannerlord", "hero.party_order_status", evtData));
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[party_order] status push crash: {ex.Message}");
            }
        }
    }
}
