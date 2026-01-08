export type ApiError = {
  name: 'ApiError';
  status: number;
  url: string;
  message: string;
};

function isAbsoluteUrl(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

export function getApiBase(): string {
  const base = (import.meta.env as Record<string, string | undefined>).VITE_API_BASE;
  return (base && base.trim()) || 'http://localhost:8000';
}

export function buildApiUrl(path: string): string {
  if (isAbsoluteUrl(path)) return path;
  const base = getApiBase().replace(/\/$/, '');
  const p = path.startsWith('/') ? path : `/${path}`;
  return `${base}${p}`;
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const url = buildApiUrl(path);
  return fetch(url, init);
}

export async function apiGetJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.headers || {}),
    },
  });

  if (!res.ok) {
    let text = '';
    try {
      text = await res.text();
    } catch {
      text = '';
    }
    const err: ApiError = {
      name: 'ApiError',
      status: res.status,
      url: res.url,
      message: text || `HTTP ${res.status}`,
    };
    throw err;
  }

  return (await res.json()) as T;
}
