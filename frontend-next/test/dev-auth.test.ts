import { describe, expect, it } from 'vitest';
import { devHelperFromLocation } from '../src/devAuth';

const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
const token = `${b64({ alg: 'HS256' })}.${b64({ channel_id: '98319857', user_id: '98319857', opaque_user_id: 'U98319857', role: 'viewer' })}.sig`;

describe('dev preview auth (outside Twitch only)', () => {
  it('passes the dev token with channel and opaque id from its claims', () => {
    const helper = devHelperFromLocation(`?dev_jwt=${token}&dev_user=shedoy23`, false);
    let got: unknown = null;
    helper?.onAuthorized(a => { got = a; });
    expect(got).toEqual({ token, channelId: '98319857', userId: 'U98319857' });
  });
  it('is ignored inside Twitch: the real helper always wins', () => {
    expect(devHelperFromLocation(`?dev_jwt=${token}`, true)).toBeNull();
  });
  it('does nothing without the parameter or with a broken token', () => {
    expect(devHelperFromLocation('', false)).toBeNull();
    expect(devHelperFromLocation('?dev_jwt=garbage', false)).toBeNull();
    expect(devHelperFromLocation(`?dev_jwt=x.${b64({ role: 'viewer' })}.y`, false)).toBeNull();
  });
});
