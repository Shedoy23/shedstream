import { policyRefusal } from '../common/policy-refusal';
import { TwitchAuthStore } from '../auth';
import { isRecord } from '../contracts';
import { requestJson } from '../skillgames/http';
import { actionKey, UnknownActionOutcomeError, type ActionReply, type PanelTransport } from './contracts';
const newClientActionId = () => typeof globalThis.crypto?.randomUUID === 'function'
  ? globalThis.crypto.randomUUID() : Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
export class HttpPanelTransport implements PanelTransport {
  private inflight = new Set<string>();
  // No automatic retry after an unknown result: the server may already have
  // accepted it. Keep this identity blocked for this transport's lifetime.
  private uncertain = new Set<string>();
  mutationBlock() { const auth = this.auth.current(); return this.uncertain.has(JSON.stringify([auth?.channelId, auth?.userId])) ? new UnknownActionOutcomeError().message : null; }
  constructor(private readonly baseUrl: string, private readonly auth: TwitchAuthStore, private readonly fetcher: typeof fetch = fetch, private readonly newId: () => string = newClientActionId) {}
  private authorization() { const value = this.auth.current(); if (!value?.token) throw new Error('Нужна авторизация Twitch'); return { ...value }; }
  async read<T>(path: string, signal?: AbortSignal): Promise<T> {
    if (!path.startsWith('/api/')) throw new Error('Недопустимый путь API');
    const authorization = this.authorization();
    const { response, body } = await requestJson(this.fetcher, this.baseUrl + path, { headers: { 'X-Twitch-JWT': authorization.token }, signal, ...((path.startsWith('/api/viewer/stats/') || path === '/api/bannerlord/config' || path === '/api/bannerlord/progression') ? { cache: 'no-store' as const } : {}) });
    const refusal = policyRefusal(response.status, body, authorization.channelId, true);
    if (refusal) throw new Error(refusal.message);
    if (!response.ok || !isRecord(body) || body.success === false) {
      throw new Error(isRecord(body) && typeof body.message === 'string' ? body.message : `Ошибка сервера (${response.status})`);
    }
    return body as T;
  }
  async action(type: string, data: Record<string, unknown>): Promise<ActionReply | null> {
    // Snapshot once. A token rotation must not change an already admitted request.
    const authorization = this.authorization();
    const identity = JSON.stringify([authorization.channelId, authorization.userId]);
    if (this.uncertain.has(identity)) throw new UnknownActionOutcomeError();
    const key = identity + ':' + actionKey(type, data);
    if (this.inflight.has(key)) return null;
    // A local ID/serialization failure happened before any request was sent.
    // It cannot be evidence of an uncertain server-side acceptance.
    const requestBody = JSON.stringify({ action_type: type, data: { ...data, client_action_id: this.newId() } });
    this.inflight.add(key);
    try {
      const { response, body } = await requestJson(this.fetcher, this.baseUrl + '/api/bannerlord/action', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Twitch-JWT': authorization.token },
        body: requestBody,
      });
      if (!Number.isInteger(response.status) || response.status < 200 || response.status >= 500) throw new Error(`Ошибка ответа сервера (${response.status})`);
      const refusal = policyRefusal(response.status, body, authorization.channelId);
      if (refusal) return refusal;
      if (!isRecord(body) || 'detail' in body || typeof body.success !== 'boolean') throw new Error(`Ошибка ответа сервера (${response.status})`);
      return body as ActionReply;
    } catch {
      this.uncertain.add(identity);
      throw new UnknownActionOutcomeError();
    } finally { this.inflight.delete(key); }
  }
  async post(path: string,data:Record<string,unknown>):Promise<ActionReply|null> {
    if(!path.startsWith('/api/bannerlord/'))throw new Error('Недопустимый путь API');
    const authorization=this.authorization(),identity=JSON.stringify([authorization.channelId,authorization.userId]);
    if(this.uncertain.has(identity))throw new UnknownActionOutcomeError();
    const key=identity+':'+path+':'+JSON.stringify(data);
    if(this.inflight.has(key))return null;
    this.inflight.add(key);
    try{
      const {response,body}=await requestJson(this.fetcher,this.baseUrl+path,{method:'POST',headers:{'Content-Type':'application/json','X-Twitch-JWT':authorization.token},body:JSON.stringify(data)});
      const refusal=policyRefusal(response.status,body,authorization.channelId);
      if(refusal)return refusal;
      if(response.status<200||response.status>=500||!isRecord(body)||typeof body.success!=='boolean')throw new Error('Неизвестный исход запроса');
      return body as ActionReply;
    }catch{this.uncertain.add(identity);throw new UnknownActionOutcomeError();}
    finally{this.inflight.delete(key);}
  }
}
