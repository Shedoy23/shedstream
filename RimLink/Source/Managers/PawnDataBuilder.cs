using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using RimWorld;
using Verse;
using RimLink.Utils;
using RimLink.Components;

namespace RimLink.Managers
{
    /// <summary>
    /// Статические методы построения JSON-данных пешек и трупов для отправки на сервер.
    /// Все методы чистые (pure): читают игровые объекты, не изменяют никакое состояние.
    /// ВСЕ методы требуют вызова из главного потока Unity.
    /// </summary>
    internal static class PawnDataBuilder
    {
        // ── Публичный интерфейс ────────────────────────────────────────────────

        public static Dictionary<string, object> BuildPawnData(string username, Pawn pawn) =>
            BuildPawnDataBase(username, pawn, pawn.Map);

        public static Dictionary<string, object> BuildCorpseData(string username, Corpse corpse) =>
            BuildPawnDataBase(username, corpse.InnerPawn, corpse.Map, isCorpse: true);

        public static string ExtractUsername(Pawn pawn)
        {
            if (ViewerIdentity.TryGetUsername(pawn, out string username)) return username;
            if (pawn.Name is NameTriple t) return t.Nick;
            if (pawn.Name is NameSingle s) return s.Name;
            return pawn.Name?.ToString()?.Replace("'", "").Trim() ?? "";
        }

        /// <summary>
        /// Определяет, является ли часть тела левой.
        /// internal — вызывается также из PawnManager.InstallImplant.
        /// </summary>
        internal static bool IsLeft(BodyPartRecord part)
        {
            string defName = part.def?.defName ?? "";
            if (defName.StartsWith("Left",  StringComparison.OrdinalIgnoreCase)) return true;
            if (defName.StartsWith("Right", StringComparison.OrdinalIgnoreCase)) return false;
            if (defName.IndexOf("Left",  StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (defName.IndexOf("Right", StringComparison.OrdinalIgnoreCase) >= 0) return false;

            string custom = part.customLabel ?? "";
            if (custom.IndexOf("left",  StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (custom.IndexOf("right", StringComparison.OrdinalIgnoreCase) >= 0) return false;
            if (custom.IndexOf("лев",   StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (custom.IndexOf("прав",  StringComparison.OrdinalIgnoreCase) >= 0) return false;

            var allSameType = part.body?.AllParts.Where(p => p.def == part.def).ToList();
            if (allSameType != null && allSameType.Count >= 2)
                return allSameType.IndexOf(part) > 0;

            if (part.parent != null && part.parent != part)
                return IsLeft(part.parent);

            return false;
        }

        // ── Построение базовых данных ──────────────────────────────────────────

        private static Dictionary<string, object> BuildPawnDataBase(string username, Pawn pawn, Map map, bool isCorpse = false)
        {
            var data = new Dictionary<string, object>
            {
                { "username",    username                                                                    },
                { "pawn_name",   ExtractUsername(pawn)                                                      },
                { "is_alive",    isCorpse ? (object)false : !pawn.Dead                                     },
                { "health",      isCorpse ? (object)0.0 : (double)pawn.health.summaryHealth.SummaryHealthPercent },
                { "world_name",  Find.World?.info?.name ?? "Unknown"                                        },
                { "world_id",    Find.World?.info?.persistentRandomValue ?? 0                               },
                { "map_id",      map?.uniqueID ?? 0                                                         },
                { "traits",      GetTraits(pawn)                                                            },
                { "equipment",   BuildEquipmentData(pawn)                                                   },
                { "hediffs",     BuildHediffData(pawn)                                                      },
                { "skills",      BuildSkillData(pawn)                                                       },
                { "implants",    BuildImplantData(pawn)                                                     },
                { "genes",       BuildGeneData(pawn)                                                        },
                { "xenotype",    BuildXenotypeData(pawn)                                                    },
                { "psylink",     BuildPsylinkData(pawn)                                                     },
                { "age",         pawn.ageTracker?.AgeBiologicalYears ?? 0                                   },
                { "gender",      pawn.gender.ToString()                                                     },
                { "faction",     pawn.Faction?.Name ?? "None"                                               },
            };
            if (isCorpse) data["is_corpse"] = true;
            return data;
        }

        // ── Снаряжение ─────────────────────────────────────────────────────────

        private static List<object> BuildEquipmentData(Pawn pawn)
        {
            var list = new List<object>();

            if (pawn.equipment?.Primary != null)
            {
                // Оборачиваем сбор данных оружия в try/catch: если что-то бросит исключение
                // (LabelCap на модовом def, TryGetQuality и т.д.), чтоб это не уронило
                // сбор всей пешки — одежда и остальное продолжат отправляться.
                try
                {
                    var w = pawn.equipment.Primary;
                    string label = null;
                    try { label = w.def.LabelCap.ToString(); } catch { }
                    if (string.IsNullOrEmpty(label)) label = w.def.label ?? w.def.defName ?? "weapon";

                    string stuff = "";
                    try { if (w.Stuff != null) stuff = w.Stuff.LabelCap.ToString() ?? w.Stuff.label ?? ""; } catch { }

                    string quality = "Normal";
                    try { quality = w.TryGetQuality(out QualityCategory qc) ? qc.ToString() : "Normal"; } catch { }

                    list.Add(new Dictionary<string, object>
                    {
                        { "slot",          "weapon"              },
                        { "def_name",      w.def.defName ?? ""   },
                        { "label",         label                 },
                        { "hp",            w.HitPoints           },
                        { "max_hp",        w.MaxHitPoints        },
                        { "quality",       quality               },
                        { "stuff",         stuff                 },
                        { "weapon_traits", GetWeaponTraits(w)    },
                        { "psi_abilities", GetWeaponPsiAbilities(w) },
                        { "is_bladelink",  IsBladelink(w)        }
                    });
                }
                catch (Exception wex)
                {
                    RimLinkLog.Warn($"[RimLink] BuildEquipmentData weapon ({pawn?.equipment?.Primary?.def?.defName ?? "?"}): {wex.Message}");
                }
            }

            if (pawn.apparel != null)
            {
                foreach (var a in pawn.apparel.WornApparel)
                {
                    list.Add(new Dictionary<string, object>
                    {
                        { "slot",        GetApparelSlot(a.def)                                             },
                        { "def_name",    a.def.defName                                                     },
                        { "label",       a.def.LabelCap.ToString() ?? a.def.label ?? a.def.defName        },
                        { "hp",          a.HitPoints                                                       },
                        { "max_hp",      a.MaxHitPoints                                                    },
                        { "quality",     a.TryGetQuality(out QualityCategory qc2) ? qc2.ToString() : "Normal" },
                        { "stuff",       a.Stuff != null ? a.Stuff.LabelCap.ToString() ?? a.Stuff.label ?? "" : "" },
                        { "description", a.def.description ?? ""                                           },
                        { "color",       a.DrawColor.ToString() ?? ""                                      }
                    });
                }
            }

            return list;
        }

        private static string GetApparelSlot(ThingDef def)
        {
            if (def.apparel == null) return "body";
            var groups = def.apparel.bodyPartGroups;
            if (groups.Any(g => g.defName == "FullHead" || g.defName == "UpperHead")) return "head";
            if (groups.Any(g => g.defName == "Eyes"))  return "eyes";
            if (groups.Any(g => g.defName == "Torso")) return "torso";
            if (groups.Any(g => g.defName == "Legs"))  return "legs";
            if (groups.Any(g => g.defName == "Hands")) return "hands";
            if (groups.Any(g => g.defName == "Feet"))  return "feet";
            if (groups.Any(g => g.defName == "Waist")) return "belt";
            if (groups.Any(g => g.defName == "Neck"))  return "neck";
            return "body";
        }

        // ── Черты оружия ───────────────────────────────────────────────────────

        private static List<object> GetWeaponTraits(ThingWithComps weapon)
        {
            var result = new List<object>();
            if (weapon == null) return result;
            try
            {
                foreach (var comp in weapon.AllComps)
                {
                    if (comp == null) continue;
                    var compType = comp.GetType();

                    object traitsValue = null;
                    var prop = compType.GetProperty("WeaponTraits",
                        System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance);
                    if (prop != null)
                        traitsValue = prop.GetValue(comp, null);
                    else
                    {
                        var field = compType.GetField("weaponTraits",
                            System.Reflection.BindingFlags.Public |
                            System.Reflection.BindingFlags.NonPublic |
                            System.Reflection.BindingFlags.Instance);
                        if (field != null)
                            traitsValue = field.GetValue(comp);
                    }

                    if (!(traitsValue is System.Collections.IEnumerable enumerable)) continue;

                    foreach (var item in enumerable)
                    {
                        if (item == null) continue;
                        var itemType = item.GetType();
                        string label   = GetReflectedString(item, itemType, "label")
                                      ?? GetReflectedString(item, itemType, "LabelCap")
                                      ?? GetReflectedString(item, itemType, "defName")
                                      ?? item.ToString();
                        string defName = GetReflectedString(item, itemType, "defName") ?? label;
                        string desc    = GetReflectedString(item, itemType, "description") ?? "";
                        if (string.IsNullOrEmpty(label)) continue;
                        result.Add(new Dictionary<string, object>
                        {
                            { "def_name",    PawnUtils.StripTags(defName) },
                            { "label",       PawnUtils.StripTags(label)   },
                            { "description", PawnUtils.StripTags(desc)    },
                        });
                    }
                    if (result.Count > 0) break;
                }
            }
            catch (Exception ex) { RimLinkLog.Warn($"[RimLink] GetWeaponTraits: {ex.Message}"); }
            return result;
        }

        private static List<object> GetWeaponPsiAbilities(ThingWithComps weapon)
        {
            var result = new List<object>();
            if (weapon?.def?.comps == null) return result;
            try
            {
                var psychicComp = weapon.def.comps.FirstOrDefault(c =>
                    c.compClass != null && (
                        c.compClass.Name.Contains("Psychic") ||
                        c.compClass.Name.Contains("Psycast") ||
                        c.compClass.FullName?.Contains("PsychicWeapon") == true));
                if (psychicComp == null) return result;

                var type = psychicComp.GetType();
                System.Collections.IEnumerable abilityList = null;

                foreach (var memberName in new[] { "abilities", "Abilities", "abilityDefs", "AbilityDefs" })
                {
                    var p = type.GetProperty(memberName,
                        System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
                    if (p != null) { abilityList = p.GetValue(psychicComp) as System.Collections.IEnumerable; break; }
                    var f = type.GetField(memberName,
                        System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
                    if (f != null) { abilityList = f.GetValue(psychicComp) as System.Collections.IEnumerable; break; }
                }

                if (abilityList != null)
                {
                    foreach (var ab in abilityList)
                    {
                        if (ab == null) continue;
                        var abType   = ab.GetType();
                        string abLabel   = GetReflectedString(ab, abType, "LabelCap")
                                       ?? GetReflectedString(ab, abType, "label")
                                       ?? GetReflectedString(ab, abType, "defName")
                                       ?? ab.ToString();
                        string abDesc    = GetReflectedString(ab, abType, "description") ?? "";
                        string abDefName = GetReflectedString(ab, abType, "defName") ?? abLabel;
                        if (string.IsNullOrEmpty(abLabel)) continue;
                        result.Add(new Dictionary<string, object>
                        {
                            { "def_name", PawnUtils.StripTags(abDefName) },
                            { "label",    PawnUtils.StripTags(abLabel)   },
                            { "desc",     PawnUtils.StripTags(abDesc)    },
                        });
                    }
                }
            }
            catch (Exception ex) { RimLinkLog.Warn($"[RimLink] GetWeaponPsiAbilities: {ex.Message}"); }
            return result;
        }

        private static bool IsBladelink(ThingWithComps weapon)
        {
            if (weapon?.def?.comps == null) return false;
            return weapon.def.comps.Any(c =>
                c.compClass != null && (
                    c.compClass.Name == "CompBladelinkBonded" ||
                    c.compClass.Name == "CompBladelink" ||
                    c.compClass.FullName?.Contains("Bladelink") == true));
        }

        private static string GetReflectedString(object obj, Type type, string memberName)
        {
            try
            {
                var prop = type.GetProperty(memberName,
                    System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance);
                if (prop != null) return prop.GetValue(obj, null)?.ToString();

                var field = type.GetField(memberName,
                    System.Reflection.BindingFlags.Public |
                    System.Reflection.BindingFlags.NonPublic |
                    System.Reflection.BindingFlags.Instance);
                if (field != null) return field.GetValue(obj)?.ToString();
            }
            catch { }
            return null;
        }

        // ── Состояние здоровья ─────────────────────────────────────────────────

        private static List<object> BuildHediffData(Pawn pawn)
        {
            var list = new List<object>();
            if (pawn.health?.hediffSet == null) return list;

            bool IsSameOrChildOf(BodyPartRecord part, BodyPartRecord possibleAncestor)
            {
                for (var p = part; p != null; p = p.parent)
                    if (ReferenceEquals(p, possibleAncestor)) return true;
                return false;
            }

            var implantedParts = new HashSet<BodyPartRecord>(
                pawn.health.hediffSet.hediffs
                    .Where(h => h != null &&
                               (h.def.hediffClass == typeof(Hediff_AddedPart) ||
                                h.def.hediffClass?.Name == "Hediff_Implant" ||
                                h.def.hediffClass == typeof(Hediff_Implant)) &&
                                h.Part != null)
                    .Select(h => h.Part));

            foreach (var h in pawn.health.hediffSet.hediffs)
            {
                if (h == null) continue;
                if (h.def?.defName == ViewerIdentity.MarkerDefName) continue;
                bool isImplant = h.def.hediffClass == typeof(Hediff_AddedPart)
                              || h.def.hediffClass?.Name == "Hediff_Implant"
                              || h.def.hediffClass == typeof(Hediff_Implant);
                if (isImplant) continue;

                bool isMissing = h.def == HediffDefOf.MissingBodyPart || h is Hediff_MissingPart;
                if (isMissing && h.Part != null)
                {
                    bool coveredByImplant = implantedParts.Any(ip =>
                        ip != null && (ReferenceEquals(ip, h.Part) || IsSameOrChildOf(h.Part, ip)));
                    if (coveredByImplant) continue;
                }

                if (isMissing && h.Part?.def != null)
                {
                    string pdn = h.Part.def.defName.ToLowerInvariant();
                    bool isTrivial = pdn.Contains("finger") || pdn.Contains("toe")
                                  || pdn.Contains("tooth")  || pdn.Contains("teeth")
                                  || pdn.Contains("nose")   || pdn.Contains("ear");
                    if (isTrivial) continue;
                }

                list.Add(new Dictionary<string, object>
                {
                    { "def_name",    h.def.defName                                                         },
                    { "label",       h.def.LabelCap.ToString() ?? h.def.label ?? h.def.defName            },
                    { "part",        h.Part?.def?.LabelCap.ToString() ?? h.Part?.def?.label ?? "whole body"},
                    { "severity",    (double)h.Severity                                                    },
                    { "is_bad",      h.def.isBad                                                           },
                    { "description", h.def.description ?? ""                                               }
                });
            }
            return list;
        }

        private static List<object> BuildImplantData(Pawn pawn)
        {
            var list = new List<object>();
            if (pawn.health?.hediffSet == null) return list;

            foreach (var h in pawn.health.hediffSet.hediffs)
            {
                if (h == null || h.def == null) continue;
                bool isImplant = h.def.hediffClass != null && (
                    typeof(Hediff_AddedPart).IsAssignableFrom(h.def.hediffClass) ||
                    typeof(Hediff_Implant).IsAssignableFrom(h.def.hediffClass));
                if (!isImplant) continue;

                string partDef   = h.Part?.def?.defName ?? "";
                string partLabel = h.Part?.def?.label ?? h.Part?.Label ?? "whole body";

                bool? isLeft = null;
                if (h.Part != null)
                {
                    var allSame     = pawn.RaceProps?.body?.AllParts?.Where(p => p.def == h.Part.def).ToList();
                    bool parentIsPaired = h.Part.parent != null &&
                        (pawn.RaceProps?.body?.AllParts?.Count(p => p.def == h.Part.parent.def) ?? 0) >= 2;
                    if ((allSame != null && allSame.Count >= 2) || parentIsPaired)
                        isLeft = IsLeft(h.Part);
                }

                string sidePrefix       = isLeft.HasValue ? (isLeft.Value ? "Лев. " : "Пр. ") : "";
                string displayPartLabel = sidePrefix + partLabel;

                list.Add(new Dictionary<string, object>
                {
                    { "def_name",        h.def.defName                      },
                    { "label",           h.def.LabelCap.ToString()          },
                    { "part_def",        partDef                            },
                    { "part_label",      partLabel                          },
                    { "part_label_full", displayPartLabel                   },
                    { "is_paired",       isLeft.HasValue                    },
                    { "is_left",         isLeft.HasValue ? (object)isLeft.Value : (object)"" },
                });
            }
            return list;
        }

        // ── Биотех ─────────────────────────────────────────────────────────────

        private static Dictionary<string, object> BuildXenotypeData(Pawn pawn)
        {
            try
            {
                if (!ModsConfig.BiotechActive) return new Dictionary<string, object>();
                var genesComp = pawn.genes;
                if (genesComp == null) return new Dictionary<string, object>();

                string xenotypeName    = "";
                string xenotypeDefName = "";
                bool   isCustom        = false;

                if (genesComp.Xenotype != null)
                {
                    string rawXenoName = genesComp.Xenotype.LabelCap.ToString()
                                      ?? genesComp.Xenotype.label
                                      ?? genesComp.Xenotype.defName ?? "";
                    xenotypeName    = Regex.Replace(rawXenoName, @"<[^>]+>", "").Trim();
                    xenotypeDefName = genesComp.Xenotype.defName;
                }
                else if (!string.IsNullOrEmpty(genesComp.xenotypeName))
                {
                    xenotypeName = Regex.Replace(genesComp.xenotypeName ?? "", @"<[^>]+>", "").Trim();
                    isCustom     = true;
                }

                if (string.IsNullOrEmpty(xenotypeName)) xenotypeName = "Базовый";

                var xenogenes = genesComp.Xenogenes
                    .Where(g => g?.def != null)
                    .Select(g => (object)new Dictionary<string, object>
                    {
                        { "def_name",      g.def.defName                                                                                       },
                        { "label",         Regex.Replace(g.def.LabelCap.ToString() ?? g.def.label ?? g.def.defName ?? "", @"<[^>]+>", "").Trim() },
                        { "is_active",     g.Active                                                                                             },
                        { "is_overridden", g.Overridden                                                                                         },
                        { "gene_class",    g.def.displayCategory?.defName ?? ""                                                                 },
                        { "biostat_met",   g.def.biostatMet                                                                                     },
                        { "biostat_arc",   g.def.biostatArc                                                                                     },
                    })
                    .ToList();

                int totalMet = genesComp.Xenogenes
                    .Where(g => g?.def != null && !g.Overridden)
                    .Sum(g => g.def.biostatMet);

                return new Dictionary<string, object>
                {
                    { "name",       xenotypeName    },
                    { "def_name",   xenotypeDefName },
                    { "is_custom",  isCustom        },
                    { "xenogenes",  xenogenes       },
                    { "metabolism", totalMet        },
                };
            }
            catch (Exception e)
            {
                RimLinkLog.Warn($"[RimLink] BuildXenotypeData: {e.Message}");
                return new Dictionary<string, object>();
            }
        }

        private static List<object> BuildGeneData(Pawn pawn)
        {
            var list = new List<object>();
            try
            {
                var genesComp = pawn.genes;
                if (genesComp == null) return list;
                foreach (var gene in genesComp.GenesListForReading)
                {
                    if (gene?.def == null) continue;
                    bool isXenogene = !gene.Overridden && genesComp.Xenogenes.Contains(gene);
                    list.Add(new Dictionary<string, object>
                    {
                        { "def_name",    gene.def.defName                                                    },
                        { "label",       gene.def.LabelCap.ToString() ?? gene.def.label ?? gene.def.defName },
                        { "is_active",   gene.Active                                                         },
                        { "xenogene",    isXenogene                                                          },
                        { "gene_class",  gene.def.displayCategory?.defName ?? ""                             },
                        { "can_remove",  !gene.Active || gene.Overridden                                     },
                        { "desc",        gene.def.description ?? ""                                          },
                        { "biostat_met", gene.def.biostatMet                                                 },
                        { "biostat_arc", gene.def.biostatArc                                                 },
                    });
                }
            }
            catch { /* Biotech не установлен */ }
            return list;
        }

        // ── Псионика ───────────────────────────────────────────────────────────

        private static Dictionary<string, object> BuildPsylinkData(Pawn pawn)
        {
            try
            {
                if (!ModsConfig.RoyaltyActive)
                    return new Dictionary<string, object> { { "level", 0 }, { "abilities", new List<object>() } };

                int level     = 0;
                var psyHediff = pawn.health?.hediffSet?.hediffs
                    ?.FirstOrDefault(h => h?.def?.defName == "PsychicAmplifier");
                if (psyHediff != null)
                    level = (int)Math.Round(psyHediff.Severity);

                var abilities = new List<object>();
                try
                {
                    var comp = pawn.abilities;
                    if (comp?.abilities != null)
                    {
                        foreach (var ab in comp.abilities)
                        {
                            if (ab?.def == null) continue;
                            float psyfocusCost = 0f;
                            try
                            {
                                var prop  = ab.def.GetType().GetProperty("requiredPsyfocus")
                                         ?? ab.def.GetType().GetProperty("RequiredPsyfocus");
                                var field = ab.def.GetType().GetField("requiredPsyfocus");
                                if (prop  != null) psyfocusCost = (float)prop.GetValue(ab.def);
                                else if (field != null) psyfocusCost = (float)field.GetValue(ab.def);
                            }
                            catch { }

                            bool isPsy = psyfocusCost > 0f
                                      || (ab.def.defName ?? "").ToLower().Contains("psy")
                                      || (ab.def.defName ?? "").ToLower().Contains("cast");
                            if (!isPsy) continue;
                            abilities.Add(new Dictionary<string, object>
                            {
                                { "def_name",      ab.def.defName                                                         },
                                { "label",         PawnUtils.StripTags(ab.def.LabelCap.ToString() ?? ab.def.label ?? ab.def.defName) },
                                { "desc",          ab.def.description ?? ""                                                },
                                { "psyfocus_cost", (double)psyfocusCost                                                   },
                            });
                        }
                    }
                }
                catch { }

                return new Dictionary<string, object>
                {
                    { "level",     level     },
                    { "abilities", abilities },
                };
            }
            catch (Exception e)
            {
                RimLinkLog.Warn($"[RimLink] BuildPsylinkData: {e.Message}");
                return new Dictionary<string, object> { { "level", 0 }, { "abilities", new List<object>() } };
            }
        }

        // ── Черты, навыки ──────────────────────────────────────────────────────

        private static List<object> GetTraits(Pawn pawn)
        {
            var list = new List<object>();
            if (pawn.story?.traits?.allTraits == null) return list;
            foreach (var t in pawn.story.traits.allTraits)
            {
                if (t?.def == null) continue;
                string rawLabel = t.LabelCap.ToString() ?? t.def.label ?? t.def.defName;

                string traitColor  = null;
                var    colorMatch  = Regex.Match(rawLabel, @"<color=(#[0-9a-fA-F]{3,8}|[a-zA-Z]+)>");
                if (colorMatch.Success)
                    traitColor = colorMatch.Groups[1].Value;

                string cleanLabel = Regex.Replace(rawLabel, @"<[^>]+>", "").Trim();
                if (string.IsNullOrEmpty(cleanLabel))
                    cleanLabel = t.def.label ?? t.def.defName;

                if (traitColor == null)
                    traitColor = t.Degree > 0 ? "#4ade80" : t.Degree < 0 ? "#f87171" : "#efeff1";

                list.Add(new Dictionary<string, object>
                {
                    { "def_name", t.def.defName                                          },
                    { "label",    cleanLabel                                              },
                    { "degree",   t.Degree                                               },
                    { "color",    traitColor                                              },
                    { "desc",     t.def.DataAtDegree(t.Degree)?.description ?? ""        },
                });
            }
            return list;
        }

        private static List<object> BuildSkillData(Pawn pawn)
        {
            var list = new List<object>();
            if (pawn.skills == null) return list;
            foreach (var s in pawn.skills.skills)
            {
                if (s == null) continue;
                list.Add(new Dictionary<string, object>
                {
                    { "def_name",    s.def.defName                                         },
                    { "label",       s.def.LabelCap.ToString() ?? s.def.label ?? s.def.defName },
                    { "level",       s.TotallyDisabled ? -1 : s.Level                     },
                    { "passion",     (int)s.passion                                        },
                    { "is_disabled", s.TotallyDisabled                                     },
                    { "xp",          (double)s.xpSinceLastLevel                            },
                });
            }
            return list;
        }
    }
}
