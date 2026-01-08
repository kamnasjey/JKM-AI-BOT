import { buildApiUrl } from './config';

export type HttpError = {
  name: 'HttpError';
  status: number;
  url: string;
  message: string;
};

export type FetchJsonOptions = {
  timeoutMs?: number;
  init?: RequestInit;
};

export async function fetchWithTimeout(pathOrUrl: string, opts?: { timeoutMs?: number; init?: RequestInit }): Promise<Response> {
  const timeoutMs = opts?.timeoutMs ?? 10_000;
  const init = opts?.init;

  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(buildApiUrl(pathOrUrl), {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        ...(init?.headers || {}),
      },
    });
  } finally {
    clearTimeout(t);
  }
}

export async function fetchJson<T>(pathOrUrl: string, opts?: FetchJsonOptions): Promise<T> {
  const res = await fetchWithTimeout(pathOrUrl, { timeoutMs: opts?.timeoutMs, init: opts?.init });

  if (!res.ok) {
    let text = '';
    try {
      text = await res.text();
    } catch {
      text = '';
    }

    const snippet = text.trim().slice(0, 400);
    const err: HttpError = {
      name: 'HttpError',
      status: res.status,
      url: res.url,
      message: snippet ? `HTTP ${res.status}: ${snippet}` : `HTTP ${res.status}`,
    };
    throw err;
  }

  return (await res.json()) as T;
}

export type HealthResponse = {
  ok: boolean;
  provider_configured?: boolean;
  uptime_s?: number;
  ts?: number;
  signals_file_exists?: boolean;
  signals_lines_estimate?: number;
};

export async function getHealth(): Promise<HealthResponse> {
  return fetchJson<HealthResponse>('/health', { timeoutMs: 5_000 });
}

export async function getSignals(limit: number): Promise<any[]> {
  return fetchJson<any[]>(`/api/signals?limit=${encodeURIComponent(String(limit))}`, { timeoutMs: 10_000 });
}
