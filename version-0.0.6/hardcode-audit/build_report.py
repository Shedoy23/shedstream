"""Build the human-readable audit from reviewed findings, without touching runtime."""
from pathlib import Path
import collections
import hashlib
import json

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
SOURCES = ['frontend.json', 'backend.json', 'connectors.json', 'supplemental.json']
CLASS_LABELS = {
    'game_truth': 'Игровые сведения/правила заменены нашей копией или выводом',
    'duplicated_platform_policy': 'Собственное правило/баланс продублирован между слоями',
    'adapter_constraint': 'Ограничение формата или возможностей адаптера',
    'platform_policy_ok': 'Обоснованная политика/контракт или уже динамический путь',
    'legacy_inactive': 'Неактивное/историческое; не считать текущей зрительской поломкой',
}
STATUS_LABELS = {'active': 'действующий путь', 'fallback': 'запасной/совместимый путь',
                 'inactive': 'неактивно/история', 'uncertain': 'доступность/условия требуют уточнения'}


def read(name):
    return json.loads((OUT / name).read_text(encoding='utf-8-sig'))


def write(name, value):
    (OUT / name).write_text(value, encoding='utf-8', newline='\n')


def source_link(e):
    label = f"{e['path']}:{e['line']}"
    return f"[{label}]({(ROOT / e['path']).as_posix()}:{e['line']})"


def main():
    documents = {name: read(name) for name in SOURCES}
    findings = [item for document in documents.values() for item in document['findings']]
    ids = [f['id'] for f in findings]
    assert len(ids) == len(set(ids)), 'Duplicate finding id'
    evidence_quotes = []
    for f in findings:
        for field in ['id', 'title', 'classification', 'priority', 'status', 'problem',
                      'impact', 'desired_source', 'recommendation', 'verification']:
            assert isinstance(f[field], str) and f[field].strip(), (f['id'], field)
        assert f['classification'] in CLASS_LABELS, (f['id'], f['classification'])
        assert f['status'] in STATUS_LABELS, (f['id'], f['status'])
        assert f['priority'] in {'P1', 'P2', 'P3', 'INFO'}, f['id']
        assert f['evidence'], f['id']
        for e in f['evidence']:
            file = ROOT / e['path']
            assert file.is_file(), (f['id'], e['path'])
            text = file.read_text(encoding='utf-8-sig').splitlines()
            start, end = e['line'], e.get('end_line', e['line'])
            assert 1 <= start <= end <= len(text), (f['id'], e, len(text))
            evidence_quotes.append({'finding': f['id'], **e,
                                    'source_sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                                    'quoted_lines': '\n'.join(f'{i+1}: {text[i]}' for i in range(start-1, min(end, start+11))),
                                    'quote_truncated': end-start+1 > 12})
    inventory = read('inventory.json')
    summary = read('inventory-summary.json')
    reviewed = set(path for doc in documents.values() for path in doc.get('reviewed_files', []))
    coverage = [{**f, 'review': 'targeted source reading' if f['path'] in reviewed else 'lexical scan only'} for f in inventory]
    stats = {'findings': len(findings),
             'classifications': dict(collections.Counter(f['classification'] for f in findings)),
             'statuses': dict(collections.Counter(f['status'] for f in findings)),
             'priorities': dict(collections.Counter(f['priority'] for f in findings)),
             'scanned_files': len(inventory),
             'targeted_files_in_scanned_scope': sum(f['path'] in reviewed for f in inventory),
             'source_commit': summary['source_commit']}
    write('all-findings.json', json.dumps({'summary': stats, 'findings': findings}, ensure_ascii=False, indent=2)+'\n')
    write('coverage.json', json.dumps(coverage, ensure_ascii=False, indent=2)+'\n')
    write('evidence-quotes.json', json.dumps(evidence_quotes, ensure_ascii=False, indent=2)+'\n')

    lines = [
        '# ShedLink 0.0.6 — аудит игровых хардкодов',
        '',
        'Дата: 28.09.2026. Проверена локальная копия `C:/Users/Edward/Desktop/work/0.0.6`.',
        f"Исходный коммит аудита: `{summary['source_commit']}`. Runtime-код в этой задаче не изменялся.",
        '',
        '## Главный вывод',
        '',
        'Чтобы новые предметы, культуры, законы и другие сущности из модов появлялись без правок JS/Python, недостаточно добавить выгрузку каталога из игры. Нужно сохранить идентификаторы, метаданные и доступность через все слои. Сейчас есть одновременно закрытые списки, ограниченные проекции, выводы по именам/тирам и копии балансовых правил.',
        '',
        f"В реестре **{len(findings)} групп наблюдений**. Это не {len(findings)} независимых багов: одна цепочка может иметь отдельные ограничения в моде, backend и UI; среди записей также допустимые политики, рабочие динамические пути и неактивная история.",
        '',
        '### Самые важные цепочки',
        '',
        '| Область | Что мешает | Что должно приходить из игры |',
        '|---|---|---|',
        '| Культуры героя | Шесть вариантов в JS и Python; отсутствие шаблона может подменить выбор случайным | Реальные культуры, названия, пригодность для создания и причина отказа |',
        '| Законы и мастерские | Ручные списки и описания; наличие объектов в игре не делает их видимыми | ID, игровые названия/описания, типы мастерских, контекстная доступность |',
        '| Навыки/атрибуты | Динамические данные встречаются с vanilla словарями и пределами UI; модовые поля теряются | Descriptors, labels, ranges, progression, разрешённые операции |',
        '| Вещи | Shop filter подменяет перечень имущества; tiers/slots/stats закрыты; extra stats отбрасываются | Все представимые сущности отдельно от sellable/equippable, typed stats и совместимость |',
        '| Свита/кланы | Конец ветки выводится по тиру, часть цен/вместимости считается вне игры, лидерство угадывается по имени | Upgrade targets, capacity, quote, clan/leader IDs и availability |',
        '| RimWorld: тело и импланты | Human/left-right/первый рецепт не представляют произвольную анатомию и операции | Recipe ID, конкретные body-part targets, условия и поддерживаемый executor |',
        '| RimWorld: исследования/события | Эпоха названа исследованием; одинаковые labels удаляют разные события; limits расходятся | Реальные условия, стабильные IDs, фактически исполняемые параметры |',
        '| ShedColony | Backend задаёт конечные списки; ответ игры в основном вычитает отсутствующее | Положительный каталог текущего инстанса, профессии, skills, job capabilities |',
        '',
        '## Что доказано исполнением текущего кода',
        '',
        'Скрипты воспроизводят **имеющееся поведение**, а не проверяют исправление. Exit 0 означает, что ожидаемый дефект/ограничение воспроизведён. Это изолированное исполнение Python/Node, не живая игра и не Twitch browser.',
        '',
        '| Проверка | Наблюдение | Доказательство |',
        '|---|---|---|',
        '| Текущий renderer прогрессии | Полученный `ModMagic` не показан, отсутствующий vanilla навык показан | `frontend-probe.cjs`, `frontend-probe-results.json` |',
        '| Тот же renderer | Focus 6 и attribute 11 дают RangeError | Те же файлы; VM с минимальным DOM |',
        '| Renderer/сравнение вещей | `mod_magic_damage` теряется при сохранении известного `swing_dmg` | Те же файлы |',
        '| Реальные store_catalog/buy_reason | tier4/required_level1 становится required_level25; level24 получает level_locked; synthetic tier7 не сохраняется | `backend-probe.py`, `backend-probe.log`; SQLite :memory: |',
        '',
        '**Граница вывода о tier7:** текущий BannerLink сам нормализует public tier до 1..6. Проба показывает закрытость backend-контракта для нового payload, а не доказывает, что установленный мод уже отправляет tier7 или что конкретный предмет исчез в игре. Таблицы уровня сейчас могут совпадать; проблема — двойное владение правилом при изменении.',
        '',
        '## Объём и честные границы',
        '',
        f"Автоматический текстовый проход: **{len(inventory)} файлов, {summary['lines_scanned']:,} строк**, без тестов/сборочных output. {summary['candidate_lines']:,} совпадений — только кандидаты. Релевантные участки **{stats['targeted_files_in_scanned_scope']} файлов** дополнительно прочитаны по цепочкам. Это не утверждение построчного семантического аудита всех {len(inventory)} файлов.",
        '',
        '| Слой | Файлов в текстовом проходе | Файлов с точечным чтением |',
        '|---|---:|---:|',
    ]
    for layer in summary['by_layer']:
        scope = [f for f in inventory if f['layer']==layer]
        lines.append(f"| {layer} | {len(scope)} | {sum(f['path'] in reviewed for f in scope)} |")
    lines += [
        '',
        '- Полный состав и SHA: `inventory.json`; метод и регулярные выражения: `inventory.py`; кандидаты: `candidates.json`; степень покрытия каждого файла: `coverage.json`.',
        '- Точные excerpts и SHA файлов для каждой ссылки: `evidence-quotes.json`. Ссылки ниже проверены на существование и границы строк; это не заменяет смысловую проверку утверждения.',
        '- CodeGraph вернул `database is locked`; графовый охват не заявляется. Текстовый поиск использован как fallback.',
        '- Minecraft game-side исходник не находится в копии. Для ShedColony проверены доступные backend/frontend/manifest пути, но не реализация отдельного Java-мода.',
        '- Runtime состояние БД, настройка feature flags у стримера, установленная DLL/JAR, конкретная сборка модов, браузер Twitch и live game не проверялись.',
        '- Миграции включены в текстовый проход; существование старого seed не делает его актуальным runtime источником. В реестр включены только названные цепочки либо явно помеченная история.',
        '- Manager и автопилот рассмотрены дополнительно для отделения ограничений адаптера/установки от копий игровых каталогов. Это не новый native-crash или installation-security аудит.',
        '',
        '## Как читать приоритеты и классификацию',
        '',
        '**P1** — первым в миграции: закрывает целую категорию контента, даёт неверный факт/отказ/обещание или ломает показ. **P2** — следующее: частичная потеря свойств, дублирование, узкая совместимость. **P3** — локализация/удобство/ограниченный край. **INFO** — сохранить как политику/контракт или не считать активным дефектом. Это приоритет работы над 0.0.6, не декларация аварии production.',
        '',
    ]
    for key,label in CLASS_LABELS.items():
        lines.append(f"- **{key}** ({stats['classifications'].get(key,0)}): {label}.")
    lines += [
        '',
        'В частности, action allowlist является границей исполнения, а не списком всех предметов: его нельзя просто удалить. Проверки identity/tenant, формата/размера payload, платформенной оплаты и доверия остаются на backend. Игровой catalog ID не выдаёт право выполнить произвольный код.',
        '',
        '## Что оставить собственным правилом ShedLink',
        '',
        '- Цены в крустиках, rate limits, права и лимиты платформы, собственные достижения/классы/силы — могут оставаться разработанным продуктом. Требуется единый владелец и согласованный показ.',
        '- Динаровая цена, если это собственная цена услуги BannerLink, тоже не обязана быть ванильной формулой. Её нельзя выдавать за native game price и независимо пересчитывать в трёх местах; публиковать effective quote от владельца правила.',
        '- Аварийный blocklist проблемного товара, запрет неподдерживаемой операции и versioned executor — нормальные ограничения. Отличать «существует в мире» от «показать» и от «можно продать/применить».',
        '- Native API/member names, поддерживаемые версии установки и сигнатуры артефактов — контракт адаптера/поставки. Их сохранение не противоречит динамическим каталогам.',
        '',
        '## План исправлений после этого аудита',
        '',
        '1. Зафиксировать владельца каждого поля: game fact, game-addon policy, platform policy или presentation. Не переносить прежний vanilla список из JS в новый Python/YAML и не называть это game discovery.',
        '2. Первый срез — cultures + policies + workshop types и расширение каталога предметов. Версии, session/save/modpack scope, replace/delete semantics, freshness и локализованные метаданные обязательны.',
        '3. Сохранить данные через backend: schema/registry, неизвестные поддерживаемые extensions, units/ranges; прекратить тихую подмену game-полей своими defaults. UI получает реальные entries, а не дополняет отсутствующие vanilla строки.',
        '4. Availability и quote получать для конкретного actor/target/context. До исполнения игра повторяет проверку; backend повторяет свои проверки оплаты/identity. Отказ по имени клана или предполагаемому концу дерева убрать по мере переноса.',
        '5. Проверить тот же подход на RimWorld: навыки/тело/рецепты/события. Для ShedColony заменить subtract-only проверку полноценным runtime registry; потребуется работа в отдельном проекте Java-коннектора.',
        '6. Сохранить 0.0.5 через compatibility adapter и поимённую миграцию действий. Устаревшую и неподдерживаемую capability показывать честно. Полный перенос и любые игровые изменения — следующая работа, в этом аудите не сделаны.',
        '',
        '### Критерий приёмки',
        '',
        'Добавить модовый предмет/культуру/закон/навык с новым ID и названием → сущность появляется без правки JS/Python-списков. Изменить диапазон или свойство → интерфейс показывает присланное значение без падения. Изменить доступность → кнопка/причина обновляется. Сменить сейв/модпак → исчезнувшие сущности не продолжают продаваться. Действие с неподдерживаемой механикой даёт явный отказ; существование карточки не обещает исполнение.',
        '',
        'Проверять отдельными fixtures: неизвестный ID; одинаковый label у двух IDs; нестандартный max/tier/stat/body part; пустой актуальный каталог; stale/partial snapshot; отключённая capability; смена сессии; changed quote; повтор запроса; старый клиент. Затем отдельный игровой прогон на реальном модпаке.',
        '',
        'Независимый перекрёстный разбор 10 кандидатов: [review-cross-layer.md](review-cross-layer.md). Четыре цепочки подтверждены без уточнений, шесть уточнены по достижимости, владельцу правил или фактическому UX. Поправки внесены в итоговый реестр.',
        '',
        '## Проверки и воспроизводимость',
        '',
        '- Существующие `test_rimworld_catalog_gate.py`, `test_shedcolony_item_catalog.py`, `test_shedcolony_catalog_check.py` выполнены в изолированном окружении: exit 0. Они характеризуют нынешнее поведение и **не доказывают** будущую архитектуру. В частности, зелёный тест ShedColony подтверждает действующий fallback при all-missing, который новый контракт должен пересмотреть.',
        '- `test_catalog_blocklist.py`: сначала exit 1 из-за двух разных временных DB (`DB_PATH` и жёсткий `Database("viewers.db")` внутри теста); после согласования этих путей — exit 0. Код теста/продукта не менялся. Вывод wrapper после успешного второго subprocess получил отдельный UnicodeEncodeError печати; сохранённый exit subprocess равен 0. Логи и все результаты в `checks/`.',
        '- Проверки blocklist частично поведенческие (приём/сохранение), частично структурные (serve/buy): не выдавать их за полный E2E.',
        '- Исполняемые пробы: `node version-0.0.6/hardcode-audit/frontend-probe.cjs`; `python version-0.0.6/hardcode-audit/backend-probe.py`. Они извлекают/импортируют текущие функции, не повторяют реализацию целиком.',
        '- Финальные проверки JSON, ссылок, неизменности runtime и исходного frozen ZIP записаны в `audit-verification.json` после сборки отчёта. Новую DLL/ZIP 0.0.6 не собирали.',
        '',
        '## Реестр наблюдений',
        '',
        '| ID | Приоритет | Путь | Наблюдение |',
        '|---|---|---|---|',
    ]
    for f in findings:
        lines.append(f"| [{f['id']}](#{f['id'].lower()}) | {f['priority']} | {STATUS_LABELS[f['status']]} | {f['title']} |")
    for f in findings:
        lines += ['', f"<a id=\"{f['id'].lower()}\"></a>", f"### {f['id']} — {f['title']}", '',
                  f"**{f['priority']} · {STATUS_LABELS[f['status']]} · {f['classification']}**", '',
                  f"**Наблюдение:** {f['problem']}", '', f"**Последствие:** {f['impact']}", '',
                  f"**Источник истины:** {f['desired_source']}", '', f"**Направление изменения:** {f['recommendation']}", '',
                  '**Код:**', '']
        for e in f['evidence']:
            lines.append(f"- {source_link(e)} — {e.get('detail','')}")
        lines += ['', f"**Проверка/граница:** {f['verification']}"]
    lines += ['', '## Ограничения отраслевых проходов', '']
    for name,doc in documents.items():
        lines += [f'### {name}', '']
        for limit in doc.get('limits',[]):
            lines.append(f'- {limit}')
        lines.append('')
    write('HARDCODE_AUDIT.md', '\n'.join(lines).rstrip()+'\n')
    write('audit-summary.json', json.dumps(stats, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(stats, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
