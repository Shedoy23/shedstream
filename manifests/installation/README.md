# Installation Manifest v1

Этот контракт описывает установку integration и не заменяет runtime manifests в
`Расширение/backend/modules/*/manifest.yaml`.

- `v1.schema.json` — строгая JSON Schema; неизвестные поля запрещены.
- `rimworld-0.1.0.json` — первый manifest, привязанный к существующему release
  archive и его SHA-256.
- `scripts/validate-installation-manifests.py` проверяет schema, локальные
  artefacts, размер/hash и безопасность путей внутри ZIP.

Проверка:

```text
python -m pip install -r scripts/requirements-manifest.txt
python scripts/validate-installation-manifests.py
```

`source.kind=repository` означает, что artefact пока локальный и manifest ещё не
готов для внешнего Manager. Перед alpha source должен стать HTTPS URL, а
`signature_status=unsigned` — либо получить подпись, либо остаться явно принятым
риском при обязательной SHA-256 проверке.
