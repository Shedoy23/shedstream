# Installation Manifest v1

Этот контракт описывает установку integration и не заменяет runtime manifests в
`Расширение/backend/modules/*/manifest.yaml`.

- `v1.schema.json` — строгая JSON Schema; неизвестные поля запрещены.
- `rimworld-0.1.1.json` — актуальный signed HTTPS Manager manifest с безопасной
  diagnostic command, привязанный к immutable release archive, SHA-256 и
  production RSA-PSS publisher signature.
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

RimLink `0.1.1` опубликован по versioned HTTPS URL без redirect; source имеет
`signature_status=signed`, а public key встроен в Manager.

Для внешнего Manager unsigned HTTPS больше не допускается: v1 schema требует
artifact signature, validator требует `signature_status=signed`, а Manager Core
проверяет RSA-PSS publisher key. Точный payload и release process:
`docs/MANAGER_RELEASE_SIGNATURE_POLICY_V1.md`.
