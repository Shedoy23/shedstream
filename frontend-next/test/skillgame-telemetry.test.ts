import { describe, expect, it, vi } from 'vitest';
import { TwitchAuthStore } from '../src/auth';
import { SkillgameUsage } from '../src/skillgames/usage';
import { authOne } from './fixtures';
function setup() { const auth = new TwitchAuthStore(); auth.authorize(authOne); const fetcher = vi.fn().mockResolvedValue(new Response('{}')); let now = 0; const usage = new SkillgameUsage(auth, 'mobile', fetcher, () => now); return { auth, fetcher, usage, advance: (ms: number) => { now += ms; } }; }
describe('privacy-safe skillgame intent counters', () => {
  it('batches allowlisted semantic counts only, at most once per 15 seconds', async () => {
    const { usage, fetcher, advance } = setup();
    usage.record('section_open', 'core:game.minesweeper');
    for (let i = 0; i < 200; i++) usage.record('action_attempt', 'core:minesweeper.open');
    usage.record('action_attempt', 'core:minesweeper.open:cell-5');
    await usage.flush(); expect(fetcher).not.toHaveBeenCalled();
    advance(15000); await usage.flush();
    const [url, request] = fetcher.mock.calls[0]; const body = JSON.parse(request.body);
    expect(url).toBe('/api/viewer/ui-usage'); expect(body.surface).toBe('mobile');
    expect(body.events).toEqual([{ kind: 'section_open', feature: 'core:game.minesweeper', count: 1 }, { kind: 'action_attempt', feature: 'core:minesweeper.open', count: 20 }]);
    expect(Object.keys(body).sort()).toEqual(['batch_id', 'events', 'surface']);
  });
  it('uses rotated token without retaining events across viewer changes or retrying network failures', async () => {
    const { usage, fetcher, auth, advance } = setup();
    usage.record('action_attempt', 'core:battleship.fire');
    auth.authorize({ ...authOne, token: 'new-token' }); advance(15000); await usage.flush();
    expect(fetcher.mock.calls[0][1].headers['X-Twitch-JWT']).toBe('new-token');
    usage.record('action_attempt', 'core:battleship.fire'); auth.authorize({ ...authOne, userId: 'other' }); advance(15000); await usage.flush();
    expect(fetcher).toHaveBeenCalledTimes(1);
    usage.record('action_attempt', 'core:minesweeper.flag'); fetcher.mockRejectedValueOnce(new Error('lost')); advance(15000); await usage.flush(); advance(15000); await usage.flush();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
