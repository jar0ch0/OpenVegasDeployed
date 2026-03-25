const BROWSER_TOKEN_KEY = "openvegas_browser_bearer_token";

function normalizeToken(raw) {
  const v = String(raw || "").trim();
  if (!v) return "";
  return v.toLowerCase().startsWith("bearer ") ? v.slice(7).trim() : v;
}

export function getBrowserToken() {
  try {
    return normalizeToken(window.localStorage.getItem(BROWSER_TOKEN_KEY) || "");
  } catch {
    return "";
  }
}

export function setBrowserToken(rawToken) {
  const token = normalizeToken(rawToken);
  if (!token) return false;
  window.localStorage.setItem(BROWSER_TOKEN_KEY, token);
  return true;
}

export function clearBrowserToken() {
  try {
    window.localStorage.removeItem(BROWSER_TOKEN_KEY);
  } catch {
    // Ignore storage errors.
  }
}

export function getLoginHref(nextPath) {
  const fallback = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  const next = String(nextPath || fallback || "/ui/balance");
  return `/ui/login?next=${encodeURIComponent(next)}`;
}

export function authHeaders(extraHeaders = {}) {
  const headers = new Headers(extraHeaders || {});
  const token = getBrowserToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return headers;
}

export async function apiFetch(url, init = {}) {
  const requestInit = {
    ...init,
    headers: authHeaders(init.headers),
  };
  return fetch(url, requestInit);
}

export async function apiJson(url, init = {}) {
  const res = await apiFetch(url, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(`${res.status}: ${JSON.stringify(body)}`);
    error.status = res.status;
    error.body = body;
    throw error;
  }
  return body;
}

export async function authProbe() {
  const token = getBrowserToken();
  if (!token) {
    return { ok: false, status: 401, data: null, reason: "missing_token" };
  }

  const res = await apiFetch("/wallet/balance", { method: "GET" });
  if (res.status === 401 || res.status === 403) {
    return { ok: false, status: res.status, data: null, reason: "unauthorized" };
  }
  if (!res.ok) {
    throw new Error(`Auth probe failed: ${res.status}`);
  }
  const data = await res.json();
  return { ok: true, status: res.status, data, reason: null };
}

export function showSignedOutPanel({ panelId = "authState", contentId = "authContent" } = {}) {
  const panel = document.getElementById(panelId);
  const content = document.getElementById(contentId);
  if (panel) panel.hidden = false;
  if (content) content.hidden = true;
}

export function showAuthedContent({ panelId = "authState", contentId = "authContent" } = {}) {
  const panel = document.getElementById(panelId);
  const content = document.getElementById(contentId);
  if (panel) panel.hidden = true;
  if (content) content.hidden = false;
}
