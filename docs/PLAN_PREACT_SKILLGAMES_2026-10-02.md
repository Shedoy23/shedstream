# План на ночь: мини-игры с React на Preact (для Астры)

Владелец 02.10: «30 раз меньше звучит вкусно» — попробовать Preact вместо React в `frontend-next`.
Ветка: работать от `feature/skill-minigames` (GitHub), свою — `feature/skillgames-preact`.
Ничего не выкладывать на прод и не подавать в Twitch: результат — ветка + отчёт.

## Почему

`frontend-next/vite.config.ts`: `minify: false` — намеренно, чтобы ревьюер Twitch читал код.
Несжатый React 19 (`react` + `react-dom`) = чанк `jsx-runtime-*.js` 566 КБ из 661 КБ всей сборки.
Правила Twitch: мобильная первая загрузка ≤ 1 МБ (§3.2) и < 3 с на ~500 Кбит/с (§3.3) — при 661 КБ
без сжатия это ~10 с. Отказ 24.08 был именно по мобильному правилу (§3.5), рисковать нельзя.
Preact с `preact/compat` — тот же API, ~10 КБ сжатым и десятки КБ несжатым: код остаётся читаемым.

## Шаги

1. **Замер «до».** `npm --prefix frontend-next ci && npm --prefix frontend-next run build`; записать размер
   каждого файла `dist/assets/*` и сумму, плюс gzip-размер (`gzip -9 -c f | wc -c`) — то, что реально
   уйдёт по сети с CDN.
2. **Проверить, что React 19-специфичное не используется.** `preact/compat` не поддерживает часть
   API React 19: `use(`, `useActionState`, `useOptimistic`, `useFormStatus`, `<form action=fn>`,
   `ref` как обычный prop без `forwardRef`, Server Components. `rg` по `frontend-next/src`. Найдено —
   переписать на обычные хуки/forwardRef ДО замены, отдельным коммитом с зелёными тестами.
3. **Заменить.** `npm --prefix frontend-next i preact` (последняя стабильная, закрепить точную
   версию), удалить `react`/`react-dom` из dependencies. В `vite.config.ts` — алиасы
   `react` → `preact/compat`, `react-dom` → `preact/compat`, `react/jsx-runtime` → `preact/jsx-runtime`,
   `react-dom/test-utils` → `preact/test-utils` (либо официальный `@preact/preset-vite`).
   `tsconfig`: `jsxImportSource: "preact"` или `paths` на compat — чтобы `tsc --noEmit` был зелёным.
   `minify: false` и `sourcemap: true` НЕ трогать (читаемость для ревьюера).
4. **Тесты.** `@testing-library/react` работает через алиасы на compat; если нет — `@testing-library/preact`.
   Все 107 тестов + typecheck + `run build` (включая `scripts/check-build.mjs`) зелёные. Тест,
   который не видели красным, не доказывает ничего: убедиться, что хотя бы один тест падает при
   поломке (например, подменить обработчик выстрела) и снова зеленеет.
5. **Живая проверка.** `python scripts/run-skillgames-local.py --allow-local-demo --port 4180`, две
   вкладки (`?player=alice`, `?player=bobby`): морской бой от поиска до конца партии, сапёр обеих
   сложностей до победы. Владелец сообщил: «сапёр не стартует» — у Claude стартовал с первого
   нажатия; проверить на узком экране (318 px) и после долгой генерации поля, описать, что видно.
6. **Замер «после»** тем же способом, таблица до/после (сырой и gzip). Цель: первая загрузка
   мобильной страницы мини-игр ≤ 200 КБ gzip.
7. **Лицензии.** `THIRD_PARTY_NOTICES.txt` в сборке обновить под Preact (MIT); проверка
   `check-build.mjs` про bundled licenses должна остаться зелёной.

## Критерии «готово»

- Ветка `feature/skillgames-preact` запушена; React в `dependencies` нет.
- typecheck, 107+ тестов, build и check-build — exit 0; один тест показан красным и снова зелёным.
- Морской бой и сапёр сыграны вживую на локальном стенде.
- Отчёт `docs/PREACT_SKILLGAMES_RESULT_2026-10-03.md`: таблица веса до/после, что пришлось переписать,
  что не проверено (Hosted Test Twitch, реальные телефоны).

## Не делать

- Не трогать старую панель (`Расширение/frontend/*`), бэкенд, мод, прод.
- Не включать минификацию «ради веса» без отдельного решения: Twitch требует читаемый код.
- Не сливать в `feature/skill-minigames` без отчёта — Claude проверит и сольёт.
