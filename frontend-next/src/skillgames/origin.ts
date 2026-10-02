/// <reference types="vite/client" />

// A deployment chooses this destination at build time. Empty means local
// same-origin routing; never derive an authenticated destination from page URLs.
export function validateSkillgameEbsOrigin(value: unknown): string {
  if (value === undefined || value === '') return '';
  const invalid = () => new Error('VITE_SKILLGAME_EBS_ORIGIN must be empty or an HTTPS origin without credentials, path, query, or fragment');
  if (typeof value !== 'string' || !/^https:\/\/[^/\\?#@\s;"'<>]+$/.test(value)) throw invalid();
  let url: URL;
  try { url = new URL(value); } catch { throw invalid(); }
  if (url.protocol !== 'https:' || url.username || url.password || url.pathname !== '/' || url.search || url.hash || url.port === '0') throw invalid();
  // URL normalization produces the only value embedded in HTML or used by HTTP.
  // This allowlist also excludes characters interpreted as CSP/HTML syntax.
  if (!/^https:\/\/(?:[a-z0-9.-]+|\[[a-f0-9:]+\])(?::[0-9]+)?$/.test(url.origin)) throw invalid();
  return url.origin;
}

export const configuredApiOrigin = validateSkillgameEbsOrigin(import.meta.env?.VITE_SKILLGAME_EBS_ORIGIN);
