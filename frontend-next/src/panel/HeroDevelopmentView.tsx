import { useSyncExternalStore } from 'react';
import { RetinueView } from './RetinueView';
import { ProgressionView } from './ProgressionView';
import { HeroLifecycleView } from './HeroLifecycleView';
import { DailyView } from './DailyView';
import { HeroProfileView } from './HeroProfileView';
import { ShopView } from './ShopView';
import { LegacyGearView } from './LegacyGearView';
import { HeroSummaryView } from './HeroSummaryView';
import type { PanelController } from './controller';
export function HeroDevelopmentView({ controller, full=false }: { controller: PanelController;full?:boolean }) {
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot);
  const hero = state.hero?.hero;
  const canRead = state.canAct && controller.ready();
  const canAct = canRead && !state.mutationBlocked;
  const build = state.build?.build;
  const newBuild = state.newBuild;
  const buildBusy = state.buildBusy;
  const manage = canAct && !!state.build?.ready && !!state.build.can_manage && !state.buildPending && !state.build.pending && !build?.in_battle && !buildBusy;
  const perform = (type: string, data: Record<string, unknown>, immediateHero = false) => { if (controller.ready()) void controller.action(type, data, { tail: 'hero', immediateHero }); };
  return <section className="panel-development" aria-label="Развитие героя">
    <div className="panel-section-heading"><div><p className="panel-eyebrow">BANNERLORD</p><h1>Развитие героя</h1></div>
      <button type="button" disabled={!canRead || state.loading} onClick={() => { void controller.refreshDevelopment(); }}>Обновить</button></div>
    {state.loading && !state.hero && <p role="status">Загружаем героя…</p>}
    {state.error && <p className="panel-error" role="alert">{state.error}</p>}
    {state.message && <p className="panel-notice" role="status">{state.message}</p>}
    <HeroLifecycleView controller={controller} />
    <HeroSummaryView controller={controller}/>
    {hero?.is_alive ? <>
      {full&&<LegacyGearView controller={controller}/>}
      {full&&<DailyView key={state.generation+':daily'} controller={controller}/>}
      <RetinueView key={state.generation + ':' + hero.hero_id} controller={controller} />
      <ProgressionView controller={controller} includeXp={!full} />
      {full&&<HeroProfileView key={state.generation+':gender'} controller={controller} mode="gender"/>}
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
    {full&&<ShopView controller={controller}/>}
  </section>;
}
