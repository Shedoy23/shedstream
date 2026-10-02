"""Bounded local transport mutations. Committed source, private byte backup, exact restore.
Run from this checkout only: python docs/evidence/panel-policy-2026-10-03/check-parser-mutations.py
"""
from pathlib import Path
import hashlib, json, subprocess
ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT/'frontend-next/src/panel/transport.ts'
OUT = Path(__file__).resolve().parent/'mutations'
OUT.mkdir(exist_ok=True)
subprocess.run(['git','diff','--exit-code','--',str(SOURCE)],cwd=ROOT,check=True)
original=SOURCE.read_bytes()
backup=OUT/'transport.ts.byte-backup'; backup.write_bytes(original)
sha=hashlib.sha256(original).hexdigest()
mutations = [
 ('remove_action_normalization', 'if (refusal) return refusal;', '', False),
 ('remove_read_message', 'if (refusal) throw new Error(refusal.message);', '', False),
 ('accept_arbitrary_4xx', 'if (refusal) return refusal;', "if (response.status >= 400 && response.status < 500) return { success: false, message: 'unsafe blanket refusal' }; if (refusal) return refusal;", False),
 ('remove_registration_http_status', "status === 403 && (", '(', False),
 ('remove_rate_http_status', "status === 429 && detail.status === 'channel_rate_limited'", "detail.status === 'channel_rate_limited'", False),
 ('accept_unknown_rate_code', "status === 429 && detail.status === 'channel_rate_limited'", 'status === 429', False),
 ('allow_mixed_envelope', 'Object.keys(body).length !== 1 || ', '', False),
 ('allow_nested_action_fields', 'if (Object.keys(detail).some(key => !fields.includes(key))) return null;', '', False),
 ('remove_channel_binding', 'String(detail.channel_id) !== channelId || ', '', False),
 ('remove_safe_integer_channel', '!Number.isSafeInteger(detail.channel_id) || ', '', False),
 ('remove_positive_channel', ' || detail.channel_id <= 0', '', False),
 ('coerce_authorization_channel', 'String(detail.channel_id) !== channelId', 'detail.channel_id !== Number(channelId)', False),
 ('remove_nonblank_message', ' || !detail.message.trim()', '', False),
 ('remove_tier_shape', "typeof detail.tier !== 'string' || !detail.tier.trim()\n    || ", '', False),
 ('remove_integer_quota', '!Number.isSafeInteger(detail.limit_per_min) || ', '', False),
 ('remove_positive_quota', ' || detail.limit_per_min <= 0', '', False),
 ('accept_poll_scope_for_action', "!(read && detail.scope === 'viewer_poll')", "detail.scope !== 'viewer_poll'", False),
 ('use_current_channel_for_action', 'policyRefusal(response.status, body, authorization.channelId);', "policyRefusal(response.status, body, this.auth.current()!.channelId);", False),
 ('remove_action_5xx_guard', ' || response.status >= 500', '', False),
 ('allow_mixed_top_level_success', " || 'detail' in body", '', False),
 # Number.isSafeInteger already rejects every non-number. This isolated guard is redundant.
 ('redundant_channel_type_guard', "typeof detail.channel_id !== 'number' || ", '', True),
]
results=[]
try:
 for name,old,new,redundant in mutations:
  source=original.decode(); assert source.count(old)==1,(name,source.count(old))
  SOURCE.write_text(source.replace(old,new,1))
  result=subprocess.run(['npm','--prefix','frontend-next','--cache','/tmp/preact-npm-cache','test','--','test/panel-policy-transport.test.tsx','--maxWorkers=2'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  (OUT/(name+'.log')).write_bytes(result.stdout)
  SOURCE.write_bytes(backup.read_bytes()); assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==sha
  subprocess.run(['git','diff','--exit-code','--',str(SOURCE)],cwd=ROOT,check=True)
  row={'name':name,'exit_code':result.returncode,'expected_redundant':redundant,'source_restored_sha256':sha}
  results.append(row);print(json.dumps(row),flush=True)
finally:
 SOURCE.write_bytes(backup.read_bytes()); assert SOURCE.read_bytes()==original
 subprocess.run(['git','diff','--exit-code','--',str(SOURCE)],cwd=ROOT,check=True)
 summary={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'source_sha256':sha,'mutations':results}
 (OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
assert len(results)==len(mutations)
assert all(r['exit_code']==(0 if r['expected_redundant'] else 1) for r in results), results
