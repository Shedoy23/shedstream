# BannerlordLink 0.1.0 — выпуск для ShedLink Manager

Дата: 2026-08-16

## Результат

BannerlordLink `0.1.0` подписан production-ключом издателя и опубликован по
неизменяемому адресу:

`https://shedoy23.ru/releases/BannerlordLink-0.1.0.zip`

- размер: `218775` байт;
- SHA-256: `2f5e431ed0f2d30c14ef684544dc316b11870109b55bbd3ac815e92ccf43416a`;
- подпись: RSA-PSS SHA-256;
- key id: `shedlink-release-2026`;
- fingerprint публичного ключа SHA-256:
  `17e6043cca11dcb9f4230d5a91325e9d5d52ba9a29bb4cc4a6ffb51618001541`.

## Доказательства

- архив перед подписью содержит ровно три разрешённых файла;
- `config.json`, PDB, исходников, backup/rollback и секретов нет;
- offline signer завершился кодом `0`;
- независимый verifier локального архива завершился кодом `0`;
- сервер до публикации не содержал финального имени;
- временный upload совпал по размеру и SHA-256 и был атомарно переименован;
- публичный HTTPS: `200`, redirect count `0`, content length `218775`;
- повторно скачанный архив имеет тот же SHA-256;
- независимый verifier скачанного архива завершился кодом `0`;
- HTTP: `404`; listing: `403`; POST: `403`;
- production `/health`: `200`;
- Manager Core self-test и Release build после встраивания манифеста: код `0`.

Backend, база, supervisor, nginx-конфигурация и Twitch frontend не изменялись.
Использован уже существующий защищённый статический `/releases/`.

