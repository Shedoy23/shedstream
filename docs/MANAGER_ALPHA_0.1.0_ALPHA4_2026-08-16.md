# ShedLink Manager 0.1.0-alpha.4

Дата: 2026-08-16

## Назначение

Первая передаваемая multi-game сборка. Стример выбирает RimWorld или
Mount & Blade II: Bannerlord, после чего Manager использует манифест выбранной
игры для поиска, установки, конфигурации и диагностики. Дашборд стримера в
Manager не переносился.

## Артефакт

- файл: `dist/releases/ShedLink.Manager-0.1.0-alpha.4-win-x64.zip`;
- SHA-256:
  `9ba1f2ef3b7cb61348897f52bad693bb8ee383e434e1e1706cd6db6fd2ae1f03`;
- source commit: `08827e9e871a`;
- runtime: self-contained Windows x64.

В архиве ровно пять файлов:

- `ShedLink.Manager.App.exe`;
- `START-HERE.txt`;
- `RELEASE.json`;
- `Release/rimworld-0.1.1.json`;
- `Release/bannerlord-0.1.0.json`.

## Проверка

- Manager Core self-test: код `0`;
- Release build: код `0`, предупреждений и ошибок нет;
- SHA-256 архива совпадает с `.sha256`;
- `RELEASE.json` указывает на фактический source commit;
- PDB, XML documentation, private key, token и `config.json` отсутствуют;
- RimWorld и Bannerlord manifests прошли независимый verifier с кодом `0`;
- опубликованный Bannerlord архив повторно скачан по HTTPS и совпал по байтам.

Живой путь Bannerlord до `Technical Ready` ещё требует запуска Manager и игры
владельцем; автоматическая и выпускная части готовы.

