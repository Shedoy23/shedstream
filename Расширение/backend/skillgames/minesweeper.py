"""Authoritative, JSON-serializable 6x6 Minesweeper rules.

Generation accepts only boards with a replayable deduction certificate. Beginner
uses visible zero/full constraints; advanced must first defeat that solver, then
be completely solved by strict-subset subtraction. Neither solver guesses or
uses hidden information to choose a move. Layout access is limited to simulating
a safe reveal. Counts (5/7) are initial product defaults, not balance findings.

Call initialize through asyncio.to_thread behind a bounded service semaphore.
The engine deliberately has no identity, persistence, timer, reward, or network
concerns. Its secret state and certificate must never be serialized to clients;
public_projection is the sole response boundary, including after a loss.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from random import SystemRandom
from time import monotonic

ROWS = COLS = 6
RULES_VERSION = 'minesweeper-v1'
TIERS = {
    'beginner': {'mine_count': 5, 'proof_class': 'direct'},
    'advanced': {'mine_count': 7, 'proof_class': 'subset'},
}
_ALL = frozenset(range(ROWS * COLS))
_NEIGHBORS = tuple(
    frozenset(
        row * COLS + col
        for row in range(max(0, cell // COLS - 1), min(ROWS, cell // COLS + 2))
        for col in range(max(0, cell % COLS - 1), min(COLS, cell % COLS + 2))
        if row * COLS + col != cell
    )
    for cell in sorted(_ALL)
)


class InvalidAction(ValueError):
    """Invalid cell, tier, action, or an action that would be a no-op."""


class GenerationError(RuntimeError):
    """No certified board could be produced inside the fixed resource budget."""


@dataclass(frozen=True)
class GenerationLimits:
    max_attempts: int = 512
    max_seconds: float = 1.0
    max_work: int = 500_000
    max_solver_steps: int = 72


DEFAULT_LIMITS = GenerationLimits()


class _Budget:
    def __init__(self, limits):
        self.limits = limits
        self.deadline = monotonic() + limits.max_seconds
        self.work = 0

    def spend(self, amount=1):
        self.work += amount
        if self.work > self.limits.max_work or monotonic() >= self.deadline:
            raise GenerationError('certification_budget_exhausted')


def _validate_cell(cell):
    if type(cell) is not int or cell not in _ALL:
        raise InvalidAction('invalid_cell')


def _reveal(cells, opened, mines, flags=frozenset()):
    """Flood zero-connected squares, respecting player flags; never open a mine."""
    queue = sorted(cells, reverse=True)
    while queue:
        cell = queue.pop()
        if cell in opened or cell in flags:
            continue
        if cell in mines:
            raise AssertionError('deduction attempted to open a mine')
        count = len(_NEIGHBORS[cell] & mines)
        opened[cell] = count
        if count == 0:
            queue.extend(sorted(_NEIGHBORS[cell] - opened.keys() - flags, reverse=True))


def _constraints(opened, known_mines, mine_count, budget):
    constraints = {}
    for cell, value in sorted(opened.items()):
        budget.spend()
        cells = frozenset(_NEIGHBORS[cell] - opened.keys() - known_mines)
        count = value - len(_NEIGHBORS[cell] & known_mines)
        if cells:
            constraints[cells] = count
    # The declared total is public evidence, not an oracle lookup.
    remaining = frozenset(_ALL - opened.keys() - known_mines)
    if remaining:
        constraints[remaining] = mine_count - len(known_mines)
    return sorted(constraints.items(), key=lambda item: (len(item[0]), tuple(sorted(item[0]))))


def _forced(cells, count):
    if cells and count == 0:
        return cells, frozenset()
    if cells and count == len(cells):
        return frozenset(), cells
    return None


def _deduce(constraints, allow_subset, budget):
    # Exhaust simple rules before claiming that an advanced step was necessary.
    for cells, count in constraints:
        budget.spend()
        forced = _forced(cells, count)
        if forced:
            return 'direct', [(cells, count)], forced
    if allow_subset:
        for small, low in constraints:
            for big, high in constraints:
                budget.spend()
                if small < big:
                    forced = _forced(big - small, high - low)
                    if forced:
                        return 'subset', [(small, low), (big, high)], forced
    return None


def _certify(mines, first_cell, allow_subset, budget):
    opened, known_mines, trace = {}, set(), []
    _reveal({first_cell}, opened, mines)
    for _ in range(budget.limits.max_solver_steps):
        budget.spend()
        if len(opened) == ROWS * COLS - len(mines):
            subset_steps = sum(step['rule'] == 'subset' for step in trace)
            return {
                'proof_class': 'subset' if subset_steps else 'direct',
                'subset_steps': subset_steps,
                'solver_steps': len(trace),
                'trace': trace,
            }
        deductions = _deduce(_constraints(opened, known_mines, len(mines), budget),
                             allow_subset, budget)
        if deductions is None:
            return None
        rule, source, (safe, marked) = deductions
        trace.append({
            'rule': rule,
            'source': [{'cells': sorted(cells), 'mines': count} for cells, count in source],
            'safe': sorted(safe),
            'mines': sorted(marked),
        })
        known_mines.update(marked)
        _reveal(safe, opened, mines)
    raise GenerationError('solver_step_budget_exhausted')


def certify_board(mines, first_cell, *, allow_subset=False, limits=None):
    """Return a server-only proof, or None if these rules cannot solve the board.

    Useful for audits and reproducibility. Resource exhaustion raises
    GenerationError; an invalid/unsafe first region raises InvalidAction.
    """
    _validate_cell(first_cell)
    mine_list = list(mines)
    for cell in mine_list:
        _validate_cell(cell)
    mine_set = frozenset(mine_list)
    if len(mine_list) != len(mine_set) or mine_set & (_NEIGHBORS[first_cell] | {first_cell}):
        raise InvalidAction('unsafe_or_invalid_layout')
    return _certify(mine_set, first_cell, allow_subset, _Budget(limits or DEFAULT_LIMITS))


def initialize(first_cell, tier='beginner', rng=None, *, limits=None):
    """Generate a certified board and perform the safe first-region opening.

    rng is a server-only random source supporting sample(population, k). Tests
    may inject random.Random; production defaults to OS-backed SystemRandom.
    It is never seeded from client input and no seed is stored in public data.
    Exhaustion is a clean retryable failure, never a guess-board fallback.
    """
    _validate_cell(first_cell)
    if not isinstance(tier, str) or tier not in TIERS:
        raise InvalidAction('invalid_tier')
    limits = limits or DEFAULT_LIMITS
    budget = _Budget(limits)
    rng = SystemRandom() if rng is None else rng
    eligible = sorted(_ALL - _NEIGHBORS[first_cell] - {first_cell})
    mine_count = TIERS[tier]['mine_count']
    for attempt in range(1, limits.max_attempts + 1):
        budget.spend()
        mines = frozenset(rng.sample(eligible, mine_count))
        certificate = _certify(mines, first_cell, False, budget)
        if tier == 'advanced':
            if certificate is not None:
                continue
            certificate = _certify(mines, first_cell, True, budget)
        if certificate is None:
            continue
        budget.spend()
        opened = {}
        _reveal({first_cell}, opened, mines)
        return {
            'rules_version': RULES_VERSION,
            'tier': tier,
            'rows': ROWS,
            'cols': COLS,
            'mine_count': mine_count,
            'first_cell': first_cell,
            'mines': sorted(mines),
            'opened': {str(cell): value for cell, value in sorted(opened.items())},
            'flags': [],
            'status': 'won' if len(opened) == ROWS * COLS - mine_count else 'active',
            'certification': certificate,
            'generation': {'attempts': attempt, 'work': budget.work},
        }
    raise GenerationError('generation_attempt_budget_exhausted')


def public_projection(state):
    """Explicit whitelist: hidden layout, seed, and deduction proof stay private."""
    return {
        'rules_version': state['rules_version'],
        'tier': state['tier'],
        'rows': state['rows'],
        'cols': state['cols'],
        'mine_count': state['mine_count'],
        'opened': dict(state['opened']),
        'flags': list(state['flags']),
        'status': state['status'],
    }


def apply_action(state, kind, cell):
    """Apply a legal move to a copy; flags are helpers, never a win condition."""
    _validate_cell(cell)
    if state['status'] != 'active':
        raise InvalidAction('game_finished')
    if not isinstance(kind, str) or kind not in {'open', 'flag', 'unflag'}:
        raise InvalidAction('invalid_action')
    if str(cell) in state['opened']:
        raise InvalidAction('cell_already_open')
    flags = set(state['flags'])
    if kind == 'unflag':
        if cell not in flags:
            raise InvalidAction('cell_not_flagged')
        flags.remove(cell)
    elif cell in flags:
        raise InvalidAction('cell_flagged')
    elif kind == 'flag':
        if len(flags) >= state['mine_count']:
            raise InvalidAction('flag_limit_reached')
        flags.add(cell)
    result = deepcopy(state)
    result['flags'] = sorted(flags)
    if kind != 'open':
        return result
    mines = frozenset(state['mines'])
    if cell in mines:
        result['status'] = 'lost'
        return result
    opened = {int(index): value for index, value in state['opened'].items()}
    _reveal({cell}, opened, mines, flags)
    result['opened'] = {str(index): value for index, value in sorted(opened.items())}
    if len(opened) == ROWS * COLS - state['mine_count']:
        result['status'] = 'won'
    return result
