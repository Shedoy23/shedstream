# Унаследованный нестабильный CI-тест, 03.10.2026

Первый опубликованный panel checkpoint: `58c2e4f9fc0a74303931b7eb335144ed1439706a`.
[GitHub Actions run](https://github.com/Shedoy23/shedstream/actions/runs/37060498062).

- Попытка 1: frontend и manager-core зелёные; checks — 144/145, упал неизменённый `test_skillgames_api.py`
- Попытка 2: единственный повтор проваленных jobs, тот же SHA, итог **success**
- Локальный повтор всего скрипта: 24/24 в исходном прогоне и первых трёх повторах; четвёртый упал
- Backend, production service и его tests в этой миграции **не менялись**

## Что воспроизведено

В локальном четвёртом повторе `SkillgamesHTTPTests.test_deadline_finalizes_without_viewer_returning`
делает синхронный `sqlite3` UPDATE (строка 513), пока настоящий async heartbeat
запущен каждые 20 ms. Если heartbeat уже держит write lock, синхронный SQLite
блокирует event loop: владелец lock не может закончить transaction. Через 5 s —
`sqlite3.OperationalError: database is locked`.

Изначальный GitHub runner захватывает, но не печатает stdout/stderr отдельного
упавшего скрипта. Поэтому конкретный локальный subtest установлен точно; что
**именно он** упал в первой CI-попытке, из того журнала доказать нельзя. Это
совместимые наблюдения, не выдуманная точная диагностика удалённого провала.

Сохранены журнал первой GitHub job, полный локальный traceback и результаты
повторов. Зелёный rerun не устраняет воспроизводимый риск тестового стенда.
Это не основание отключить gate, повторять CI до зелёного или назвать flaky test
исправленным.

## Минимальное предложение, НЕ применено

Внутри только этого async-теста заменить блокирующий `with sqlite3.connect(self.path)`
на `async with self.db._connect() as conn`, затем `await conn.execute(...)` и
`await conn.commit()`. Сохранить настоящий heartbeat, deadline/elo assertions и
сценарий без возврата зрителя. Отдельный regression должен принудительно создать
конкуренцию за lock и доказать red → green, затем серия повторов.

Файл лежит внутри `Расширение/backend/`, а согласованный Preact-план запрещает
менять backend. Поэтому даже это test-only предложение оставлено на отдельное
разрешение. Продакшен heartbeat/service менять для починки теста не предлагается.
