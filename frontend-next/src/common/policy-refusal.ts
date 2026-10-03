import { isRecord } from '../contracts';
// Only these exact outer require_jwt_user refusals precede action-body parsing,
// charge and enqueue. A generic 4xx (or a mixed action/policy envelope) proves nothing.
export function policyRefusal(status: number, body: unknown, channelId: string, read = false): {success:false;message:string} | null {
  if (!isRecord(body) || Object.keys(body).length !== 1 || !isRecord(body.detail)) return null;
  const detail = body.detail;
  if (typeof detail.channel_id !== 'number' || !Number.isSafeInteger(detail.channel_id) || detail.channel_id <= 0
    || String(detail.channel_id) !== channelId || typeof detail.message !== 'string' || !detail.message.trim()) return null;
  const registration = status === 403 && (detail.status === 'channel_not_registered' || detail.status === 'channel_pending_approval');
  const rate = status === 429 && detail.status === 'channel_rate_limited';
  if (!registration && !rate) return null;
  const fields = rate ? ['status', 'channel_id', 'message', 'tier', 'limit_per_min', 'scope'] : ['status', 'channel_id', 'message'];
  if (Object.keys(detail).some(key => !fields.includes(key))) return null;
  if (rate && (typeof detail.tier !== 'string' || !detail.tier.trim()
    || typeof detail.limit_per_min !== 'number' || !Number.isSafeInteger(detail.limit_per_min) || detail.limit_per_min <= 0
    || (detail.scope !== 'channel' && !(read && detail.scope === 'viewer_poll')))) return null;
  // Retry-After belongs to HTTP policy, not a game-action cooldown or retry command.
  return { success: false, message: detail.message };
}
