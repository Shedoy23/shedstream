import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/preact';
import { TournamentView } from '../src/TournamentView';
import { idle, running } from './fixtures';
afterEach(cleanup);
const state = { data: idle, loading: false, error: null, notice: null, canAct: true, pending: false };

describe('React tournament rendering', () => {
  it('renders the verified queue and emits the exact join action', () => {
    const onAction = vi.fn();
    render(<TournamentView state={state} onAction={onAction} onRefresh={() => {}} />);
    expect(screen.getByText('viewer_one')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Вступить/ }));
    expect(onAction).toHaveBeenCalledWith({ action_type: 'hero.join_tournament', data: { price: 0 } });
  });
  it('escapes participant strings and requires a cancellable prediction confirmation', () => {
    const onAction = vi.fn();
    const { container } = render(<TournamentView state={{ ...state, data: running }} onAction={onAction} onRefresh={() => {}} />);
    expect(container.querySelector('img')).toBeNull();
    fireEvent.click(screen.getAllByRole('button', { name: /Прогноз/ })[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));
    expect(onAction).not.toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole('button', { name: /Прогноз/ })[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить прогноз' }));
    expect(onAction).toHaveBeenCalledWith({ action_type: 'tournament.predict', data: { target: 'viewer_one' } });
  });
  it('closes confirmation when state changes and does not submit an obsolete target', () => {
    const onAction = vi.fn();
    const { rerender } = render(<TournamentView state={{ ...state, data: running }} onAction={onAction} onRefresh={() => {}} />);
    fireEvent.click(screen.getAllByRole('button', { name: /Прогноз/ })[0]);
    rerender(<TournamentView state={state} onAction={onAction} onRefresh={() => {}} />);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(onAction).not.toHaveBeenCalled();
  });
  it('shows backend refusal literally and disables mutations while data is stale', () => {
    render(<TournamentView state={{ ...state, error: 'unknown refusal <b>detail</b>', canAct: false }} onAction={() => {}} onRefresh={() => {}} />);
    expect(screen.getByRole('alert').textContent).toContain('unknown refusal <b>detail</b>');
    expect((screen.getByRole('button', { name: /Вступить/ }) as HTMLButtonElement).disabled).toBe(true);
  });
  it('does not invent a default price or offer mutations for an unfamiliar status', () => {
    render(<TournamentView state={{ ...state, data: { ...idle, state: { ...idle.state, status: 'future_state' } } }} onAction={() => {}} onRefresh={() => {}} />);
    expect(screen.queryByRole('button', { name: /Вступить/ })).toBeNull();
    expect(screen.getByText(/future_state/)).toBeTruthy();
  });
  it('closes confirmation when a new tournament reuses the same round and players', () => {
    const onAction = vi.fn();
    const { rerender } = render(<TournamentView state={{ ...state, data: running }} onAction={onAction} onRefresh={() => {}} />);
    fireEvent.click(screen.getAllByRole('button', { name: /Прогноз/ })[0]);
    rerender(<TournamentView state={{ ...state, data: { ...running, state: { ...running.state, started_at: '2026-10-02T12:00:00Z' } } }} onAction={onAction} onRefresh={() => {}} />);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(onAction).not.toHaveBeenCalled();
  });
  it('cancels prediction on Escape without creating an action', () => {
    const onAction = vi.fn();
    render(<TournamentView state={{ ...state, data: running }} onAction={onAction} onRefresh={() => {}} />);
    fireEvent.click(screen.getAllByRole('button', { name: /Прогноз/ })[0]);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(onAction).not.toHaveBeenCalled();
  });

});
