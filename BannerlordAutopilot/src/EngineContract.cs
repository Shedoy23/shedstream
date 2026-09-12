using System;
using System.Collections.Generic;
using System.Reflection;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

namespace BannerlordAutopilot
{
    /// <summary>Проверка структуры движка ПЕРЕД тем, как что-то включать.
    ///
    /// Мод скомпилирован под конкретную сборку 1.4.8. Запустить его могут на
    /// другой версии игры или рядом с модом, который подменил эти типы. Тогда
    /// вместо работы будет ошибка разрешения метода посреди кампании. Поэтому
    /// при старте спрашиваем рантайм: те ли это члены, тех ли типов. Не
    /// сошлось — автопилот не включается, игра работает как обычно.
    ///
    /// ЧЕГО ЭТА ПРОВЕРКА НЕ ДЕЛАЕТ. Она сверяет структуру, а не поведение:
    /// метод с прежней сигнатурой, но другим смыслом, она не заметит.
    ///
    /// 12.09 независимая проверка построила API, где AIBehaviorScores был
    /// строкой, поле Party — целым числом, одного используемого метода не было
    /// вовсе, — и прежний контракт принял его «19 из 19». Он сверял только
    /// наличие имён, пропускал часть реально используемых вызовов и накручивал
    /// счётчик при повторном запуске. Теперь сверяются типы полей, параметры и
    /// возвращаемые значения всех вызовов, которыми пользуется мод.</summary>
    internal static class EngineContract
    {
        internal static bool Ok { get; private set; }
        internal static string Report { get; private set; } = "проверка не выполнялась";

        private static readonly List<string> Problems = new List<string>();
        private static int _checked;

        private const BindingFlags Inst = BindingFlags.Public | BindingFlags.Instance;
        private const BindingFlags Stat = BindingFlags.Public | BindingFlags.Static;

        internal static bool Verify()
        {
            Problems.Clear();
            _checked = 0;

            // ── Типы, которые нельзя назвать напрямую, берём из полей и сверяем по имени
            Type vec2 = typeof(AIBehaviorData).GetField("Position", Inst)?.FieldType;
            Need(vec2 != null && vec2.Name == "CampaignVec2", "AIBehaviorData.Position : CampaignVec2");
            Type navigation = typeof(MobileParty.NavigationType);

            // ── Сбор оценок
            MemberOf(typeof(MobileParty), "ThinkParamsCache", Inst, typeof(PartyThinkParams));
            Method(typeof(PartyThinkParams), "Reset", Inst, typeof(void), typeof(MobileParty));
            PropertyInfo scores = typeof(PartyThinkParams).GetProperty("AIBehaviorScores", Inst);
            Need(scores != null && typeof(IEnumerable<(AIBehaviorData, float)>).IsAssignableFrom(scores.PropertyType),
                "PartyThinkParams.AIBehaviorScores : IEnumerable<(AIBehaviorData, float)>");
            MemberOf(typeof(CampaignEventDispatcher), "Instance", Stat, typeof(CampaignEventDispatcher));
            Method(typeof(CampaignEventDispatcher), "AiHourlyTick", Inst, typeof(void),
                typeof(MobileParty), typeof(PartyThinkParams));

            // ── Описание решения
            FieldOf(typeof(AIBehaviorData), "AiBehavior", typeof(AiBehavior));
            FieldNamed(typeof(AIBehaviorData), "Party", "IMapPoint");
            FieldOf(typeof(AIBehaviorData), "NavigationType", navigation);
            FieldOf(typeof(AIBehaviorData), "IsFromPort", typeof(bool));
            FieldOf(typeof(AIBehaviorData), "IsTargetingPort", typeof(bool));
            FieldOf(typeof(AIBehaviorData), "WillGatherArmy", typeof(bool));

            // ── Применение решения
            Method(typeof(SetPartyAiAction), "GetActionForVisitingSettlement", Stat, typeof(void),
                typeof(MobileParty), typeof(Settlement), navigation, typeof(bool), typeof(bool));
            Method(typeof(SetPartyAiAction), "GetActionForPatrollingAroundSettlement", Stat, typeof(void),
                typeof(MobileParty), typeof(Settlement), navigation, typeof(bool), typeof(bool));
            if (vec2 != null)
            {
                Method(typeof(SetPartyAiAction), "GetActionForPatrollingAroundPoint", Stat, typeof(void),
                    typeof(MobileParty), vec2, navigation, typeof(bool));
            }
            Method(typeof(SetPartyAiAction), "GetActionForEscortingParty", Stat, typeof(void),
                typeof(MobileParty), typeof(MobileParty), navigation, typeof(bool), typeof(bool));

            // ── Состояние партии
            MemberOf(typeof(MobileParty), "MainParty", Stat, typeof(MobileParty));
            MemberOf(typeof(MobileParty), "IsActive", Inst, typeof(bool));
            MemberOf(typeof(MobileParty), "IsMoving", Inst, typeof(bool));
            MemberOf(typeof(MobileParty), "CurrentSettlement", Inst, typeof(Settlement));
            MemberOf(typeof(MobileParty), "BesiegedSettlement", Inst, typeof(Settlement));
            MemberOf(typeof(MobileParty), "TargetSettlement", Inst, typeof(Settlement));
            MemberOf(typeof(MobileParty), "LastVisitedSettlement", Inst, typeof(Settlement));
            MemberOf(typeof(MobileParty), "DefaultBehavior", Inst, typeof(AiBehavior));
            MemberOf(typeof(MobileParty), "Ai", Inst, typeof(MobilePartyAi));
            MemberExists(typeof(MobileParty), "MapEvent", Inst);
            MemberExists(typeof(MobileParty), "SiegeEvent", Inst);
            MemberExists(typeof(MobileParty), "Army", Inst);
            if (vec2 != null)
            {
                MemberOf(typeof(MobileParty), "Position", Inst, vec2, needWrite: true);
            }
            Method(typeof(MobileParty), "SetMoveModeHold", Inst, typeof(void));
            MemberOf(typeof(MobilePartyAi), "IsDisabled", Inst, typeof(bool));
            MemberOf(typeof(MobilePartyAi), "DoNotMakeNewDecisions", Inst, typeof(bool));

            // ── Встреча и выход из поселения (повтор кнопки «Уйти»)
            MemberExists(typeof(PlayerEncounter), "Current", Stat);
            MemberExists(typeof(PlayerEncounter), "Battle", Stat);
            MemberOf(typeof(PlayerEncounter), "EncounterSettlement", Stat, typeof(Settlement));
            MemberOf(typeof(PlayerEncounter), "EncounteredMobileParty", Stat, typeof(MobileParty));
            Method(typeof(PlayerEncounter), "LeaveSettlement", Stat, typeof(void));
            Method(typeof(PlayerEncounter), "Finish", Stat, typeof(void), typeof(bool));
            MemberOf(typeof(Settlement), "IsUnderSiege", Inst, typeof(bool));
            if (vec2 != null)
            {
                MemberOf(typeof(Settlement), "GatePosition", Inst, vec2);
            }

            // ── Прочее
            MemberOf(typeof(Hero), "MainHero", Stat, typeof(Hero));
            MemberOf(typeof(Hero), "IsPrisoner", Inst, typeof(bool));
            MemberOf(typeof(Campaign), "Current", Stat, typeof(Campaign));

            Ok = Problems.Count == 0;
            Report = Ok
                ? "структура движка совпала со всеми " + _checked + " ожиданиями"
                : "НЕ СОВПАЛО (" + Problems.Count + " из " + _checked + "): " + string.Join("; ", Problems.ToArray());
            return Ok;
        }

        private static void Need(bool condition, string what)
        {
            _checked++;
            if (!condition)
            {
                Problems.Add(what);
            }
        }

        /// <summary>Метод с точными параметрами и возвращаемым типом.</summary>
        private static void Method(Type type, string name, BindingFlags flags, Type returns, params Type[] args)
        {
            MethodInfo m = type.GetMethod(name, flags, null, args, null);
            Need(m != null && m.ReturnType == returns,
                type.Name + "." + name + "(" + args.Length + " арг.) → " + returns.Name);
        }

        /// <summary>Свойство или поле нужного типа (и с записью, если она нужна).</summary>
        private static void MemberOf(Type type, string name, BindingFlags flags, Type expected, bool needWrite = false)
        {
            Type actual = MemberType(type, name, flags, needWrite, out bool writable);
            // CampaignVec2 берётся из поля движка, и при несовпадении его имя —
            // уже чужое; в сообщении нужно ОЖИДАЕМОЕ имя, иначе оно путает.
            string label = expected.Name == "CampaignVec2" || name == "Position" || name == "GatePosition"
                ? "CampaignVec2" : expected.Name;
            Need(actual == expected && (!needWrite || writable),
                type.Name + "." + name + " : " + label + (needWrite ? " (запись)" : ""));
        }

        private static void MemberExists(Type type, string name, BindingFlags flags)
        {
            Need(MemberType(type, name, flags, false, out _) != null, type.Name + "." + name);
        }

        private static void FieldOf(Type type, string name, Type expected)
        {
            Need(type.GetField(name, Inst)?.FieldType == expected, type.Name + "." + name + " : " + expected.Name);
        }

        private static void FieldNamed(Type type, string name, string expectedTypeName)
        {
            Need(type.GetField(name, Inst)?.FieldType.Name == expectedTypeName,
                type.Name + "." + name + " : " + expectedTypeName);
        }

        private static Type MemberType(Type type, string name, BindingFlags flags, bool needWrite, out bool writable)
        {
            PropertyInfo p = type.GetProperty(name, flags);
            if (p != null)
            {
                writable = p.CanWrite && p.GetSetMethod() != null;
                return p.PropertyType;
            }
            FieldInfo f = type.GetField(name, flags);
            if (f != null)
            {
                writable = !f.IsInitOnly;
                return f.FieldType;
            }
            writable = false;
            return null;
        }
    }
}
