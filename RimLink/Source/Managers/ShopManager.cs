using System;
using System.Collections.Generic;
using System.Linq;
using RimWorld;
using Verse;
using RimLink.Utils;

namespace RimLink.Managers
{
    /// <summary>
    /// Формирует и отправляет на сервер каталог всех доступных предметов:
    /// одежда, оружие, импланты (через их ThingDef/RecipeDef), нейротренеры.
    ///
    /// Цена в очках = BaseMarketValue × коэффициент из конфига.
    /// Каталог пересчитывается при каждой синхронизации чтобы учитывать смену модов.
    /// </summary>
    public class ShopManager
    {
        // Коэффициент перевода Silver → очки зрителя
        public float PriceMultiplier = 1.5f;

        // Минимальная и максимальная цена в очках
        public int MinPrice = 50;
        public int MaxPrice = 1000000;

        // Блэклист проблемных предметов — используется для одежды и оружия
        private static readonly HashSet<string> BlacklistedPrefixes = new HashSet<string>
        {
            "GoldenCube", "MysteriousCargo", "VoidMonolith", "Shard",
            "WarpedObelisk", "Obelisk", "FleshMass", "Revenant"
        };

        // ── Построение каталога ────────────────────────────────────────────────

        public List<object> BuildCatalogRaw()
        {
            var result = new List<object>();

            // 1. Одежда
            foreach (var def in DefDatabase<ThingDef>.AllDefs)
            {
                if (!def.IsApparel) continue;
                if (def.BaseMarketValue <= 0) continue;
                // — нет apparel-компонента (формально IsApparel=true, но носить нельзя)
                if (def.apparel == null) continue;
                if (def.IsCorpse) continue;
                // — Это здание/структура, а не предмет (Anomaly DLC)
                if (def.building != null) continue;
                if (typeof(Building).IsAssignableFrom(def.thingClass)) continue;
                // defName-блэклист известных проблемных предметов
                if (IsBlacklisted(def.defName)) continue;
                // — слишком дорогой для игрового предмета = явно квестовый
                if (def.BaseMarketValue > 50000) continue;
                // — Нет рецепта крафта: предмет нельзя сделать = механоидное/NPC снаряжение
                if (def.recipeMaker == null) continue;
                // — Предмет ещё не изучен — не показываем в магазине
                if (!IsThingResearched(def)) continue;

                try
                {
                    result.Add(MakeItem(
                        category:     "apparel",
                        defName:      def.defName,
                        label:        PawnUtils.StripTags(def.label),
                        desc:         PawnUtils.StripTags(def.description ?? ""),
                        price:        def.BaseMarketValue,
                        techLevel:    def.techLevel.ToString(),
                        displayLabel: ApparelDisplayLabel(def),
                        tooltip:      TooltipApparel(def),
                        extra:        new Dictionary<string, object>
                        {
                            { "layers",              def.apparel?.layers?.Select(l => l.defName).ToList() ?? new List<string>() },
                            { "body_parts",          def.apparel?.bodyPartGroups?.Select(g => g.defName).ToList() ?? new List<string>() },
                            { "research_unlocked", true }, // прошёл фильтр по эпохе
                        }
                    ));
                }
                catch (Exception ex) { RimLinkLog.Warn($"[RimLink] Catalog apparel skip '{def?.defName}': {ex.Message}"); }
            }

            // 2. Оружие (ближнее и дальнобойное)
            foreach (var def in DefDatabase<ThingDef>.AllDefs)
            {
                if (!def.IsWeapon) continue;
                if (def.BaseMarketValue <= 0) continue;
                // Исключаем квестовые/аномальные предметы без нормального equipmentType
                if (def.equipmentType == EquipmentType.None) continue;
                // — Это здание/структура, а не предмет (Anomaly DLC)
                if (def.building != null) continue;
                if (typeof(Building).IsAssignableFrom(def.thingClass)) continue;
                // — У оружия должен быть verbs (дальнобойное) ИЛИ tools (ближнее).
                // Ближнее оружие описывается через Tools, Verbs у него пустой — не отсекаем.
                bool hasVerbs = def.Verbs != null && def.Verbs.Count > 0;
                bool hasTools = def.tools != null && def.tools.Count > 0;
                if (!hasVerbs && !hasTools) continue;
                // defName-блэклист известных проблемных предметов Anomaly
                if (IsBlacklisted(def.defName)) continue;
                if (def.BaseMarketValue > 50000) continue;
                // — Нет рецепта крафта: предмет нельзя сделать = механоидное/NPC оружие
                // Исключение: BladeLink-оружие (Royalty) — у него нет recipeMaker,
                // но есть CompProperties_Bladelink (или CompBladelinkBonded в 1.6).
                // Проверяем через имя класса компа чтобы не зависеть от Royalty DLC напрямую.
                bool isBladelink = def.comps != null && def.comps.Any(c =>
                    c.compClass != null && (
                        c.compClass.Name == "CompBladelinkBonded" ||
                        c.compClass.Name == "CompBladelink" ||
                        c.compClass.FullName?.Contains("Bladelink") == true));
                if (def.recipeMaker == null && !isBladelink) continue;
                // — Оружие ещё не изучено — не показываем в магазине
                if (!IsThingResearched(def)) continue;

                string wType = def.IsRangedWeapon ? "ranged" : "melee";

                try
                {
                    result.Add(MakeItem(
                        category:     "weapon",
                        defName:      def.defName,
                        label:        PawnUtils.StripTags(def.label),
                        desc:         PawnUtils.StripTags(def.description ?? ""),
                        price:        def.BaseMarketValue,
                        techLevel:    def.techLevel.ToString(),
                        displayLabel: WeaponDisplayLabel(def),
                        tooltip:      TooltipWeapon(def),
                        extra:        new Dictionary<string, object>
                        {
                            { "weapon_type",       wType },
                            { "damage",            def.tools?.FirstOrDefault()?.power ?? 0 },
                            { "research_unlocked", true }, // прошёл фильтр по эпохе
                        }
                    ));
                }
                catch (Exception ex) { RimLinkLog.Warn($"[RimLink] Catalog weapon skip '{def?.defName}': {ex.Message}"); }
            }

            // 3. Импланты — ищем рецепты хирургии (RecipeDef) которые устанавливают импланты
            foreach (var recipe in DefDatabase<RecipeDef>.AllDefs)
            {
                if (recipe.addsHediff == null) continue;
                if (!recipe.IsSurgery) continue;
                // IsAssignableFrom проверяет всю иерархию наследования —
                // импланты из модов часто наследуют Hediff_Implant косвенно
                // (напр. Hediff_AddedPart_Psychic из VPE), Name == "Hediff_Implant" их пропускал
                if (recipe.addsHediff.addedPartProps == null &&
                    (recipe.addsHediff.hediffClass == null ||
                     !typeof(Hediff_Implant).IsAssignableFrom(recipe.addsHediff.hediffClass))) continue;
                // — Имплант ещё не изучен — не показываем в магазине
                if (!IsRecipeResearched(recipe)) continue;

                // Приоритет 1: вещь которая выпадает при удалении импланта (самая точная цена)
                float price = 0f;
                var spawnThing = recipe.addsHediff?.spawnThingOnRemoved;
                if (spawnThing != null && spawnThing.BaseMarketValue > 0)
                    price = spawnThing.BaseMarketValue;

                // Приоритет 2: сумма всех ингредиентов × их количество
                if (price <= 0f && recipe.ingredients != null)
                {
                    foreach (var ing in recipe.ingredients)
                    {
                        var ingDef = ing?.filter?.AnyAllowedDef;
                        if (ingDef == null) continue;
                        price += ingDef.BaseMarketValue * ing.GetBaseCount();
                    }
                }

                // Fallback
                if (price <= 0f) price = 500f;

                try
                {
                    result.Add(MakeItem(
                        category:     "implant",
                        defName:      recipe.addsHediff.defName,
                        label:        PawnUtils.StripTags(recipe.label),
                        desc:         PawnUtils.StripTags(recipe.description ?? recipe.addsHediff.description ?? ""),
                        price:        price,
                        techLevel:    "Industrial",
                        displayLabel: ImplantDisplayLabel(recipe),
                        tooltip:      TooltipImplant(recipe),
                        extra:        new Dictionary<string, object>
                        {
                            { "hediff_def",        recipe.addsHediff.defName },
                            { "body_parts",        recipe.appliedOnFixedBodyParts?.Select(p => p.label).ToList() ?? new List<string>() },
                            { "is_paired",         IsPairedImplantRecipe(recipe) },
                            { "research_unlocked", true }, // прошёл фильтр по эпохе
                        }
                    ));
                }
                catch (Exception ex) { RimLinkLog.Warn($"[RimLink] Catalog implant skip '{recipe?.addsHediff?.defName}': {ex.Message}"); }
            }

            // 4. Нейротренеры — ThingDef с comps содержащим CompUseEffect_LearnSkill
            foreach (var def in DefDatabase<ThingDef>.AllDefs)
            {
                if (def.BaseMarketValue <= 0) continue;
                // menuHidden removed in 1.5

                bool isNeurotrainer = def.comps != null &&
                    def.comps.Any(c => c.compClass?.Name == "CompUseEffect_LearnSkill");

                if (!isNeurotrainer) continue;

                string skillName = ExtractNeurotrainerSkill(def);
                // ИСПРАВЛЕНО: убираем оператор ? для TaggedString
                string neuroLabel = PawnUtils.StripTags(def.LabelCap.ToString() ?? def.label ?? def.defName);

                result.Add(MakeItem(
                    category:     "neurotrainer",
                    defName:      def.defName,
                    label:        PawnUtils.StripTags(def.label),
                    desc:         PawnUtils.StripTags(def.description ?? ""),
                    price:        def.BaseMarketValue,
                    techLevel:    def.techLevel.ToString(),
                    displayLabel: $"{neuroLabel} (навык)",
                    tooltip:      TooltipNeurotrainer(def),
                    extra:        new Dictionary<string, object>
                    {
                        { "skill", skillName }
                    }
                ));
            }

            // 5. Черты характера
            foreach (var def in DefDatabase<TraitDef>.AllDefs)
            {
                if (def == null || string.IsNullOrEmpty(def.defName)) continue;

                var degrees = def.degreeDatas;
                if (degrees == null || degrees.Count == 0)
                {
                    string traitLabel = PawnUtils.StripTags(def.label ?? def.defName);
                    result.Add(MakeItem(
                        category:     "trait",
                        defName:      def.defName,
                        label:        traitLabel,
                        desc:         "",
                        price:        1000f,
                        techLevel:    "Human",
                        displayLabel: TraitDisplayLabel(traitLabel, 0),
                        tooltip:      TooltipTrait(def, def.degreeDatas?.FirstOrDefault()),
                        extra: new Dictionary<string, object> { { "trait_def", def.defName }, { "degree", 0 }, { "base_price", 1000 } }
                    ));
                }
                else
                {
                    foreach (var deg in degrees)
                    {
                        if (deg == null) continue;
                        string traitLabel = PawnUtils.StripTags(deg.label ?? def.label ?? def.defName);
                        result.Add(MakeItem(
                            category:     "trait",
                            defName:      $"{def.defName}:{deg.degree}",
                            label:        traitLabel,
                            desc:         deg.description ?? "",
                            price:        1000f,
                            techLevel:    "Human",
                            displayLabel: TraitDisplayLabel(traitLabel, deg.degree),
                            tooltip:      TooltipTrait(def, deg),
                            extra: new Dictionary<string, object> { { "trait_def", def.defName }, { "degree", deg.degree }, { "base_price", 1000 } }
                        ));
                    }
                }
            }

            // Ивенты намеренно убраны отсюда — они строятся и отправляются
            // через EventManager.BuildEventCatalog() → API.SyncEventCatalog().
            // Дублирование приводило к расхождению цен между магазином и реальным каталогом.

            // 6. Гены (Biotech DLC)
            if (ModsConfig.BiotechActive)
            {
                foreach (var def in DefDatabase<GeneDef>.AllDefs)
                {
                    if (def == null || string.IsNullOrEmpty(def.defName)) continue;

                    int geneTier = def.biostatArc > 0 ? 3
                                 : def.biostatMet < -2 ? 2
                                 : def.biostatMet > 0  ? 1
                                 : 0;

                    result.Add(MakeItem(
                        category:     "gene",
                        defName:      def.defName,
                        label:        PawnUtils.StripTags(def.label ?? def.defName),
                        desc:         PawnUtils.StripTags(def.description ?? ""),
                        price:        1000f,
                        techLevel:    "Spacer",
                        displayLabel: GeneDisplayLabel(def),
                        tooltip:      TooltipGene(def),
                        extra: new Dictionary<string, object>
                        {
                            { "biostat_cpx",  def.biostatCpx },
                            { "biostat_met",  def.biostatMet },
                            { "gene_class",   def.displayCategory?.defName ?? "misc" },
                            { "bio_tier",     geneTier },
                            { "base_price",   1000 }
                        }
                    ));
                }
            }

            // 8. Ксенотипы (Biotech DLC) — только базовые (не созданные игроком)
            if (ModsConfig.BiotechActive)
            {
                foreach (var xeno in DefDatabase<XenotypeDef>.AllDefs)
                {
                    if (xeno == null || string.IsNullOrEmpty(xeno.defName)) continue;

                    // Пропускаем кастомные ксенотипы созданные игроком:
                    // у них нет modContentPack (они из сохранения, а не из мода/ваниллы)
                    if (xeno.modContentPack == null) continue;

                    // Пропускаем «пустой» ксенотип и технические
                    if (xeno.defName == "Baseliner") continue;

                    string xenoName  = PawnUtils.StripTags(xeno.LabelCap.ToString() ?? xeno.label ?? xeno.defName);
                    string sourceMod = xeno.modContentPack?.Name ?? "Vanilla";

                    var geneList = xeno.genes?
                        .Select(g => g?.defName ?? "")
                        .Where(g => !string.IsNullOrEmpty(g))
                        .ToList() ?? new List<string>();

                    result.Add(MakeItem(
                        category:     "xenotype",
                        defName:      xeno.defName,
                        label:        PawnUtils.StripTags(xeno.label ?? xeno.defName),
                        desc:         xeno.description ?? "",
                        price:        5000f,
                        techLevel:    "Spacer",
                        displayLabel: $"{xenoName} (ксенотип)",
                        extra: new Dictionary<string, object>
                        {
                            { "genes",       geneList            },
                            { "gene_count",  geneList.Count      },
                            { "source_mod",  sourceMod           },
                            { "has_archite", xeno.genes?.Any(g => g?.biostatArc > 0) ?? false }
                        }
                    ));
                }
            }

            return result;
        }

        /// <summary>
        /// Собирает каталог с учётом пользовательских цен из PriceSettings.
        /// Предметы с IsEnabled=false исключаются.
        /// </summary>
        public List<object> BuildCatalogWithPrices(PriceSettings prices)
        {
            var raw    = BuildCatalogRaw();
            var result = new List<object>();

            foreach (var item in raw)
            {
                if (!(item is Dictionary<string, object> d)) continue;

                string defName  = d.ContainsKey("def_name") ? d["def_name"]?.ToString() : "";
                string category = d.ContainsKey("category") ? d["category"]?.ToString() : "misc";
                int    defPrice = d.ContainsKey("price")    ? Convert.ToInt32(d["price"]) : 0;

                // Пропускаем отключённые предметы
                if (!prices.IsEnabled(defName)) continue;

                // Применяем цену
                int finalPrice = prices.GetPrice(defName, category, defPrice);

                var copy = new Dictionary<string, object>(d);
                copy["price"] = finalPrice;
                result.Add(copy);
            }

            RimLinkLog.Msg($"[RimLink] BuildCatalogWithPrices: {result.Count} предметов (из {raw.Count})");
            return result;
        }

        // ── Helpers ────────────────────────────────────────────────────────────

        /// <summary>
        /// Проверяет, находится ли defName в блэклисте проблемных предметов.
        /// </summary>
        private static bool IsBlacklisted(string defName)
        {
            return BlacklistedPrefixes.Any(prefix => defName.StartsWith(prefix));
        }

        private Dictionary<string, object> MakeItem(
            string category, string defName, string label, string desc,
            float price, string techLevel, Dictionary<string, object> extra,
            string displayLabel = null, string tooltip = null)
        {
            int pointCost = Math.Max(MinPrice, Math.Min(MaxPrice, (int)(price * PriceMultiplier)));

            var d = new Dictionary<string, object>
            {
                { "category",          category               },
                { "def_name",          defName                },
                { "label",             label                  },
                { "display_label",     displayLabel ?? label  },
                { "desc",              desc                   },
                { "price",             pointCost              },
                { "tech_level",        techLevel              },
                { "tooltip",           tooltip ?? desc        },
                { "research_unlocked", true                   }, // переопределяется ниже при необходимости
            };

            if (extra != null)
                foreach (var kv in extra)
                    d[kv.Key] = kv.Value;

            return d;
        }

        // ── display_label helpers ──────────────────────────────────────────────

        private static string ApparelDisplayLabel(ThingDef def)
        {
            // ИСПРАВЛЕНО: убираем оператор ? для TaggedString
            string name = PawnUtils.StripTags(def.LabelCap.ToString() ?? def.label ?? def.defName);
            string slot = ApparelSlotHint(def);
            return string.IsNullOrEmpty(slot) ? name : $"{name} ({slot})";
        }

        private static string ApparelSlotHint(ThingDef def)
        {
            if (def.apparel == null) return "";
            var g = def.apparel.bodyPartGroups;
            if (g == null || g.Count == 0) return "";
            if (g.Any(x => x.defName == "FullHead" || x.defName == "UpperHead")) return "голова";
            if (g.Any(x => x.defName == "Eyes"))   return "глаза";
            if (g.Any(x => x.defName == "Torso"))  return "туловище";
            if (g.Any(x => x.defName == "Legs"))   return "ноги";
            if (g.Any(x => x.defName == "Hands"))  return "руки";
            if (g.Any(x => x.defName == "Feet"))   return "обувь";
            if (g.Any(x => x.defName == "Waist"))  return "пояс";
            if (g.Any(x => x.defName == "Neck"))   return "шея";
            return "тело";
        }

        private static string WeaponDisplayLabel(ThingDef def)
        {
            // ИСПРАВЛЕНО: добавляем исправление и здесь для согласованности
            string name = PawnUtils.StripTags(def.LabelCap.ToString() ?? def.label ?? def.defName);
            string wtype = def.IsRangedWeapon ? "дальнобойное" : "ближнее";
            return $"{name} ({wtype})";
        }

        private static string ImplantDisplayLabel(RecipeDef recipe)
        {
            // ИСПРАВЛЕНО: убираем оператор ? для TaggedString
            string name = PawnUtils.StripTags(recipe.LabelCap.ToString() ?? recipe.label ?? recipe.defName);
            var parts   = recipe.appliedOnFixedBodyParts;
            if (parts != null && parts.Count > 0)
            {
                string partNames = string.Join(", ", parts.Select(p => PawnUtils.StripTags(p.label ?? p.defName)));
                return $"{name} ({partNames})";
            }
            return name;
        }

        private static string TraitDisplayLabel(string label, int degree)
        {
            if (degree == 0) return label;
            return $"{label} ({degree:+#;-#})";
        }

        private static string GeneDisplayLabel(GeneDef def)
        {
            // ИСПРАВЛЕНО: убираем оператор ? для TaggedString
            string name = PawnUtils.StripTags(def.LabelCap.ToString() ?? def.label ?? def.defName);
            string category = PawnUtils.StripTags(def.displayCategory?.label ?? def.displayCategory?.defName ?? "");
            return string.IsNullOrEmpty(category) ? name : $"{name} ({category})";
        }

        // ── Tooltip builders ──────────────────────────────────────────────────

        /// <summary>
        /// Краткий тултип для одежды: слот + ключевые статы защиты/тепла/передвижения.
        /// </summary>
        private static string TooltipApparel(ThingDef def)
        {
            var lines = new System.Text.StringBuilder();
            try
            {
                string slot = ApparelSlotHint(def);
                if (!string.IsNullOrEmpty(slot))
                    lines.AppendLine($"📍 Слот: {slot}");

                // Статы самого предмета
                if (def.statBases != null)
                {
                    foreach (var sm in def.statBases)
                    {
                        if (sm?.stat == null) continue;
                        string n = sm.stat.defName;
                        float  v = sm.value;
                        if (n == "ArmorRating_Sharp"  && v > 0) lines.AppendLine($"🛡 Защита (рез.): {v:P0}");
                        if (n == "ArmorRating_Blunt"  && v > 0) lines.AppendLine($"🛡 Защита (удар): {v:P0}");
                        if (n == "ArmorRating_Heat"   && v > 0) lines.AppendLine($"🔥 Защита (огонь): {v:P0}");
                        if (n == "Insulation_Cold"    && v > 0) lines.AppendLine($"❄️ Тепло: +{v:F1}°C");
                        if (n == "Insulation_Heat"    && v > 0) lines.AppendLine($"☀️ Охлаждение: +{v:F1}°C");
                        if (n == "MoveSpeed"          && v != 0) lines.AppendLine($"🏃 Скорость: {(v > 0 ? "+" : "")}{v:F2}");
                    }
                }
                // Бонусные статы при ношении
                if (def.equippedStatOffsets != null)
                {
                    foreach (var sm in def.equippedStatOffsets)
                    {
                        if (sm?.stat == null || sm.value == 0) continue;
                        string sign = sm.value > 0 ? "+" : "";
                        string lbl  = PawnUtils.StripTags(sm.stat.LabelCap.ToString() ?? sm.stat.label ?? sm.stat.defName);
                        lines.AppendLine($"✦ {lbl}: {sign}{sm.value:G3}");
                    }
                }
                if (def.BaseMarketValue > 0)
                    lines.AppendLine($"💰 Ценность: {def.BaseMarketValue:F0} сер.");
            }
            catch { }
            return lines.ToString().Trim();
        }

        /// <summary>
        /// Краткий тултип для оружия: тип, урон, DPS, дальность.
        /// </summary>
        private static string TooltipWeapon(ThingDef def)
        {
            var lines = new System.Text.StringBuilder();
            try
            {
                bool ranged = def.IsRangedWeapon;
                lines.AppendLine(ranged ? "🎯 Тип: дальнобойное" : "⚔️ Тип: ближнее");

                if (def.tools != null && def.tools.Count > 0)
                {
                    float bestDmg = 0f;
                    foreach (var t in def.tools)
                        if (t != null && t.power > bestDmg) bestDmg = t.power;
                    if (bestDmg > 0) lines.AppendLine($"⚔️ Урон: {bestDmg:F1}");
                }

                if (ranged && def.Verbs != null && def.Verbs.Count > 0)
                {
                    var verb = def.Verbs[0];
                    if (verb != null)
                    {
                        if (verb.range > 0)         lines.AppendLine($"📏 Дальность: {verb.range:F0}");
                        // Урон снаряда и пробитие — API в 1.6 нестабильно,
                        // основной урон уже показан через tools[].power выше
                        if (verb.warmupTime > 0) lines.AppendLine($"⏱ Прицел: {verb.warmupTime:F1}с");
                    }
                }

                if (def.equippedStatOffsets != null)
                {
                    foreach (var sm in def.equippedStatOffsets)
                    {
                        if (sm?.stat == null || sm.value == 0) continue;
                        string sign = sm.value > 0 ? "+" : "";
                        string lbl  = PawnUtils.StripTags(sm.stat.LabelCap.ToString() ?? sm.stat.defName);
                        lines.AppendLine($"✦ {lbl}: {sign}{sm.value:G3}");
                    }
                }
                if (def.BaseMarketValue > 0)
                    lines.AppendLine($"💰 Ценность: {def.BaseMarketValue:F0} сер.");

                // Пси-способности оружия — проверяем через comps по имени класса,
                // чтобы не зависеть от VPE/Royalty DLL напрямую.
                if (def.comps != null)
                {
                    // CompProperties_PsychicWeapon (VPE и ванильный Royalty)
                    var psychicComp = def.comps.FirstOrDefault(c =>
                        c.compClass != null && (
                            c.compClass.Name.Contains("Psychic") ||
                            c.compClass.Name.Contains("Psycast") ||
                            c.compClass.FullName?.Contains("PsychicWeapon") == true));
                    if (psychicComp != null)
                    {
                        lines.AppendLine("🔮 Псионическое оружие");
                        // Пробуем вытащить список способностей через рефлексию
                        try
                        {
                            var abilitiesProp = psychicComp.GetType().GetProperty("abilities")
                                             ?? psychicComp.GetType().GetProperty("Abilities")
                                             ?? psychicComp.GetType().GetField("abilities")?.GetType().GetProperty("Value");
                            var abilitiesField = psychicComp.GetType().GetField("abilities");
                            System.Collections.IEnumerable abilityList = null;
                            if (abilitiesProp != null)
                                abilityList = abilitiesProp.GetValue(psychicComp) as System.Collections.IEnumerable;
                            else if (abilitiesField != null)
                                abilityList = abilitiesField.GetValue(psychicComp) as System.Collections.IEnumerable;

                            if (abilityList != null)
                            {
                                foreach (var ab in abilityList)
                                {
                                    if (ab == null) continue;
                                    // AbilityDef — ищем label/LabelCap
                                    string abLabel = null;
                                    var labelProp = ab.GetType().GetProperty("LabelCap")
                                                 ?? ab.GetType().GetProperty("label");
                                    if (labelProp != null)
                                        abLabel = labelProp.GetValue(ab)?.ToString();
                                    if (string.IsNullOrEmpty(abLabel))
                                    {
                                        var labelField = ab.GetType().GetField("label");
                                        if (labelField != null)
                                            abLabel = labelField.GetValue(ab)?.ToString();
                                    }
                                    if (!string.IsNullOrEmpty(abLabel))
                                        lines.AppendLine($"  ✦ {PawnUtils.StripTags(abLabel)}");
                                }
                            }
                        }
                        catch { }
                    }

                    // Bladelink — уже известный псионический эффект
                    bool isBladelink = def.comps.Any(c =>
                        c.compClass != null && (
                            c.compClass.Name == "CompBladelinkBonded" ||
                            c.compClass.Name == "CompBladelink" ||
                            c.compClass.FullName?.Contains("Bladelink") == true));
                    if (isBladelink)
                        lines.AppendLine("🔗 Bladelink — привязывается к носителю");
                }
            }
            catch { }
            return lines.ToString().Trim();
        }

        /// <summary>
        /// Краткий тултип для импланта: часть тела + ключевые бонусы из HediffStage.
        /// </summary>
        private static string TooltipImplant(RecipeDef recipe)
        {
            var lines = new System.Text.StringBuilder();
            try
            {
                var hediff = recipe.addsHediff;
                if (hediff == null) return "";

                // Часть тела
                if (recipe.appliedOnFixedBodyParts != null && recipe.appliedOnFixedBodyParts.Count > 0)
                {
                    string parts = string.Join(", ", recipe.appliedOnFixedBodyParts
                        .Select(p => PawnUtils.StripTags(p.label ?? p.defName)));
                    lines.AppendLine($"📍 Устанавливается: {parts}");
                }

                // Стадии (бонусы)
                var stage = hediff.stages?.FirstOrDefault();
                if (stage != null)
                {
                    if (stage.statOffsets != null)
                    {
                        foreach (var sm in stage.statOffsets)
                        {
                            if (sm?.stat == null || sm.value == 0) continue;
                            string sign = sm.value > 0 ? "+" : "";
                            string lbl  = PawnUtils.StripTags(sm.stat.LabelCap.ToString() ?? sm.stat.defName);
                            lines.AppendLine($"✦ {lbl}: {sign}{sm.value:G3}");
                        }
                    }
                    if (stage.statFactors != null)
                    {
                        foreach (var sm in stage.statFactors)
                        {
                            if (sm?.stat == null) continue;
                            string lbl = PawnUtils.StripTags(sm.stat.LabelCap.ToString() ?? sm.stat.defName);
                            lines.AppendLine($"✦ {lbl}: ×{sm.value:G3}");
                        }
                    }
                    if (stage.capMods != null)
                    {
                        foreach (var cm in stage.capMods)
                        {
                            if (cm?.capacity == null) continue;
                            string lbl = PawnUtils.StripTags(cm.capacity.LabelCap.ToString() ?? cm.capacity.defName);
                            if (cm.offset != 0)
                            {
                                string sign = cm.offset > 0 ? "+" : "";
                                lines.AppendLine($"✦ {lbl}: {sign}{cm.offset:P0}");
                            }
                            else if (cm.setMax != 0)
                                lines.AppendLine($"✦ {lbl}: макс. {cm.setMax:P0}");
                        }
                    }
                }

                // Описание если нет статов
                if (lines.Length == 0 && !string.IsNullOrEmpty(hediff.description))
                    lines.AppendLine(Truncate(PawnUtils.StripTags(hediff.description), 120));
            }
            catch { }
            return lines.ToString().Trim();
        }

        /// <summary>
        /// Краткий тултип для нейротренера: название навыка + сколько XP даёт.
        /// </summary>
        private static string TooltipNeurotrainer(ThingDef def)
        {
            try
            {
                var comp = def.comps?.OfType<CompProperties_UseEffect>()
                    .FirstOrDefault(c => c.compClass?.Name == "CompUseEffect_LearnSkill");
                string skillName = PawnUtils.StripTags(def.label ?? def.defName);
                return $"🧠 Повышает навык: {skillName}\n+20000 XP (~2-4 уровня)";
            }
            catch { return ""; }
        }

        /// <summary>
        /// Краткий тултип для черты: эффекты из описания + modifiers.
        /// </summary>
        private static string TooltipTrait(TraitDef def, TraitDegreeData deg)
        {
            var lines = new System.Text.StringBuilder();
            try
            {
                if (deg != null)
                {
                    // Статовые модификаторы черты
                    if (deg.statOffsets != null)
                        foreach (var sm in deg.statOffsets)
                        {
                            if (sm?.stat == null || sm.value == 0) continue;
                            string sign = sm.value > 0 ? "+" : "";
                            string lbl  = PawnUtils.StripTags(sm.stat.LabelCap.ToString() ?? sm.stat.defName);
                            lines.AppendLine($"✦ {lbl}: {sign}{sm.value:G3}");
                        }
                    if (deg.statFactors != null)
                        foreach (var sm in deg.statFactors)
                        {
                            if (sm?.stat == null) continue;
                            string lbl = PawnUtils.StripTags(sm.stat.LabelCap.ToString() ?? sm.stat.defName);
                            lines.AppendLine($"✦ {lbl}: ×{sm.value:G3}");
                        }

                    // Запрещает навыки (поле на уровне TraitDef, не TraitDegreeData)
                    if (def != null && def.disabledWorkTags != WorkTags.None)
                    {
                        lines.AppendLine($"⛔ Запрещает работу: {def.disabledWorkTags}");
                    }

                    // Краткое описание (первые 100 символов)
                    if (!string.IsNullOrEmpty(deg.description) && lines.Length < 80)
                    {
                        string d = PawnUtils.StripTags(deg.description);
                        lines.AppendLine(d.Length > 120 ? d.Substring(0, 117) + "..." : d);
                    }
                }
            }
            catch { }
            return lines.ToString().Trim();
        }

        /// <summary>
        /// Краткий тултип для гена: биостаты + ключевые эффекты.
        /// </summary>
        private static string TooltipGene(GeneDef def)
        {
            var lines = new System.Text.StringBuilder();
            try
            {
                // Биостаты
                if (def.biostatCpx != 0)  lines.AppendLine($"🧬 Сложность: {(def.biostatCpx > 0 ? "+" : "")}{def.biostatCpx}");
                if (def.biostatMet != 0)  lines.AppendLine($"⚡ Метаболизм: {(def.biostatMet > 0 ? "+" : "")}{def.biostatMet}");
                if (def.biostatArc > 0)   lines.AppendLine($"👁 Архитный ген");

                // Статы
                if (def.statFactors != null)
                    foreach (var sm in def.statFactors)
                    {
                        if (sm?.stat == null) continue;
                        string lbl = PawnUtils.StripTags(sm.stat.LabelCap.ToString() ?? sm.stat.defName);
                        lines.AppendLine($"✦ {lbl}: ×{sm.value:G3}");
                    }
                if (def.statOffsets != null)
                    foreach (var sm in def.statOffsets)
                    {
                        if (sm?.stat == null || sm.value == 0) continue;
                        string sign = sm.value > 0 ? "+" : "";
                        string lbl  = PawnUtils.StripTags(sm.stat.LabelCap.ToString() ?? sm.stat.defName);
                        lines.AppendLine($"✦ {lbl}: {sign}{sm.value:G3}");
                    }

                // Описание (усечённое)
                if (!string.IsNullOrEmpty(def.description) && lines.Length < 60)
                {
                    string d = PawnUtils.StripTags(def.description);
                    lines.AppendLine(d.Length > 120 ? d.Substring(0, 117) + "..." : d);
                }
            }
            catch { }
            return lines.ToString().Trim();
        }

        /// <summary>Усечь строку до maxLen символов.</summary>
        private static string Truncate(string s, int maxLen = 120)
        {
            if (string.IsNullOrEmpty(s)) return s ?? "";
            return s.Length <= maxLen ? s : s.Substring(0, maxLen - 3) + "...";
        }

        // ── Tech level helpers ─────────────────────────────────────────────────

        /// <summary>
        /// Возвращает текущую эпоху колонии игрока.
        /// Берётся из фракции игрока (Faction.OfPlayer.def.techLevel).
        /// Fallback: Industrial если фракция недоступна.
        /// </summary>
        private static TechLevel GetColonyTechLevel()
        {
            try
            {
                return Faction.OfPlayer?.def?.techLevel ?? TechLevel.Industrial;
            }
            catch { return TechLevel.Industrial; }
        }

        /// <summary>
        /// Предмет доступен в магазине если его techLevel <= эпохи колонии.
        /// Предметы без явного techLevel (Undefined) — пропускаем (скорее всего мусор).
        /// </summary>
        private static bool IsWithinColonyTech(TechLevel itemTech)
        {
            if (itemTech == TechLevel.Undefined) return false;
            return itemTech <= GetColonyTechLevel();
        }

        // Оставляем для обратной совместимости (импланты/рецепты не имеют прямого techLevel)
        private static bool IsThingResearched(ThingDef def)
        {
            return IsWithinColonyTech(def.techLevel);
        }

        private static bool IsRecipeResearched(RecipeDef recipe)
        {
            // 1. Проверяем, требует ли рецепт незавершенного исследования
            if (recipe.researchPrerequisite != null && !recipe.researchPrerequisite.IsFinished)
                return false;

            // 2. Пробуем найти через продукт (для совместимости с твоей логикой)
            try
            {
                var produced = recipe.products?.FirstOrDefault()?.thingDef;
                if (produced != null) return IsWithinColonyTech(produced.techLevel);
            }
            catch { }
            
            // 3. Если нет рецепта производства, считаем доступным
            return true;
        }

        /// <summary>Удаляет XML/Unity rich-text теги из строки (например &lt;color=#fff&gt;текст&lt;/color&gt;).</summary>
        private static string ExtractNeurotrainerSkill(ThingDef def)
        {
            // Ищем компонент обучения навыку
            var comp = def.comps?.OfType<CompProperties_UseEffect>()
                        .FirstOrDefault(c => c.compClass == typeof(CompUseEffect_LearnSkill)) 
                        as CompProperties_UseEffect_LearnSkill;

            if (comp?.skill != null)
                return comp.skill.defName; // Возвращает "Shooting", "Melee" и т.д.

            // Fallback (на случай если компонент сломан), но более надежный чем парсинг
            return def.label?.Split(' ').FirstOrDefault() ?? def.defName;
        }

        /// <summary>
        /// Авто-определяет, является ли имплант парным:
        /// парный = часть тела рецепта встречается 2+ раз в теле гуманоида.
        /// </summary>
        private static bool IsPairedImplantRecipe(RecipeDef recipe)
        {
            try
            {
                if (recipe.appliedOnFixedBodyParts == null || recipe.appliedOnFixedBodyParts.Count == 0)
                    return false;

                var humanDef = DefDatabase<ThingDef>.GetNamed("Human", errorOnFail: false);
                var bodyDef = humanDef?.race?.body;
                if (bodyDef == null) return false;

                var partDef = recipe.appliedOnFixedBodyParts[0];
                return bodyDef.AllParts.Count(p => p.def == partDef) >= 2;
            }
            catch { return false; }
        }
    }
}