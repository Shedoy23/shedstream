// Поведение зеркала состояния героя: снимок считается доставленным только
// после подтверждения бэкендом.
//
// ЧТО ЭТО ПРОВЕРЯЕТ. До 2026-09-09 `HeroStateSync.PushIfChanged` писал хэш в
// кэш ДО отправки и выбрасывал её результат. Сбой сети означал, что кэш уже
// утверждает «доставлено», и неизменившийся снимок не уходил НИКОГДА — зеркало
// замерзало до следующего изменения героя. Отдельно `BackendClient` считал
// подтверждением наличие `"status":"ok"` в теле, хотя бэкенд отвечает так
// ВСЕГДА, а отказ конверта лежит внутри `acks[].success`.
//
// Harness подключает настоящие `StateSyncTracker` и `EventAckParser` (см.
// csproj), поэтому проверяется рабочий механизм, а не пересказ алгоритма.

using System;
using System.Collections.Generic;
using BannerlordLink.Net;
using BannerlordLink.Util;

var failures = new List<string>();

void Check(string name, bool ok, string detail = null)
{
    Console.WriteLine((ok ? "  OK   " : "  FAIL ") + name);
    if (!ok)
    {
        if (detail != null) Console.WriteLine("       " + detail);
        failures.Add(name);
    }
}

const string StateA = "{\"gold\":100,\"level\":5}";
const string StateB = "{\"gold\":250,\"level\":6}";

// ── a) отправка не прошла, состояние не изменилось → шлём снова ──────────────
{
    var t = new StateSyncTracker();
    var sent = t.TryBeginSend("alice", StateA, out var first);
    t.Fail(first);                                  // сеть отвалилась
    var again = t.TryBeginSend("alice", StateA, out _);
    Check("a) после неудачи тот же снимок отправляется снова",
          sent && again,
          $"первая отправка={sent}, повтор={again} (ожидалось true/true)");
}

// ── b) отправка прошла → без изменений не повторяем ─────────────────────────
{
    var t = new StateSyncTracker();
    t.TryBeginSend("alice", StateA, out var first);
    var confirmed = t.Confirm(first);
    var again = t.TryBeginSend("alice", StateA, out _);
    Check("b) подтверждённый снимок повторно не отправляется",
          confirmed && !again,
          $"подтверждение={confirmed}, повтор={again} (ожидалось true/false)");
}

// ── c) итог НА СЕРВЕРЕ, а не локальные флаги ────────────────────────────────
// Первая версия этого сценария сравнивала только локальные подтверждения и была
// зелёной при живой дыре: сервер мог применить задержавшийся A ПОСЛЕ B, и в базе
// оставался устаревший снимок, а локально значилось «B подтверждён» — повтора не
// будет никогда. Внешняя проверка воспроизвела это на настоящем классе:
//   server=A actual=B staleAckAccepted=False resend=False
// Поэтому здесь моделируется СЕРВЕР с произвольным порядком применения, и
// проверяется его итоговое состояние.
{
    // Модель сервера: применяет снимки в том порядке, в каком к нему приходят.
    string serverState = null;
    var t = new StateSyncTracker();

    // Тик 1: состояние A — уходит.
    var startedA = t.TryBeginSend("alice", StateA, out var attemptA);
    // Тик 2: состояние уже B, но ответа по A ещё нет.
    var startedB = t.TryBeginSend("alice", StateB, out var attemptB);

    Check("c1) вторая отправка не стартует, пока первая в полёте",
          startedA && !startedB,
          $"A стартовала={startedA} (ждали true), B стартовала={startedB} (ждали false)");

    // Сервер применяет ТО, ЧТО РЕАЛЬНО УЛЕТЕЛО, и в худшем реалистичном
    // порядке: сеть не обязана сохранять очерёдность. Если параллельные
    // отправки разрешены (поведение до правки), моделируем именно ту
    // перестановку, которую нашла внешняя проверка: сначала B, потом
    // задержавшийся A — и в базе остаётся A.
    if (startedB)
    {
        serverState = StateB; t.Confirm(attemptB);
        serverState = StateA; t.Confirm(attemptA);   // A догнал и перезаписал
    }
    else
    {
        serverState = StateA; t.Confirm(attemptA);
        // Следующий тик: отправка свободна, состояние героя — B.
        if (t.TryBeginSend("alice", StateB, out var attemptB2))
        {
            serverState = StateB;
            t.Confirm(attemptB2);
        }
    }

    Check("c2) на сервере в итоге НОВЫЙ снимок, а не задержавшийся старый",
          serverState == StateB,
          $"на сервере {(serverState == StateA ? "A (устаревший)" : serverState ?? "ничего")}, "
          + "ожидался B; и повтора не будет — зеркало замерзает");

    // И зеркало успокаивается: актуальное состояние подтверждено, лишних пушей нет.
    Check("c3) после доставки B повторных отправок не требуется",
          !t.TryBeginSend("alice", StateB, out _));
}

// ── d) callback из прошлой сессии не портит кэш нового сейва ────────────────
{
    var t = new StateSyncTracker();
    t.TryBeginSend("alice", StateA, out var beforeLoad);
    t.ResetForNewSession();                              // загрузили другой сейв
    var acceptedAfterLoad = t.Confirm(beforeLoad);       // ответ прошлой сессии
    var needsSend = t.TryBeginSend("alice", StateA, out _);
    Check("d) подтверждение прошлой сессии отвергается, новый сейв синкается",
          !acceptedAfterLoad && needsSend && t.ConfirmedCount == 0,
          $"принято={acceptedAfterLoad} (ждали false), нужен пуш={needsSend} (true), "
          + $"подтверждённых={t.ConfirmedCount} (0)");
}

// ── e) явный отказ события не помечает снимок доставленным ─────────────────
{
    // Настоящие формы ответа бэкенда (routes/module_api.py).
    const string rejectedManifest =
        "{\"status\": \"ok\", \"acks\": [{\"id\": \"e1\", \"success\": false, "
        + "\"error\": \"event_not_in_manifest\"}]}";
    const string rejectedHandler =
        "{\"status\": \"ok\", \"acks\": [{\"id\": \"e1\", \"success\": false, "
        + "\"error\": \"KeyError: 'username'\"}]}";
    const string accepted =
        "{\"status\": \"ok\", \"acks\": [{\"id\": \"e1\", \"success\": true}]}";
    const string acceptedDuplicate =
        "{\"status\": \"ok\", \"acks\": [{\"id\": \"e1\", \"success\": true, \"duplicate\": true}]}";
    const string noAcks = "{\"status\": \"ok\"}";

    var manifestAcked = EventAckParser.IsAcked(rejectedManifest, out var e1);
    var handlerAcked = EventAckParser.IsAcked(rejectedHandler, out _);
    var okAcked = EventAckParser.IsAcked(accepted, out _);
    var dupAcked = EventAckParser.IsAcked(acceptedDuplicate, out _);
    var emptyAcked = EventAckParser.IsAcked(noAcks, out _);

    Check("e1) отказ конверта внутри status=ok НЕ считается подтверждением",
          !manifestAcked && !handlerAcked,
          $"manifest={manifestAcked}, handler={handlerAcked} (ожидалось false/false); "
          + $"причина manifest: {e1}");
    Check("e2) настоящий ACK и дубликат считаются подтверждением",
          okAcked && dupAcked,
          $"ack={okAcked}, duplicate={dupAcked} (ожидалось true/true)");
    Check("e3) ответ без acks подтверждением не считается",
          !emptyAcked);

    // И связка: отклонённое событие оставляет снимок неподтверждённым.
    var t = new StateSyncTracker();
    t.TryBeginSend("alice", StateA, out var attempt);
    if (!EventAckParser.IsAcked(rejectedManifest, out _)) t.Fail(attempt);
    var resend = t.TryBeginSend("alice", StateA, out _);
    Check("e4) после отказа события снимок уходит повторно",
          resend && t.ConfirmedCount == 0);
}

Console.WriteLine();
if (failures.Count > 0)
{
    Console.WriteLine("ПРОВАЛЕНО: " + string.Join("; ", failures));
    return 1;
}
Console.WriteLine("ВСЁ ЗЕЛЁНОЕ");
return 0;
