using System.Collections.Generic;
using System.Linq;
using RimWorld;
using Verse;

namespace RimLink
{
    /// <summary>
    /// Хранит переопределённые цены для каждого предмета/ивента.
    /// Сериализуется через Scribe в Mod_RimLink.xml автоматически.
    /// Ключ = defName (или "defName:degree" для черт).
    /// </summary>
    public class PriceSettings : ModSettings
    {
        // defName → цена в очках (0 = использовать дефолт)
        public Dictionary<string, int> Overrides = new Dictionary<string, int>();

        // Глобальные множители по категориям
        public float MultiplierApparel     = 1.0f;
        public float MultiplierWeapon      = 1.0f;
        public float MultiplierImplant     = 1.0f;
        public float MultiplierNeurotrainer= 1.0f;
        public float MultiplierTrait       = 1.0f;
        public float MultiplierIncident    = 1.0f;
        public float MultiplierGene        = 1.0f;
        public float MultiplierXenotype    = 1.0f;

        // Настройки подключения (сохраняются между сессиями)
        public string ServerUrl    = RimLinkConstants.DefaultServerUrl;
        public int    SyncInterval = RimLinkConstants.DefaultSyncInterval;

        // Базовые цены прогрессии (1-я покупка = Base, 2-я = Base*2, и т.д.)
        public int ProgressiveBaseTrait = 1000;  // 1000 → 2000 → 3000...
        public int ProgressiveBaseGene  = 1000;  // 1000 → 2000 → 3000...

        // Enabled/disabled для каждого предмета (false = не показывать в магазине)
        public Dictionary<string, bool> Enabled = new Dictionary<string, bool>();

        /// <summary>
        /// Импланты, помеченные как парные (hediffDefName → true).
        /// Для парных имплантов команда install_implant ТРЕБУЕТ partHint ("left"/"right").
        /// По умолчанию авто-определение по количеству частей тела в рецепте.
        /// Пустой словарь = всё на авто; явный false = принудительно одиночный.
        /// </summary>
        public Dictionary<string, bool> PairedImplants = new Dictionary<string, bool>();

        public override void ExposeData()
        {
            Scribe_Collections.Look(ref Overrides,      "priceOverrides",  LookMode.Value, LookMode.Value);
            Scribe_Collections.Look(ref Enabled,        "itemEnabled",     LookMode.Value, LookMode.Value);
            Scribe_Collections.Look(ref PairedImplants, "pairedImplants",  LookMode.Value, LookMode.Value);

            Scribe_Values.Look(ref MultiplierApparel,      "multApparel",      1.0f);
            Scribe_Values.Look(ref MultiplierWeapon,       "multWeapon",       1.0f);
            Scribe_Values.Look(ref MultiplierImplant,      "multImplant",      1.0f);
            Scribe_Values.Look(ref MultiplierNeurotrainer, "multNeurotrainer", 1.0f);
            Scribe_Values.Look(ref MultiplierTrait,        "multTrait",        1.0f);
            Scribe_Values.Look(ref MultiplierIncident,     "multIncident",     1.0f);
            Scribe_Values.Look(ref MultiplierGene,         "multGene",         1.0f);
            Scribe_Values.Look(ref MultiplierXenotype,     "multXenotype",     1.0f);

            Scribe_Values.Look(ref ProgressiveBaseTrait, "progressiveBaseTrait", 1000);
            Scribe_Values.Look(ref ProgressiveBaseGene,  "progressiveBaseGene",  1000);

            Scribe_Values.Look(ref ServerUrl,    "serverUrl",    RimLinkConstants.DefaultServerUrl);
            Scribe_Values.Look(ref SyncInterval, "syncInterval", RimLinkConstants.DefaultSyncInterval);

            if (Overrides      == null) Overrides      = new Dictionary<string, int>();
            if (Enabled        == null) Enabled        = new Dictionary<string, bool>();
            if (PairedImplants == null) PairedImplants = new Dictionary<string, bool>();
        }

        /// <summary>Получить финальную цену с учётом переопределения и множителя.</summary>
        public int GetPrice(string defName, string category, int defaultPrice)
        {
            if (Overrides.TryGetValue(defName, out int custom) && custom > 0)
                return custom;
            float mult = GetMultiplier(category);
            return System.Math.Max(1, (int)(defaultPrice * mult));
        }

        /// <summary>
        /// Рассчитать прогрессивную цену.
        /// count — сколько уже куплено ранее (0 = первая покупка).
        /// Результат: Base * (count + 1), т.е. 1-я = Base, 2-я = Base*2, ...
        /// </summary>
        public int CalcProgressivePrice(string category, int count)
        {
            int basePrice = category == "gene" ? ProgressiveBaseGene : ProgressiveBaseTrait;
            return System.Math.Max(1, basePrice * (count + 1));
        }

        /// <summary>Предмет включён в магазин?</summary>
        public bool IsEnabled(string defName)
        {
            if (Enabled.TryGetValue(defName, out bool val)) return val;
            return true;
        }

        public void SetPrice(string defName, int price)
        {
            if (price <= 0) Overrides.Remove(defName);
            else            Overrides[defName] = price;
        }

        public void SetEnabled(string defName, bool enabled)
        {
            if (enabled) Enabled.Remove(defName);
            else         Enabled[defName] = false;
        }

        /// <summary>
        /// Является ли имплант парным по настройкам.
        /// Если явно задан — возвращает это значение.
        /// Иначе — авто: парный если рецепт ставится на 2+ одинаковых части тела.
        /// </summary>
        public bool IsPaired(string hediffDefName)
        {
            if (PairedImplants.TryGetValue(hediffDefName, out bool val))
                return val;
            return IsAutoDetectedPaired(hediffDefName);
        }

        public void SetPaired(string hediffDefName, bool paired)
        {
            // Если совпадает с авто — убираем из словаря (не храним лишнее)
            if (paired == IsAutoDetectedPaired(hediffDefName))
                PairedImplants.Remove(hediffDefName);
            else
                PairedImplants[hediffDefName] = paired;
        }

        private static bool IsAutoDetectedPaired(string hediffDefName)
        {
            try
            {
                var hediffDef = DefDatabase<HediffDef>.GetNamed(hediffDefName, false);
                if (hediffDef == null) return false;

                var recipe = DefDatabase<RecipeDef>.AllDefs
                    .FirstOrDefault(r => r.addsHediff == hediffDef
                                      && r.appliedOnFixedBodyParts != null
                                      && r.appliedOnFixedBodyParts.Count > 0);
                if (recipe == null) return false;

                // Считаем сколько таких частей тела есть в стандартном теле гуманоида
                var humanDef = DefDatabase<ThingDef>.GetNamed("Human", errorOnFail: false);
                var bodyDef = humanDef?.race?.body;
                if (bodyDef == null) return false;

                var partDef = recipe.appliedOnFixedBodyParts[0];
                int count = bodyDef.AllParts.Count(p => p.def == partDef);
                return count >= 2;
            }
            catch { return false; }
        }

        private float GetMultiplier(string category)
        {
            switch (category)
            {
                case "apparel":      return MultiplierApparel;
                case "weapon":       return MultiplierWeapon;
                case "implant":      return MultiplierImplant;
                case "neurotrainer": return MultiplierNeurotrainer;
                case "trait":        return MultiplierTrait;
                case "incident":     return MultiplierIncident;
                case "gene":         return MultiplierGene;
                case "xenotype":     return MultiplierXenotype;
                default:             return 1.0f;
            }
        }
    }
}
