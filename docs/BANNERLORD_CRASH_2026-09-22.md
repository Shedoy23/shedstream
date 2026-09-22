# Краш Bannerlord 22.09.2026 13:10 — причина найдена (ТОЧНО)

Дамп: `C:\ProgramData\Mount and Blade II Bannerlord\crashes\2026-09-22_08.10.26`
(`dump.dmp`, 1 ГБ). Игра 1.4.8.119303, прожила 44 минуты (старт 12:26).
Разбор — `scripts/triage-crash.ps1` + `dotnet-dump` + `ilspycmd`.

**Короткая версия: крашит НАШ мод.** Платное действие «выйти из клана»
(`hero.leave_clan`) оставляет клан с указателем на лидера, который уже не в
клане. На следующем суточном тике ванильное голосование о мире разыменовывает
этот указатель и игра падает. **Сейв уже в этом состоянии — падение повторится
на следующем игровом дне.**

## 1. Что именно упало

`System.NullReferenceException`, управляемый стек из дампа (снизу вверх):

```
Campaign.Tick
 └ CampaignPeriodicEventManager.PeriodicDailyTick
    └ CampaignEvents.DailyTickClan
       └ KingdomDecisionProposalBehavior.DailyTickClan(Clan)
          └ Kingdom.AddDecision → KingdomElection.Setup
             └ KingdomElection.DetermineInitialSupport
                └ MakePeaceKingdomDecision.DetermineSupport
                   └ DefaultDiplomacyModel.GetScoreOfDeclaringPeaceForClan
                      └ DefaultDiplomacyModel.GetRelationScore   ← NRE здесь
```

Ванильный код (декомпиляция `TaleWorlds.CampaignSystem.dll`,
`DefaultDiplomacyModel`, строка 1249):

```csharp
private static float GetRelationScore(IFaction factionDeclaresWar,
                                      IFaction factionDeclaredWar,
                                      IFaction evaluatingFaction)
{
    int relationWithClan  = factionDeclaresWar.Leader.Clan.GetRelationWithClan(...);
    int relationWithClan2 = evaluatingFaction.Leader.Clan.GetRelationWithClan(...);
```

Ваниль без проверок берёт `Leader.Clan`. Достаточно одного клана, у которого
лидер есть, а `лидер.Clan == null`.

## 2. Кто этот клан — найдено в дампе

Перебор кучи (`dotnet-dump analyze`):

| что искали | результат |
|---|---|
| объектов `Clan` | 146 |
| кланов с `_leader == null` | 7 — все с `_kingdom == null` (бандитские фракции, в королевские решения не попадают) |
| **лидеров клана с `_clan == null`** | **1** |

Этот один — герой `CharacterObject_10088`, имя **`endorphine13`**
(адрес `0000020b125415c8`, `_heroState=1` — жив и активен, `_clan = null`,
`_supporterOf = null`).

Клан, который всё ещё считает его лидером (блок 131):
`[BLink] Рой пчел`, `_tier = 5`, **`_isEliminated = 1`**, но
**`_kingdom = 0000020b126cb888`** — а это ЖИВОЕ королевство
(`_isEliminated = 0`, свой правящий клан на месте).

То есть уничтоженный клан продолжает числиться в живом королевстве и держит
ссылку на лидера, которого в нём нет. `KingdomDecisionProposalBehavior`
перебирает кланы королевства, доходит до него, и `evaluatingFaction.Leader.Clan`
даёт null.

## 3. Как это состояние создал мод

Лог мода `bannerlordlink_20260922.txt`, дважды за сессию (12:07:33 и 12:28:55):

```
[leave_clan] @endorphine13: handler called, processing...
[leave_clan] @endorphine13: leader без членов → ChangeClanLeaderAction.ApplyWithoutSelectedNewLeader OK
[leave_clan] @endorphine13: public setter OK (clan=null verified)
[leave_clan] @endorphine13: left '[BLink] Рой пчел' → wanderer
```

`LeaveClanHandler.cs` для случая «лидер без членов» зовёт
`ChangeClanLeaderAction.ApplyWithoutSelectedNewLeader(clan)`, а в комментарии
над вызовом написано, что этот API «сам убирает leader без killing hero».
**Это неверно.** Декомпиляция:

```csharp
private static void ApplyInternal(Clan clan, Hero newLeader = null)
{
    Hero leader = clan.Leader;
    if (newLeader == null)
    {
        Dictionary<Hero, int> heirApparents = clan.GetHeirApparents();
        if (heirApparents.Count == 0)
        {
            return;            // ← молча НИЧЕГО не делает
        }
        ...
    }
    ...
    clan.SetLeader(newLeader);
}
```

Нет членов → нет наследников → метод **возвращается, не тронув `_leader`**.
Мод печатает «OK», затем сам зануляет `hero.Clan` и проверяет… `hero.Clan == null`
— то есть ровно то, что только что записал сам. Наблюдаемый эффект вызова
(`clan.Leader != hero`) не проверяется никогда.

Это наш собственный класс дефекта из `CLAUDE.md`: **«Платное действие обязано
детектить тихий no-op ДО ack-true… детект по НАБЛЮДАЕМОМУ эффекту, не по копии
внутренней формулы движка»**. Здесь проверка смотрела на свою же запись, а не
на результат чужого вызова.

Отдельно: комментарий в коде ссылается на BLT (`ClanManagement.cs:802`) как на
образец. Даже если у BLT так и есть, для 1.4.8 утверждение о поведении API
ложно — а проверено оно не было.

## 4. Почему упало именно в 13:10, а не сразу

Состояние создано в 12:28. Ваниль трогает `GetRelationScore` только когда
королевство заводит решение о мире — это суточный тик. Первый тик после
поломки пришёлся на 13:10:20 (`Before Daily Tick: Весна, 3 день, 1131 год`),
и на нём же лог мода обрывается.

Поэтому в логе нет ни `CRASHED`, ни записи глобального хука: исключение
прилетело внутри ванильного тика, и процесс умер.

## 5. Что чинить

**Срочно, иначе повторится:** сейв уже содержит битый клан. Даже с исправленным
модом старый сейв упадёт на следующем игровом дне.

1. **Не создавать это состояние.** В `LeaveClanHandler` после вызова API
   проверять НАБЛЮДАЕМОЕ: `clan.Leader != hero`. Не сработало (нет наследников)
   — не выдумывать полусостояние, а довести до конца: вывести клан из
   королевства и занулить `_leader` (fallback в коде уже есть), либо отказать
   зрителю с возвратом. Молча оставлять висящую ссылку нельзя.
2. **Починить существующие сейвы.** Пройти на `OnGameLoadFinished` по всем
   кланам и вылечить те, где `Leader == null` при наличии королевства или
   `Leader.Clan != clan`: снять клан с королевства и занулить лидера. Это
   ремонт входа, а не глушение исключения — как требует правило
   «Vanilla NRE: чинить причину, prefix чинит вход».
3. **Бэкстоп.** Prefix на `DefaultDiplomacyModel.GetRelationScore`, который при
   битой фракции пишет в лог имя клана и возвращает 0 вместо падения. Только
   как страховка поверх пунктов 1–2, не вместо них.

## 6. Границы этого разбора

- Причина падения доказана стеком из дампа, состоянием объектов в дампе и
  декомпиляцией ванильного метода. Это не гипотеза.
- **Фикса нет** — в код не лез: живая ветка `codex/poststream-fixes-20260922`
  в работе у смены Codex.
- Не проверено, сколько ещё зрителей проходили этот путь раньше: в логе 22.09
  он виден у `endorphine13` дважды. По другим дням не искал.
- Семь бандитских кланов без лидера — ванильная норма (они вне королевств), к
  крашу отношения не имеют; их имена я не разрешал.
- Связь с багрепортами #61/#62 (королевство без главы, влияние на политику из
  мёртвого клана) вероятна по симптомам, но отдельно не доказана.
