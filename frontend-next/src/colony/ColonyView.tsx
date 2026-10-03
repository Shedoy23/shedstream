import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import type { ViewerClient } from '../common/client';
import { ConfirmDialog } from '../common/ConfirmDialog';
import { colonyActions, type ColonyKind } from './contracts';
import '../common/common.css';
import {ColonyController} from './controller';
type Choice = { kind: ColonyKind; type: string; label: string; detail: string; price: number; data: Record<string, unknown>; citizen?: number };
const quote = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n) && n >= 0;
export function ColonyView({ client, controller }: { client: ViewerClient; controller?:ColonyController }) {
  const game=useMemo(()=>controller||new ColonyController(),[controller]);
  const {config,citizen,cap,message:loadMessage,actionMessage,busy,uncertain}=useSyncExternalStore(game.subscribe,game.snapshot);
  const message=actionMessage||loadMessage;
  const [tab, setTab] = useState('me'), [selected, setSelected] = useState<Record<string, string>>({}), [choice, setChoice] = useState<Choice | null>(null);
  const latest = useRef({ config, citizen, cap }); latest.current = { config, citizen, cap };
  useEffect(() => {
    const stop=controller?undefined:game.attach(client);
    return () => { stop?.(); };
  }, [client,controller,game]);
  const skills = citizen?.state?.skills && Object.keys(citizen.state.skills).length ? citizen.state.skills : citizen?.skills || {};
  const targets = cap?.targets, requests = citizen?.state?.requests;
  const options = (kind: ColonyKind): [string, string][] => {
    if (kind === 'job') return (cap?.jobs || []).filter(j => j.free > 0).map(j => [j.job, `${j.job} (${j.free} свободно)`]);
    if (kind === 'xp') return Object.keys(skills).map(key => [key, `${key}: ${skills[key]}`]);
    if (kind === 'give_item' || kind === 'supply' || kind === 'min_stock') return (config?.item_catalog?.[kind] || []).filter(p => Array.isArray(p) && typeof p[0] === 'string' && !!p[0]).map(p => [p[0], String(p[1] || p[0])]);
    if (kind === 'start_research' || kind === 'finish_research') return (targets?.researches || []).filter(r => r.state === (kind === 'start_research' ? 'available' : 'in_progress')).map(r => [r.branch + '|' + r.id, r.name || r.id]);
    if (kind === 'clear_backlog') return (targets?.buildings || []).map(b => [b.pos, `${b.type} (${b.backlog} в очереди)`]);
    if (kind === 'upgrade_building') return (targets?.upgradable || []).filter(b => !b.in_progress).map(b => [b.pos, `${b.type} ${b.pos} · уровень ${b.level}`]);
    if (kind === 'set_guard_task') return [['guard', 'Охрана'], ['patrol', 'Патруль']];
    if (kind === 'set_guard_retreat') return [['on', 'Отступать'], ['off', 'Не отступать']];
    return [];
  };
  const selectIds: Partial<Record<ColonyKind, string>> = { job: 'sc-job-select', xp: 'sc-skill-select', give_item: 'sc-give-select', supply: 'sc-supply-select', min_stock: 'sc-minstock-item-select', clear_backlog: 'sc-backlog-select', upgrade_building: 'sc-upgrade-select', start_research: 'sc-research-start-select', finish_research: 'sc-research-finish-select', set_guard_task: 'sc-guardtask-select', set_guard_retreat: 'sc-retreat-select' };
  const value = (kind: ColonyKind) => selected[kind] ?? options(kind)[0]?.[0] ?? '';
  const payload = (kind: ColonyKind, request?: string): Record<string, unknown> => {
    if (kind === 'job') return { job: value(kind) };
    if (kind === 'xp') return { skill: value(kind) };
    if (kind === 'give_item' || kind === 'supply') return { item: value(kind) };
    if (kind === 'min_stock') return { item: value(kind), qty: Number(selected.qty ?? '1') };
    if (kind === 'clear_backlog' || kind === 'upgrade_building') return { building: value(kind) };
    if (kind === 'start_research' || kind === 'finish_research') { const [branch, ...rest] = value(kind).split('|'); return { branch, research: rest.join('|') }; }
    if (kind === 'set_guard_task') return { task: value(kind) };
    if (kind === 'set_guard_retreat') return { retreat: value(kind) !== 'off' };
    if (kind === 'fulfill' && request) return { request_id: request };
    return {};
  };
  const allowed = (kind: ColonyKind, data: Record<string, unknown>) => {
    if (!citizen?.success || !cap?.success || cap.stale !== false || busy || uncertain) return false;
    if (kind === 'spawn') return !citizen.linked;
    if (!citizen.linked) return false;
    if (kind === 'home' && cap.free_beds != null && cap.free_beds <= 0) return false;
    if (kind === 'cure' && citizen.state?.sick === false) return false;
    if (kind === 'heal' && citizen.state?.hp !== undefined && citizen.state.max_hp !== undefined && citizen.state.hp >= citizen.state.max_hp) return false;
    if (kind === 'give_tools' && !(citizen.state?.job || citizen.job)) return false;
    if (kind === 'upgrade_building' && !targets?.can_build) return false;
    if (kind === 'min_stock' && (!targets?.min_stock?.warehouse || !Number.isInteger(data.qty) || Number(data.qty) <= 0)) return false;
    if (kind === 'fulfill' && data.request_id) return !!requests?.some(r => typeof r !== 'string' && r.id === data.request_id && r.deliverable !== false);
    if (selectIds[kind]) { const actual = kind === 'job' ? data.job : kind === 'xp' ? data.skill : kind.includes('research') ? data.branch + '|' + data.research : kind === 'set_guard_task' ? data.task : kind === 'set_guard_retreat' ? (data.retreat ? 'on' : 'off') : data.building ?? data.item; return options(kind).some(([id]) => id === actual); }
    return true;
  };
  useEffect(() => { if (choice && (choice.citizen !== citizen?.citizen_id || !allowed(choice.kind, choice.data) || config?.action_prices?.[choice.type] !== choice.price)) setChoice(null); }, [citizen, cap, config, busy, uncertain, choice]);
  const submit = () => {
    const intent = choice; setChoice(null);
    if (!intent || !allowed(intent.kind, intent.data) || latest.current.config?.action_prices?.[intent.type] !== intent.price || latest.current.citizen?.citizen_id !== intent.citizen) return;
    void game.action(client,intent.type,intent.data,intent.label);
  };
  const button = (kind: ColonyKind, type: string, label: string, data = payload(kind)) => {
    const price = config?.action_prices?.[type];
    return <button type="button" data-sc={kind} disabled={!quote(price) || !allowed(kind, data)} onClick={() => { if (quote(price)) setChoice({ kind, type, label, detail: options(kind).find(([id]) => id === value(kind))?.[1] || '', price, data, citizen: citizen?.citizen_id }); }}>{label} · {quote(price) ? `${price.toLocaleString('ru-RU')} 💎` : 'Цена недоступна'}</button>;
  };
  return <section className="panel-card"><h1>Колония стримера</h1><p role="status">{message}</p>{(!cap || cap.stale) && <p role="alert">Нет свежего снимка Minecraft — покупки недоступны.</p>}
    {citizen?.linked && <><h2>{citizen.name || 'Мой колонист'}</h2><p>Работа: {citizen.state?.job || citizen.job || 'нет'} · Дом: {citizen.state?.has_home ? 'есть' : 'нет'}</p><p>Здоровье: {citizen.state?.hp ?? citizen.hp ?? 'неизвестно'}{citizen.state?.max_hp !== undefined ? ` / ${citizen.state.max_hp}` : ''} · Сытость: {citizen.state?.saturation ?? 'неизвестно'}</p><p>Настроение: {citizen.state?.happiness ?? 'неизвестно'} · {citizen.status}</p><dl>{Object.entries(skills).map(([skill, level]) => <div key={skill}><dt>{skill}</dt><dd>{level}</dd></div>)}</dl><nav className="panel-tabs" aria-label="Колония">{[['me', 'Колонист'], ['gear', 'Экипировка'], ['colony', 'Колония']].map(([key, title]) => <button type="button" key={key} aria-pressed={tab === key} onClick={() => setTab(key)}>{title}</button>)}</nav></>}
    {['me', 'gear', 'colony'].map(pane => <div key={pane} hidden={tab !== pane}>{colonyActions.filter(([, , , section]) => section === pane).filter(([kind]) => kind === 'spawn' ? !citizen?.linked : citizen?.linked).map(([kind, type, label]) => <details key={kind} open><summary>{label}</summary>
      {selectIds[kind] && <label>{label}<select id={selectIds[kind]} value={value(kind)} onInput={e => { const val = e.currentTarget.value; setSelected(s => ({ ...s, [kind]: val })); }}>{options(kind).length ? options(kind).map(([id, text]) => <option key={id} value={id}>{text}</option>) : <option value="">Нет доступных вариантов</option>}</select></label>}
      {kind === 'min_stock' && <label>Количество стаков<input id="sc-minstock-qty-select" type="number" step="1" value={selected.qty ?? '1'} onInput={e => { const val = e.currentTarget.value; setSelected(s => ({ ...s, qty: val })); }} /></label>}
      {kind === 'fulfill' && requests ? requests.length ? requests.map((r, i) => <div key={typeof r === 'string' ? i : r.id || i}>{typeof r !== 'string' && r.deliverable === false ? <p>{r.text} — выполнит колония</p> : button(kind, type, 'Выполнить: ' + (typeof r === 'string' ? r : r.text), payload(kind, typeof r === 'string' ? undefined : r.id))}</div>) : <p>Просьб сейчас нет.</p> : button(kind, type, label)}
    </details>)}</div>)}
    {choice && <ConfirmDialog title={choice.label} confirm={() => { void submit(); }} cancel={() => setChoice(null)}><p>Списать {choice.price.toLocaleString('ru-RU')} 💎 и отправить заявку в игру?</p>{choice.detail && <p>{choice.detail}{choice.kind === 'min_stock' ? ` — ${String(choice.data.qty)} стаков` : ''}</p>}<p>Действие выполнится позже. При отказе игры результат и возврат сообщит сервер.</p></ConfirmDialog>}
  </section>;
}
