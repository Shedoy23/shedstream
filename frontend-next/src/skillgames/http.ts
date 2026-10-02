// An infrastructure timeout, independent of game deadlines. Covers response body
// reads as well as headers, and works even if an injected fetch ignores abort.
export async function requestJson(fetcher: typeof fetch, url: string, options: RequestInit) {
  const abort = new AbortController();
  let rejectDeadline!: (error: Error) => void;
  const interrupted = new Promise<never>((_, reject) => { rejectDeadline = reject; });
  const onAbort = () => { abort.abort(); rejectDeadline(new Error('Запрос отменён')); };
  options.signal?.addEventListener('abort', onAbort, { once: true });
  const timer = setTimeout(() => { abort.abort(); rejectDeadline(new Error('Сервер не ответил за 20 секунд. Повторите проверку.')); }, 20000);
  if (options.signal?.aborted) onAbort();
  try {
    return await Promise.race([
      fetcher(url, { ...options, signal: abort.signal }).then(async response => ({ response, body: await response.json() as unknown })),
      interrupted,
    ]);
  } finally { clearTimeout(timer); options.signal?.removeEventListener('abort', onAbort); }
}
