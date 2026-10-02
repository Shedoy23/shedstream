import { useSyncExternalStore } from 'react';
import { actionKey, validPrice } from './contracts';
import type { PanelController } from './controller';
const groups = [
  ['Vigor', 'Сила', [['OneHanded', 'Одноручное'], ['TwoHanded', 'Двуручное'], ['Polearm', 'Древковое']]],
  ['Control', 'Точность', [['Bow', 'Лук'], ['Crossbow', 'Арбалет'], ['Throwing', 'Метательное']]],
  ['Endurance', 'Выносливость', [['Riding', 'Верховая езда'], ['Athletics', 'Атлетика'], ['Crafting', 'Кузнечное']]],
  ['Cunning', 'Хитрость', [['Scouting', 'Разведка'], ['Tactics', 'Тактика'], ['Roguery', 'Бесчестие']]],
  ['Social', 'Социальность', [['Charm', 'Обаяние'], ['Leadership', 'Лидерство'], ['Trade', 'Торговля']]],
  ['Intelligence', 'Интеллект', [['Steward', 'Управление'], ['Medicine', 'Медицина'], ['Engineering', 'Инженерия']]],
] as const;
const money = (value: number) => value.toLocaleString('ru-RU') + ' 💰';
export function HeroDevelopmentView({ controller }: { controller: PanelController }) {
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot);
  const hero = state.hero?.hero;
  const canAct = state.canAct && controller.ready();
  const build = state.build?.build;
  const newBuild = !!state.build?.enabled || build?.version === 1;
  const buildBusy = state.busy.some(key => key.startsWith('hero.set_specialization:') || key.startsWith('hero.claim_starter:'));
  const manage = canAct && !!state.build?.ready && !!state.build.can_manage && !state.buildPending && !state.build.pending && !build?.in_battle && !buildBusy;
  const attributePrice = state.config?.attribute_cost;
  const hasPriceError = !validPrice(attributePrice) || !Array.isArray(state.config?.focus_tier_costs);
  const perform = (type: string, data: Record<string, unknown>, immediateHero = false) => { if (controller.ready()) void controller.action(type, data, { tail: 'hero', immediateHero }); };
  return <section className="panel-development" aria-label="Развитие героя">
    <div className="panel-section-heading"><div><p className="panel-eyebrow">BANNERLORD</p><h1>Развитие героя</h1></div>
      <button type="button" disabled={!canAct || state.loading} onClick={() => { void controller.refreshDevelopment(); }}>Обновить</button></div>
    {state.loading && !state.hero && <p role="status">Загружаем героя…</p>}
    {state.error && <p className="panel-error" role="alert">{state.error}</p>}
    {state.message && <p className="panel-notice" role="status">{state.message}</p>}
    {state.hero && !state.hero.has_hero && <div className="panel-card"><h2>Герой ещё не создан</h2><p>Создание героя доступно в действующей панели.</p></div>}
    {hero && <article className="panel-card panel-hero"><p className="panel-eyebrow">ВАШ ГЕРОЙ</p><h2>{hero.display_name}</h2>
      <div className="panel-summary"><span>Уровень {hero.level}</span><strong>{money(hero.gold)}</strong></div>
      <p className="panel-muted">{!hero.is_alive ? 'Герой погиб' : hero.is_prisoner ? 'В плену' : hero.is_wounded ? 'Ранен' : 'Жив'}</p></article>}
    {hero && !hero.is_alive && <p>Развитие погибшего героя недоступно. Возрождение доступно в действующей панели.</p>}
    {hero?.is_alive ? <>
      <section className="panel-card" aria-label="Атрибуты и навыки"><h2>Атрибуты и навыки</h2>
        <p className="panel-muted">Атрибут влияет на три навыка. Фокус повышает скорость развития навыка.</p>
        {hasPriceError && <p className="panel-error" role="status">Сервер не передал цены развития. Покупки без подтверждённой цены недоступны.</p>}
        {groups.map(([key, label, skills]) => {
          const value = state.hero?.attributes?.[key] ?? state.hero?.attributes?.[key.toLowerCase()] ?? 0;
          const attributeData = { attribute_key: key, amount: 1 };
          const cooldown = controller.cooldown('hero.add_attribute');
          return <div className="panel-attribute-group" key={key}>
            <div className="panel-attribute"><strong>{label}</strong><span>{value}/10</span>
              <button type="button" className="panel-progress-button" data-attr={key} aria-label={`Повысить атрибут ${label}`} title={validPrice(attributePrice) ? `+1 в ${label}. Списать ${money(attributePrice)}` : 'Цена недоступна'}
                disabled={!canAct || value >= 10 || !validPrice(attributePrice) || cooldown > 0 || state.busy.includes(actionKey('hero.add_attribute', attributeData))}
                onClick={() => perform('hero.add_attribute', attributeData, true)}>{cooldown > 0 ? `${Math.ceil(cooldown)} с` : '+1'}<small>{validPrice(attributePrice) ? money(attributePrice) : '—'}</small></button></div>
            {skills.map(([skillKey, skillLabel]) => {
              const skill = state.hero?.skills?.find(s => s.skill_key === skillKey); const focus = skill?.focus ?? 0;
              const price = state.config?.focus_tier_costs?.[focus]; const cd = controller.cooldown('hero.add_focus');
              const data = { skill_key: skillKey, amount: 1 };
              return <div className="panel-skill" key={skillKey}><span>{skillLabel}<small>Уровень {skill?.level ?? 0} · Фокус {focus}/5</small></span>
                <button type="button" className="panel-progress-button" data-skill={skillKey} aria-label={`Добавить фокус ${skillLabel}`} title={validPrice(price) ? `+1 focus в ${skillLabel}. Списать ${money(price)}` : 'Цена недоступна'}
                  disabled={!canAct || focus >= 5 || !validPrice(price) || cd > 0 || state.busy.includes(actionKey('hero.add_focus', data))}
                  onClick={() => perform('hero.add_focus', data, true)}>{cd > 0 ? `${Math.ceil(cd)} с` : '+1'}<small>{focus >= 5 ? 'Максимум' : validPrice(price) ? money(price) : '—'}</small></button></div>;
            })}
          </div>;
        })}
      </section>
      <section className="panel-card" aria-label="Специализация и комплект">
        {newBuild ? !state.build?.ready || !build ? <p role="status">{state.build?.message || 'Данные сборки героя ещё синхронизируются с игрой.'}</p> : <>
          <h2>Специализация</h2><p className="panel-muted">Один пассивный бонус. Оружие и броню выбираешь свободно в «Инвентаре».</p>
          {(state.buildPending || state.build.pending || buildBusy) ? <p className="panel-notice" role="status">Заявка отправлена — ждём подтверждения из игры.</p> : state.build.message ? <p role="status">{state.build.message}</p> : null}
          <div className="panel-choices">{build.specializations?.map(spec => <button type="button" key={spec.id} data-bnr-build-spec={spec.id} aria-pressed={build.specialization === spec.id} disabled={!manage || build.specialization === spec.id} onClick={() => perform('hero.set_specialization', { specialization: spec.id })}><strong>{spec.label}</strong><span>{spec.description}</span></button>)}</div>
          {build.starter_claimed ? <p className="panel-muted">✓ Стартовый набор получен. Все вещи — во вкладке «Инвентарь».</p> : <><h2>Стартовый комплект</h2><p className="panel-muted">Один бесплатный набор на героя. Полученные вещи можно заменить через магазин.</p>
            <div className="panel-choices">{build.starter_kits?.map(kit => <article key={kit.id}><h3>{kit.label}</h3><p>{kit.items?.map(item => item.name || item.item_id).join(' · ')}</p><button type="button" data-bnr-build-starter={kit.id} disabled={!manage || !kit.available} onClick={() => perform('hero.claim_starter', { starter_kit: kit.id })}>Получить бесплатно</button>{!kit.available && kit.reason && <p className="panel-muted">{kit.reason}</p>}</article>)}</div></>}
        </> : state.hero?.equipment_shop_ready ? <p className="panel-muted">Снаряжение выбирается во вкладке «Инвентарь». Текущие способности пока сохраняются.</p> : state.classes ? <>
          <label htmlFor="panel-class-select">Класс</label><select id="panel-class-select" disabled={!canAct} value={state.classes.current?.class_key || ''} onChange={event => { const key = event.currentTarget.value; if (key && key !== state.classes?.current?.class_key) perform('hero.set_class', { price: 0, class_key: key }); }}>
            {!state.classes.current?.class_key && <option value="" disabled>— выбери класс —</option>}{state.classes.classes.map(option => <option key={option.class_key} value={option.class_key}>{option.name}</option>)}
          </select>{state.classes.current && <p className="panel-muted">Класс lvl {state.classes.current.class_level} · {state.classes.current.primary_skill} {state.classes.current.primary_skill_level}{state.classes.current.next_threshold ? `/${state.classes.current.next_threshold} → lvl ${(state.classes.current.class_level || 0) + 1}` : ' (MAX)'}</p>}
        </> : <p className="panel-muted">Загружаем варианты развития…</p>}
      </section>
    </> : null}
  </section>;
}
