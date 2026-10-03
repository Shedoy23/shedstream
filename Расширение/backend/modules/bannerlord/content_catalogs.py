"""Validated runtime metadata. Identity, commerce and execution stay separate."""
import json

CATALOG_TYPES = ('cultures', 'policies', 'skills', 'attributes', 'workshop_types')
_IDENTITY_FIELDS = ('save_id', 'equipment_session_id', 'content_catalog_seq')


def _text(value, limit, *, required=False):
    return (isinstance(value, str) and len(value) <= limit
            and (not required or bool(value.strip()))
            and all(c.isprintable() or c in '\n\r\t' for c in value))


async def current_identity(conn, channel_id):
    row = await (await conn.execute(
        'SELECT s.current_save_id,e.session_id FROM bannerlord_channel_state s '
        'JOIN bannerlord_equipment_sessions e ON e.channel_id=s.channel_id WHERE s.channel_id=?',
        (channel_id,))).fetchone()
    return (row[0], row[1]) if row and row[0] and row[1] else (None, None)


async def store_catalog(db, channel_id, data):
    kind, seq = data.get('catalog'), data.get('catalog_seq')
    entries = data.get('entries')
    save_id, session_id = data.get('save_id'), data.get('equipment_session_id')
    if (kind not in CATALOG_TYPES or type(seq) is not int or not 0 < seq <= 9223372036854775807
            or not isinstance(entries, list) or len(entries) > 20000
            or not _text(save_id, 256, required=True) or not _text(session_id, 256, required=True)):
        return False
    normalized, seen = [], set()
    for item in entries:
        if not isinstance(item, dict):
            return False
        key = item.get('id')
        if not _text(key, 256, required=True) or key in seen:
            return False
        name, description = item.get('name', key), item.get('description', '')
        if not _text(name, 512, required=True) or not _text(description, 8192):
            return False
        entry = dict(id=key, name=name, description=description)
        if 'available' in item:
            if type(item['available']) is not bool:
                return False
            entry['available'] = item['available']
        elif kind == 'cultures':
            # Discovery alone does not prove a usable character template.
            entry['available'] = False
        if 'unavailable_reason' in item:
            if not _text(item['unavailable_reason'], 512):
                return False
            entry['unavailable_reason'] = item['unavailable_reason']
        seen.add(key)
        normalized.append(entry)
    payload = json.dumps(normalized, ensure_ascii=False)
    if len(payload.encode('utf-8')) > 8 * 1024 * 1024:
        return False
    async with db._connect() as conn:
        await conn.execute('BEGIN IMMEDIATE')
        if await current_identity(conn, channel_id) != (save_id, session_id):
            await conn.rollback()
            return False
        previous = await (await conn.execute(
            'SELECT save_id,equipment_session_id,catalog_seq FROM bannerlord_content_catalogs '
            'WHERE channel_id=? AND catalog_type=?', (channel_id, kind))).fetchone()
        if previous and tuple(previous[:2]) == (save_id, session_id) and seq <= previous[2]:
            await conn.rollback()
            return False
        await conn.execute(
            'INSERT INTO bannerlord_content_catalogs(channel_id,catalog_type,save_id,equipment_session_id,catalog_seq,entries_json) '
            'VALUES(?,?,?,?,?,?) ON CONFLICT(channel_id,catalog_type) DO UPDATE SET '
            'save_id=excluded.save_id,equipment_session_id=excluded.equipment_session_id,'
            'catalog_seq=excluded.catalog_seq,entries_json=excluded.entries_json,updated_at=CURRENT_TIMESTAMP',
            (channel_id, kind, save_id, session_id, seq, payload))
        await conn.commit()
    return True


async def read_catalogs(conn, channel_id):
    save_id, session_id = await current_identity(conn, channel_id)
    result = dict(success=True, save_id=save_id, equipment_session_id=session_id)
    for kind in CATALOG_TYPES:
        result[kind] = dict(available=False, reason='content_catalog_not_ready', entries=[])
    if save_id is None:
        return result
    rows = await (await conn.execute(
        'SELECT catalog_type,catalog_seq,entries_json FROM bannerlord_content_catalogs '
        'WHERE channel_id=? AND save_id=? AND equipment_session_id=?',
        (channel_id, save_id, session_id))).fetchall()
    for kind, seq, payload in rows:
        if kind in CATALOG_TYPES:
            result[kind] = dict(available=True, reason=None, entries=json.loads(payload), catalog_seq=seq)
    return result


def refusal(reason):
    messages = {
        'invalid_culture': 'Некорректный идентификатор культуры',
        'content_catalog_not_ready': 'Игра ещё не передала культуры текущего сохранения. Подожди обновления.',
        'content_catalog_changed': 'Сохранение или игровая сессия изменились. Обнови список культур.',
        'culture_not_found': 'Этой культуры нет в текущем каталоге игры',
        'culture_unavailable': 'В игре нет доступного шаблона героя этой культуры',
    }
    return dict(success=False, reason=reason, message=messages[reason])


async def validate_create(conn, channel_id, data, *, prepared=False):
    """Run again under the outbox transaction; viewer identity fields are never trusted."""
    culture = data.get('culture')
    if culture is None:
        culture = ''
    if not _text(culture, 256) or (culture and not culture.strip()):
        return refusal('invalid_culture')
    previous = tuple(data.get(k) for k in _IDENTITY_FIELDS[:2]) if prepared else (None, None)
    for key in _IDENTITY_FIELDS:
        data.pop(key, None)
    data['culture'] = culture  # Game IDs are opaque and case-sensitive.
    snapshot = await read_catalogs(conn, channel_id)
    # A viewer may constrain the displayed snapshot, never select the target save.
    context = data.pop('content_context', None)
    if context is not None and (not isinstance(context, dict)
            or (context.get('save_id'), context.get('equipment_session_id')) !=
            (snapshot['save_id'], snapshot['equipment_session_id'])):
        return refusal('content_catalog_changed')
    catalog = snapshot['cultures']
    if culture:
        if not catalog['available']:
            return refusal('content_catalog_not_ready')
        entry = next((x for x in catalog['entries'] if x['id'] == culture), None)
        if entry is None:
            return refusal('culture_not_found')
        if entry.get('available') is not True:
            return refusal('culture_unavailable')
    identity = (snapshot['save_id'], snapshot['equipment_session_id'])
    if prepared and any(previous) and previous != identity:
        return refusal('content_catalog_changed')
    if catalog['available']:
        data.update(save_id=identity[0], equipment_session_id=identity[1],
                    content_catalog_seq=catalog['catalog_seq'])
    return None
