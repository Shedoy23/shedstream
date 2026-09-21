"""Mission snapshot to viewer: siege gating, order status, channel and TTL isolation."""
import asyncio
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.bannerlord import _adapter as module
from modules._base import ModuleEnvelope

async def main():
    channel = 998877
    module._battle_stats[channel] = {'updated_at': time.time(), 'participants': []}
    adapter = module.BannerlordAdapter(None)
    async def publish(**extra):
        adapter._on_battle_stats(channel, ModuleEnvelope(
            id='order-test', kind='event', type='battle.stats_snapshot', ts=time.time(),
            data={'participants': [{'username': 'Alice', 'alive': True, 'order_status': 'blocked'}], **extra}))
    try:
        await publish(is_siege=True)
        result = module.get_my_battle_stats(channel, 'ALICE')
        assert result['is_siege'] is True
        assert result['my_stats']['order_status'] == 'blocked'
        assert module.get_my_battle_stats(channel + 1, 'Alice')['is_siege'] is False
        assert module.get_my_battle_stats(channel, 'Bob')['my_stats'] is None
        for value in (False, 'true', None):
            await publish(is_siege=value)
            assert module.get_my_battle_stats(channel, 'Alice')['is_siege'] is False
        await publish()
        assert module.get_my_battle_stats(channel, 'Alice')['is_siege'] is False
        await publish(is_siege=True)
        module._battle_stats[channel]['updated_at'] = 0
        assert module.get_my_battle_stats(channel, 'Alice')['is_siege'] is False
        module._battle_stats[channel]['updated_at'] = time.time()
        module._battle_stats[channel]['final'] = True
        assert module.get_my_battle_stats(channel, 'Alice')['is_siege'] is False
        print('PASS order snapshot: siege, legacy, TTL, final, viewer and channel isolation')
    finally:
        module._battle_stats.pop(channel, None)

if __name__ == '__main__':
    asyncio.run(main())
