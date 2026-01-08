function isAbsoluteUrl(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

export function getApiBase(): string {
  const v = (import.meta.env as Record<string, string | undefined>).VITE_API_BASE;
  return (v && v.trim()) || 'http://localhost:8000';
}

export function buildApiUrl(pathOrUrl: string): string {
  if (isAbsoluteUrl(pathOrUrl)) return pathOrUrl;

  const base = getApiBase().replace(/\/$/, '');
  const path = pathOrUrl.startsWith('/') ? pathOrUrl : `/${pathOrUrl}`;
  return `${base}${path}`;
}
