// Autotest log-analysis workflow (Bannerlord extension pipeline).
// Run via the Workflow tool with args:
//   { modSlice: "<path to mod-log slice>", backendSlice: "<path to backend-log slice>", channel: "shedoy23 (ch=98319857)" }
// Observers run on SONNET (cheap, accurate log parsing); final synthesis on OPUS.
export const meta = {
  name: 'autotest-log-analysis',
  description: 'Correlate Bannerlord mod + backend log slices from a live test window; classify each action end-to-end and flag every anomaly',
  phases: [
    { title: 'Observe', detail: 'Sonnet observers extract per-layer timelines (mod + backend)', model: 'sonnet' },
    { title: 'Synthesize', detail: 'Opus correlates cross-layer, classifies, flags anomalies', model: 'opus' },
  ],
}

const modSlice = args.modSlice
const backendSlice = args.backendSlice
const channel = args.channel || 'shedoy23 (ch=98319857)'

const OBS = {
  type: 'object',
  properties: {
    layer: { type: 'string' },
    entries: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          ts: { type: 'string' },
          action_id: { type: 'string' },
          kind: { type: 'string', description: 'action / event / ack / power / mirror / crash / refusal / redemption / other' },
          type: { type: 'string' },
          outcome: { type: 'string', description: 'ok / failed / error / refused / unknown' },
          snippet: { type: 'string' },
        },
        required: ['ts', 'kind', 'outcome', 'snippet'],
      },
    },
    errors: { type: 'array', items: { type: 'string' }, description: 'every error/exception/traceback/refusal captured verbatim' },
    summary: { type: 'string' },
  },
  required: ['layer', 'entries', 'errors', 'summary'],
}

phase('Observe')
const [modObs, beObs] = await parallel([
  () => agent(
    `Analyze a Bannerlord MOD log slice from a live test window. File: ${modSlice}\n` +
    `Read it with Bash (cat / grep -nE). Extract a COMPLETE structured timeline of everything:\n` +
    `- actions: 'poll got N action(s)' then 'action[<id>] type=<type>' and the following result (success / '... не найден' / PostFailed:<reason> / exception)\n` +
    `- events pushed + ACK: 'event <type> -> ACK: {...success...}' (hero.*, properties_snapshot)\n` +
    `- power buff: '[PowersMission]' lines (hp×/scale), retinue HP\n` +
    `- mirror: 'properties_snapshot pushed (...)'\n` +
    `- clan-gate refusals: 'not_clan_leader'\n` +
    `- crashes/exceptions: 'CRASHED' / 'Exception' / stacktrace / '[*] ... error'\n` +
    `- lifecycle: 'session_start', 'unloaded'\n` +
    `Put EVERY error/exception/refusal verbatim into 'errors'. Be exhaustive — miss nothing.`,
    { label: 'observe:mod', phase: 'Observe', model: 'sonnet', schema: OBS }
  ),
  () => agent(
    `Analyze a BACKEND (FastAPI, prod) log slice for channel ${channel}. File: ${backendSlice}\n` +
    `Read it with Bash (cat / grep -nE), focusing on lines for THIS channel (98319857 / shedoy23 / 'bannerlord'). Extract a COMPLETE structured timeline:\n` +
    `- viewer actions charged + enqueued (action_id, module_actions, action type)\n` +
    `- events received from the mod + handling: '[bannerlord:<ch>] ...', 'properties_snapshot mirror: fiefs n=.. -.. workshops .. caravans ..', reconcile counts\n` +
    `- ACKs, and any ERROR / Traceback / WARNING / refund / 'action.failed'\n` +
    `- channel-points redemptions (context only)\n` +
    `Put EVERY error/traceback verbatim into 'errors'. Be exhaustive.`,
    { label: 'observe:backend', phase: 'Observe', model: 'sonnet', schema: OBS }
  ),
])

phase('Synthesize')
const report = await agent(
  `You are the senior analyst synthesizing an END-TO-END autotest of a Twitch-extension -> FastAPI-backend -> Bannerlord-mod pipeline. ` +
  `Two per-layer observation reports follow (parsed by Sonnet observers).\n\n` +
  `=== MOD layer ===\n${JSON.stringify(modObs, null, 1)}\n\n=== BACKEND layer ===\n${JSON.stringify(beObs, null, 1)}\n\n` +
  `TASK:\n` +
  `1. Correlate by action_id across layers: backend enqueue -> mod poll/apply -> result -> ACK. For each viewer action build the trace and CLASSIFY: OK / FAILED / ERROR / ORPHAN (enqueued-not-applied, or applied-no-ack) / UNEXPECTED.\n` +
  `2. Verify the features under test THIS session:\n` +
  `   (a) properties_snapshot MIRROR — mod pushes on session_start + ~every 30s on change; backend reconciles (fiefs/workshops/caravans n=.. -..) with NO errors.\n` +
  `   (b) CLAN-GATE — caravan/workshop buy by a NON-leader -> 'not_clan_leader' refusal + backend refund; by a clan leader -> succeeds.\n` +
  `   (c) POWER BUFF — no crashes/exceptions from HP×2 or skill seeding; hero + retinue spawn cleanly.\n` +
  `   (d) GENDER change (hero.set_gender) works.\n` +
  `3. Flag EVERY anomaly with evidence (ts + snippet): mod crashes/exceptions, backend tracebacks, ACK failures, orphaned actions, double-processing, unexpected refusals, '... не найден'.\n` +
  `OUTPUT (markdown): (1) one-line VERDICT; (2) per-feature table a-d (pass/fail + evidence); (3) full ANOMALY list (severity + evidence); (4) actions covered + coverage gaps; (5) recommended fix for each real issue. Be rigorous and concrete — the streamer acts on this.`,
  { label: 'synthesize', phase: 'Synthesize', model: 'opus' }
)

return report
