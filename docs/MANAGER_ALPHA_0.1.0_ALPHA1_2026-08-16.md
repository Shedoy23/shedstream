# ShedLink Manager 0.1.0-alpha.1

- Дата сборки: 2026-08-16
- Runtime: Windows x64, self-contained single-file
- Source commit: `77cfebe9a28a`

## Артефакты

- архив: `dist/releases/ShedLink.Manager-0.1.0-alpha.1-win-x64.zip`;
- SHA-256 архива:
  `ee0653381561a60febcd6851a2c3a4010fb28571cfb96c596fa15a2c70a8433e`;
- размер архива: `67,831,146` bytes;
- SHA-256 EXE:
  `4f342d67312af82f51378ccbba8fc6db8b4af4426a7b815058736a5a1597ad56`;
- Product version:
  `0.1.0-alpha.1+77cfebe9a28a5f142cd7fb4bdbc896ca14298e7c`.

Рядом с ZIP создан отдельный файл `.zip.sha256`. В самом архиве находятся
только четыре файла:

```text
ShedLink.Manager.App.exe
Release/rimworld-0.1.1.json
START-HERE.txt
RELEASE.json
```

PDB, XML documentation, исходники, private key и credentials отсутствуют.

## Проверка

- publish выполнен как `win-x64`, self-contained, single-file;
- manifest `rimworld-0.1.1.json` включён;
- metadata указывает на фактический source commit;
- SHA-256 архива повторно совпал с `.sha256`;
- архив распакован в уникальную папку Windows Temp вне repository;
- упакованный EXE успешно запустился и оставался рабочим после startup;
- тестовый процесс штатно закрыт, временная папка удалена;
- Manager Core self-test и production Update/Repair rehearsal были зелёными до
  формирования alpha.

## Известное ограничение

Authenticode status EXE: `NotSigned`. Для текущей закрытой alpha это допустимо и
описано в `START-HERE.txt`; Windows может показать предупреждение неизвестного
издателя. Покупка Windows code-signing certificate не требуется для внутренней
проверки. Clean Windows без dev tools остаётся отдельным M1 evidence.
