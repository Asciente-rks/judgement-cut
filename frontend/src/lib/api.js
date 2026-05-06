const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const resp = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });

  if (!resp.ok) {
    const text = await resp.text();
    const err = new Error(text || `Request failed: ${resp.status}`);
    err.status = resp.status;
    throw err;
  }

  return resp.json();
}

function authHeader(token) {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function login(username, password) {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function fetchMe(token) {
  return request("/v1/me", { headers: authHeader(token) });
}

export async function fetchFeaturedDeals(token, limit = 20) {
  return request(`/v1/deals/featured?limit=${limit}`, {
    headers: authHeader(token),
  });
}

export async function searchDeals(token, title, pageSize = 60) {
  const q = new URLSearchParams({ title, pageSize: String(pageSize) });
  return request(`/v1/deals/search?${q.toString()}`, {
    headers: authHeader(token),
  });
}

export async function fetchPriceHistory(token, dealId, limit = 50) {
  return request(`/v1/deals/${encodeURIComponent(dealId)}/history?limit=${limit}`, {
    headers: authHeader(token),
  });
}

export async function fetchThumbnail(token, dealId) {
  return request(`/v1/deals/${encodeURIComponent(dealId)}/thumbnail`, {
    headers: authHeader(token),
  });
}

export async function fetchExchangeRate(token, base = "USD", target = "PHP") {
  const q = new URLSearchParams({ base, target });
  return request(`/v1/exchange-rate?${q.toString()}`, {
    headers: authHeader(token),
  });
}

export async function fetchPlatforms(token) {
  return request("/v1/admin/platforms", { headers: authHeader(token) });
}

export async function togglePlatform(token, name, enabled) {
  return request(
    `/v1/admin/platforms/${encodeURIComponent(name)}/toggle?enabled=${enabled}`,
    { method: "POST", headers: authHeader(token) },
  );
}

export async function fetchUsers(token) {
  return request("/v1/admin/users", { headers: authHeader(token) });
}

export async function setUserAdmin(token, username, enabled) {
  return request(
    `/v1/admin/users/${encodeURIComponent(username)}/admin?enabled=${enabled}`,
    { method: "POST", headers: authHeader(token) },
  );
}

export async function fetchScraperMonitor(token) {
  return request("/v1/admin/monitor/scraper", { headers: authHeader(token) });
}
