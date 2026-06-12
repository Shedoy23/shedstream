using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using UnityEngine;
using RimWorld;
using Verse;
using RimLink.API;
using RimLink.Managers;

namespace RimLink
{
    public class RimLinkMod : Mod, IDisposable
    {
        public static RimLinkMod    Instance     { get; private set; }
        public static RimLinkAPI    API          { get; private set; }
        public static PawnManager   PawnManager  { get; private set; }
        public static ShopManager   ShopManager  { get; private set; }
        public static EventManager  EventManager { get; private set; }
        public static CommandQueue  CommandQueue { get; private set; }
        public static PriceSettings Prices       { get; private set; }

        public static readonly ConcurrentQueue<Dictionary<string, object>> PendingCommands
            = new ConcurrentQueue<Dictionary<string, object>>();

        // Делегируем в Prices — настройки теперь сохраняются между запусками
        public string ServerUrl
        {
            get => Prices?.ServerUrl ?? RimLinkConstants.DefaultServerUrl;
            set { if (Prices != null) Prices.ServerUrl = value; }
        }
        public int SyncInterval
        {
            get => Prices?.SyncInterval ?? 30;
            set { if (Prices != null) Prices.SyncInterval = value; }
        }
        public string ModuleToken
        {
            get => Prices?.ModuleToken ?? "";
            set { if (Prices != null) Prices.ModuleToken = value; }
        }

        private volatile bool _running = true;
        private Thread _syncThread;
        private volatile int _consecutiveErrors = 0;

        // UI state
        private Vector2 _priceScrollPos = Vector2.zero;
        private string  _priceSearch    = "";
        private string  _activeTab      = "main";
        private string  _filterCat      = "all";
        private volatile string  _uploadStatus   = "";
        private volatile bool _uploadBusy     = false;
        private List<CatalogEntry> _catalogCache = null;

        private static readonly string[] FilterCategories = { "all","apparel","weapon","implant","neurotrainer","trait","incident","gene","xenotype" };
        private static readonly string[] FilterLabels = { "Все","Одежда","Оружие","Импланты","Навыки","Черты","Ивенты","Гены","Ксенотипы" };

        private const float PriceRowHeight = 26f;
        private const float PriceCheckboxWidth = 26f;
        private const float PriceCategoryWidth = 90f;
        private const float PriceNameWidth = 220f;
        private const float PriceDefWidth = 70f;
        private const float PriceInputWidth = 90f;
        private const float PricePairedWidth = 80f;

        public RimLinkMod(ModContentPack content) : base(content)
        {
            Instance     = this;
            Prices       = GetSettings<PriceSettings>();
            API          = new RimLinkAPI(this);
            PawnManager  = new PawnManager();
            ShopManager  = new ShopManager();
            EventManager = new EventManager();
            CommandQueue = new CommandQueue();

            Log.Message("[RimLink] Инициализация мода...");
            Log.Message($"[RimLink] Сервер: {ServerUrl}");

            _syncThread = new Thread(SyncLoop) { Name = "RimLink-Sync", IsBackground = true };
            _syncThread.Start();

            // Подписка на закрытие игры
            Application.quitting += Stop;
        }

        private const int COMMAND_POLL_INTERVAL_MS = RimLinkConstants.CommandPollIntervalMs;
        private const int MAX_BACKOFF_MS           = RimLinkConstants.MaxBackoffMs;

        private void SyncLoop()
        {
            while (_running)
            {
                try
                {
                    // Exponential backoff: 5s → 10s → 20s → 40s → 60s (max) при ошибках
                    int waitMs = _consecutiveErrors == 0
                        ? COMMAND_POLL_INTERVAL_MS
                        : Math.Min(COMMAND_POLL_INTERVAL_MS * (1 << Math.Min(_consecutiveErrors - 1, 4)), MAX_BACKOFF_MS);

                    Thread.Sleep(waitMs);
                    if (!_running) break;
                    if (Current.Game == null) continue;

                    var commands = API.GetCommands();
                    if (commands == null)
                    {
                        // null = сетевая ошибка
                        _consecutiveErrors++;
                        if (_consecutiveErrors == 1 || _consecutiveErrors % 5 == 0)
                            Log.Warning($"[RimLink] Сервер недоступен (попытка #{_consecutiveErrors}), следующий опрос через {Math.Min(COMMAND_POLL_INTERVAL_MS * (1 << Math.Min(_consecutiveErrors, 4)), MAX_BACKOFF_MS) / 1000}с");
                        continue;
                    }

                    if (_consecutiveErrors > 0)
                    {
                        Log.Message("[RimLink] Соединение восстановлено");
                        _consecutiveErrors = 0;
                    }

                    if (commands.Count > 0)
                    {
                        Log.Message($"[RimLink] Получено команд: {commands.Count}");
                        foreach (var cmd in commands)
                            PendingCommands.Enqueue(cmd);
                    }
                }
                catch (ThreadInterruptedException) { break; }
                catch (Exception ex) { Log.Error($"[RimLink] SyncLoop: {ex.Message}"); }
            }
        }

        // ── Settings UI ────────────────────────────────────────────────────────
        public override void DoSettingsWindowContents(Rect inRect)
        {
            var tabRow = new Rect(inRect.x, inRect.y, inRect.width, 30f);
            float hw = inRect.width / 2f;
            
            if (Widgets.ButtonText(new Rect(tabRow.x,      tabRow.y, hw - 2f, 30f), "⚙️ Основные", true, true, true))
                _activeTab = "main";
            if (Widgets.ButtonText(new Rect(tabRow.x + hw, tabRow.y, hw - 2f, 30f), "💎 Цены магазина", true, true, true))
            {
                _activeTab    = "prices";
                _catalogCache = null;
            }

            var body = new Rect(inRect.x, inRect.y + 34f, inRect.width, inRect.height - 34f);
            if (_activeTab == "main") DrawMainTab(body);
            else                      DrawPricesTab(body);
        }

        // ── Вкладка: Основные ─────────────────────────────────────────────────
        private void DrawMainTab(Rect rect)
        {
            var ls = new Listing_Standard();
            ls.Begin(rect);

            ls.Label("URL сервера:");
            ServerUrl = ls.TextEntry(ServerUrl);
            ls.Gap();
            ls.Label("Module-токен (вставь из дашборда — авторизация мода):");
            ModuleToken = ls.TextEntry(ModuleToken);
            ls.Gap();
            ls.Label($"Интервал синхронизации: {SyncInterval} сек");
            SyncInterval = (int)ls.Slider(SyncInterval, 30, 300);
            ls.GapLine();
            ls.Label("Множители цен:");
            ls.Gap(4f);
            SliderRow(ls, "👕 Одежда",       ref Prices.MultiplierApparel);
            SliderRow(ls, "⚔️ Оружие",        ref Prices.MultiplierWeapon);
            SliderRow(ls, "🦾 Импланты",      ref Prices.MultiplierImplant);
            SliderRow(ls, "🧠 Нейротренеры",  ref Prices.MultiplierNeurotrainer);
            SliderRow(ls, "🧬 Черты",         ref Prices.MultiplierTrait);
            SliderRow(ls, "🎲 Ивенты",        ref Prices.MultiplierIncident);
            SliderRow(ls, "🧬 Гены",          ref Prices.MultiplierGene);
            SliderRow(ls, "🧬 Ксенотипы",      ref Prices.MultiplierXenotype);
            ls.GapLine();

            if (!string.IsNullOrEmpty(_uploadStatus))
            { ls.Label(_uploadStatus); ls.Gap(4f); }

            if (!_uploadBusy)
            { if (ls.ButtonText("📤 Выгрузить каталог на сервер")) UploadCatalog(); }
            else
            { ls.Label("⏳ Загрузка..."); }

            ls.End();
        }

        private void SliderRow(Listing_Standard ls, string label, ref float val)
        {
            var r = ls.GetRect(26f);
            Widgets.Label(new Rect(r.x, r.y, 150f, r.height), label);
            val = Widgets.HorizontalSlider(new Rect(r.x + 155f, r.y + 4f, r.width - 230f, r.height - 4f), val, 0.1f, 5.0f);
            Widgets.Label(new Rect(r.x + r.width - 70f, r.y, 70f, r.height), $"×{val:F2}");
        }

        // ── Вкладка: Редактор цен ─────────────────────────────────────────────
        private void DrawPricesTab(Rect rect)
        {
            DrawPriceControls(new Rect(rect.x, rect.y, rect.width, 56f));
            DrawPriceList(new Rect(rect.x, rect.y + 60f, rect.width, rect.height - 60f));
        }

        private void DrawPriceControls(Rect r)
        {
            _priceSearch = Widgets.TextField(new Rect(r.x, r.y, 200f, 26f), _priceSearch);

            if (!_uploadBusy)
            { if (Widgets.ButtonText(new Rect(r.x + 210f, r.y, 150f, 26f), "📤 Выгрузить", true, true, true)) UploadCatalog(); }
            else { Widgets.Label(new Rect(r.x + 210f, r.y, 150f, 26f), "⏳ Занято..."); }

            if (Widgets.ButtonText(new Rect(r.x + 370f, r.y, 130f, 26f), "🔄 Сбросить", true, true, true))
            {
                Prices.Overrides.Clear(); 
                WriteSettings();
                _uploadStatus = "✅ Цены сброшены";
            }
            
            if (!string.IsNullOrEmpty(_uploadStatus))
                Widgets.Label(new Rect(r.x + 510f, r.y, r.width - 510f, 26f), _uploadStatus);

            float bw = r.width / FilterCategories.Length;
            for (int i = 0; i < FilterCategories.Length; i++)
            {
                var br = new Rect(r.x + i * bw, r.y + 30f, bw - 2f, 24f);
                if (_filterCat == FilterCategories[i]) GUI.color = new Color(0.6f, 0.4f, 1f);
                if (Widgets.ButtonText(br, FilterLabels[i], true, true, true))
                { _filterCat = FilterCategories[i]; _catalogCache = null; }
                GUI.color = Color.white;
            }
        }

        private void DrawPriceList(Rect rect)
        {
            try
            {
                if (_catalogCache == null) _catalogCache = BuildCatalogEntries();

                IEnumerable<CatalogEntry> list = _catalogCache;
                if (_filterCat != "all")
                    list = list.Where(e => e.Category == _filterCat);
                
                if (!string.IsNullOrEmpty(_priceSearch))
                {
                    string q = _priceSearch;
                    list = list.Where(e => 
                        (e.Label != null && e.Label.IndexOf(q, StringComparison.OrdinalIgnoreCase) >= 0) ||
                        (e.DefName != null && e.DefName.IndexOf(q, StringComparison.OrdinalIgnoreCase) >= 0)
                    );
                }

                var finalList = list.ToList();
                bool showPaired = (_filterCat == "implant" || _filterCat == "all");

                var hdr = new Rect(rect.x, rect.y, rect.width, PriceRowHeight);
                GUI.color = new Color(0.18f, 0.18f, 0.18f);
                GUI.DrawTexture(hdr, BaseContent.WhiteTex);
                GUI.color = Color.white;
                float hx = hdr.x + 4f;
                Widgets.Label(new Rect(hx + PriceCheckboxWidth, hdr.y, PriceCategoryWidth, PriceRowHeight), "Категория");
                Widgets.Label(new Rect(hx + PriceCheckboxWidth + PriceCategoryWidth, hdr.y, PriceNameWidth, PriceRowHeight), "Название");
                Widgets.Label(new Rect(hx + PriceCheckboxWidth + PriceCategoryWidth + PriceNameWidth, hdr.y, PriceDefWidth, PriceRowHeight), "Дефолт");
                Widgets.Label(new Rect(hx + PriceCheckboxWidth + PriceCategoryWidth + PriceNameWidth + PriceDefWidth, hdr.y, PriceInputWidth, PriceRowHeight), "Цена");
                if (showPaired)
                    Widgets.Label(new Rect(hx + PriceCheckboxWidth + PriceCategoryWidth + PriceNameWidth + PriceDefWidth + PriceInputWidth, hdr.y, PricePairedWidth, PriceRowHeight), "Парный");

                var scroll = new Rect(rect.x, rect.y + PriceRowHeight, rect.width, rect.height - PriceRowHeight);
                var view   = new Rect(0, 0, rect.width - 16f, finalList.Count * PriceRowHeight);
                Widgets.BeginScrollView(scroll, ref _priceScrollPos, view);

                for (int i = 0; i < finalList.Count; i++)
                {
                    var e   = finalList[i];
                    var row = new Rect(0, i * PriceRowHeight, view.width, PriceRowHeight);

                    if (i % 2 == 0) { GUI.color = new Color(0.14f, 0.14f, 0.14f); GUI.DrawTexture(row, BaseContent.WhiteTex); GUI.color = Color.white; }

                    float rx = row.x + 4f;
                    float ry = row.y + 2f;

                    bool en = Prices.IsEnabled(e.DefName), en2 = en;
                    Widgets.Checkbox(new Vector2(rx, ry), ref en2, 20f);
                    if (en2 != en) { Prices.SetEnabled(e.DefName, en2); WriteSettings(); }

                    GUI.color = CatColor(e.Category);
                    Widgets.Label(new Rect(rx + PriceCheckboxWidth, ry, PriceCategoryWidth, PriceRowHeight - 2f), CatLabel(e.Category));
                    GUI.color = Color.white;

                    if (!en) GUI.color = Color.gray;
                    Widgets.Label(new Rect(rx + PriceCheckboxWidth + PriceCategoryWidth, ry, PriceNameWidth, PriceRowHeight - 2f), e.Label);
                    GUI.color = Color.white;

                    Widgets.Label(new Rect(rx + PriceCheckboxWidth + PriceCategoryWidth + PriceNameWidth, ry, PriceDefWidth, PriceRowHeight - 2f), e.DefaultPrice + "💎");

                    string cur = Prices.Overrides.TryGetValue(e.DefName, out int ov) ? ov.ToString() : "";
                    string nw  = Widgets.TextField(new Rect(rx + PriceCheckboxWidth + PriceCategoryWidth + PriceNameWidth + PriceDefWidth, ry, PriceInputWidth - 8f, PriceRowHeight - 4f), cur);
                    if (nw != cur)
                    {
                        if (string.IsNullOrWhiteSpace(nw)) Prices.Overrides.Remove(e.DefName);
                        else if (int.TryParse(nw, out int p) && p > 0) Prices.Overrides[e.DefName] = p;
                        WriteSettings();
                    }

                    if (showPaired && e.Category == "implant")
                    {
                        bool paired  = Prices.IsPaired(e.DefName);
                        bool paired2 = paired;
                        Widgets.Checkbox(new Vector2(rx + PriceCheckboxWidth + PriceCategoryWidth + PriceNameWidth + PriceDefWidth + PriceInputWidth, ry), ref paired2, 20f);
                        if (paired2 != paired) { Prices.SetPaired(e.DefName, paired2); WriteSettings(); }
                    }
                }
                Widgets.EndScrollView();
                if (finalList.Count == 0)
                    Widgets.Label(new Rect(scroll.x + 10f, scroll.y + 10f, scroll.width, 30f), "Ничего не найдено");
            }
            catch (Exception ex)
            {
                Log.Error($"[RimLink] DrawPriceList: {ex}");
            }
        }

        // ── Кэш каталога ──────────────────────────────────────────────────────
        private List<CatalogEntry> BuildCatalogEntries()
        {
            var result = new List<CatalogEntry>();
            try
            {
                var rawCatalog = ShopManager.BuildCatalogWithPrices(Prices);
                foreach (var item in rawCatalog)
                {
                    if (!(item is Dictionary<string, object> d)) continue;
                    string def  = d["def_name"]?.ToString() ?? "";
                    string lbl  = d["label"]?.ToString()    ?? def;
                    string cat  = d["category"]?.ToString() ?? "misc";
                    int    pr   = d["price"] is int iP ? iP : (d["price"] != null ? Convert.ToInt32(d["price"]) : 0);
                    if (!string.IsNullOrEmpty(def))
                        result.Add(new CatalogEntry { DefName = def, Label = lbl, Category = cat, DefaultPrice = pr });
                }
            }
            catch (Exception e) { Log.Warning($"[RimLink] BuildCatalogEntries: {e.Message}"); }
            return result.OrderBy(e => e.Category).ThenBy(e => e.Label).ToList();
        }

        // ── Выгрузка ──────────────────────────────────────────────────────────
        private void UploadCatalog()
        {
            if (_uploadBusy) return;
            _uploadBusy = true;
            _uploadStatus = "⏳ Подготовка каталога...";

            // Строим каталог в главном потоке (читает DefDatabase и игровые объекты)
            List<object> catalog = null;
            try
            {
                catalog = ShopManager.BuildCatalogWithPrices(Prices);
            }
            catch (Exception e)
            {
                _uploadStatus = $"❌ Ошибка построения: {e.Message}";
                Log.Warning($"[RimLink] UploadCatalog Build: {e.Message}");
                _uploadBusy = false;
                return;
            }

            _uploadStatus = $"⏳ Отправка {catalog.Count} предметов...";

            // Отправляем в фоновом потоке
            new Thread(() =>
            {
                try
                {
                    RimLinkMod.API.SyncShopCatalog(catalog);
                    _uploadStatus = $"✅ Выгружено {catalog.Count} предметов!";
                    Log.Message($"[RimLink] Каталог выгружен: {catalog.Count} шт.");
                }
                catch (Exception e)
                {
                    _uploadStatus = $"❌ Ошибка: {e.Message}";
                    Log.Warning($"[RimLink] UploadCatalog: {e.Message}");
                }
                finally { _uploadBusy = false; }
            }) { IsBackground = true, Name = "RimLink-Upload" }.Start();
        }

        private Color CatColor(string c)
        {
            switch (c)
            {
                case "apparel": return new Color(0.4f,0.8f,1.0f);
                case "weapon": return new Color(1.0f,0.5f,0.4f);
                case "implant": return new Color(0.4f,1.0f,0.6f);
                case "neurotrainer": return new Color(1.0f,0.8f,0.3f);
                case "trait": return new Color(0.8f,0.5f,1.0f);
                case "incident": return new Color(1.0f,0.6f,0.2f);
                case "gene": return new Color(0.5f,1.0f,0.9f);
                case "xenotype": return new Color(1.0f,0.85f,0.5f);
                default: return Color.white;
            }
        }

        private string CatLabel(string c)
        {
            switch (c)
            {
                case "apparel": return "👕 Одежда";
                case "weapon": return "⚔️ Оружие";
                case "implant": return "🦾 Имплант";
                case "neurotrainer": return "🧠 Навык";
                case "trait": return "🧬 Черта";
                case "incident": return "🎲 Ивент";
                case "gene": return "🧫 Ген";
                case "xenotype": return "🧬 Ксенотип";
                default: return c;
            }
        }

        public override string SettingsCategory() => "RimLink — Twitch Integration";

        public override void WriteSettings()
        {
            base.WriteSettings();
            API.UpdateServerUrl(ServerUrl);
            _catalogCache = null;

            if (Current.Game != null)
            {
                // Отправляем каталог событий в фоновом потоке
                new System.Threading.Thread(() =>
                {
                    try
                    {
                        var evts = EventManager.BuildEventCatalog(Prices);
                        API?.SyncEventCatalog(evts);
                    }
                    catch (Exception e)
                    {
                        Log.Error($"[RimLink] WriteSettings SyncError: {e}");
                        if (!string.IsNullOrEmpty(e.Message))
                            _uploadStatus = $"❌ Ошибка синхронизации событий: {e.Message}";
                    }
                }) { IsBackground = true }.Start();
            }
        }

        // ✅ ИСПРАВЛЕННЫЙ МЕТОД
        public void Stop()
        {
            // Отписка безопасна даже без проверки на null.
            // В C# нельзя читать события извне, только += и -=
            Application.quitting -= Stop;
            
            _running = false;
            if (_syncThread != null && _syncThread.IsAlive)
            {
                _syncThread.Interrupt();
                _syncThread.Join(1000);
            }
            Log.Message("[RimLink] Фоновый поток остановлен");
        }

        public void Dispose()
        {
            Stop();
        }
    }

    public class CatalogEntry
    {
        public string DefName;
        public string Label;
        public string Category;
        public int    DefaultPrice;
    }
}