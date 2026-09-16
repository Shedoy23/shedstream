"""Real SQLite regression for deterministic Bannerlord equipment purchases."""
import asyncio
import json
import tempfile
from pathlib import Path
from test_bannerlord_buy_action import _build_db, _make_anon_request, CHANNEL_ID

async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = await _build_db(str(Path(tmp) / 'equipment.db'))
        try:
            from routes.bannerlord import _bannerlord_buy_action_locked
            # Baseline RED: this authorized dinar action is not yet purchasable.
            result = await _bannerlord_buy_action_locked(
                _make_anon_request(), 'alice', CHANNEL_ID,
                'hero.buy_equipment', {'item_id': 'test_sword', 'price': -500})
            assert result.get('reason') == 'inventory_not_ready', result
        finally:
            await db._pool.close()

if __name__ == '__main__':
    asyncio.run(main())

