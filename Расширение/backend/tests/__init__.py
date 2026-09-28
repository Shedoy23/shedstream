"""
backend/tests — automated smoke-tests для критичных архитектурных
инвариантов. Standalone (без pytest), запускаются как:

    cd Расширение/backend
    python tests/test_multi_tenant_isolation.py

Цель — защита от регресса. Покрывают:
- resolve_channel_id strict-режим (M4 follow-up а)
- Module API token round-trip (issue → verify → tampered reject)
- Per-channel data isolation (M1+M4 multi-tenant)
- Idempotent ACK + cross-channel guard (Module API §4)

См. ARCHITECTURE.md §9 testing strategy.
"""
