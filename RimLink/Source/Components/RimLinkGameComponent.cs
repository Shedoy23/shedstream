using System.Collections.Generic;
using System;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using RimWorld;
using Verse;

namespace RimLink.Components
{
    /// <summary>
    /// Подключается к игровому циклу после полной загрузки карты.
    /// Именно здесь безопасно читать пешки, карту и мир.
    /// RimWorld создаёт GameComponent автоматически для активной игры.
    /// </summary>
    public class RimLinkGameComponent : GameComponent
    {
        private int _syncTicks = 0;
        private int _deathCheckTicks = 0; // <-- ИСПРАВЛЕНИЕ: объявлена переменная
        
        private int SyncIntervalTicks =>
            RimLinkMod.Instance != null ? RimLinkMod.Instance.SyncInterval * 60 : 3000;
            
        private bool _gameLoaded = false;
        private bool _offlineSent = false;
        private bool _sessionInitialized = false;
        private bool _quittingSubscribed = false;
        private int _heartbeatInFlight = 0;

        private const int MAX_COMMANDS_PER_TICK = 5;
        private const int COMMAND_BUDGET_MS = 8;

        // Heartbeat по реальному времени (не игровым тикам) — работает и на паузе
        private float _heartbeatRealTime = 0f;
        private const float HEARTBEAT_REAL_INTERVAL = 30f;

        public RimLinkGameComponent(Game game) { }

        private static void SyncCatalogsInBackground()
        {
            List<object> catalog = null;
            List<object> events  = null;

            try
            {
                if (RimLinkMod.ShopManager != null && RimLinkMod.Prices != null)
                    catalog = RimLinkMod.ShopManager.BuildCatalogWithPrices(RimLinkMod.Prices);
            }
            catch (Exception ex) { Log.Warning($"[RimLink] BuildShopCatalog: {ex.Message}"); }

            try
            {
                if (RimLinkMod.EventManager != null && RimLinkMod.Prices != null)
                    events = RimLinkMod.EventManager.BuildEventCatalog(RimLinkMod.Prices);
            }
            catch (Exception ex) { Log.Warning($"[RimLink] BuildEventCatalog: {ex.Message}"); }

            var capCatalog = catalog;
            var capEvents  = events;
            Task.Run(() =>
            {
                try
                {
                    if (capCatalog != null) RimLinkMod.API?.SyncShopCatalog(capCatalog);
                    if (capEvents != null)  RimLinkMod.API?.SyncEventCatalog(capEvents);
                }
                catch (Exception ex) { Log.Warning($"[RimLink] SyncCatalogs bg: {ex.Message}"); }
            });
        }

        public override void FinalizeInit()
        {
            base.FinalizeInit();
            TryInitializeSession("игра загружена");
        }

        public override void StartedNewGame()
        {
            base.StartedNewGame();
            TryInitializeSession("новая игра");
        }

        private void TryInitializeSession(string reason)
        {
            if (_sessionInitialized || Current.Game == null) return;
            bool worldReady = (Find.Maps != null && Find.Maps.Count > 0)
                || PawnsFinder.AllMapsCaravansAndTravellingTransporters_Alive.Count > 0;
            if (!worldReady) return;

            _sessionInitialized = true;
            _gameLoaded = true;
            RimLinkMod.GameSessionActive = true;
            _offlineSent = false;
            _heartbeatRealTime = 0f;
            Log.Message($"[RimLink] Инициализация сессии ({reason})");

            if (!_quittingSubscribed)
            {
                UnityEngine.Application.quitting += OnApplicationQuitting;
                _quittingSubscribed = true;
            }

            RimLinkMod.PawnManager?.LoadFromCurrentMap();
            SyncCatalogsInBackground();
        }

        public override void GameComponentTick()
        {
            base.GameComponentTick();

            if (!_sessionInitialized)
                TryInitializeSession("отложенная готовность мира");
            if (!_gameLoaded) return;
            if (RimLinkMod.CommandQueue == null) return;
            
            _syncTicks++;
            _deathCheckTicks++;

            RimLinkMod.CommandQueue.FlushBudget(MAX_COMMANDS_PER_TICK, COMMAND_BUDGET_MS);

            // 1. Периодическая полная синхронизация
            if (_syncTicks >= SyncIntervalTicks)
            {
                _syncTicks = 0;
                try
                {
                    if (Current.Game != null)
                        RimLinkMod.PawnManager?.SyncAll();
                }
                catch (Exception ex)
                {
                    Log.Warning($"[RimLink] GameComponentTick SyncAll: {ex.Message}");
                }
            }

            // 2. МОМЕНТАЛЬНАЯ ПРОВЕРКА СМЕРТИ (~1 раз в секунду)
            if (_deathCheckTicks >= 60)
            {
                _deathCheckTicks = 0;
                try
                {
                    RimLinkMod.PawnManager?.CheckAndSyncDeaths();
                }
                catch (Exception ex)
                {
                    Log.Warning($"[RimLink] GameComponentTick death check: {ex.Message}");
                }
            }
        }

        public override void GameComponentUpdate()
        {
            base.GameComponentUpdate();

            if (_gameLoaded && !_offlineSent && Current.ProgramState == ProgramState.Entry)
            {
                SendOfflineNotification();
                return;
            }

            if (_gameLoaded)
            {
                _heartbeatRealTime += Time.unscaledDeltaTime;
                if (_heartbeatRealTime >= HEARTBEAT_REAL_INTERVAL)
                {
                    _heartbeatRealTime = 0f;
                    if (Interlocked.CompareExchange(ref _heartbeatInFlight, 1, 0) != 0)
                        return;

                    Task.Run(() =>
                    {
                        try { RimLinkMod.API?.Heartbeat(); }
                        catch (Exception ex)
                        {
                            #if DEBUG
                            Log.Warning($"[RimLink] Heartbeat failed: {ex.Message}");
                            #else
                            _ = ex;
                            #endif
                        }
                        finally { Interlocked.Exchange(ref _heartbeatInFlight, 0); }
                    });
                }
            }
        }

        public override void GameComponentOnGUI()
        {
            base.GameComponentOnGUI();
        }

        private void OnApplicationQuitting()
        {
            UnsubscribeFromQuitting();
            SendOfflineNotification();
        }

        private void SendOfflineNotification()
        {
            if (_offlineSent) return;
            _offlineSent = true;
            _gameLoaded  = false;
            RimLinkMod.GameSessionActive = false;
            _sessionInitialized = false;
            UnsubscribeFromQuitting();

            RimLinkMod.CommandQueue?.ClearPending();
            RimLinkMod.PawnManager?.Clear();

            Log.Message("[RimLink] Игра закрывается — отправляем offline");
            Task.Run(() =>
            {
                try { RimLinkMod.API?.SendOffline(); }
                catch (Exception ex) { Log.Warning($"[RimLink] Offline notification failed: {ex.Message}"); }
            });
        }

        private void UnsubscribeFromQuitting()
        {
            if (!_quittingSubscribed) return;
            UnityEngine.Application.quitting -= OnApplicationQuitting;
            _quittingSubscribed = false;
        }

        public override void ExposeData()
        {
            base.ExposeData();
        }
    }
}
