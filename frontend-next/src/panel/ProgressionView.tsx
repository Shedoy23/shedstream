import { useLayoutEffect, useState, useSyncExternalStore } from 'react';
import { ConfirmDialog } from '../common/ConfirmDialog';
import '../common/common.css';
import type { PanelController } from './controller';
import { actionKey } from './contracts';
import { contentName, progressionActionType, progressionContext, progressionMoney, progressionQuote, progressionReason, type AttributeProgression, type GoldOffer, type ProgressionKind, type SkillProgression } from './progression';
type Selection = {kind: ProgressionKind; id: string; label: string; data: Record<string, unknown>; price: number; generation: number};
const display = (n: unknown) => typeof n === 'number' && Number.isFinite(n) ? String(n) : '—';
const money = (n: number, currency = '💰') => n.toLocaleString('ru-RU') + ' ' + currency;
// Presentation grouping only. IDs, prices and limits still come from the game.
const vanillaAttribute:Record<string,string>={onehanded:'vigor',twohanded:'vigor',polearm:'vigor',bow:'control',crossbow:'control',throwing:'control',riding:'endurance',athletics:'endurance',crafting:'endurance',scouting:'cunning',tactics:'cunning',roguery:'cunning',charm:'social',leadership:'social',trade:'social',steward:'intelligence',medicine:'intelligence',engineering:'intelligence'};
export function ProgressionView({controller,includeXp=true}: {controller: PanelController;includeXp?:boolean}) {
  const s = useSyncExternalStore(controller.subscribe, controller.snapshot), snapshot = s.progression;
  const [selection,setSelection] = useState<Selection | null>(null);
  const context = progressionContext(snapshot,s.hero), game = context ? snapshot?.progression : null;
  const attributes: AttributeProgression[] = Array.isArray(game?.attributes) ? game.attributes.filter(a => a && typeof a.id === 'string')
    : Object.entries(s.hero?.attributes || {}).map(([id,value]) => ({id,value}));
  const skills: SkillProgression[] = Array.isArray(game?.skills) ? game.skills.filter(a => a && typeof a.id === 'string')
    : (s.hero?.skills || []).map(skill => ({id:skill.skill_key,level:skill.level,focus:skill.focus}));
  const group=(skill:SkillProgression)=>(skill.attribute||vanillaAttribute[skill.id.toLowerCase()]||'').toLowerCase();
  const known=new Set(attributes.map(a=>a.id.toLowerCase()));
  const currentQuote = (kind: ProgressionKind, id: string) => progressionQuote(controller.snapshot().progression,kind,id,controller.snapshot().hero);
  useLayoutEffect(() => {
    if (selection && (!s.canAct || selection.generation !== s.generation || JSON.stringify(currentQuote(selection.kind,selection.id)) !== JSON.stringify(selection.data))) setSelection(null);
  },[selection,s.progression,s.hero,s.canAct,s.generation]);
  const choose = (kind: ProgressionKind,id: string,label: string) => {
    const data = currentQuote(kind,id);
    if (!controller.ready() || s.mutationBlocked || !data || controller.cooldown(progressionActionType(kind)) > 0) return;
    setSelection({kind,id,label,data,price:Number(data.expected_cost_gold ?? data.expected_platform_price),generation:s.generation});
  };
  const button = (kind: 'focus' | 'attribute', id: string, options: GoldOffer[] | undefined) => {
    const type = progressionActionType(kind), data = progressionQuote(snapshot,kind,id,s.hero);
    const option = Array.isArray(options) ? options.find(o => o?.amount === 1) : undefined;
    const name = contentName(kind === 'focus' ? s.catalogs?.skills : s.catalogs?.attributes,id);
    const price = option?.cost_gold, cd = controller.cooldown(type);
    const reason = !context || snapshot?.pending ? progressionReason(snapshot) : option?.reason_text || option?.reason || (!data ? 'Нет доступного предложения игры' : '');
    return <span><button type="button" className="panel-progress-button" {...(kind === 'focus' ? {'data-skill':id} : {'data-attr':id})}
      aria-label={`${kind === 'focus' ? 'Добавить фокус' : 'Повысить атрибут'} ${name}`}
      title={reason || (progressionMoney(price) ? `+1 · ${money(price)}` : 'Цена недоступна')}
      disabled={!s.canAct || s.mutationBlocked || !data || cd > 0 || s.busy.includes(actionKey(type,data || {}))}
      onClick={() => choose(kind,id,name)}>{cd > 0 ? `${Math.ceil(cd)} с` : '+1'}<small>{progressionMoney(price) ? money(price) : '—'}</small></button>
      {reason && <small className="panel-muted">{reason}</small>}</span>;
  };
  const skillRow=(skill:SkillProgression)=><div className="panel-skill" key={skill.id}><span>{contentName(s.catalogs?.skills,skill.id)}
    <small>Уровень {display(skill.level)} · Фокус {display(skill.focus)}{typeof skill.native_focus_limit === 'number' ? '/' + display(skill.native_focus_limit) : ''}</small>
    {typeof skill.focus_limit === 'number' && <small>Предел покупки: {display(skill.focus_limit)}</small>}</span>{button('focus',skill.id,skill.focus_options)}</div>;
  const ungrouped=skills.filter(skill=>!known.has(group(skill)));
  return <section className="panel-card" aria-label="Атрибуты и навыки"><h2>Атрибуты и навыки</h2>
    <p className="panel-muted">Значения, цены и пределы покупок передаёт игра. Заявка применяется после подтверждения из игры.</p>
    {(!context || snapshot?.pending) && <p role="status" className="panel-notice">{progressionReason(snapshot)}</p>}
    {!attributes.length && !skills.length && <p>Игра не передала навыки и атрибуты.</p>}
    {attributes.map(a => <div className="panel-attribute-group" data-attribute-group={a.id.toLowerCase()} key={a.id}><div className="panel-attribute">
      <strong>{contentName(s.catalogs?.attributes,a.id)}</strong><span>{display(a.value)}{typeof a.native_limit === 'number' ? '/' + display(a.native_limit) : ''}</span>
      {button('attribute',a.id,a.options)}</div>{typeof a.limit === 'number' && <small className="panel-muted">Предел покупки: {display(a.limit)}</small>}{skills.filter(skill=>group(skill)===a.id.toLowerCase()).map(skillRow)}</div>)}
    {!!ungrouped.length&&<div className="panel-attribute-group" data-attribute-group="other"><h3>Прочие навыки</h3>{ungrouped.map(skillRow)}</div>}
    {includeXp&&!!snapshot?.xp_offers?.length && <><h3>Опыт в случайный навык</h3><div className="panel-choices">{snapshot.xp_offers.map(offer => {
      const data = progressionQuote(snapshot,'xp',offer.id,s.hero), reason = snapshot.pending ? progressionReason(snapshot) : offer.reason_text || offer.reason;
      return <article key={offer.id}><p>+{display(offer.xp)} XP · {progressionMoney(offer.price) ? money(offer.price,'💎') : 'Цена недоступна'}</p>
        <button type="button" data-bnr-skillxp={offer.id} disabled={!s.canAct || s.mutationBlocked || !data || controller.cooldown('hero.add_skill') > 0 || s.busy.includes(actionKey('hero.add_skill',data || {}))} onClick={() => choose('xp',offer.id,`+${offer.xp} XP`)}>Купить опыт</button>{reason && <p className="panel-muted">{reason}</p>}</article>;
    })}</div></>}
    {selection && <ConfirmDialog title="Подтвердить прокачку" cancel={() => setSelection(null)} confirm={() => {
      const shown = selection; setSelection(null);
      if (shown.generation === controller.identityGeneration()) void controller.progressionAction(shown.kind,shown.id,shown.data);
    }}><p>{selection.label}: {selection.kind === 'xp' ? 'покупка опыта' : '+1'}. Стоимость {money(selection.price,selection.kind === 'xp' ? '💎' : '💰')}.</p><p>Это заявка; окончательный результат придёт из игры.</p></ConfirmDialog>}
  </section>;
}
