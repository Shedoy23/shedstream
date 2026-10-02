import { afterEach, describe, expect, it, vi } from 'vitest';
import { options, render } from 'preact';
import { SkillgameView } from '../src/skillgames/SkillgameView';
import { TournamentView } from '../src/TournamentView';
import { parseSnapshot } from '../src/skillgames/contracts';
import { resumed } from './skillgame-fixtures';
import { running } from './fixtures';

// No testing-library act: it flushes passive effects before the click and hides
// the actual Preact first-paint race. Hold the next frame, flush render microtasks.
const originalFrame = options.requestAnimationFrame;
let frames: Array<() => void> = [];
let root: HTMLDivElement;
async function flushRenders() { for (let i = 0; i < 10; i++) await Promise.resolve(); }
function mount() {
  frames = [];
  options.requestAnimationFrame = callback => { frames.push(callback); };
  root = document.createElement('div'); document.body.append(root);
}
function button(text: string) {
  const found = [...root.querySelectorAll('button')].find(element => element.textContent === text);
  if (!found) throw new Error(`Button not found: ${text}`);
  return found;
}
afterEach(async () => {
  if (root) { render(null, root); root.remove(); }
  while (frames.length) frames.shift()!();
  await flushRenders();
  options.requestAnimationFrame = originalFrame;
});

describe('Preact first interactive frame', () => {
  it.each(['Завершить партию', 'Сбросить попытку'])('keeps %s open and focused after the first immediate click', async label => {
    mount(); const submit = vi.fn();
    render(<SkillgameView state={{ data: parseSnapshot(resumed), loading: false, pending: false, uncertain: false, error: null, notice: null, canAct: true, receivedAt: Date.now() }} onSubmit={submit} onRefresh={vi.fn()} onRetry={vi.fn()} />, root);
    const trigger = button(label); trigger.focus(); trigger.click();
    await flushRenders();
    expect(root.querySelector('[role="dialog"]')).not.toBeNull();
    expect(document.activeElement).toBe(button('Остаться'));
    while (frames.length) frames.shift()!();
    await flushRenders();
    expect(root.querySelector('[role="dialog"]')).not.toBeNull();
    button('Остаться').click(); await flushRenders();
    expect(root.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(submit).not.toHaveBeenCalled();
  });

  it('keeps the first prediction confirmation open before passive effects run', async () => {
    mount(); const action = vi.fn();
    render(<TournamentView state={{ data: running, loading: false, pending: false, error: null, notice: null, canAct: true }} onAction={action} onRefresh={vi.fn()} />, root);
    const trigger = button('Прогноз'); trigger.focus(); trigger.click();
    await flushRenders();
    expect(root.querySelector('[role="dialog"]')).not.toBeNull();
    expect(document.activeElement).toBe(button('Подтвердить прогноз'));
    while (frames.length) frames.shift()!();
    await flushRenders();
    expect(root.querySelector('[role="dialog"]')).not.toBeNull();
    button('Отмена').click(); await flushRenders();
    expect(document.activeElement).toBe(trigger);
    expect(action).not.toHaveBeenCalled();
  });
});
