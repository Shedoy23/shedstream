using System.Collections.Generic;
using System;
using UnityEngine;
using RimWorld;
using Verse;

namespace RimLink.Components
{
    /// <summary>
    /// Подключается к игровому циклу после полной загрузки карты.
    /// Именно здесь безопасно читать пешки, карту и мир.
    /// Регистрируется через Defs/GameComponent.xml
    /// </summary>
    public class RimLinkGameComponent : GameComponent
    {
        private int _syncTicks = 0;
        private int _deathCheckTicks = 0; // <-- ИСПРАВЛЕНИЕ: объявлена переменная
        
        private int SyncIntervalTicks =>
            RimLinkMod.Instance != null ? RimLinkMod.Instance.SyncInterval * 60 : 3000;
            
        private bool _gameLoaded = false;
        private bool _offlineSent = false;

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
            new System.Threading.Thread(() =>
            {
                try
                {
                    if (capCatalog != null) RimLinkMod.API?.SyncShopCatalog(capCatalog);
                    if (capEvents != null)  RimLinkMod.API?.SyncEventCatalog(capEvents);
                }
                catch (Exception ex) { Log.Warning($"[RimLink] SyncCatalogs bg: {ex.Message}"); }
            }) { IsBackground = true, Name = "RimLink-SyncCatalogs" }.Start();
        }

        public override void FinalizeInit()
        {
            base.FinalizeInit();
            Log.Message("[RimLink] Игра загружена — начинаем синхронизацию");

            UnityEngine.Application.quitting -= OnApplicationQuitting;
            UnityEngine.Application.quitting += OnApplicationQuitting;

            // SessionStart теперь вызывается внутри LoadFromCurrentMap() в одном фоновом потоке
            // вместе с SyncPawnsBulk — это исключает гонку, из-за которой мёртвые пешки
            // без трупа раньше оставались в БД (session-start мог сработать после bulk-sync).
            RimLinkMod.PawnManager?.LoadFromCurrentMap();
            SyncCatalogsInBackground();

            _gameLoaded = true;
            _offlineSent = false;
        }

        public override void StartedNewGame()
        {
            base.StartedNewGame();
            Log.Message("[RimLink] Новая игра — инициализация");
            RimLinkMod.PawnManager?.LoadFromCurrentMap();
            SyncCatalogsInBackground();
            _gameLoaded = true;
            _offlineSent = false;
        }

        public override void GameComponentTick()
        {
            base.GameComponentTick();
            
            if (!_gameLoaded) return;
            if (RimLinkMod.CommandQueue == null || RimLinkMod.PendingCommands == null) return;
            
            _syncTicks++;
            _deathCheckTicks++;

            while (RimLinkMod.PendingCommands.TryDequeue(out var cmd))
            {
                try { RimLinkMod.CommandQueue.Enqueue(cmd); }
                catch (Exception ex) { Log.Warning($"[RimLink] Enqueue cmd failed: {ex.Message}"); }
            }
            RimLinkMod.CommandQueue.FlushAll();

            // 1. Периодическая полная синхронизация
            if (_syncTicks >= SyncIntervalTicks)
            {
                _syncTicks = 0;
                try
                {
                    if (Current.Game?.CurrentMap != null)
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
                    System.Threading.Tasks.Task.Run(() =>
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
            UnityEngine.Application.quitting -= OnApplicationQuitting;
            if (_gameLoaded && !_offlineSent)
                SendOfflineNotification();
        }

        private void SendOfflineNotification()
        {
            if (_offlineSent) return;
            _offlineSent = true;
            _gameLoaded  = false;
            Log.Message("[RimLink] Игра закрывается — отправляем offline");
            try { RimLinkMod.API?.SendOffline(); }
            catch (Exception ex) { Log.Warning($"[RimLink] Offline notification failed: {ex.Message}"); }
        }

        public override void ExposeData()
        {
            base.ExposeData();
        }
    }
}
