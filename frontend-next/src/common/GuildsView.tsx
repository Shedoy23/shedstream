import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { ViewerRuntime } from './runtime';
import { ConfirmDialog } from './ConfirmDialog';
import './common.css';
interface Guild { guild_id: number; name: string; tagline?: string; master: string; my_role?: string; balance: number; member_count?: number; members?: { username: string; role: string }[]; skills?: Record<string, number>; top_contributors?: { username: string; total: number }[] }
interface Skill { skill_key: string; name: string; description?: string; max_level: number; cost_per_level: number[] }
interface Reply { success?: boolean; message?: string; in_guild?: boolean; guild?: Guild; guilds?: Guild[]; skills?: Skill[] }
interface Pending { action: string; body?: Record<string, unknown>; title: string; cost?: number; owner?: number; level?: number }
// The legacy public skill catalog is cached for the shell lifetime, not persisted.
const skillCache = new WeakMap<ViewerRuntime, Skill[]>();
export function GuildsView({ runtime }: { runtime: ViewerRuntime }) {
  const { client, config } = useSyncExternalStore(runtime.subscribe, runtime.snapshot);
  const [skills, setSkills] = useState<Skill[]>([]), [mine, setMine] = useState<Guild | null>(null), [info, setInfo] = useState<Guild | null>(null), [guilds, setGuilds] = useState<Guild[]>([]);
  const [name, setName] = useState(''), [tagline, setTagline] = useState(''), [amount, setAmount] = useState(''), [message, setMessage] = useState(''), [busy, setBusy] = useState(true), [pending, setPending] = useState<Pending | null>(null);
  const alive = useRef(true), generation = useRef(0);
  const current = () => alive.current && client && runtime.snapshot().client === client;
  const createCost = typeof config?.guild_create_cost === 'number' && Number.isFinite(config.guild_create_cost) && config.guild_create_cost >= 0 ? config.guild_create_cost : null;
  async function refresh() {
    if (!client) return; const seq = ++generation.current;
    const data = await client.read<Reply>('/api/guild/my'); if (!current() || seq !== generation.current) return;
    if (!data.success) throw new Error(data.message || 'Не удалось загрузить гильдию');
    setInfo(null); setMine(data.in_guild && data.guild ? data.guild : null);
    if (!data.in_guild) { const list = await client.read<Reply>('/api/guild/list'); if (current() && seq === generation.current) { if (!list.success) throw new Error(list.message || 'Не удалось загрузить список'); setGuilds(list.guilds || []); } }
  }
  useEffect(() => { alive.current = true; setBusy(true); setPending(null);
    void (async () => { if (!client) return; let catalog = skillCache.get(runtime); if (!catalog) { const data = await client.read<Reply>('/api/guild/skills/config', false); if (data.success) { catalog = data.skills || []; skillCache.set(runtime, catalog); } }
      if (!current()) return; setSkills(catalog || []); await refresh();
    })().catch(error => { if (current()) setMessage(error instanceof Error ? error.message : 'Сеть недоступна'); }).finally(() => { if (current()) setBusy(false); });
    return () => { alive.current = false; generation.current++; };
  }, [client, runtime]);
  async function detail(id: number) {
    if (!client || busy) return; setBusy(true); setMessage(''); const seq = ++generation.current;
    try { const data = await client.read<Reply>('/api/guild/' + id); if (current() && seq === generation.current) { if (!data.success || !data.guild) throw new Error(data.message || 'Гильдия не найдена'); setInfo(data.guild); } }
    catch (error) { if (current()) setMessage(error instanceof Error ? error.message : 'Сеть недоступна'); } finally { if (current()) setBusy(false); }
  }
  async function back() { setBusy(true); setPending(null); try { await refresh(); } catch (error) { if (current()) setMessage(error instanceof Error ? error.message : 'Сеть недоступна'); } finally { if (current()) setBusy(false); } }
  async function execute(action: Pending) {
    if (!client || busy || !current()) return;
    const skill = action.action === 'upgrade-skill' ? skills.find(s => s.skill_key === action.body?.skill_key) : null;
    if ((action.owner !== undefined && mine?.guild_id !== action.owner) || (action.action === 'create' && action.cost !== createCost) || (skill && (mine?.skills?.[skill.skill_key] || 0) !== action.level)) { setPending(null); setMessage('Гильдия или цена изменились. Проверь данные ещё раз.'); return; }
    setPending(null); setBusy(true); setMessage('');
    try {
      const data = await client.post<Reply>('/api/guild/' + action.action, action.body); if (!current()) return;
      setMessage(data.message || (data.success ? 'Готово' : 'Сервер отказал в действии'));
      if (data.success) { if (action.action === 'create' || action.action === 'contribute') void client.refreshUser().catch(error => { if (current()) setMessage(error.message); }); await refresh(); }
    } catch (error) { if (current()) setMessage(error instanceof Error ? error.message : 'Сеть недоступна. Результат неизвестен.'); } finally { if (current()) setBusy(false); }
  }
  const card = info || mine;
  return <section className="panel-card"><h2>Гильдии</h2>{message && <p role="status">{message}</p>}{busy && <p aria-live="polite">Загрузка…</p>}
    {card ? <><h3>{card.name}</h3><p>{card.tagline}</p><p>Глава: @{card.master} · {card.member_count ?? card.members?.length ?? '—'} участников</p><p>Копилка: {card.balance.toLocaleString('ru-RU')} 💎</p>
      {info ? <><h3>Участники</h3>{info.members?.map(member => <p key={member.username}>@{member.username} · {member.role}</p>)}<h3>Вкладчики</h3>{info.top_contributors?.map(member => <p key={member.username}>@{member.username} · {member.total} 💎</p>)}<button type="button" disabled={busy} onClick={() => { void execute({ action: 'join', body: { guild_id: info.guild_id }, title: info.name }); }}>Вступить</button><button type="button" disabled={busy} onClick={() => { void back(); }}>Назад</button></> : <>
        <label>Сумма вклада<input type="number" value={amount} onInput={e => setAmount(e.currentTarget.value)} /></label><button type="button" disabled={busy || !Number.isFinite(parseInt(amount, 10)) || parseInt(amount, 10) <= 0} onClick={() => setPending({ action: 'contribute', body: { amount: parseInt(amount, 10) }, title: `Вклад в ${card.name}`, cost: parseInt(amount, 10), owner: card.guild_id })}>Внести</button>
        <h3>Навыки гильдии</h3>{skills.map(skill => { const level = card.skills?.[skill.skill_key] || 0, cost = skill.cost_per_level[level], knownCost = typeof cost === 'number' && Number.isFinite(cost) && cost >= 0; return <article className="panel-card" key={skill.skill_key}><h4>{skill.name} · {level}/{skill.max_level}</h4><p>{skill.description}</p>{level >= skill.max_level ? <p>Максимальный уровень</p> : card.my_role === 'master' && (knownCost ? <button type="button" disabled={busy || card.balance < cost} onClick={() => setPending({ action: 'upgrade-skill', body: { skill_key: skill.skill_key }, title: skill.name, cost, owner: card.guild_id, level })}>Прокачать {skill.name} за {cost} 💎</button> : <p>Цена следующего уровня не получена.</p>)}</article>; })}
        <button type="button" disabled={busy} onClick={() => { void detail(card.guild_id); }}>Участники и вкладчики</button>
        <button type="button" disabled={busy} onClick={() => setPending({ action: card.my_role === 'master' ? 'disband' : 'leave', owner: card.guild_id, title: card.my_role === 'master' ? `Расформировать ${card.name}? Копилка будет потеряна.` : `Покинуть ${card.name}?` })}>{card.my_role === 'master' ? 'Расформировать гильдию' : 'Покинуть гильдию'}</button>
      </>}
    </> : !busy && <><h3>Создать гильдию</h3><label>Название гильдии<input value={name} onInput={e => setName(e.currentTarget.value)} /></label><label>Девиз<input value={tagline} onInput={e => setTagline(e.currentTarget.value)} /></label>{createCost === null ? <p>Цена создания не получена от сервера.</p> : <button type="button" disabled={busy || !name.trim()} onClick={() => setPending({ action: 'create', body: { name: name.trim(), tagline: tagline.trim() }, title: `Создать гильдию «${name.trim()}»?`, cost: createCost })}>Создать за {createCost} 💎</button>}
      <h3>Гильдии канала</h3>{guilds.length ? guilds.map(guild => <article className="panel-card" key={guild.guild_id}><h4>{guild.name}</h4><p>{guild.tagline}</p><p>@{guild.master} · {guild.member_count} участников · {guild.balance} 💎</p><button type="button" disabled={busy} onClick={() => { void detail(guild.guild_id); }}>Открыть {guild.name}</button></article>) : <p>Пока нет гильдий.</p>}
    </>}
    {pending && <ConfirmDialog title={pending.title} confirm={() => { void execute(pending); }} cancel={() => setPending(null)}>{pending.cost !== undefined && <p>{pending.action === 'upgrade-skill' ? 'Из копилки гильдии' : 'С твоего баланса'}: {pending.cost} 💎</p>}</ConfirmDialog>}
  </section>;
}
