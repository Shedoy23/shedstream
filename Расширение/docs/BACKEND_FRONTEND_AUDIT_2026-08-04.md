# Аудит backend и Twitch frontend 0.0.2 — 2026-08-04

## Итог

Backend и текущий frontend-кандидат 0.0.2 прошли аудит, регрессионные проверки и развернуты на production `shedoy23.ru`. Production отвечает штатно, база цела, очередь игровых действий не содержит зависших записей. Архив Twitch frontend 0.0.2 собран отдельно, но не загружался и не публиковался через Twitch Developer Console: этот этап требует Hosted Test, Review и Release в консоли Twitch.

## Исправленные проблемы

### Критическая: потеря возврата валюты при отрицательном ACK

Раньше `success=false` мог сначала перевести действие в терминальное состояние, а затем потерять исключение при неудачном возврате валюты. Повтор ACK уже не мог безопасно завершить refund.

Теперь receipt отрицательного ACK записывается без терминального перехода, refund и перевод действия в `failed` выполняются атомарно. При ошибке backend возвращает HTTP 503 `refund_retry_required`, оставляет действие доступным для повтора и не допускает двойной возврат. Поле `success` принимается только как JSON boolean, текстовое `"false"` отклоняется с HTTP 400.

### Высокая: подмена Twitch user id

Удален неаутентифицированный fallback по числовому `opaque_id` и lookup кэша до проверки подписи. Идентификатор пользователя теперь берется только из проверенного Twitch JWT. Клиентский alias кэшируется только при совпадении с подписанными claims.

### Совместимость с опубликованной 0.0.1

Возвращен безопасный read-only `GET /api/event/status` с инертным ответом старого формата. Удаленные mutation endpoints `/api/event/contribute` и `/api/event/bid` остаются 404.

Опубликованный клиент 0.0.1 продолжает работать с текущим backend по основным контрактам. Его старые анонимные запросы статуса RimWorld остаются 401 по проектному решению: в них нет JWT и channel identity, поэтому поддержать их без утечки данных между каналами невозможно. В 0.0.2 эти запросы отправляются с JWT и учитывают жизненный цикл активного модуля.

Точный исходный ZIP 0.0.1 локально отсутствует. Для полного бинарного сравнения его нужно выгрузить из Twitch Developer Console; восстановление по текущему git не считается эквивалентным артефактом.

### Средняя: контракт кэша подписок

Внутренний sentinel отрицательного кэша `-1` больше не выходит наружу как tier подписки. Публичный результат для отсутствующей подписки — `None`.

### Twitch review hygiene

- Убраны вводящие в заблуждение упоминания Bits: игровая механика питомцев использует только внутренние кристаллы.
- Подписка Twitch не дает игрового преимущества; сохраняется только косметический бейдж.
- Убран видимый Boosty badge из 0.0.2, чтобы не выводить сторонний продуктовый брендинг в Twitch Extension. Поле backend сохранено ради совместимости с 0.0.1.
- Текст раскрытия внутренней валюты описывает награду за активность на канале, а не за финансовую поддержку.
- В Twitch-архив не включается OBS-only `overlay.html`; в extension/mobile shells нет inline scripts или inline handlers.

## Проверки

- Backend standalone tests: 40/40.
- Критический ACK/refund regression suite: 36 проверок, включая падение refund и безопасный retry.
- Frontend module lifecycle: 9/9.
- Python `compileall`: успешно.
- Синтаксис всех frontend JavaScript файлов: успешно.
- Consistency lint: успешно; остается одно известное предупреждение о 20 Bannerlord policies, которые пока не представлены в UI-каталоге расширения.
- Twitch pack validation: 22 файла, 822.5 KB без сжатия.
- Browser smoke production: desktop и mobile загружаются без console errors/warnings; inline scripts отсутствуют; на viewport 360×800 горизонтального переполнения нет.

## Production и данные

- Supervisor service `twitchbot`: RUNNING после перезапуска.
- `https://shedoy23.ru/health`: `status=ok`, `db=ok`.
- SQLite `PRAGMA integrity_check`: `ok`.
- Отрицательных балансов: 0.
- Зависших `dispatched` старше 2 минут: 0.
- `queued` старше 10 минут: 0.
- Дубликатов action id: 0.
- Свежих traceback/syntax/import/critical записей после deploy: 0.
- Перед deploy создан rollback-архив `/root/deploy-backups/shedlink-code-pre-20260804-0525.tar.gz`.

## Артефакт 0.0.2

- Путь: `dist/shedlink-0.0.2.zip`
- Размер: 225569 bytes
- SHA-256: `01D86E562F27A19BF59EF7C072B66B27209466BD72CFBCBBE96B1B801B4B62EB`
- Cache bust frontend assets: `202608040521`
- Source provenance: git base `ae846573e2c234744eacfc9e1084f0c561eeab40` плюс аудированные изменения текущего worktree.

## Что еще требует Twitch Developer Console

Twitch требует загрузить новую версию, проверить ее в Hosted Test, отправить на Review и только после одобрения выполнить Release. При rollout backend должен одновременно принимать трафик старого и нового frontend. Поэтому production backend уже совместим с 0.0.1 и 0.0.2, но сам ZIP 0.0.2 еще не считается опубликованным Twitch-релизом.

Официальные источники:

- https://dev.twitch.tv/docs/extensions/life-cycle
- https://dev.twitch.tv/docs/extensions/guidelines-and-policies/
- https://dev.twitch.tv/docs/extensions/monetization/
- https://dev.twitch.tv/docs/extensions/reference/

