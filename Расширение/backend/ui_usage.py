"""UI intent contract. Never use these client claims as money/game authority.

Only allowlisted semantic keys, aggregated per existing linked Twitch identity.
The canonical action names come from existing game manifests, not a second list.
"""
from pathlib import Path
import re
import uuid

import yaml

CLIENT = 'frontend-pilot-v1'
MODULES = frozenset(('core', 'bannerlord', 'rimworld', 'shedcolony'))
SECTIONS = frozenset(
    ['core:tab.' + key for key in ('bot', 'integration', 'shop', 'stats')]
    + ['bannerlord:tab.' + key for key in ('combat', 'hero', 'inventory', 'dynasty')]
    + ['bannerlord:section.' + key for key in ('army', 'caravans', 'diplomacy', 'fiefs', 'partyorders', 'workshops')]
    + ['bannerlord:details.' + key for key in (
        'caravan-buy', 'diplo-peace', 'diplo-policy', 'dyn-clan', 'dyn-kingdom',
        'dyn-profile', 'dyn-upgrades', 'hero-gender', 'hero-progression',
        'inv-achievements', 'inv-forge', 'kingdom-create', 'kingdom-join',
        'locked-create', 'locked-join', 'party-order', 'retinue', 'vas-create',
        'ws-buy')])


def _manifest_actions():
    result = set()
    for module in MODULES - {'core'}:
        path = Path(__file__).parent / 'modules' / module / 'manifest.yaml'
        manifest = yaml.safe_load(path.read_text(encoding='utf-8'))
        names = manifest.get('actions', []) + manifest.get('extensions', {}).get('actions', [])
        result.update(module + ':' + name for name in names if isinstance(name, str))
    return frozenset(result)


ACTIONS = _manifest_actions()


def validate_batch(body):
    """Reject unknown fields rather than accidentally collecting private data."""
    if not isinstance(body, dict) or set(body) != {'batch_id', 'surface', 'events'}:
        raise ValueError('invalid_batch')
    batch_id = body['batch_id']
    if not isinstance(batch_id, str) or len(batch_id) != 36:
        raise ValueError('invalid_batch_id')
    try:
        if str(uuid.UUID(batch_id)) != batch_id:
            raise ValueError('invalid_batch_id')
    except (ValueError, AttributeError):
        raise ValueError('invalid_batch_id') from None
    if body['surface'] not in ('desktop', 'mobile'):
        raise ValueError('invalid_surface')
    events = body['events']
    if not isinstance(events, list) or not 1 <= len(events) <= 20:
        raise ValueError('invalid_events')
    total = 0
    for event in events:
        if not isinstance(event, dict) or set(event) != {'kind', 'feature', 'count'}:
            raise ValueError('invalid_event')
        kind, feature, count = event['kind'], event['feature'], event['count']
        if not isinstance(feature, str) or not re.fullmatch(r'[a-z0-9_.:-]{1,96}', feature):
            raise ValueError('invalid_feature')
        allowed = (kind == 'section_open' and feature in SECTIONS
                   or kind == 'action_attempt' and feature in ACTIONS
                   or kind == 'panel_view' and feature in {m + ':panel' for m in MODULES})
        if not allowed:
            raise ValueError('unknown_feature')
        if type(count) is not int or not 1 <= count <= 20:
            raise ValueError('invalid_count')
        total += count
    if total > 100:
        raise ValueError('batch_too_large')
    return body
