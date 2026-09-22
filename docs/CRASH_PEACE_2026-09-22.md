# Краш 22.09 около12:09, отчёт07.10.20 UTC

Дамп: C:/ProgramData/Mount and Blade II Bannerlord/crashes/2026-09-22_07.10.20/dump.dmp.
Поток40 OS1928, exception0000026aeb0cdf68: NullReferenceException.
Стек: DefaultDiplomacyModel.GetRelationScore → GetScoreOfDeclaringPeaceForClan → MakePeaceKingdomDecision.DetermineSupport → KingdomElection.Setup → Kingdom.AddDecision → KingdomDecisionProposalBehavior.DailyTickClan.
Это суточный расчёт мира на карте. Камера не участвует в стеке; журнал автопилота заканчивается продолжением пути к Корсии12:09:10.
В GetRelationScore разыменовываются Leader.Clan трёх фракций. Две стороны мира из аргументов дампа (267e276d790/267e276d530) имеют IsEliminated=false, ruling clan, ненулевого лидера и Clan. evaluatingFaction оптимизирован и отсутствует в clrstack -a; конкретный null не установлен. Не объявлять доказанной причиной уничтоженное королевство или камеру.
Доказательства: D:/shedlink-build/crash-1210-{threads,stack,factions,leaders,heroes}.txt; декомпилированный DefaultDiplomacyModel.cs, GetRelationScore.
Исправления этого краша в поставленной DLL нет. Следующий шаг: восстановить evaluatingFaction из машинного стека/регистров и проверить его лидера, затем узкая защита/исправление источника повреждения.
