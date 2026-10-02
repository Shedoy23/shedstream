import { afterEach, describe, expect, it, vi } from 'vitest';

const originModule = () => import('../src/skillgames/origin');

afterEach(() => { vi.unstubAllEnvs(); vi.resetModules(); window.history.replaceState({}, '', '/'); });

describe('skillgame EBS origin boundary', () => {
  it('defaults to same-origin and never accepts a query-provided destination', async () => {
    vi.stubEnv('VITE_SKILLGAME_EBS_ORIGIN', '');
    window.history.replaceState({}, '', '/?api_origin=https://untrusted.invalid&VITE_SKILLGAME_EBS_ORIGIN=https://untrusted.invalid');
    const { configuredApiOrigin, validateSkillgameEbsOrigin } = await originModule();
    expect(configuredApiOrigin).toBe('');
    expect(validateSkillgameEbsOrigin(undefined)).toBe('');
    expect(validateSkillgameEbsOrigin('')).toBe('');
  });

  it('uses only the validated build environment and canonicalizes HTTPS origins', async () => {
    vi.stubEnv('VITE_SKILLGAME_EBS_ORIGIN', 'https://EBS.EXAMPLE.INVALID:443');
    const { configuredApiOrigin, validateSkillgameEbsOrigin } = await originModule();
    expect(configuredApiOrigin).toBe('https://ebs.example.invalid');
    expect(validateSkillgameEbsOrigin('https://ebs.example.invalid:8443')).toBe('https://ebs.example.invalid:8443');
    expect(validateSkillgameEbsOrigin('https://[::1]:8443')).toBe('https://[::1]:8443');
  });

  it.each([
    'http://ebs.example.invalid', '//ebs.example.invalid', 'ebs.example.invalid',
    'https://user:password@ebs.example.invalid', 'https://@ebs.example.invalid',
    'https://ebs.example.invalid/', 'https://ebs.example.invalid/api',
    'https://ebs.example.invalid?target=other', 'https://ebs.example.invalid?',
    'https://ebs.example.invalid#fragment', 'https://ebs.example.invalid#',
    ' https://ebs.example.invalid', 'https://ebs.example.invalid ', ' ',
    'https://ebs.example.invalid\\untrusted.invalid', 'https://ebs.example.invalid\n',
    'https://', "https://ebs.example.invalid;connect-src='*'", 'https://ebs.example.invalid:0',
  ])('rejects unsafe or non-origin configuration: %j', async value => {
    vi.stubEnv('VITE_SKILLGAME_EBS_ORIGIN', '');
    const { validateSkillgameEbsOrigin } = await originModule();
    expect(() => validateSkillgameEbsOrigin(value)).toThrow(/VITE_SKILLGAME_EBS_ORIGIN/);
  });

  it('fails closed when the compiled environment contains an invalid origin', async () => {
    vi.stubEnv('VITE_SKILLGAME_EBS_ORIGIN', 'http://ebs.example.invalid');
    await expect(originModule()).rejects.toThrow(/VITE_SKILLGAME_EBS_ORIGIN/);
  });
});
