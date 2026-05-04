import { useEffect, useMemo, useState } from "react";
import logo from "./assets/JudgementCut_Logo.png";
import { fetchFeaturedDeals, login } from "./lib/api";
import { sampleDeals, sampleEpicFree } from "./data/sample";

const PLATFORM_CONFIG = [
  {
    key: "steam",
    label: "Steam Sales",
    storeIds: ["1"],
    accent: "from-sky-400/80 via-cyan-300/60 to-blue-300/40",
  },
  {
    key: "epic",
    label: "Epic Free",
    storeIds: ["25"],
    accent: "from-amber-200/80 via-yellow-300/70 to-amber-400/50",
    free: true,
  },
  {
    key: "gog",
    label: "GOG Sales",
    storeIds: ["7"],
    accent: "from-indigo-300/70 via-sky-300/60 to-slate-300/40",
  },
  {
    key: "humble",
    label: "Humble Sales",
    storeIds: ["11"],
    accent: "from-orange-300/70 via-amber-300/60 to-yellow-200/50",
  },
];

const STORE_NAME = {
  1: "Steam",
  7: "GOG",
  11: "Humble",
  25: "Epic",
};

const STORE_KEY_MAP = {
  steam: "steam",
  epic: "epic",
  gog: "gog",
  humble: "humble",
};

const STORE_LABEL_MAP = {
  steam: "Steam",
  epic: "Epic",
  gog: "GOG",
  humble: "Humble",
};

function decodeJwt(token) {
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const json = atob(normalized);
    return JSON.parse(json);
  } catch {
    return null;
  }
}

function formatPrice(value) {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (Number.isNaN(num)) return value;
  return `$${num.toFixed(2)}`;
}

function resolvePlatformKey(deal) {
  const storeId = String(deal.storeID || deal.store_id || "");
  const idMatch = PLATFORM_CONFIG.find((p) =>
    p.storeIds.includes(storeId),
  )?.key;
  if (idMatch) return idMatch;

  const rawName = String(deal.storeName || deal.store || "").toLowerCase();
  const nameKey = Object.keys(STORE_KEY_MAP).find((key) =>
    rawName.includes(key),
  );
  return nameKey ? STORE_KEY_MAP[nameKey] : null;
}

function resolveStoreLabel(deal) {
  const storeId = String(deal.storeID || deal.store_id || "");
  if (STORE_NAME[storeId]) return STORE_NAME[storeId];

  const raw = String(deal.storeName || deal.store || "");
  const rawLower = raw.toLowerCase();
  const nameKey = Object.keys(STORE_LABEL_MAP).find((key) =>
    rawLower.includes(key),
  );
  return nameKey ? STORE_LABEL_MAP[nameKey] : raw || "Unknown";
}

export default function App() {
  const [session, setSession] = useState(() => {
    const token = localStorage.getItem("jc_token");
    const mode = localStorage.getItem("jc_mode") || (token ? "live" : null);
    const user = localStorage.getItem("jc_user");
    return { token, mode, user };
  });
  const [form, setForm] = useState({ username: "", password: "" });
  const [error, setError] = useState("");
  const [status, setStatus] = useState({ loading: false, source: "sample" });
  const [deals, setDeals] = useState([]);
  const [epicFree, setEpicFree] = useState([]);

  useEffect(() => {
    if (session?.mode !== "live" || !session?.token) return;
    let cancelled = false;

    async function loadDeals() {
      setStatus({ loading: true, source: "live" });
      try {
        const data = await fetchFeaturedDeals(session.token);
        if (!cancelled) {
          setDeals(Array.isArray(data) ? data : []);
          setEpicFree([]);
          setStatus({ loading: false, source: "live" });
        }
      } catch (err) {
        if (!cancelled) {
          setStatus({ loading: false, source: "sample" });
          setDeals([]);
          setEpicFree([]);
          setError("Backend unreachable. Showing sample data.");
        }
      }
    }

    loadDeals();
    return () => {
      cancelled = true;
    };
  }, [session]);

  const groupedDeals = useMemo(() => {
    const liveDeals = deals.length ? deals : sampleDeals;
    const map = {};
    for (const platform of PLATFORM_CONFIG) {
      map[platform.key] = [];
    }

    for (const deal of liveDeals) {
      const key = resolvePlatformKey(deal);
      if (key) map[key].push(deal);
    }

    return map;
  }, [deals]);

  const epicItems = epicFree.length ? epicFree : sampleEpicFree;

  function persistSession(next) {
    if (next.token) {
      localStorage.setItem("jc_token", next.token);
    } else {
      localStorage.removeItem("jc_token");
    }
    if (next.mode) {
      localStorage.setItem("jc_mode", next.mode);
    } else {
      localStorage.removeItem("jc_mode");
    }
    if (next.user) {
      localStorage.setItem("jc_user", next.user);
    } else {
      localStorage.removeItem("jc_user");
    }
    setSession(next);
  }

  async function handleLogin(event) {
    event.preventDefault();
    setError("");
    setStatus((prev) => ({ ...prev, loading: true }));
    try {
      const resp = await login(form.username, form.password);
      const token = resp.access_token;
      const claims = decodeJwt(token) || {};
      const userLabel = claims.sub || form.username;
      persistSession({ token, mode: "live", user: userLabel });
    } catch (err) {
      setStatus((prev) => ({ ...prev, loading: false }));
      setError("Login failed. Check credentials or API base URL.");
    }
  }

  function handleDemo() {
    setError("");
    persistSession({ token: null, mode: "demo", user: "Demo" });
  }

  function handleLogout() {
    persistSession({ token: null, mode: null, user: null });
    setDeals([]);
    setEpicFree([]);
  }

  if (!session?.mode) {
    return (
      <div className="min-h-screen px-6 py-12">
        <div className="mx-auto grid w-full max-w-5xl items-center gap-10 md:grid-cols-[1.1fr_0.9fr]">
          <div className="space-y-6">
            <div className="logo-aura floaty">
              <img src={logo} alt="Judgement Cut" className="w-full max-w-xl" />
            </div>
            <div className="space-y-3">
              <h1 className="text-4xl md:text-5xl">Judgement Cut</h1>
              <p className="text-lg text-slate-200/80">
                Track the sharpest deals across every platform. One blade,
                endless discounts.
              </p>
              <div className="flex flex-wrap gap-3 text-sm text-slate-200/70">
                <span className="badge rounded-full px-4 py-1">
                  Steam, Epic, GOG, Humble
                </span>
                <span className="badge rounded-full px-4 py-1">
                  Zyte + CheapShark Sync
                </span>
                <span className="badge rounded-full px-4 py-1">
                  Lambda ready
                </span>
              </div>
            </div>
          </div>

          <div className="glass-card rounded-2xl p-8">
            <div className="mb-6 space-y-2">
              <h2 className="text-3xl">Login</h2>
              <p className="text-sm text-slate-200/70">
                Use your seeded account to access the dashboard.
              </p>
            </div>

            <form className="space-y-4" onSubmit={handleLogin}>
              <label className="block text-sm text-slate-200/80">
                Username
                <input
                  type="text"
                  value={form.username}
                  onChange={(event) =>
                    setForm({ ...form, username: event.target.value })
                  }
                  className="mt-2 w-full rounded-xl border border-white/10 bg-slate-900/60 px-4 py-3 text-white outline-none focus:border-sky-400/70"
                  placeholder="admin"
                />
              </label>
              <label className="block text-sm text-slate-200/80">
                Password
                <input
                  type="password"
                  value={form.password}
                  onChange={(event) =>
                    setForm({ ...form, password: event.target.value })
                  }
                  className="mt-2 w-full rounded-xl border border-white/10 bg-slate-900/60 px-4 py-3 text-white outline-none focus:border-sky-400/70"
                  placeholder="adminpass"
                />
              </label>
              {error ? <p className="text-sm text-amber-200">{error}</p> : null}
              <button
                type="submit"
                className="w-full rounded-xl bg-gradient-to-r from-sky-400 via-cyan-300 to-blue-300 px-4 py-3 font-semibold text-slate-900 transition hover:brightness-110"
                disabled={status.loading}
              >
                {status.loading ? "Signing in..." : "Enter the Vault"}
              </button>
            </form>

            <button
              className="mt-4 w-full rounded-xl border border-white/15 px-4 py-3 text-sm text-slate-100/80 transition hover:border-white/30"
              onClick={handleDemo}
            >
              Enter Demo Mode
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-white/10 bg-slate-950/70 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-4">
            <img src={logo} alt="Judgement Cut" className="h-12 w-auto" />
            <div>
              <div className="text-xl font-semibold">Judgement Cut</div>
              <div className="text-xs text-slate-200/70">
                Deal Command Center
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="badge rounded-full px-3 py-1 text-xs">
              {status.source === "live" ? "Live Sync" : "Sample Data"}
            </span>
            <div className="flex items-center gap-2 rounded-full border border-white/10 bg-slate-900/70 px-3 py-1">
              <div className="h-7 w-7 rounded-full bg-gradient-to-br from-sky-400 to-blue-700"></div>
              <div className="text-sm">{session.user || "Operator"}</div>
              <button
                className="text-xs text-slate-200/70 hover:text-white"
                onClick={handleLogout}
              >
                Logout
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-10 px-6 pb-16 pt-8">
        <section className="glass-card rounded-3xl p-8">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
            <div className="space-y-3">
              <h1 className="text-3xl md:text-4xl">Platform Pulse</h1>
              <p className="text-slate-200/70">
                Scanned by Zyte, filtered by CheapShark, delivered with a single
                blade stroke.
              </p>
              <div className="flex flex-wrap gap-3 text-xs text-slate-200/70">
                <span className="badge rounded-full px-3 py-1">
                  JWT protected
                </span>
                <span className="badge rounded-full px-3 py-1">RBAC ready</span>
                <span className="badge rounded-full px-3 py-1">TiDB + R2</span>
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-slate-950/40 px-5 py-4 text-sm">
              <div className="text-slate-200/70">Sync status</div>
              <div className="mt-1 text-lg">
                {status.loading
                  ? "Syncing..."
                  : status.source === "live"
                    ? "Online"
                    : "Offline"}
              </div>
              <div className="text-xs text-slate-200/60">
                {status.source === "live"
                  ? "Lambda live data"
                  : "Sample backup"}
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-8">
          {PLATFORM_CONFIG.map((platform, index) => (
            <PlatformSection
              key={platform.key}
              platform={platform}
              items={
                platform.free ? epicItems : groupedDeals[platform.key] || []
              }
              revealDelay={index * 0.08}
            />
          ))}
        </section>
      </main>
    </div>
  );
}

function PlatformSection({ platform, items, revealDelay }) {
  const display = items.slice(0, 4);
  return (
    <div className="glass-card rounded-3xl p-6 md:p-8">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-2xl">{platform.label}</h2>
          <p className="text-sm text-slate-200/70">
            {platform.free ? "Free games only" : "Live sales and discounts"}
          </p>
        </div>
        <div
          className={`rounded-full bg-gradient-to-r ${platform.accent} px-4 py-2 text-xs font-semibold text-slate-900 shadow`}
        >
          {platform.free ? "Claim before it ends" : "Live deals"}
        </div>
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {display.map((deal, idx) => (
          <DealCard
            key={deal.dealID || deal.id || idx}
            deal={deal}
            free={platform.free}
            delay={revealDelay + idx * 0.06}
          />
        ))}
      </div>

      {display.length === 0 ? (
        <div className="mt-6 text-sm text-slate-200/70">
          No items yet. Waiting for the next crawl.
        </div>
      ) : null}
    </div>
  );
}

function DealCard({ deal, free, delay }) {
  const price = free
    ? 0
    : (deal.salePrice ?? deal.price ?? deal.sale_price ?? deal.price);
  const normal = deal.normalPrice ?? deal.normal_price ?? deal.normalPrice;
  const storeName = resolveStoreLabel(deal);
  const savings = deal.savings ? `${Number(deal.savings).toFixed(0)}%` : "";

  return (
    <div
      className="raised reveal rounded-2xl border border-white/10 bg-slate-950/60 p-4"
      style={{ animationDelay: `${delay}s` }}
    >
      <div className="text-xs uppercase tracking-widest text-slate-200/50">
        {storeName}
      </div>
      <div className="mt-2 text-base font-semibold">{deal.title}</div>
      <div className="mt-3 flex items-end justify-between">
        <div>
          <div className="text-lg font-semibold text-glow">
            {free ? "FREE" : formatPrice(price)}
          </div>
          <div className="text-xs text-slate-200/60 line-through">
            {formatPrice(normal)}
          </div>
        </div>
        {savings ? (
          <div className="rounded-full border border-emerald-300/40 bg-emerald-400/10 px-2 py-1 text-xs text-emerald-200">
            {savings}
          </div>
        ) : null}
      </div>
    </div>
  );
}
