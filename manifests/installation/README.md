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
python scripts/test-installation-manifests.py
python scripts/test-installation-transaction.py
```

`scripts/installation_transaction.py` — platform-neutral reference для staging,
atomic directory swap и recovery. Он фиксирует требуемое поведение core Manager,
но не выбирает будущую UI-технологию.

`source.kind=repository` означает, что artefact пока локальный и manifest ещё не
готов для внешнего Manager. Перед alpha source должен стать HTTPS URL, а
`signature_status=unsigned` обязан стать `signed`.

Для внешнего Manager unsigned HTTPS больше не допускается: v1 schema требует
artifact signature, validator требует `signature_status=signed`, а Manager Core
проверяет RSA-PSS publisher key. Точный payload и release process:
`docs/MANAGER_RELEASE_SIGNATURE_POLICY_V1.md`.
