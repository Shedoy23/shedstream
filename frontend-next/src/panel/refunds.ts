// Fixed presentation text from the shipped viewer. Never expose unknown raw
// diagnostic reasons, which can contain internal exception details.
const reasons: Record<string,string> = {
    in_mission:             'Нельзя во время боя или миссии',
    no_active_mission:      'Сначала вступи в бой',
    arena_or_tournament:    'Сила недоступна на арене и турнире',
    hero_not_spawned:       'Твой герой ещё не вышел на поле боя',
    hero_not_found_or_dead: 'Герой не найден или мёртв',
    hero_not_found:         'Герой не найден',
    not_enough_hero_gold:   'Не хватает динаров у героя',
    attribute_maxed:        'Атрибут уже на максимуме',
    all_attributes_maxed:   'Все атрибуты прокачаны до максимума',
    no_attributes_object:   'Нет данных по атрибутам героя',
    skill_focus_maxed:      'Фокус навыка уже на максимуме',
    all_skills_focus_maxed: 'Все фокусы прокачаны до максимума',
    no_skills_object:       'Нет данных по навыкам героя',
    is_prisoner:            'Твой герой в плену',
    already_clan_leader:    'Ты уже глава клана',
    not_clan_leader:        'Только для главы клана',
    clan_name_exists:       'Клан с таким именем уже существует',
    no_clan:                'Сначала нужно вступить или создать клан',
    in_player_clan:         'Недоступно в клане игрока',
    already_in_party:       'Отряд уже создан',
    clan_party_limit:       'Достигнут лимит отрядов клана',
    no_kingdom:             'Сначала нужно вступить в королевство',
    not_king:               'Только для короля',
    not_authorized:         'Недостаточно прав',
    not_at_war:             'Вы не в состоянии войны',
    self_target:            'Нельзя выбрать себя',
    target_not_found:       'Цель не найдена',
    town_not_found:         'Город не найден',
    no_campaign:            'Действие сейчас недоступно',
    no_inventory:           'Нет инвентаря',
    no_matching_item:       'Подходящий предмет не найден',
    // 2026-06-15 «Кузница» (перековка качества) — отказы ReforgeQualityHandler.
    already_best:           'Предмет уже наилучшего качества — крустики возвращены',
    slot_empty:             'В этом слоте ничего не надето',
    no_quality_group:       'У этого предмета нельзя улучшить качество',
    no_modifier:            'У этого предмета нет вариантов улучшения качества',
    unknown_slot:           'Неизвестный слот',
};
export function refundText(reason: string | undefined, refunded: boolean) {
  const base = (reason || '').split(':')[0];
  const text = !reason || reason === 'unspecified' ? 'Сейчас недоступно'
    : (Object.hasOwn(reasons,reason) ? reasons[reason] : Object.hasOwn(reasons,base) ? reasons[base] : base === 'unknown' ? 'Неизвестный параметр действия' : 'Действие не удалось');
  return '❌ ' + text + (refunded ? ' — крустики возвращены' : '');
}
