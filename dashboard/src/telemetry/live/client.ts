// The only way the page talks to the VM: same-origin /api, served by the bridge (bridge/README.md).
// The custom header makes every write a non-simple request, so another site cannot post to the bridge from your browser.

export class BridgeError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

interface Options {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  timeoutMs?: number
  signal?: AbortSignal
}

export async function api<T>(path: string, { method = 'GET', body, timeoutMs = 8000, signal }: Options = {}): Promise<T> {
  const timeout = AbortSignal.timeout(timeoutMs)
  const res = await fetch(`/api${path}`, {
    method,
    headers: { 'X-Hermes-Dash': '1', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    credentials: 'same-origin',
  }).catch((err: unknown) => {
    const reason = err instanceof DOMException && err.name === 'TimeoutError' ? 'The bridge did not answer in time' : 'The bridge cannot be reached'
    throw new BridgeError(0, reason)
  })
  const text = await res.text()
  let data: unknown = null
  try { data = text ? JSON.parse(text) : null } catch { /* not JSON */ }
  if (!res.ok) {
    const msg = (data && typeof data === 'object' && 'error' in data && typeof data.error === 'string') ? data.error : `HTTP ${res.status}`
    throw new BridgeError(res.status, msg)
  }
  return data as T
}
