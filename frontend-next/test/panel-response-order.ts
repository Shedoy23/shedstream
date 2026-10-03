import { setImmediate as nextResponseTurn } from 'node:timers/promises';
import type { LegacyFixtures } from './panel-legacy-harness';
// Explicit network scenario: the concurrent hero response reaches both clients
// before the action acknowledgement. Fast acknowledgements and stale reads are
// covered separately. Promise depth inside a transport is not network latency.
export function heroBeforeAction(fixtures: LegacyFixtures) {
  const action=fixtures.action;
  fixtures.action=async(request,call)=>{
    await nextResponseTurn();
    return typeof action==='function'?action(request,call):action;
  };
}
export { nextResponseTurn };
