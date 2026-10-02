"""Server-only Battleship rules; HTTP authentication, clocks and ELO live in service.

Starter balance, not empirically calibrated: 6x6, fleet 3/2/2/1, no touching.
Every shot alternates, even a hit. A server-random initial turn is not a random
winner. Only explicit projections may cross a client boundary. Opponent fleets
remain secret after completion as well (no replay/board-reveal endpoint).
"""
from __future__ import annotations

import copy
import random
from collections import Counter

ROWS = COLS = 6
FLEET = (3, 2, 2, 1)
RULES_VERSION = 'battleship-classic-v1'


class InvalidAction(ValueError):
    """Invalid input, player, phase, turn, or already applied move."""


def _cell(value):
    if type(value) is not int or not 0 <= value < ROWS * COLS:
        raise InvalidAction('Клетка вне поля')
    return value


def _adjacent(cell):
    row, col = divmod(cell, COLS)
    return {r * COLS + c for r in range(max(0, row-1), min(ROWS, row+2))
            for c in range(max(0, col-1), min(COLS, col+2))}


def validate_fleet(ships):
    """Validate all ships together; order and orientation are immaterial."""
    if not isinstance(ships, list) or len(ships) != len(FLEET):
        raise InvalidAction('Нужен весь флот')
    if any(not isinstance(ship, list) for ship in ships):
        raise InvalidAction('Неверный формат корабля')
    if Counter(map(len, ships)) != Counter(FLEET):
        raise InvalidAction('Неверные размеры кораблей')
    blocked = set()
    for ship in ships:
        cells = sorted(_cell(cell) for cell in ship)
        if len(set(cells)) != len(cells):
            raise InvalidAction('Корабль занимает клетку дважды')
        horizontal = all(cell // COLS == cells[0] // COLS for cell in cells) and cells == list(range(cells[0], cells[0]+len(cells)))
        vertical = all(cell % COLS == cells[0] % COLS for cell in cells) and cells == list(range(cells[0], cells[0]+len(cells)*COLS, COLS))
        if not (horizontal or vertical):
            raise InvalidAction('Корабль должен быть прямым и непрерывным')
        if blocked.intersection(cells):
            raise InvalidAction('Корабли не могут пересекаться или соприкасаться')
        blocked.update(neighbor for cell in cells for neighbor in _adjacent(cell))
    return True


def generate_fleet(rng=None):
    """Small bounded backtracking, never unbounded random rejection."""
    rng = rng or random.SystemRandom()
    candidates = {}
    for size in set(FLEET):
        options = set()
        for row in range(ROWS):
            for col in range(COLS):
                if col + size <= COLS:
                    options.add(tuple(row*COLS+col+i for i in range(size)))
                if row + size <= ROWS:
                    options.add(tuple((row+i)*COLS+col for i in range(size)))
        candidates[size] = sorted(options)
        rng.shuffle(candidates[size])
    budget = [10000]

    def place(index, blocked):
        if index == len(FLEET):
            return []
        for option in candidates[FLEET[index]]:
            budget[0] -= 1
            if budget[0] < 0:
                raise InvalidAction('Не удалось расставить флот; попробуйте снова')
            if blocked.intersection(option):
                continue
            result = place(index+1, blocked | {n for cell in option for n in _adjacent(cell)})
            if result is not None:
                return [list(option)] + result
        return None

    result = place(0, set())
    if result is None:
        raise InvalidAction('Не удалось расставить флот; попробуйте снова')
    validate_fleet(result)
    return result


def new_game(players, now=0):
    if (not isinstance(players, list) or len(players) != 2
            or any(not isinstance(p, str) or not p for p in players)
            or len(set(players)) != 2):
        raise InvalidAction('Нужны два разных игрока')
    return {'rules_version': RULES_VERSION, 'players': list(players),
            'fleets': {p: [] for p in players}, 'ready': {p: False for p in players},
            'shots': {p: [] for p in players}, 'phase': 'placement', 'status': 'active',
            'turn': None, 'turn_started_at': None, 'started_at': now, 'winner': None}


def _player(state, username):
    if username not in state['players']:
        raise InvalidAction('Вы не участник этой партии')
    return next(p for p in state['players'] if p != username)


def apply_action(state, username, action, cell=None, ships=None, now=0):
    opponent = _player(state, username)
    if state['status'] != 'active':
        raise InvalidAction('Партия уже завершена')
    out = copy.deepcopy(state)
    if action in ('place', 'autoplace', 'ready'):
        if out['phase'] != 'placement' or out['ready'][username]:
            raise InvalidAction('Расстановка уже подтверждена')
        if action in ('place', 'autoplace'):
            fleet = generate_fleet() if action == 'autoplace' else ships
            validate_fleet(fleet)
            out['fleets'][username] = copy.deepcopy(fleet)
        else:
            validate_fleet(out['fleets'][username])
            out['ready'][username] = True
            if all(out['ready'].values()):
                out['phase'] = 'active'
                out['turn'] = random.SystemRandom().choice(out['players'])
                out['turn_started_at'] = now
        return out
    if action != 'fire':
        raise InvalidAction('Неизвестное действие')
    if out['phase'] != 'active':
        raise InvalidAction('Дождитесь расстановки обоих игроков')
    if out['turn'] != username:
        raise InvalidAction('Сейчас ход соперника')
    cell = _cell(cell)
    if cell in out['shots'][username]:
        raise InvalidAction('В эту клетку уже стреляли')
    out['shots'][username].append(cell)
    occupied = {c for ship in out['fleets'][opponent] for c in ship}
    if occupied.issubset(out['shots'][username]):
        out.update(status='won', phase='finished', winner=username, turn=None)
    else:
        out['turn'] = opponent
        out['turn_started_at'] = now
    return out


def public_projection(state, username):
    opponent = _player(state, username)
    own_fleet = state['fleets'][username]
    enemy_fleet = state['fleets'][opponent]
    enemy_cells = {cell for ship in enemy_fleet for cell in ship}
    own_cells = {cell for ship in own_fleet for cell in ship}
    shots = state['shots'][username]
    incoming = state['shots'][opponent]
    # Sunk count reveals only facts established by this player's shots, never
    # an unhit coordinate or an arrangement inferred by inspecting hidden ships.
    return {'rules_version': RULES_VERSION, 'rows': ROWS, 'cols': COLS,
            'fleet_sizes': list(FLEET), 'phase': state['phase'], 'status': state['status'],
            'own_ships': copy.deepcopy(own_fleet), 'ready': state['ready'][username],
            'opponent_ready': state['ready'][opponent], 'opponent': opponent,
            'shots': [{'cell': c, 'result': 'hit' if c in enemy_cells else 'miss'} for c in shots],
            'incoming': [{'cell': c, 'result': 'hit' if c in own_cells else 'miss'} for c in incoming],
            'sunk_count': sum(bool(ship) and set(ship).issubset(shots) for ship in enemy_fleet),
            'your_turn': state['turn'] == username, 'turn_started_at': state['turn_started_at'],
            'winner': state['winner']}
