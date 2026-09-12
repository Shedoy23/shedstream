using System;
using System.Collections.Generic;
using System.Reflection;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

namespace BannerlordAutopilot
{
    /// <summary>Проверка структуры движка ПЕРЕД тем, как что-то включать.
    ///
    /// Зачем это нужно, хотя мы ни на что не патчимся. Мод скомпилирован под
    /// конкретную сборку 1.4.8. Запустить его могут на другой версии игры или
    /// рядом с модом, который подменил эти же типы. Тогда вместо работы будет
    /// MissingMethodException посреди кампании — то есть падение в проде.
    ///
    /// Поэтому при старте мы спрашиваем у рантайма: те ли это методы, с теми
    /// ли сигнатурами. Не сошлось — автопилот НЕ включается, причина пишется в
    /// лог, игра продолжает работать как обычно. Это прямое требование
    /// спецификации: «при несовпадении структуры не включать».
    ///
    /// Ровно одно исключение из принципа «ничего не менять при несовпадении»:
    /// мы не отключаем сам мод — он просто остаётся бездействующим.</summary>
    internal static class EngineContract
    {
        internal static bool Ok { get; private set; }
        internal static string Report { get; private set; } = "проверка не выполнялась";

        private static readonly List<string> Problems = new List<string>();

        internal static bool Verify()
        {
            Problems.Clear();

            // 1. Кэш параметров раздумий у партии. Именно его переиспользует
            //    штатный цикл, поэтому и мы берём его, а не создаём свой:
            //    так оценки собираются в тот же объект, что у NPC.
            var thinkCache = typeof(MobileParty).GetProperty("ThinkParamsCache",
                BindingFlags.Public | BindingFlags.Instance);
            Need(thinkCache != null && thinkCache.PropertyType == typeof(PartyThinkParams),
                "MobileParty.ThinkParamsCache (public, тип PartyThinkParams)");

            // 2. Сброс параметров перед сбором — иначе оценки прошлого часа
            //    сложатся с новыми.
            Need(typeof(PartyThinkParams).GetMethod("Reset",
                    BindingFlags.Public | BindingFlags.Instance, null,
                    new[] { typeof(MobileParty) }, null) != null,
                "PartyThinkParams.Reset(MobileParty)");

            // 3. Собственно список оценок.
            Need(typeof(PartyThinkParams).GetProperty("AIBehaviorScores",
                    BindingFlags.Public | BindingFlags.Instance) != null,
                "PartyThinkParams.AIBehaviorScores");

            // 4. Рассылка «соберите оценки» всем AI-поведениям. Это и есть
            //    штатный сбор: те же подписчики, что работают для NPC.
            Need(typeof(CampaignEventDispatcher).GetProperty("Instance",
                    BindingFlags.Public | BindingFlags.Static) != null,
                "CampaignEventDispatcher.Instance");
            Need(typeof(CampaignEventDispatcher).GetMethod("AiHourlyTick",
                    BindingFlags.Public | BindingFlags.Instance, null,
                    new[] { typeof(MobileParty), typeof(PartyThinkParams) }, null) != null,
                "CampaignEventDispatcher.AiHourlyTick(MobileParty, PartyThinkParams)");

            // 5. Применение решения. Берём только те действия, которые
            //    прототипу разрешены: поездка в поселение, патруль, эскорт.
            //    Осадных и рейдовых намеренно нет — они вне области первого
            //    прототипа (барьер исполнения осады, см. исследование).
            NeedMethod(typeof(SetPartyAiAction), "GetActionForVisitingSettlement",
                new[] { typeof(MobileParty), typeof(Settlement), typeof(MobileParty.NavigationType), typeof(bool), typeof(bool) });
            NeedMethod(typeof(SetPartyAiAction), "GetActionForPatrollingAroundSettlement",
                new[] { typeof(MobileParty), typeof(Settlement), typeof(MobileParty.NavigationType), typeof(bool), typeof(bool) });
            NeedMethod(typeof(SetPartyAiAction), "GetActionForEscortingParty",
                new[] { typeof(MobileParty), typeof(MobileParty), typeof(MobileParty.NavigationType), typeof(bool), typeof(bool) });

            // 6. Флаги AI: их мы читаем при включении и восстанавливаем при
            //    выключении. Если структура разошлась — восстановить не сможем,
            //    а значит включаться нельзя.
            var aiType = typeof(MobilePartyAi);
            Need(aiType.GetProperty("IsDisabled", BindingFlags.Public | BindingFlags.Instance) != null,
                "MobilePartyAi.IsDisabled");
            Need(aiType.GetProperty("DoNotMakeNewDecisions", BindingFlags.Public | BindingFlags.Instance) != null,
                "MobilePartyAi.DoNotMakeNewDecisions");
            Need(aiType.GetProperty("RethinkAtNextHourlyTick", BindingFlags.Public | BindingFlags.Instance) != null,
                "MobilePartyAi.RethinkAtNextHourlyTick");
            NeedMethod(aiType, "SetDoNotMakeNewDecisions", new[] { typeof(bool) });
            NeedMethod(aiType, "EnableAi", Type.EmptyTypes);

            // 7. Поля описания решения — по ним мы и понимаем, что выбрал AI.
            foreach (string field in new[] { "AiBehavior", "Party", "Position", "NavigationType", "IsFromPort", "IsTargetingPort" })
            {
                Need(typeof(AIBehaviorData).GetField(field, BindingFlags.Public | BindingFlags.Instance) != null,
                    "AIBehaviorData." + field);
            }

            Ok = Problems.Count == 0;
            Report = Ok
                ? "структура движка совпала со всеми " + CheckedCount + " ожиданиями"
                : "НЕ СОВПАЛО (" + Problems.Count + "): " + string.Join("; ", Problems.ToArray());
            return Ok;
        }

        private static int CheckedCount;

        private static void Need(bool condition, string what)
        {
            CheckedCount++;
            if (!condition)
            {
                Problems.Add(what);
            }
        }

        private static void NeedMethod(Type type, string name, Type[] args)
        {
            MethodInfo method = type.GetMethod(name,
                BindingFlags.Public | BindingFlags.Static | BindingFlags.Instance,
                null, args, null);
            Need(method != null, type.Name + "." + name + "(" + args.Length + " арг.)");
        }
    }
}
