function getUrlParam(key: string): string | null {
  try {
    return new URLSearchParams(window.location.search).get(key);
  } catch {
    return null;
  }
}

export function getAuthToken(): string | null {
  return (
    getUrlParam('token') ||
    window.localStorage.getItem('jkm_ai_session_v1') ||
    window.localStorage.getItem('token') ||
    window.localStorage.getItem('session_token')
  );
}

export function buildAuthHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = getAuthToken();
  const h: Record<string, string> = {
    Accept: 'application/json',
    ...(extra || {}),
  };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}
