"""Standalone server Minesweeper contract and certification regression tests.

Run from backend: python tests/test_minesweeper_engine.py
No browser, database, third-party solver, or pytest is required.
"""
from __future__ import annotations

import copy
import json
import random
import sys
import time
import unittest
from itertools import combinations
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from skillgames import minesweeper as game
except ImportError as exc:
    raise AssertionError(
        "Missing authoritative Minesweeper engine: first-region safety and "
        "no-guess difficulty certification are not implemented"
    ) from exc


def neighbors(cell):
    row, col = divmod(cell, 6)
    return {
        r * 6 + c
        for r in range(max(0, row - 1), min(6, row + 2))
        for c in range(max(0, col - 1), min(6, col + 2))
        if (r, c) != (row, col)
    }


def reveal(cells, opened, mines):
    queue = list(cells)
    while queue:
        cell = queue.pop()
        assert cell not in mines, "Certification attempted to open a mine"
        if cell in opened:
            continue
        opened.add(cell)
        if not neighbors(cell) & mines:
            queue.extend(neighbors(cell) - opened)


def check_certificate(test, state):
    """Replay mathematical witnesses independently of the production solver.

    Each source must be an actual visible clue or the public total mine count;
    each newly opened/marked square must follow by a zero/full constraint or
    subtraction of a strict subset. Reading the layout only simulates reveals.
    """
    mines = set(state['mines'])
    opened, known_mines = set(), set()
    reveal({state['first_cell']}, opened, mines)
    subset_steps = 0
    for step in state['certification']['trace']:
        constraints = {
            (frozenset(set(range(36)) - opened - known_mines), len(mines) - len(known_mines))
        }
        for cell in opened:
            adjacent = neighbors(cell)
            constraints.add((frozenset(adjacent - opened - known_mines),
                             len(adjacent & mines) - len(adjacent & known_mines)))
        source = [(frozenset(s['cells']), s['mines']) for s in step['source']]
        for constraint in source:
            test.assertIn(constraint, constraints, 'witness must use visible evidence')
        if step['rule'] == 'direct':
            test.assertEqual(len(source), 1)
            cells, count = source[0]
        else:
            test.assertEqual(step['rule'], 'subset')
            test.assertEqual(len(source), 2)
            (small, low), (big, high) = source
            test.assertTrue(small < big)
            cells, count = big - small, high - low
            subset_steps += 1
        safe, marked = set(step['safe']), set(step['mines'])
        test.assertTrue(cells)
        if count == 0:
            test.assertEqual(safe, set(cells))
            test.assertFalse(marked)
        else:
            test.assertEqual(count, len(cells))
            test.assertEqual(marked, set(cells))
            test.assertFalse(safe)
        test.assertFalse(safe & mines)
        test.assertTrue(marked <= mines)
        known_mines.update(marked)
        reveal(safe, opened, mines)
    test.assertEqual(opened, set(range(36)) - mines, 'proof must solve every safe cell')
    test.assertEqual(subset_steps, state['certification']['subset_steps'])
    test.assertEqual(state['certification']['proof_class'],
                     'subset' if subset_steps else 'direct')


class MinesweeperEngineTests(unittest.TestCase):
    def make(self, tier='beginner', seed=0, cell=14):
        return game.initialize(cell, tier, random.Random(seed))

    def test_many_seeds_all_first_cells_have_safe_regions_and_verified_proofs(self):
        begin = time.monotonic()
        attempts, work = [], []
        for tier in ('beginner', 'advanced'):
            for first in range(36):
                for seed in range(3):
                    with self.subTest(tier=tier, first=first, seed=seed):
                        state = self.make(tier, seed, first)
                        self.assertEqual(state['rules_version'], game.RULES_VERSION)
                        self.assertEqual(state['status'], 'active')
                        self.assertGreater(state['certification']['solver_steps'], 0)
                        self.assertEqual(len(state['mines']), game.TIERS[tier]['mine_count'])
                        self.assertFalse(set(state['mines']) & (neighbors(first) | {first}))
                        self.assertEqual(state['opened'][str(first)], 0)
                        self.assertTrue(neighbors(first) <= set(map(int, state['opened'])))
                        check_certificate(self, state)
                        direct = game.certify_board(state['mines'], first, allow_subset=False)
                        self.assertEqual(direct is not None, tier == 'beginner')
                        self.assertEqual(state['certification']['proof_class'],
                                         game.TIERS[tier]['proof_class'])
                        attempts.append(state['generation']['attempts'])
                        work.append(state['generation']['work'])
                        self.assertLessEqual(attempts[-1], game.DEFAULT_LIMITS.max_attempts)
                        self.assertLessEqual(work[-1], game.DEFAULT_LIMITS.max_work)
        print(f'216 certified boards / all 36 starts: {time.monotonic()-begin:.3f}s; '
              f'max attempts={max(attempts)}, max work={max(work)}')

    def test_trivial_first_flood_wins_are_rejected_before_play(self):
        trivial = [5, 29, 30, 34, 35]

        class TrivialFirst(random.Random):
            calls = 0

            def sample(self, population, k):
                self.calls += 1
                if self.calls == 1:
                    assert set(trivial) <= set(population)
                    return trivial
                return super().sample(population, k)

        source = TrivialFirst(0)
        state = game.initialize(0, rng=source)
        self.assertEqual(state['status'], 'active', 'initial flood is not a rated skill win')
        self.assertGreater(state['certification']['solver_steps'], 0)
        self.assertGreaterEqual(state['generation']['rejected_trivial'], 1)
        self.assertGreater(source.calls, 1)
        self.assertNotEqual(state['mines'], trivial)

    def test_first_region_safety_is_not_incidental_solver_filtering(self):
        # If the generator merely excludes the clicked cell, this legal sample
        # would put mines in all five neighbors of edge cell 1. Direct logic can
        # solve that board, so certification alone is not first-region safety.
        class NeighborFirst(random.Random):
            def sample(self, population, k):
                if neighbors(1) <= set(population):
                    return sorted(neighbors(1))
                return super().sample(population, k)

        state = game.initialize(1, rng=NeighborFirst(0))
        self.assertFalse(neighbors(1) & set(state['mines']))
        self.assertEqual(state['opened']['1'], 0)

    def test_public_projection_whitelist_and_detached_values(self):
        state = self.make()
        public = game.public_projection(state)
        self.assertEqual(set(public), {'rules_version', 'tier', 'rows', 'cols',
                                      'mine_count', 'opened', 'flags', 'status'})
        self.assertEqual((public['rows'], public['cols']), (6, 6))
        self.assertEqual(json.loads(json.dumps(state)), state)
        self.assertEqual(json.loads(json.dumps(public)), public)
        public['opened']['999'] = 9
        public['flags'].append(999)
        self.assertNotIn('999', state['opened'])
        self.assertNotIn(999, state['flags'])
        for terminal in ('won', 'lost'):
            state['status'] = terminal
            self.assertEqual(set(game.public_projection(state)), set(public))

    def test_deterministic_rng_and_input_state_immutability(self):
        state = self.make(seed=9)
        other = self.make(seed=9)
        self.assertEqual(state['mines'], other['mines'])
        self.assertEqual(state['certification'], other['certification'])
        before = copy.deepcopy(state)
        mine = state['mines'][0]
        after = game.apply_action(state, 'flag', mine)
        self.assertEqual(state, before)
        self.assertEqual(after['flags'], [mine])
        restored = game.apply_action(after, 'unflag', mine)
        self.assertFalse(restored['flags'])
        self.assertEqual(after['flags'], [mine])

    def test_flags_optional_victory_and_terminal_protection(self):
        state = self.make(seed=4)
        for cell in range(36):
            if cell not in state['mines'] and str(cell) not in state['opened']:
                state = game.apply_action(state, 'open', cell)
        self.assertEqual(state['status'], 'won')
        self.assertFalse(state['flags'])
        self.assertEqual(len(state['opened']), 36 - len(state['mines']))
        before = copy.deepcopy(state)
        for kind in ('open', 'flag', 'unflag'):
            with self.assertRaises(game.InvalidAction):
                game.apply_action(state, kind, state['mines'][0])
        self.assertEqual(state, before)

    def test_mine_hit_loses_without_leaking_remaining_mines(self):
        state = self.make()
        lost = game.apply_action(state, 'open', state['mines'][0])
        self.assertEqual(lost['status'], 'lost')
        self.assertEqual(state['status'], 'active')
        self.assertEqual(lost['opened'], state['opened'])
        self.assertNotIn('mines', game.public_projection(lost))
        with self.assertRaises(game.InvalidAction):
            game.apply_action(lost, 'open', 35)

    def test_illegal_cells_actions_flags_and_noops_are_rejected(self):
        state = self.make()
        before = copy.deepcopy(state)
        for bad in (True, False, -1, 36, 1.0, '1', None, [1]):
            with self.subTest(cell=bad):
                with self.assertRaises(game.InvalidAction):
                    game.initialize(bad)
                with self.assertRaises(game.InvalidAction):
                    game.apply_action(state, 'open', bad)
        for tier in ('expert', '', None, [], {}):
            with self.assertRaises(game.InvalidAction):
                game.initialize(0, tier)
        for kind in ('chord', '', None, [], {}):
            with self.assertRaises(game.InvalidAction):
                game.apply_action(state, kind, 0)
        first = state['first_cell']
        for kind in ('open', 'flag', 'unflag'):
            with self.assertRaises(game.InvalidAction):
                game.apply_action(state, kind, first)
        mine = state['mines'][0]
        flagged = game.apply_action(state, 'flag', mine)
        for kind in ('open', 'flag'):
            with self.assertRaises(game.InvalidAction):
                game.apply_action(flagged, kind, mine)
        with self.assertRaises(game.InvalidAction):
            game.apply_action(state, 'unflag', mine)
        self.assertEqual(state, before)

    def test_flagged_safe_cell_blocks_win_until_opened(self):
        state = self.make(seed=5)
        safe = next(c for c in range(36)
                    if c not in state['mines'] and str(c) not in state['opened'])
        state = game.apply_action(state, 'flag', safe)
        for cell in range(36):
            if cell != safe and cell not in state['mines'] and str(cell) not in state['opened']:
                state = game.apply_action(state, 'open', cell)
        self.assertEqual(state['status'], 'active')
        self.assertNotIn(str(safe), state['opened'])
        state = game.apply_action(state, 'unflag', safe)
        state = game.apply_action(state, 'open', safe)
        self.assertEqual(state['status'], 'won')

    def test_flag_limit_and_solver_step_limit_are_enforced(self):
        state = self.make()
        for cell in state['mines']:
            state = game.apply_action(state, 'flag', cell)
        hidden_safe = next(c for c in range(36)
                           if c not in state['mines'] and str(c) not in state['opened'])
        with self.assertRaises(game.InvalidAction):
            game.apply_action(state, 'flag', hidden_safe)
        with self.assertRaises(game.GenerationError):
            game.certify_board(state['mines'], state['first_cell'],
                               limits=game.GenerationLimits(max_solver_steps=0))

    def test_exhausted_generation_never_returns_uncertified_fallback(self):
        for limits in (game.GenerationLimits(max_attempts=0),
                       game.GenerationLimits(max_seconds=0),
                       game.GenerationLimits(max_work=0)):
            with self.assertRaises(game.GenerationError):
                game.initialize(0, 'advanced', random.Random(0), limits=limits)
        with patch.object(game, '_certify', return_value=None) as certify:
            with self.assertRaises(game.GenerationError):
                game.initialize(0, 'beginner', random.Random(0),
                                limits=game.GenerationLimits(max_attempts=3))
            self.assertEqual(certify.call_count, 3)
        with patch.object(game, 'monotonic', side_effect=[0.0, 2.0]):
            with self.assertRaises(game.GenerationError):
                game.initialize(0, limits=game.GenerationLimits(max_seconds=1))

    def test_ambiguous_layout_is_refused_and_proof_budgets_enforced(self):
        # Independently enumerate all layouts consistent with the stalled clues.
        # Every unknown (except proven mine 2) can still be either safe or a mine.
        mines = {2, 9, 25, 29, 35}
        opened = {0, 1, 6, 7, 12, 13, 8, 14, 18, 19, 20, 26}
        unknown = set(range(36)) - opened
        models = []
        for positions in combinations(sorted(unknown - {2}), 4):
            candidate = set(positions) | {2}
            if all(len(neighbors(c) & candidate) == len(neighbors(c) & mines)
                   for c in opened):
                models.append(candidate)
        self.assertGreater(len(models), 1)
        self.assertEqual(set.intersection(*models), {2})
        self.assertEqual(set.union(*models), unknown)
        self.assertIsNone(game.certify_board(mines, 0, allow_subset=True))

        class RepeatedAmbiguousLayout:
            calls = 0

            def sample(self, population, k):
                self.calls += 1
                return sorted(mines)

        source = RepeatedAmbiguousLayout()
        with self.assertRaises(game.GenerationError):
            game.initialize(0, rng=source,
                            limits=game.GenerationLimits(max_attempts=3))
        self.assertEqual(source.calls, 3)
        with self.assertRaises(game.GenerationError):
            game.certify_board(self.make()['mines'], 14,
                               limits=game.GenerationLimits(max_work=0))


if __name__ == '__main__':
    unittest.main(verbosity=2)
