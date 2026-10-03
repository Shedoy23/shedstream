// Isolated loopback fixtures. No real JWT, backend, payment, or external bytes.
import { chromium } from 'playwright';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { resolve, extname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import http from 'node:http';
import {gzipSync} from 'node:zlib';
const root = fileURLToPath(new URL('../', import.meta.url));
const dist = resolve(root, 'dist');
const output = resolve(root, '../docs/evidence/full-port/browser');
mkdirSync(output, { recursive: true });
const read = name => JSON.parse(readFileSync(resolve(root, 'test/panel-fixtures/' + name), 'utf8')).responses;
const f = read('real-responses.json'), c = read('combat-responses.json'), r = read('forge-tournament-responses.json');
const g = read('game-progression-responses.json');
const properties = read('property-responses.json');
const profile = read('hero-profile-responses.json');
const children = read('children-responses.json');
const civic = read('vassal-ransom-responses.json');
const rewards = read('upgrade-achievement-responses.json');
const commerce = read('commerce-responses.json');
const games=read('community-game-responses.json');
const social=read('social-family-responses.json');let socialStatus=social.single,socialProposals=social.proposals;
const rw=read('rimworld-responses.json');let rwPawn=rw.pawn,rwCooldown=rw.cooldown;
const queues=new Map(),rooms=new Map();let tugStatus=games.tug_status_idle;
const h = read('hero-lifecycle-responses.json'), k = read('kingdom-responses.json'), party = read('party-responses.json');
let heroSnapshot=r.hero_forge;
let dailySnapshot=h.daily_ready;
let tournament = r.tournament_empty;
let petsEnabled = true;
let closedCases = [71, 72];
const petSkin = { item_id: 'skin_frog_samurai', name: 'Лягушка-самурай', slot: 'body', rarity: 'epic', png_path: '/fixture-pet.png', price_crustics: 500000 };
let petOwned = false, petName = 'Друг';
let activeModule = 'bannerlord';
const fixtureToken = 'fixture.' + Buffer.from(JSON.stringify({ user_id: '456', channel_id: '123' })).toString('base64') + '.fixture';
let notices = [{ id: 91, text: 'Цель исчезла до выполнения заявки.', amount: 2300 }];
let inGuild = false;
let voteActive = true;
const voteEvent = { event_id: 51, template_name: 'Следующая игра', ends_at: '', total_pool: 4200, allow_proposals: true, options: [{ id: 701, label: 'Игра А', description: 'Первый вариант', pool: 1200 }, { id: 702, label: 'Игра Б', description: 'Второй вариант', pool: 3000 }] };
const guild = { guild_id: 29, name: 'Стражи', tagline: 'Вместе', master: 'alice', my_role: 'master', balance: 100000, member_count: 2, members: [{ username: 'alice', role: 'master' }, { username: 'bob', role: 'member' }], skills: { watch: 0 }, top_contributors: [{ username: 'alice', total: 4567 }] };
const guildSkills = [{ skill_key: 'watch', name: 'Сила сообщества', description: 'Серверное описание', max_level: 3, cost_per_level: [12345, 23456, 34567] }];
const colonySource = readFileSync(resolve(root, '../Расширение/frontend/viewer-shedcolony.js'), 'utf8');
const colonyConfig = { action_prices: Object.fromEntries([...colonySource.matchAll(/^\s+(\w+):\s*\{ type: '([^']+)',\s*price: \d+ \},/gm)].map((m, i) => [m[2], 1200 + i * 37])), item_catalog: { give_item: [['minecraft:bread', 'Хлеб']], supply: [['minecraft:oak_log', 'Брёвна']], min_stock: [['minecraft:torch', 'Факелы']] } };
const colonist = { success: true, linked: true, citizen_id: 41, name: 'Алиса', job: 'knight', hp: 12, skills: { Athletics: 5, Strength: 8 }, status: 'На работе', state: { job: 'knight', hp: 12, max_hp: 20, saturation: 30, sick: true, happiness: 5, has_home: false, requests: [{ id: 'req-A', text: 'Нужен хлеб', deliverable: true }] } };
const colonyCapacity = { success: true, jobs: [{ job: 'farmer', free: 2, total: 3 }], free_beds: 3, stale: false, data_age_sec: 1, targets: { researches: [{ branch: 'technology', id: 'mining/one', name: 'Копка', state: 'available' }, { branch: 'civilian', id: 'farm/two', name: 'Ферма', state: 'in_progress' }], buildings: [{ pos: '1,2,3', type: 'builder', backlog: 2 }], min_stock: { warehouse: true }, can_build: true, upgradable: [{ pos: '4,5,6', type: 'warehouse', level: 1, in_progress: false }] } };
const trace = [], errors = [], blocked = [], screenshots = [], startupAssets=[];
const api = new Map([
  ['/api/duel/leaderboard',games.rps_leaderboard],['/api/tictactoe/leaderboard',games.ttt_leaderboard],
  ['/api/bannerlord/shop',commerce.shop],['/api/bannerlord/status',commerce.status],
  ['/api/bannerlord/clan-upgrades',rewards.catalog],['/api/bannerlord/clan-upgrades/buy',rewards.buy.response],['/api/bannerlord/achievements',rewards.achievements],
  ['/api/bannerlord/vassals',civic.vassals],['/api/bannerlord/eligible-heirs',civic.eligible],['/api/bannerlord/ransom-pool',civic.ransom],
  ['/api/bannerlord/heirs',children.heirs],['/api/bannerlord/my-children',children.children],['/api/bannerlord/proposals',children.proposals],['/api/bannerlord/public-children',children.public_children],
  ['/api/bannerlord/my-workshops',properties.workshops],['/api/bannerlord/my-caravans',properties.caravans],['/api/bannerlord/my-fiefs',properties.fiefs],['/api/bannerlord/inheritance-log',properties.inheritance],['/api/bannerlord/settlements',properties.settlements],
  ['/api/bannerlord/content-catalogs', g.catalogs], ['/api/bannerlord/progression', g.progression],
  ['/api/user/resolve-twitch-token', { login: 'alice' }], ['/api/bannerlord/config', r.config],
  ['/api/bannerlord/my-hero', r.hero_forge], ['/api/bannerlord/classes', c.classes_by_key.tank],
  ['/api/bannerlord/build', c.build_no_session], ['/api/bannerlord/my-buffs', c.buffs_empty],
  ['/api/bannerlord/equipment-shop', r.equipment_forge], ['/api/bannerlord/battle-status', c.battle_siege],
  ['/api/viewer/stats/alice', f.stats], ['/api/user/level/alice', f.level], ['/api/duel/list', f.duels],
  ['/api/viewer/ui-usage', f.usage_ok],
  ['/api/core/config', { tts_cost: 7700, tts_max_len: 190, guild_create_cost: 1300, divorce_cost: social.config.divorce_cost, voting_min_bid: 73, voting_min_pledge: 127, voting_bid_presets: [73, 731, 7310], voting_pledge_presets: [127, 1270] }],
  ['/api/voting/bid', { success: true, message: 'Голос учтён' }], ['/api/voting/propose', { success: true, message: 'На одобрении' }],
  ['/api/promo/use', { success: true, message: 'Промокод принят' }], ['/api/tts/submit', { success: true, message: 'Добавлено в очередь' }], ['/api/bug-report', { success: true, message: 'Сообщение принято' }],
  ['/api/viewer/online-list', { users: ['alice', 'bob'] }], ['/api/viewer/online', { status: 'ok' }],
  ['/api/viewer/perks', { success: true, role: 'moderator', twitch_sub_tier: 2 }],
  ['/api/viewer/activity', { status: 'ok' }], ['/api/viewer/attendance', { rewarded: false }],
  ['/api/viewer/achievements/alice', { achievements: [{ key: 'first', emoji: '⭐', name: 'Первый шаг', description: 'Посетить стрим', reward: 456, unlocked: true }] }],
  ['/api/viewer/streak/alice', { current_streak: 3, max_streak: 8 }],
]);
let colonyLoseResponse=false,resolverGate=null;
const colonyRemountEvidence=[];
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  if (url.pathname.startsWith('/api/')) {
    let body = ''; for await (const part of req) body += part;
    trace.push({ method: req.method, path: url.pathname, query: url.search, body });
    let data;
    if(url.pathname==='/api/user/resolve-twitch-token'){if(resolverGate)await resolverGate;data={login:'alice'};}
    else if(url.pathname==='/api/match/queue/status')data=queues.get(url.searchParams.get('game_type'));
    else if(url.pathname==='/api/marriage/status/alice')data=socialStatus;
    else if(url.pathname==='/api/marriage/proposals/alice')data=socialProposals;
    else if(url.pathname==='/api/marriage/propose')data=social.propose;
    else if(url.pathname==='/api/marriage/reject'){data=social.reject;socialProposals={proposals:socialProposals.proposals.filter(name=>name!==JSON.parse(body).from_user)};}
    else if(url.pathname==='/api/marriage/divorce'){data=social.divorce;socialStatus=social.single;}
    else if(url.pathname==='/api/rimworld/config')data=rw.config;
    else if(url.pathname==='/api/rimworld/status')data=rw.status;
    else if(url.pathname==='/api/rimworld/colonists')data=rw.colonists;
    else if(url.pathname==='/api/rimworld/my-pawn/alice')data=rwPawn;
    else if(url.pathname==='/api/rimworld/heal-cooldown/alice')data=rwCooldown;
    else if(url.pathname==='/api/rimworld/catalog')data=url.searchParams.get('category')?rw[url.searchParams.get('category')]:rw.catalog;
    else if(url.pathname==='/api/rimworld/events')data=rw.events;
    else if(url.pathname==='/api/rimworld/pawn-skills/alice')data=rw.skills;
    else if(url.pathname==='/api/rimworld/create-pawn')data=rw.create;
    else if(url.pathname==='/api/rimworld/heal-pawn'){data=rw.heal;rwCooldown=rw.cooldown_after;}
    else if(url.pathname==='/api/rimworld/resurrect-pawn')data=rw.resurrect;
    else if(url.pathname==='/api/rimworld/remove-trait')data=rw.remove_trait;
    else if(url.pathname==='/api/rimworld/remove-gene')data=rw.remove_gene;
    else if(url.pathname==='/api/rimworld/buy-item')data=JSON.parse(body).def_name?rw.xeno:rw.item;
    else if(url.pathname==='/api/rimworld/buy-implant')data=JSON.parse(body).part_hint?rw.paired_implant:rw.implant;
    else if(url.pathname==='/api/rimworld/buy-trait')data=rw.trait;
    else if(url.pathname==='/api/rimworld/buy-gene')data=rw.gene;
    else if(url.pathname==='/api/rimworld/train-skill')data=rw.neuro;
    else if(url.pathname==='/api/rimworld/buy-passion')data=rw.passion;
    else if(url.pathname==='/api/rimworld/reset-passion')data=rw.reset;
    else if(url.pathname==='/api/rimworld/trigger-event')data=rw.event;
    else if(url.pathname==='/api/match/queue'||url.pathname==='/api/match/queue/cancel'){const game=JSON.parse(body).game_type,cancel=url.pathname.endsWith('/cancel');queues.set(game,games[game+(cancel?'_idle':'_queued')]);data=games[game+(cancel?'_cancel':'_join')];}
    else if(url.pathname==='/api/rps/poll'||url.pathname==='/api/tictactoe/poll')data=rooms.get(url.pathname.split('/')[2]);
    else if(url.pathname==='/api/rps/move'||url.pathname==='/api/tictactoe/move'){const game=url.pathname.split('/')[2];data=games[game+'_move'];rooms.set(game,games[game+'_after']);}
    else if(url.pathname==='/api/tug/status')data=tugStatus;
    else if(url.pathname==='/api/tug/pull'){data=games.tug_pull;tugStatus=games.tug_after;}
    else if (url.pathname === '/api/viewer/stats/alice') data = { ...f.stats, active_module: activeModule };
    else if (url.pathname === '/api/bannerlord/my-hero') data=heroSnapshot;
    else if (url.pathname === '/api/bannerlord/party-orders') data=party.orders_none;
    else if (url.pathname === '/api/bannerlord/kingdom-state') data=heroSnapshot.hero?.kingdom_name?k.kingdom_ruler:k.kingdom_independent;
    else if (url.pathname === '/api/bannerlord/daily-status') data=dailySnapshot;
    else if (url.pathname === '/api/bannerlord/daily-claim') {const kind=JSON.parse(body).reward_type;dailySnapshot=h['daily_claimed_'+kind];data=h['daily_'+kind];}
    else if (url.pathname === '/api/notices') data = { success: true, notices };
    else if (url.pathname === '/api/notices/ack') { notices = []; data = { success: true }; }
    else if (url.pathname === '/api/guild/skills/config') data = { success: true, skills: guildSkills };
    else if (url.pathname === '/api/guild/my') data = { success: true, in_guild: inGuild, ...(inGuild ? { guild } : {}) };
    else if (url.pathname === '/api/guild/list') data = { success: true, guilds: [guild] };
    else if (url.pathname === '/api/guild/29') data = { success: true, guild };
    else if (url.pathname === '/api/guild/create') { inGuild = true; data = { success: true, message: 'Гильдия создана' }; }
    else if (url.pathname === '/api/guild/upgrade-skill') { guild.skills.watch = 1; data = { success: true, message: 'Навык улучшен' }; }
    else if (url.pathname === '/api/voting/status') data = { success: true, active_event: voteActive ? voteEvent : null, pool_units: 540, threshold: 947, pool_pct: 57, has_default_template: true, top_bidders: [{ username: 'bob', total: 4200 }] };
    else if (url.pathname === '/api/shedcolony/config') data = colonyConfig;
    else if (url.pathname === '/api/shedcolony/my-colonist') data = colonist;
    else if (url.pathname === '/api/shedcolony/capacity') data = colonyCapacity;
    else if (url.pathname === '/api/shedcolony/action') {
      if(colonyLoseResponse){
        // Send incomplete JSON after receiving the complete request. Dropping
        // before any response bytes can trigger Chromium transport retries;
        // the separate probe records that limit of a client-side action guard.
        res.writeHead(200,{'Content-Type':'application/json','Content-Length':'100','Connection':'close'});
        res.write('{"success":');setTimeout(()=>res.destroy(),50);return;
      }
      data = { success: true, action_id: 'fixture-only', message: 'Принято' };
    }
    else if (url.pathname === '/api/pet/my') data = { success: true, pet: { pet_type: petOwned ? 'creature' : 'egg', name: petName }, inventory: petOwned ? [petSkin] : [], equipped: petOwned ? { body: petSkin } : {} };
    else if (url.pathname === '/api/pet/catalog') data = { success: true, items: [{ ...petSkin, owned: petOwned }] };
    else if (url.pathname === '/api/pet/purchase') { petOwned = true; data = { success: true, hatched: true, message: 'Питомец вылупился' }; }
    else if (url.pathname === '/api/pet/name') { petName = JSON.parse(body).name; data = { success: true, message: 'Имя сохранено' }; }
    else if (url.pathname === '/api/viewer/cases') data = { success: true, cases: closedCases.map(id => ({ id, tier: 'rare', source: 'quest', opened_at: null })), unopened_counts: { rare: closedCases.length, total: closedCases.length }, lifetime_count: 5 };
    else if (url.pathname === '/api/case/preview') data = { success: true, tiers: [{ tier: 'rare', label: 'Редкий', reward_points: 1234 }] };
    else if (url.pathname === '/api/viewer/case/open') { closedCases = closedCases.filter(id => id !== JSON.parse(body).case_id); data = { success: true, tier: 'rare', reward_points: 1234, message: 'Кейс открыт: +1234 💎' }; }
    else if (url.pathname === '/api/viewer/cases/open-all') { closedCases = []; data = { success: true, message: 'Все кейсы открыты' }; }
    else if (url.pathname === '/api/overlay/pets') data = { enabled: petsEnabled };
    else if (url.pathname === '/api/streamer/pets/overlay-toggle') { petsEnabled = JSON.parse(body).enabled; data = { success: true, enabled: petsEnabled }; }
    else if (url.pathname === '/api/bannerlord/tournament') data = tournament;
    else if (url.pathname === '/api/bannerlord/action') {
      const action = JSON.parse(body);
      if (action.action_type === 'hero.join_tournament') { data = r.join.response; tournament = r.tournament_joined; }
      else if (action.action_type === 'tournament.predict') { data = r.predict.response; tournament = r.tournament_predicted; }
      else if (action.action_type === 'hero.add_focus') data = g.focus_success.response;
      else if (action.action_type === 'hero.add_skill') data=g.xp_success.response;
      else if (action.action_type === 'player.give_item') data=commerce.gold_0.response;
      else if (action.action_type === 'hero.army_create') data=commerce.catalog_buy.response;
      else if (action.action_type === 'hero.upgrade_gear') data=commerce.upgrade.response;
      else if (action.action_type === 'hero.reequip_gear') data=commerce.reequip.response;
      else if (action.action_type === 'hero.discard_item') data=commerce.discard.response;
      else if (action.action_type === 'hero.create') data=heroSnapshot.has_hero?h.respawn.response:action.data.culture?h.create_culture.response:h.create_random.response;
      else if (action.action_type === 'hero.enact_policy') data=k.policy_enact.response;
      else if (action.action_type === 'hero.buy_workshop') data=properties.workshop_modded.response;
      else if (action.action_type === 'hero.sell_workshop') data=properties.workshop_sell.response;
      else if (action.action_type === 'hero.buy_caravan') data=properties.caravan_buy.response;
      else if (action.action_type === 'hero.sell_caravan') data=properties.caravan_sell.response;
      else if (action.action_type === 'hero.set_gender') data=profile['gender_'+action.data.gender].response;
      else if (action.action_type === 'hero.marry') data=profile.marry.response;
      else if (action.action_type === 'hero.divorce') data=profile.divorce.response;
      else if (action.action_type === 'hero.make_baby') data=profile.baby.response;
      else if (action.action_type === 'hero.rename_child') data=children.rename.response;
      else if (action.action_type === 'hero.create_vassal_clan') data=civic.create.response;
      else if (action.action_type === 'hero.rename_vassal') data=civic.rename.response;
      else if (action.action_type === 'hero.pay_ransom') data=civic.ransom_pay.response;
      else if (action.action_type === 'hero.change_child_looks') data=children.looks.response;
      else if (action.action_type === 'hero.respec_child_skills') data=children.respec.response;
      else if (action.action_type === 'hero.propose_marriage') data=children.propose.response;
      else if (action.action_type === 'hero.cancel_proposal') data=children.cancel.response;
      else if (action.action_type === 'hero.respond_marriage_proposal') data=children[action.data.accept?'accept':'reject'].response;
    } else data = api.get(url.pathname);
    if (data === undefined) { errors.push('Unmatched fixture ' + req.method + ' ' + req.url); res.writeHead(500); res.end(JSON.stringify({ success: false, message: 'Unmatched fixture' })); return; }
    res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data)); return;
  }
  if (url.pathname === '/fixture-pet.png') { res.setHeader('Content-Type', 'image/png'); res.end(readFileSync(resolve(root, '../Расширение/frontend/pet-assets/v2/frog_samurai/south.png'))); return; }
  const path = resolve(dist, '.' + decodeURIComponent(url.pathname));
  if (!path.startsWith(dist + sep)) { res.writeHead(403); res.end(); return; }
  try {
    const content = readFileSync(path);
    res.setHeader('Content-Type', ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' })[extname(path)] || 'application/octet-stream');
    res.end(content);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise(resolve => server.listen(4187, '127.0.0.1', resolve));
let browser;
try {
  browser = await chromium.launch({ ...(process.env.PANEL_BROWSER_PATH ? { executablePath: process.env.PANEL_BROWSER_PATH } : {}), headless: true, chromiumSandbox: true });
  for (const width of [1280, 375]) {
    const panelPage=width===375?'panel-mobile.html':'panel-extension.html';
    tournament = r.tournament_empty;
    heroSnapshot=r.hero_forge;
    api.set('/api/bannerlord/classes',c.classes_by_key.tank);
    dailySnapshot=h.daily_ready;
    activeModule = 'bannerlord';
    inGuild = false; guild.skills.watch = 0;
    voteActive = true; voteEvent.ends_at = new Date(Date.now() + 600000).toISOString();
    notices = [{ id: 91, text: 'Цель исчезла до выполнения заявки.', amount: 2300 }];
    closedCases = [71, 72];
    petOwned = false; petName = 'Друг';
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    await context.route('**/*', async route => {
      const u = new URL(route.request().url());
      if (u.href === 'https://extension-files.twitch.tv/helper/v1/twitch-ext.min.js') {
        await route.fulfill({ contentType: 'text/javascript', body: `(()=>{const listeners={},authListeners=[],auth={token:${JSON.stringify(fixtureToken)},channelId:"123",userId:"fixture-alice",clientId:"extension-fixture"};let seq=0;window.__fixtureAuthorize=()=>{auth.token+='-rotated';authListeners.forEach(cb=>cb({...auth}));};window.__fixtureEvent=(type,data)=>(listeners.broadcast||[]).forEach(cb=>cb('broadcast','application/json',JSON.stringify({v:1,type,seq:++seq,ts:Date.now(),data})));window.Twitch={ext:{onAuthorized(cb){authListeners.push(cb);queueMicrotask(()=>cb({...auth}))},listen(target,cb){(listeners[target]??=[]).push(cb)},unlisten(target,cb){listeners[target]=(listeners[target]||[]).filter(fn=>fn!==cb)},actions:{requestIdShare(){}}}}})();` }); return;
      }
      if (u.origin === 'http://127.0.0.1:4187') { await route.continue(); return; }
      blocked.push(u.origin + u.pathname); await route.abort();
    });
    const page = await context.newPage();
    const startupPaths=new Set();let collectingStartup=true;
    page.on('request',request=>{const url=new URL(request.url());if(collectingStartup&&url.origin==='http://127.0.0.1:4187'&&!url.pathname.startsWith('/api/'))startupPaths.add(decodeURIComponent(url.pathname));});
    const capture = async options => { await page.screenshot(options); screenshots.push(options.path.slice(output.length+1)); };
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto('http://127.0.0.1:4187/'+panelPage);
    await page.getByRole('status').filter({ hasText: 'Крустики вернулись: +2300' }).waitFor();
    await page.locator('[aria-label="Турнир зрителей"]').waitFor({state:'attached'});
    // Capture all immediately mounted lazy imports before the first user click.
    // This is local gzip potential, not transferred bytes or Twitch load timing.
    let stable=false;for(let tries=0;tries<20;tries++){const before=startupPaths.size;await page.waitForTimeout(250);if(before===startupPaths.size){stable=true;break;}}
    if(!stable)throw Error('Startup asset requests did not settle');collectingStartup=false;
    const assets=[...startupPaths].sort().map(path=>{const file=resolve(dist,'.'+path);if(!file.startsWith(dist+sep))throw Error('Unexpected startup asset '+path);const bytes=readFileSync(file);return {path,raw_bytes:bytes.length,gzip9_bytes:gzipSync(bytes,{level:9}).length};});
    const gzip9_bytes=assets.reduce((sum,x)=>sum+x.gzip9_bytes,0);startupAssets.push({width,page:panelPage,assets,gzip9_bytes,raw_bytes:assets.reduce((sum,x)=>sum+x.raw_bytes,0),budget_bytes:150000,includes_immediate_lazy_imports:true,excludes:['Twitch Helper (local fixture)','API JSON'],twitch_timing_verified:false});
    if(gzip9_bytes>150000)throw Error('Panel startup exceeds 150 KB gzip: '+gzip9_bytes);
    await capture({ path: resolve(output, `shell-refund-${width}.png`), fullPage: true });
    await page.getByRole('button',{name:'Свернуть панель',exact:true}).click();
    await page.getByRole('navigation',{name:'Панель зрителя'}).waitFor({state:'hidden'});
    await capture({path:resolve(output,`shell-collapsed-${width}.png`),fullPage:true});
    await page.getByRole('button',{name:'Развернуть панель',exact:true}).click();
    await page.getByRole('navigation',{name:'Панель зрителя'}).waitFor();
    await page.getByRole('button', { name: 'Закрыть уведомление', exact: true }).click();
    await page.getByRole('button', { name: 'Промокод', exact: true }).click();
    await page.getByLabel('Промокод', { exact: true }).fill(' autumn ');
    await page.getByRole('button', { name: 'Активировать', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Промокод принят' }).waitFor();
    await page.getByRole('button', { name: 'Квесты', exact: true }).click();
    await capture({ path: resolve(output, `profile-quests-${width}.png`), fullPage: true });
    await page.getByRole('button', { name: 'Озвучить сообщение', exact: true }).click();
    await page.getByLabel('Текст для озвучки', { exact: true }).fill('Привет, стрим!');
    await page.getByRole('button', { name: 'Озвучить за 7700 💎', exact: true }).click();
    await page.getByRole('dialog').waitFor();
    await capture({ path: resolve(output, `profile-tts-${width}.png`), fullPage: true });
    await page.getByRole('button', { name: 'Подтвердить', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Заявка принята' }).waitFor();
    await page.getByRole('button', { name: 'Сообщить о баге', exact: true }).click();
    await page.getByLabel('Что сломалось?', { exact: true }).fill('Проверка формы только на локальном стенде');
    await page.getByRole('button', { name: 'Отправить', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Сообщение принято' }).waitFor();
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) errors.push(`profile overflows viewport ${width}`);
    await page.getByRole('button', { name: 'Игра', exact: true }).click();
    await page.locator('#bnr-join-tournament-btn').click();
    await page.getByRole('status').filter({ hasText: 'Заявка на участие отправлена.' }).waitFor();
    await capture({ path: resolve(output, `tournament-queue-${width}.png`), fullPage: true });
    tournament = r.tournament_running;
    await page.locator('[data-target="bobby"]').click();
    await page.getByRole('dialog').waitFor();
    await capture({ path: resolve(output, `tournament-confirm-${width}.png`), fullPage: true });
    await page.locator('#bnr-predict-confirm').click();
    await page.getByRole('status').filter({ hasText: 'Прогноз принят.' }).waitFor();
    for (const [label, slug] of [['Развитие', 'hero'], ['Снаряжение', 'equipment'], ['Клан, отряд и армия', 'dynasty'], ['Боевые действия', 'combat']]) {
      await page.getByRole('button', { name: label, exact: true }).click();
      if (slug === 'hero') {
        await page.locator('#bnr-daily-claim-gold').click();
        await page.getByRole('status').filter({hasText:'Заявка на ежедневную награду принята'}).waitFor();
        await page.getByText('Сегодня уже забрал:',{exact:false}).waitFor();
        await capture({path:resolve(output,`daily-${width}.png`),fullPage:true});
        await page.locator('[data-skill="OneHanded"]').click();
        await page.getByRole('dialog', {name:'Подтвердить прокачку'}).waitFor();
        await capture({path:resolve(output, `progression-confirm-${width}.png`),fullPage:true});
        await page.getByRole('button', {name:'Подтвердить',exact:true}).click();
        await page.getByRole('status').filter({hasText:'Заявка на прокачку отправлена.'}).waitFor();
        const action = trace.filter(row => row.path === '/api/bannerlord/action').map(row => JSON.parse(row.body)).findLast(body => body.action_type === 'hero.add_focus');
        if (action?.data.expected_cost_gold !== g.progression.progression.skills.find(skill => skill.id === 'OneHanded').focus_options[0].cost_gold || action?.data.progression_context?.equipment_session_id !== g.progression.context.equipment_session_id) throw Error('Browser progression quote/context mismatch');
      }
      await capture({ path: resolve(output, `${slug}-${width}.png`), fullPage: true });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      if (overflow) errors.push(`${slug} overflows viewport ${width}`);
    }
    await page.getByRole('button', { name: 'Сообщество', exact: true }).click();
    await page.getByRole('button', { name: 'Кейсы', exact: true }).click();
    try { await page.getByRole('button', { name: 'Открыть кейс 71' }).waitFor({ timeout: 10000 }); }
    catch (error) { await capture({ path: resolve(output, `cases-failure-${width}.png`), fullPage: true }); writeFileSync(resolve(output, 'cases-failure.json'), JSON.stringify({ errors, trace, text: await page.locator('body').innerText() }, null, 2)); throw error; }
    await capture({ path: resolve(output, `cases-${width}.png`), fullPage: true });
    await page.getByRole('button', { name: 'Открыть кейс 71' }).click();
    await page.getByRole('status').filter({ hasText: 'Кейс открыт' }).waitFor();
    await page.getByRole('button', { name: 'Открыть кейс 71' }).waitFor({ state: 'detached' });
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) errors.push(`cases overflows viewport ${width}`);
    await page.getByRole('button', { name: 'Питомцы', exact: true }).click();
    await page.getByLabel('Имя питомца', { exact: true }).fill('Звезда');
    await page.getByRole('button', { name: 'Сохранить имя', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Имя сохранено' }).waitFor();
    await page.getByRole('button', { name: 'Магазин питомцев', exact: true }).click();
    await page.getByRole('button', { name: 'Купить Лягушка-самурай', exact: true }).click();
    await page.getByRole('dialog').waitFor();
    await capture({ path: resolve(output, `pets-confirm-${width}.png`), fullPage: true });
    await page.getByRole('button', { name: 'Подтвердить', exact: true }).click();
    await page.getByAltText('Питомец', { exact: true }).waitFor();
    await capture({ path: resolve(output, `pets-${width}.png`), fullPage: true });
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) errors.push(`pets overflows viewport ${width}`);
    await page.getByRole('button', { name: 'Гильдии', exact: true }).click();
    await page.getByRole('button', { name: 'Открыть Стражи', exact: true }).click();
    await page.getByText('@bob · member', { exact: true }).waitFor();
    await capture({ path: resolve(output, `guild-detail-${width}.png`), fullPage: true });
    await page.getByRole('button', { name: 'Назад', exact: true }).click();
    await page.getByLabel('Название гильдии', { exact: true }).fill('Стражи');
    await page.getByLabel('Девиз', { exact: true }).fill('Вместе');
    await page.getByRole('button', { name: 'Создать за 1300 💎', exact: true }).click();
    await page.getByRole('button', { name: 'Подтвердить', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Гильдия создана' }).waitFor();
    await page.getByRole('button', { name: 'Прокачать Сила сообщества за 12345 💎', exact: true }).click();
    await page.getByRole('dialog').waitFor();
    await capture({ path: resolve(output, `guild-confirm-${width}.png`), fullPage: true });
    await page.getByRole('button', { name: 'Подтвердить', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Навык улучшен' }).waitFor();
    await capture({ path: resolve(output, `guild-${width}.png`), fullPage: true });
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) errors.push(`guild overflows viewport ${width}`);
    await page.getByRole('button', { name: 'Голосование', exact: true }).click();
    await page.getByRole('button', { name: 'Голосовать за Игра А', exact: true }).click();
    await page.getByRole('button', { name: '731 💎', exact: true }).click();
    await capture({ path: resolve(output, `voting-confirm-${width}.png`), fullPage: true });
    await page.getByRole('button', { name: 'Подтвердить', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Голос учтён' }).waitFor();
    await page.getByRole('button', { name: 'Предложить свою игру', exact: true }).click();
    await page.getByLabel('Название игры', { exact: true }).fill('Новая игра');
    await page.getByRole('button', { name: '1270 💎', exact: true }).click();
    await capture({ path: resolve(output, `voting-proposal-${width}.png`), fullPage: true });
    await page.getByRole('button', { name: 'Подтвердить', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'На одобрении' }).waitFor();
    voteActive = false;
    await page.evaluate(() => window.__fixtureEvent('vote_ended', { event_id: 51, winner: { label: 'Игра Б', pool: 3000 } }));
    await page.getByRole('heading', { name: 'Игра Б', exact: true }).waitFor();
    await capture({ path: resolve(output, `voting-result-${width}.png`), fullPage: true });
    await page.getByRole('button', { name: 'К копилке', exact: true }).click();
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) errors.push(`voting overflows viewport ${width}`);
    await page.getByRole('button', { name: 'Статистика', exact: true }).click();
    await page.getByText('Первый шаг', { exact: false }).waitFor();
    await page.getByRole('button', { name: 'Обновить статистику', exact: true }).click();
    await capture({ path: resolve(output, `statistics-${width}.png`), fullPage: true });
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) errors.push(`statistics overflows viewport ${width}`);
    petsEnabled = true;
    await page.goto('http://127.0.0.1:4187/config.html');
    await page.getByRole('button', { name: 'Выключить' }).click();
    await page.getByRole('status').filter({ hasText: 'Сохранено' }).waitFor();
    await capture({ path: resolve(output, `config-${width}.png`), fullPage: true });
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) errors.push(`config overflows viewport ${width}`);
    activeModule = 'shedcolony'; const colonyTraceStart = trace.length;
    await page.goto('http://127.0.0.1:4187/'+panelPage);
    await page.getByRole('button', { name: 'Игра', exact: true }).click();
    await page.locator('#sc-skill-select').selectOption('Strength');
    await page.waitForTimeout(5200);
    await page.locator('[data-sc="xp"]').click();
    await page.getByRole('dialog').waitFor();
    await capture({ path: resolve(output, `colony-confirm-${width}.png`), fullPage: true });
    await page.getByRole('button', { name: 'Подтвердить', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Заявка принята' }).waitFor();
    const sent = trace.slice(colonyTraceStart).find(q => q.path === '/api/shedcolony/action');
    if (!sent || JSON.parse(sent.body).data.skill !== 'Strength') errors.push('Colony lost the selected skill after a poll');
    for (const [label, slug] of [['Колонист', 'colony-citizen'], ['Экипировка', 'colony-equipment'], ['Колония', 'colony-town']]) {
      await page.getByRole('button', { name: label, exact: true }).click();
      await capture({ path: resolve(output, `${slug}-${width}.png`), fullPage: true });
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) errors.push(`${slug} overflows viewport ${width}`);
    }
    if (trace.slice(colonyTraceStart).some(q => q.path.startsWith('/api/bannerlord/'))) errors.push('Inactive Bannerlord requested data on a ShedColony channel');
    // The fixture receives the POST bytes, then truncates its response. A held
    // real resolver request forces ViewerShell's resolving gate and game unmount.
    await page.getByRole('button',{name:'Колонист',exact:true}).click();
    const beforeLoss=trace.filter(q=>q.path==='/api/shedcolony/action').length;
    colonyLoseResponse=true;
    await page.locator('[data-sc="heal"]').click();await page.getByRole('button',{name:'Подтвердить',exact:true}).click();
    await page.getByRole('status').filter({hasText:'Исход заявки неизвестен'}).waitFor();
    const beforeRemountPosts=trace.filter(q=>q.path==='/api/shedcolony/action').length-beforeLoss;
    const oldColonyButton=await page.locator('[data-sc="heal"]').elementHandle();
    let releaseResolver;resolverGate=new Promise(resolve=>{releaseResolver=resolve;});
    try{
      await page.evaluate(()=>window.__fixtureAuthorize());
      await page.getByRole('heading',{name:'Колония стримера'}).waitFor({state:'detached'});
      if(await oldColonyButton.evaluate(node=>node.isConnected))throw Error('Colony did not unmount during JWT resolution');
      await capture({path:resolve(output,`colony-jwt-resolving-${width}.png`),fullPage:true});
    }finally{releaseResolver();resolverGate=null;}
    await page.getByRole('heading',{name:'Колония стримера'}).waitFor();
    await page.getByRole('status').filter({hasText:'Исход заявки неизвестен'}).waitFor();
    if(!await page.locator('[data-sc="heal"]').isDisabled())throw Error('Colony unknown guard lost after JWT remount');
    await page.locator('[data-sc="heal"]').evaluate(button=>button.click());
    await capture({path:resolve(output,`colony-unknown-after-jwt-${width}.png`),fullPage:true});
    const receivedPosts=trace.filter(q=>q.path==='/api/shedcolony/action').length-beforeLoss;
    if(receivedPosts!==1)throw Error('Colony repeated a paid request after response loss: '+receivedPosts);
    colonyRemountEvidence.push({width,receivedPosts,beforeRemountPosts,lossMode:'truncated-json-response',resolverHeld:true,oldComponentDetached:true,unknownGuardRetained:true});
    colonyLoseResponse=false;
    activeModule='bannerlord';heroSnapshot=h.hero_absent;
    await page.reload();await page.getByRole('button',{name:'Игра',exact:true}).click();await page.getByRole('button',{name:'Развитие',exact:true}).click();
    await page.locator('[data-bnr-culture="Mod.Culture-X"]').waitFor();
    await capture({path:resolve(output,`hero-create-${width}.png`),fullPage:true});
    await page.locator('[data-bnr-culture="Mod.Culture-X"]').click();
    await page.getByRole('status').filter({hasText:'Заявка на создание героя отправлена'}).waitFor();
    const creation=trace.filter(q=>q.path==='/api/bannerlord/action').map(q=>JSON.parse(q.body)).findLast(q=>q.action_type==='hero.create');
    if(creation.data.culture!=='Mod.Culture-X'||creation.data.content_context.equipment_session_id!=='session-a')throw Error('Browser culture/context mismatch');
    heroSnapshot=h.hero_dead;
    await page.reload();await page.getByRole('button',{name:'Игра',exact:true}).click();await page.getByRole('button',{name:'Развитие',exact:true}).click();
    await page.locator('#bnr-heir-respawn').click();await page.getByRole('dialog',{name:'Начать заново?'}).waitFor();
    await capture({path:resolve(output,`hero-respawn-${width}.png`),fullPage:true});
    await page.getByRole('button',{name:'Подтвердить',exact:true}).click();
    await page.getByRole('status').filter({hasText:'Заявка на создание героя отправлена'}).waitFor();
    heroSnapshot=k.hero_ruler;
    await page.reload();await page.getByRole('button',{name:'Игра',exact:true}).click();await page.getByRole('button',{name:'Клан, отряд и армия',exact:true}).click();
    await page.locator('[data-bnr-details="diplo-policy"] > summary').click();
    await page.locator('[data-policy-id="Mod.Policy-X"]').click();await page.getByRole('dialog',{name:'Подтвердить закон'}).waitFor();
    await capture({path:resolve(output,`policy-confirm-${width}.png`),fullPage:true});
    await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('dialog').waitFor({state:'detached'});
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))errors.push(`policy overflows viewport ${width}`);
    await capture({path:resolve(output,`policies-${width}.png`),fullPage:true});
    await page.getByRole('region',{name:'Имущество и наследование',exact:true}).waitFor();
    await page.getByText('Унаследованная мастерская',{exact:false}).waitFor();
    await capture({path:resolve(output,`properties-${width}.png`),fullPage:true});
    for(const kind of ['ws','caravan']){
      await page.locator(`[data-bnr-details="${kind}-buy"] > summary`).click();
      await page.locator(kind==='ws'?'#bnr-ws-town':'#bnr-caravan-home').selectOption('town_fixture');
      if(kind==='ws')await page.locator('input[value="Mod.Workshop-X"]').check();
      await page.locator(`#bnr-${kind}-buy-confirm`).click();
      await page.getByRole('dialog',{name:'Подтвердить покупку имущества'}).waitFor();
      await capture({path:resolve(output,`${kind}-buy-confirm-${width}.png`),fullPage:true});
      await page.getByRole('button',{name:'Подтвердить',exact:true}).click();
      await page.getByRole('dialog').waitFor({state:'detached'});
      await page.locator(`.bnr-${kind}-sell`).first().click();
      await page.getByRole('dialog',{name:'Подтвердить продажу имущества'}).waitFor();
      await capture({path:resolve(output,`${kind}-sell-confirm-${width}.png`),fullPage:true});
      await page.getByRole('button',{name:'Подтвердить',exact:true}).click();
      await page.getByRole('dialog').waitFor({state:'detached'});
    }
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))errors.push(`properties overflows viewport ${width}`);
    heroSnapshot=profile.hero_married;
    await page.reload();await page.getByRole('button',{name:'Игра',exact:true}).click();await page.getByRole('button',{name:'Клан, отряд и армия',exact:true}).click();
    await page.getByRole('region',{name:'Семья героя',exact:true}).waitFor();
    await capture({path:resolve(output,`hero-family-${width}.png`),fullPage:true});
    for(const action of ['make-baby','divorce']){
      await page.locator(`#bnr-${action}-btn`).click();
      await page.getByRole('dialog',{name:'Подтвердить действие героя'}).waitFor();
      await capture({path:resolve(output,`${action}-confirm-${width}.png`),fullPage:true});
      await page.getByRole('button',{name:'Подтвердить',exact:true}).click();
      await page.getByRole('dialog').waitFor({state:'detached'});
    }
    heroSnapshot=profile.hero_single;
    await page.reload();await page.getByRole('button',{name:'Игра',exact:true}).click();await page.getByRole('button',{name:'Клан, отряд и армия',exact:true}).click();
    await page.locator('#bnr-marry-btn').click();await page.getByRole('dialog').waitFor();
    await capture({path:resolve(output,`marry-confirm-${width}.png`),fullPage:true});
    await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('dialog').waitFor({state:'detached'});
    await page.getByRole('button',{name:'Клан, отряд и армия',exact:true}).click();
    await page.getByRole('region',{name:'Взрослые дети и предложения',exact:true}).waitFor();
    await capture({path:resolve(output,`children-heirs-${width}.png`),fullPage:true});
    await page.locator('[data-proposal-id="200"] .bnr-prop-accept').click();
    await page.locator(`[data-proposal-id="${children.outgoing_id}"] .bnr-fam-cancel`).click();
    await page.getByRole('dialog').waitFor();await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('dialog').waitFor({state:'detached'});
    for(const kind of ['rename','looks']){
      await page.locator(`.bnr-fam-${kind}`).first().click();
      await page.getByLabel(kind==='rename'?'Новое имя ребёнка':'Код внешности ребёнка').fill(kind==='rename'?' Новое имя ':' fixture-body-properties ');
      await page.getByRole('button',{name:'Продолжить',exact:true}).click();await page.getByRole('dialog',{name:'Подтвердить действие с ребёнком'}).waitFor();
      if(kind==='rename')await capture({path:resolve(output,`child-rename-confirm-${width}.png`),fullPage:true});
      await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('dialog').waitFor({state:'detached'});
    }
    await page.locator('.bnr-fam-respec').first().click();await page.getByRole('dialog').waitFor();await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('dialog').waitFor({state:'detached'});
    await page.locator('.bnr-fam-propose').first().click();await page.getByLabel('Зритель для предложения').fill(' @BoB ');await page.getByRole('button',{name:'Найти детей',exact:true}).click();await page.getByLabel('Ребёнок другого зрителя').selectOption('child-b');await page.getByRole('button',{name:'Продолжить',exact:true}).click();
    await page.getByRole('dialog',{name:'Подтвердить действие с ребёнком'}).waitFor();await capture({path:resolve(output,`child-propose-confirm-${width}.png`),fullPage:true});await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('dialog').waitFor({state:'detached'});
    await page.getByRole('button',{name:'Развитие',exact:true}).click();
    await page.getByRole('button',{name:'Клан, отряд и армия',exact:true}).click();
    await page.getByRole('region',{name:'Вассальные кланы',exact:true}).waitFor();
    await page.locator('[data-bnr-details="dyn-upgrades"] summary').click();
    await page.locator('[data-bnr-upg-id="fixture-a"]').check();await page.locator('[data-bnr-upg-id="fixture-b"]').check();
    await capture({path:resolve(output,`clan-upgrades-${width}.png`),fullPage:true});await page.locator('.bnr-bulk-buy').click();await page.getByRole('dialog').waitFor();
    await capture({path:resolve(output,`clan-upgrades-confirm-${width}.png`),fullPage:true});await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('dialog').waitFor({state:'detached'});
    await capture({path:resolve(output,`vassals-ransom-${width}.png`),fullPage:true});
    await page.locator('.bnr-vas-rename').first().click();await page.getByLabel('Новое имя клана',{exact:true}).fill('Южный дом');await page.locator('[data-bnr-vassal-rename-form] button[type="submit"]').click();
    await page.getByRole('dialog').waitFor();await capture({path:resolve(output,`vassal-rename-confirm-${width}.png`),fullPage:true});await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('dialog').waitFor({state:'detached'});
    await page.locator('[data-bnr-details="vas-create"] summary').click();await page.locator('#bnr-vas-name-input').fill('Дом наследника');await page.locator('#bnr-vas-confirm').click();
    await page.getByRole('dialog').waitFor();await capture({path:resolve(output,`vassal-create-confirm-${width}.png`),fullPage:true});await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('dialog').waitFor({state:'detached'});
    await page.locator('[data-captured="bob"] .bnr-ransom-pay').click();await page.getByRole('dialog').waitFor();await capture({path:resolve(output,`ransom-confirm-${width}.png`),fullPage:true});await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('dialog').waitFor({state:'detached'});
    await page.getByRole('button',{name:'Развитие',exact:true}).click();
    await page.locator('[data-gender-set="female"]').click();await page.getByRole('dialog').waitFor();
    await capture({path:resolve(output,`gender-confirm-${width}.png`),fullPage:true});
    await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('dialog').waitFor({state:'detached'});
    await page.getByRole('button',{name:'Снаряжение',exact:true}).click();await page.locator('[data-bnr-details="inv-achievements"] summary').click();await page.locator('[data-hero-achievement="bloodthirsty"]').waitFor();
    await capture({path:resolve(output,`hero-achievements-${width}.png`),fullPage:true});
    heroSnapshot=commerce.hero;api.set('/api/bannerlord/classes',commerce.classes);
    await page.reload();await page.getByRole('button',{name:'Игра',exact:true}).click();await page.getByRole('button',{name:'Развитие',exact:true}).click();
    await page.getByRole('region',{name:'Карточка героя',exact:true}).getByText('Побед в турнирах: 3',{exact:true}).waitFor();
    await capture({path:resolve(output,`hero-summary-${width}.png`),fullPage:true});
    for(const [selector,slug] of [['[data-bnr-givegold]','shop-gold'],['[data-bnr-skillxp]','shop-xp'],['[data-bnr-buy="hero.army_create"]','shop-catalog'],['#bnr-inline-upgrade-btn','legacy-upgrade'],['#bnr-reequip-btn','legacy-reequip']]){
      await page.locator(selector).first().click();await page.getByRole('dialog').waitFor();await capture({path:resolve(output,`${slug}-confirm-${width}.png`),fullPage:true});await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('dialog').waitFor({state:'detached'});
    }
    await page.getByRole('button',{name:'Снаряжение',exact:true}).click();await page.locator('.bnr-discard-btn[data-slot="head"]').click();await page.getByRole('dialog').waitFor();
    await capture({path:resolve(output,`legacy-discard-confirm-${width}.png`),fullPage:true});await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('dialog').waitFor({state:'detached'});
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))errors.push(`legacy inventory overflows viewport ${width}`);
    await page.getByRole('button',{name:'Сообщество',exact:true}).click();
    for(const [game,label] of [['rps','Дуэли'],['tictactoe','Крестики-нолики'],['tug','Канат']]){
      queues.set(game,games[game+'_idle']);rooms.set(game,games[game+'_active']);tugStatus=games.tug_status_idle;
      await page.getByRole('button',{name:label,exact:true}).click();if(game==='rps')await page.locator('#duel-find-btn').click();
      await page.locator(game==='rps'?'#rps-queue-btn':game==='tug'?'#tug-find':'#ttt-find-btn').click();
      await page.locator(game==='rps'?'#rps-leave-btn':game==='tug'?'#tug-cancel':'#ttt-cancel-btn').waitFor();await capture({path:resolve(output,`${game}-queued-${width}.png`),fullPage:true});
      queues.set(game,games[game+'_matched']);if(game==='tug')tugStatus=games.tug_active;
      const move=game==='rps'?'[data-rps-move="rock"]':game==='tug'?'#tug-pull':'[data-ttt-cell="5"]';await page.locator(move).waitFor();
      await capture({path:resolve(output,`${game}-match-${width}.png`),fullPage:true});await page.locator(move).click();
      if(game==='tug'){await page.locator(move).click();await page.locator(move).click();await page.getByText('Рывков: 3',{exact:false}).waitFor();}
      if(game==='tictactoe')await page.locator('[data-ttt-cell="5"]').filter({hasText:'❌'}).waitFor();
      if(game==='rps')await page.locator('[data-rps-move="rock"][disabled]').waitFor();
      if(game==='tug')tugStatus=games.tug_finished;else rooms.set(game,games[game+'_finished']);
      await page.getByText('Победа',{exact:true}).waitFor();await capture({path:resolve(output,`${game}-finished-${width}.png`),fullPage:true});
      if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))errors.push(`${game} overflows viewport ${width}`);
      await page.locator(game==='rps'?'#rps-close-btn':game==='tug'?'#tug-close':'#ttt-close-btn').click();
    }
    socialStatus=social.single;socialProposals=social.proposals;
    await page.getByRole('button',{name:'Семья',exact:true}).click();await page.getByRole('button',{name:'Принять @bob',exact:true}).waitFor();
    if(!await page.getByRole('button',{name:'Принять @bob',exact:true}).isDisabled())throw Error('Unsafe marriage accept was enabled');
    await capture({path:resolve(output,`social-family-${width}.png`),fullPage:true});await page.getByRole('button',{name:'Отклонить @bob',exact:true}).click();await page.getByRole('button',{name:'Принять @bob',exact:true}).waitFor({state:'detached'});
    await page.getByLabel('Кому предложить брак',{exact:true}).selectOption('bob');await page.getByRole('button',{name:'Предложить',exact:true}).click();await page.getByRole('status').filter({hasText:'Ждём ответа'}).waitFor();
    await capture({path:resolve(output,`social-propose-${width}.png`),fullPage:true});await page.getByRole('button',{name:'Закрыть',exact:true}).click();
    socialStatus=social.married;await page.getByRole('button',{name:'Семья',exact:true}).click();await page.getByRole('button',{name:'Развестись',exact:true}).click();await page.getByRole('dialog').waitFor();
    await capture({path:resolve(output,`social-divorce-confirm-${width}.png`),fullPage:true});await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('status').filter({hasText:'Развод оформлен'}).waitFor();
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))errors.push(`social family overflows viewport ${width}`);
    if(trace.some(q=>q.path==='/api/marriage/accept'))errors.push('Blocked marriage accept sent a request');
    activeModule='rimworld';rwPawn=rw.pawn;rwCooldown=rw.cooldown;
    await page.goto('http://127.0.0.1:4187/'+panelPage);await page.getByRole('button',{name:'Игра',exact:true}).click();
    await page.getByRole('heading',{name:'Алиса',exact:true}).waitFor();await page.getByRole('button',{name:'Обновить пешку',exact:true}).click();
    await capture({path:resolve(output,`rimworld-pawn-${width}.png`),fullPage:true});
    for(const [label,slug] of [['Лечить','heal'],['Удалить черту Задумчивый','remove-trait'],['Удалить ген Старый ген','remove-gene']]){
      await page.getByRole('button',{name:label,exact:true}).click();await page.getByRole('dialog').waitFor();await capture({path:resolve(output,`rimworld-${slug}-confirm-${width}.png`),fullPage:true});await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('dialog').waitFor({state:'detached'});
      if(slug==='remove-trait'){await page.getByRole('dialog',{name:'Огоньки страсти',exact:true}).waitFor();await page.getByRole('button',{name:'Закрыть каталог пешки',exact:true}).click();}
    }
    rwPawn=rw.dead_pawn;await page.getByRole('button',{name:'Обновить пешку',exact:true}).click();await page.getByRole('button',{name:'Воскресить',exact:true}).click();await page.getByRole('dialog').waitFor();await capture({path:resolve(output,`rimworld-resurrect-${width}.png`),fullPage:true});await page.getByRole('button',{name:'Подтвердить',exact:true}).click();
    rwPawn=rw.empty_pawn;await page.getByRole('button',{name:'Обновить пешку',exact:true}).click();await page.getByRole('button',{name:'Создать пешку',exact:true}).click();await page.getByRole('dialog').waitFor();await capture({path:resolve(output,`rimworld-create-${width}.png`),fullPage:true});await page.getByRole('button',{name:'Подтвердить',exact:true}).click();
    rwPawn=rw.pawn;await page.getByRole('button',{name:'Обновить пешку',exact:true}).click();
    await page.getByLabel('Поиск товаров',{exact:true}).fill('Меч');await page.getByText('Подробнее о Меч поселенца',{exact:true}).click();await capture({path:resolve(output,`rimworld-shop-search-${width}.png`),fullPage:true});await page.getByLabel('Поиск товаров',{exact:true}).fill('');
    for(const [label,slug] of [['Купить Меч поселенца','item'],['Купить Упорный','trait'],['Купить Зоркость','gene'],['Купить Сердце','implant'],['Купить Парная рука','paired-implant'],['Заказать Гости из долины','event']]){
      await page.getByRole('button',{name:label,exact:true}).click();if(slug==='paired-implant'){await capture({path:resolve(output,`rimworld-implant-sides-${width}.png`),fullPage:true});await page.getByRole('button',{name:'Правая сторона',exact:true}).click();}
      await page.getByRole('dialog',{name:'Подтверждение RimWorld'}).waitFor();await capture({path:resolve(output,`rimworld-${slug}-confirm-${width}.png`),fullPage:true});await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('dialog',{name:'Подтверждение RimWorld'}).waitFor({state:'detached'});
    }
    for(const [open,label,slug] of [['Нейротренеры','Купить Урок строительства','neuro'],['Ксенотипы','Купить Путник','xenotype'],['Огоньки страсти','Повысить страсть Стрельба','passion'],['Огоньки страсти','Сбросить страсть Строительство','passion-reset']]){
      await page.getByRole('button',{name:open,exact:true}).click();await page.getByRole('button',{name:label,exact:true}).waitFor();await capture({path:resolve(output,`rimworld-${slug}-${width}.png`),fullPage:true});await page.getByRole('button',{name:label,exact:true}).click();await page.getByRole('dialog',{name:'Подтверждение RimWorld'}).waitFor();await capture({path:resolve(output,`rimworld-${slug}-confirm-${width}.png`),fullPage:true});await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('dialog',{name:'Подтверждение RimWorld'}).waitFor({state:'detached'});
      if(slug==='passion'||slug==='passion-reset'){await page.waitForTimeout(2100);}
      // Xenotype success closes its catalog asynchronously. Wait for that
      // specified outcome; a count-then-click races the accepted response.
      if(slug==='xenotype')await page.getByRole('button',{name:'Закрыть каталог пешки',exact:true}).waitFor({state:'detached'});
      else await page.getByRole('button',{name:'Закрыть каталог пешки',exact:true}).click();
    }
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))errors.push(`RimWorld overflows viewport ${width}`);
    await context.close();
  }
  const result = { browser: browser.version(), widths: [1280, 375], browserSandbox: true, cspBypass: false, errors, blocked, screenshots, startupAssets, colonyRemountEvidence, trace };
  writeFileSync(resolve(output, 'verification.json'), JSON.stringify(result, null, 2));
  if (errors.length || blocked.length) throw new Error(JSON.stringify({ errors, blocked }));
  console.log(JSON.stringify({ browser: result.browser, screenshots: screenshots.length, output, errors: 0, externalRequests: 0 }));
} finally { await browser?.close(); await new Promise(resolve => server.close(resolve)); }
