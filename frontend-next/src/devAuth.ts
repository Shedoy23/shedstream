import type { TwitchAuthorization } from './auth';
import type { IdentityHelper } from './skillgames/identity';

// 03.10: dev preview outside Twitch, same contract as the old panel
// (`?dev_jwt=<TOKEN>`, viewer.js "DEV PREVIEW MODE"). The token must be signed
// by our server (/api/admin/dev/jwt); the server still resolves the identity.
// Used only when the page is NOT inside Twitch, so the real helper always wins.
export function devHelperFromLocation(search: string, insideTwitch: boolean): IdentityHelper | null {
  if (insideTwitch) return null;
  const token = new URLSearchParams(search).get('dev_jwt');
  if (!token) return null;
  const claims = decodeClaims(token);
  if (!claims) return null;
  const authorization: TwitchAuthorization = {
    token,
    channelId: String(claims.channel_id ?? ''),
    userId: String(claims.opaque_user_id ?? claims.user_id ?? ''),
  };
  if (!authorization.channelId || !authorization.userId) return null;
  return { environment: 'dev', onAuthorized: callback => callback(authorization) };
}

function decodeClaims(token: string): Record<string, unknown> | null {
  const part = token.split('.')[1];
  if (!part) return null;
  try {
    const base64 = part.replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
    const value: unknown = JSON.parse(atob(padded));
    return value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}
