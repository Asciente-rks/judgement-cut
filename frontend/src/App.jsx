import { useCallback, useEffect, useMemo, useState } from "react";
import logo from "./assets/JudgementCut_Logo.png";
import {
  fetchExchangeRate,
  fetchFeaturedDeals,
  fetchMe,
  fetchPlatforms,
  fetchPriceHistory,
  fetchScraperMonitor,
  fetchThumbnail,
  fetchUsers,
  login,
  searchDeals,
  setUserAdmin,
  togglePlatform,
} from "./lib/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

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

const STORE_NAME = { 1: "Steam", 7: "GOG", 11: "Humble", 25: "Epic" };

// ISO 4217 codes the UI lets the user toggle between. PHP first because
// the audience is in PH; USD is the canonical price source.
const CURRENCIES = [
  { code: "PHP", symbol: "₱", label: "PHP" },
  { code: "USD", symbol: "$", label: "USD" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolvePlatformKey(deal) {
  const storeId = String(deal.storeID || deal.store_id || "");
  const idMatch = PLATFORM_CONFIG.find((p) => p.storeIds.includes(storeId))?.key;
  if (idMatch) return idMatch;

  const raw = String(deal.storeName || deal.store || "").toLowerCase();
  return (
    PLATFORM_CONFIG.find((p) => raw.includes(p.key))?.key ?? null
  );
}

function resolveStoreLabel(deal) {
  const storeId = String(deal.storeID || deal.store_id || "");
  if (STORE_NAME[storeId]) return STORE_NAME[storeId];
  const raw = String(deal.storeName || deal.store || "");
  return raw || "Unknown";
}

function dealId(deal) {
  return deal.dealID || deal.deal_id || deal.id;
}

function pickPrice(deal) {
  // Prefer numeric, accept strings; null/undefined returns null.
  const candidates = [deal.salePrice, deal.price, deal.sale_price];
  for (const v of candidates) {
    if (v === null || v === undefined || v === "") continue;
    const num = Number(v);
    if (!Number.isNaN(num)) return num;
  }
  return null;
}

function pickNormalPrice(deal) {
  const candidates = [deal.normalPrice, deal.normal_price];
  for (const v of candidates) {
    if (v === null || v === undefined || v === "") continue;
    const num = Number(v);
    if (!Number.isNaN(num)) return num;
  }
  return null;
}

function pickThumbnail(deal) {
  return deal.thumbnail_url || deal.thumb || deal.thumbnail || null;
}

function decodeJwt(token) {
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(normalized));
  } catch {
    return null;
  }
}

// Format a USD price into the active currency, using the cached FX
// rate. If FX hasn't loaded yet, fall back to USD so the UI never
// shows broken values.
function formatPrice(value, currency, fxRate) {
  if (value === null || value === undefined || value === "") return "—";
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);

  const cur = CURRENCIES.find((c) => c.code === currency) || CURRENCIES[1];
  if (currency === "USD" || !fxRate || cur.code === "USD") {
    return `$${num.toFixed(2)}`;
  }
  const converted = num * fxRate;
  return `${cur.symbol}${converted.toFixed(2)}`;
}

// ---------------------------------------------------------------------------
// Top-level App
// ---------------------------------------------------------------------------

export default function App() {
  const [session, setSession] = useState(() => ({
    token: localStorage.getItem("jc_token") || null,
  }));
  const [me, setMe] = useState(null);
  const [meError, setMeError] = useState(null);

  const [view, setView] = useState("dashboard"); // dashboard | search | admin
  const [currency, setCurrency] = useState(
    () => localStorage.getItem("jc_currency") || "PHP",
  );
  const [fxRate, setFxRate] = useState(null);

  const [deals, setDeals] = useState([]);
  const [dealsLoading, setDealsLoading] = useState(false);
  const [dealsError, setDealsError] = useState(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState(null);

  const [selectedDeal, setSelectedDeal] = useState(null);

  // ----- Auth boot: resolve /me from token -----
  useEffect(() => {
    if (!session.token) {
      setMe(null);
      return;
    }
    let cancelled = false;
    (async () => {
      setMeError(null);
      try {
        const data = await fetchMe(session.token);
        if (!cancelled) setMe(data);
      } catch (err) {
        if (!cancelled) {
          if (err.status === 401) {
            // token expired / invalid - log out
            persistToken(null);
          } else {
            // backend down - keep token, show error in UI
            setMeError(err.message || String(err));
            // Best-effort: pull username from JWT so the UI isn't blank
            const claims = decodeJwt(session.token) || {};
            setMe({
              username: claims.sub || "Operator",
              is_admin: !!claims.is_admin,
              degraded: true,
            });
          }
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session.token]);

  // ----- Featured deals -----
  const loadFeatured = useCallback(async () => {
    if (!session.token) return;
    setDealsLoading(true);
    setDealsError(null);
    try {
      const data = await fetchFeaturedDeals(session.token, 80);
      setDeals(Array.isArray(data) ? data : []);
    } catch (err) {
      setDealsError(err.message || String(err));
      setDeals([]);
    } finally {
      setDealsLoading(false);
    }
  }, [session.token]);

  useEffect(() => {
    if (session.token && view === "dashboard") loadFeatured();
  }, [session.token, view, loadFeatured]);

  // ----- FX rate (USD -> active currency) -----
  useEffect(() => {
    if (!session.token) return;
    if (currency === "USD") {
      setFxRate(1);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchExchangeRate(session.token, "USD", currency);
        if (!cancelled) setFxRate(data.rate);
      } catch {
        if (!cancelled) setFxRate(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session.token, currency]);

  // ----- Currency persistence -----
  useEffect(() => {
    localStorage.setItem("jc_currency", currency);
  }, [currency]);

  // ----- Login / logout -----
  function persistToken(token) {
    if (token) localStorage.setItem("jc_token", token);
    else localStorage.removeItem("jc_token");
    setSession({ token });
    if (!token) {
      setMe(null);
      setDeals([]);
      setSearchResults([]);
      setSelectedDeal(null);
      setView("dashboard");
    }
  }

  // ----- Search -----
  async function handleSearch(query) {
    if (!query.trim() || !session.token) return;
    setSearchLoading(true);
    setSearchError(null);
    setView("search");
    try {
      const data = await searchDeals(session.token, query.trim(), 60);
      setSearchResults(Array.isArray(data) ? data : []);
    } catch (err) {
      setSearchError(err.message || String(err));
      setSearchResults([]);
    } finally {
      setSearchLoading(false);
    }
  }

  // ----- Render -----

  if (!session.token) {
    return <LoginScreen onLogin={persistToken} />;
  }

  return (
    <div className="min-h-screen">
      <Header
        me={me}
        currency={currency}
        setCurrency={setCurrency}
        fxRate={fxRate}
        view={view}
        setView={setView}
        onLogout={() => persistToken(null)}
        onSearch={handleSearch}
        searchQuery={searchQuery}
        setSearchQuery={setSearchQuery}
      />

      <main className="mx-auto max-w-6xl space-y-10 px-6 pb-16 pt-8">
        {meError ? (
          <Banner kind="warn">
            Backend identity check failed ({meError}). Some features may be
            degraded.
          </Banner>
        ) : null}

        {view === "dashboard" && (
          <DashboardView
            deals={deals}
            loading={dealsLoading}
            error={dealsError}
            onRetry={loadFeatured}
            currency={currency}
            fxRate={fxRate}
            token={session.token}
            onOpenHistory={(deal) => setSelectedDeal(deal)}
          />
        )}

        {view === "search" && (
          <SearchView
            query={searchQuery}
            results={searchResults}
            loading={searchLoading}
            error={searchError}
            currency={currency}
            fxRate={fxRate}
            token={session.token}
            onOpenHistory={(deal) => setSelectedDeal(deal)}
            onClear={() => {
              setSearchQuery("");
              setSearchResults([]);
              setView("dashboard");
            }}
          />
        )}

        {view === "admin" && me?.is_admin && (
          <AdminPanel token={session.token} me={me} />
        )}
      </main>

      {selectedDeal ? (
        <PriceHistoryModal
          deal={selectedDeal}
          token={session.token}
          currency={currency}
          fxRate={fxRate}
          onClose={() => setSelectedDeal(null)}
        />
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function Header({
  me,
  currency,
  setCurrency,
  fxRate,
  view,
  setView,
  onLogout,
  onSearch,
  searchQuery,
  setSearchQuery,
}) {
  return (
    <header className="sticky top-0 z-20 border-b border-white/10 bg-slate-950/70 backdrop-blur">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-6 py-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => setView("dashboard")}
            className="flex items-center gap-3 text-left"
          >
            <img src={logo} alt="Judgement Cut" className="h-12 w-auto" />
            <div>
              <div className="text-xl font-semibold">Judgement Cut</div>
              <div className="text-xs text-slate-200/70">
                Deal Command Center
              </div>
            </div>
          </button>
        </div>

        <div className="flex flex-1 items-center gap-3 lg:max-w-xl lg:justify-end">
          <SearchBar
            value={searchQuery}
            onChange={setSearchQuery}
            onSubmit={onSearch}
          />
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <CurrencyToggle
            currency={currency}
            setCurrency={setCurrency}
            fxRate={fxRate}
          />
          <NavTabs view={view} setView={setView} isAdmin={!!me?.is_admin} />
          <UserPill me={me} onLogout={onLogout} />
        </div>
      </div>
    </header>
  );
}

function SearchBar({ value, onChange, onSubmit }) {
  return (
    <form
      className="flex flex-1 items-center gap-2 rounded-full border border-white/10 bg-slate-900/70 px-4 py-2"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(value);
      }}
    >
      <span className="text-slate-200/60" aria-hidden="true">
        ⌕
      </span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Search any game across all platforms..."
        className="flex-1 bg-transparent text-sm text-white outline-none placeholder:text-slate-200/40"
      />
      {value ? (
        <button
          type="button"
          onClick={() => onChange("")}
          className="text-xs text-slate-200/50 hover:text-white"
        >
          ×
        </button>
      ) : null}
    </form>
  );
}

function CurrencyToggle({ currency, setCurrency, fxRate }) {
  return (
    <div className="flex items-center gap-1 rounded-full border border-white/10 bg-slate-900/70 px-1 py-1 text-xs">
      {CURRENCIES.map((c) => (
        <button
          key={c.code}
          onClick={() => setCurrency(c.code)}
          className={`rounded-full px-3 py-1 transition ${
            currency === c.code
              ? "bg-gradient-to-r from-sky-400 via-cyan-300 to-blue-300 font-semibold text-slate-900"
              : "text-slate-200/70 hover:text-white"
          }`}
          title={
            c.code !== "USD" && fxRate
              ? `1 USD ≈ ${fxRate.toFixed(2)} ${c.code}`
              : c.label
          }
        >
          {c.label}
        </button>
      ))}
    </div>
  );
}

function NavTabs({ view, setView, isAdmin }) {
  const tabs = [
    { key: "dashboard", label: "Deals" },
    ...(isAdmin ? [{ key: "admin", label: "Admin" }] : []),
  ];
  return (
    <div className="flex items-center gap-1 rounded-full border border-white/10 bg-slate-900/70 px-1 py-1 text-xs">
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => setView(t.key)}
          className={`rounded-full px-3 py-1 transition ${
            view === t.key
              ? "bg-white/10 font-semibold text-white"
              : "text-slate-200/70 hover:text-white"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

function UserPill({ me, onLogout }) {
  return (
    <div className="flex items-center gap-2 rounded-full border border-white/10 bg-slate-900/70 px-3 py-1">
      <div
        className={`h-7 w-7 rounded-full bg-gradient-to-br ${
          me?.is_admin ? "from-amber-300 to-orange-500" : "from-sky-400 to-blue-700"
        }`}
      ></div>
      <div className="text-sm">
        {me?.username || "Operator"}
        {me?.is_admin ? (
          <span className="ml-1 text-[10px] uppercase tracking-wider text-amber-200">
            admin
          </span>
        ) : null}
      </div>
      <button
        className="text-xs text-slate-200/70 hover:text-white"
        onClick={onLogout}
      >
        Logout
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dashboard view
// ---------------------------------------------------------------------------

function DashboardView({
  deals,
  loading,
  error,
  onRetry,
  currency,
  fxRate,
  token,
  onOpenHistory,
}) {
  const grouped = useMemo(() => {
    const map = Object.fromEntries(PLATFORM_CONFIG.map((p) => [p.key, []]));
    for (const deal of deals) {
      const key = resolvePlatformKey(deal);
      if (key) map[key].push(deal);
    }
    return map;
  }, [deals]);

  return (
    <>
      <section className="glass-card rounded-3xl p-8">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="space-y-3">
            <h1 className="text-3xl md:text-4xl">Platform Pulse</h1>
            <p className="text-slate-200/70">
              Scanned by Zyte, filtered by CheapShark, delivered with a single
              blade stroke.
            </p>
            <div className="flex flex-wrap gap-3 text-xs text-slate-200/70">
              <span className="badge rounded-full px-3 py-1">JWT protected</span>
              <span className="badge rounded-full px-3 py-1">RBAC enforced</span>
              <span className="badge rounded-full px-3 py-1">TiDB + R2</span>
            </div>
          </div>
          <div className="rounded-2xl border border-white/10 bg-slate-950/40 px-5 py-4 text-sm">
            <div className="text-slate-200/70">Sync status</div>
            <div className="mt-1 text-lg">
              {loading ? "Syncing..." : error ? "Offline" : "Online"}
            </div>
            <div className="text-xs text-slate-200/60">
              {error ? "Backend unreachable" : `${deals.length} live deals`}
            </div>
          </div>
        </div>
      </section>

      {error ? (
        <Banner kind="error">
          Could not load deals: {error}{" "}
          <button
            onClick={onRetry}
            className="underline underline-offset-2 hover:text-white"
          >
            Retry
          </button>
        </Banner>
      ) : null}

      <section className="grid gap-8">
        {PLATFORM_CONFIG.map((platform, index) => (
          <PlatformSection
            key={platform.key}
            platform={platform}
            items={grouped[platform.key] || []}
            revealDelay={index * 0.08}
            currency={currency}
            fxRate={fxRate}
            token={token}
            onOpenHistory={onOpenHistory}
            loading={loading}
          />
        ))}
      </section>
    </>
  );
}

function PlatformSection({
  platform,
  items,
  revealDelay,
  currency,
  fxRate,
  token,
  onOpenHistory,
  loading,
}) {
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
            key={dealId(deal) || idx}
            deal={deal}
            free={platform.free}
            delay={revealDelay + idx * 0.06}
            currency={currency}
            fxRate={fxRate}
            token={token}
            onOpenHistory={onOpenHistory}
          />
        ))}
      </div>

      {display.length === 0 ? (
        <div className="mt-6 text-sm text-slate-200/70">
          {loading ? "Loading..." : "No items yet. Waiting for the next crawl."}
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Deal card with lazy thumbnail
// ---------------------------------------------------------------------------

function DealCard({
  deal,
  free,
  delay,
  currency,
  fxRate,
  token,
  onOpenHistory,
}) {
  const id = dealId(deal);
  const price = free ? 0 : pickPrice(deal);
  const normal = pickNormalPrice(deal);
  const storeName = resolveStoreLabel(deal);
  const savings = deal.savings ? `${Number(deal.savings).toFixed(0)}%` : "";

  // Render the origin URL straight from the deal payload. We only call
  // /v1/deals/{id}/thumbnail (which mirrors to R2) if the origin <img>
  // fails to load, keeping the happy path at zero Lambda cost per card.
  const initialThumb = pickThumbnail(deal);
  const [thumbUrl, setThumbUrl] = useState(initialThumb);

  async function handleThumbnailError() {
    if (!id || !token) {
      setThumbUrl(null);
      return;
    }
    try {
      const data = await fetchThumbnail(token, id);
      setThumbUrl(data.url);
    } catch {
      setThumbUrl(null);
    }
  }

  return (
    <div
      className="raised reveal flex flex-col overflow-hidden rounded-2xl border border-white/10 bg-slate-950/60"
      style={{ animationDelay: `${delay}s` }}
    >
      <DealThumbnail
        url={thumbUrl}
        title={deal.title}
        onError={handleThumbnailError}
      />
      <div className="flex flex-1 flex-col p-4">
        <div className="text-xs uppercase tracking-widest text-slate-200/50">
          {storeName}
        </div>
        <div className="mt-2 line-clamp-2 text-base font-semibold">
          {deal.title}
        </div>
        <div className="mt-3 flex items-end justify-between">
          <div>
            <div className="text-lg font-semibold text-glow">
              {free ? "FREE" : formatPrice(price, currency, fxRate)}
            </div>
            <div className="text-xs text-slate-200/60 line-through">
              {formatPrice(normal, currency, fxRate)}
            </div>
          </div>
          {savings ? (
            <div className="rounded-full border border-emerald-300/40 bg-emerald-400/10 px-2 py-1 text-xs text-emerald-200">
              {savings}
            </div>
          ) : null}
        </div>

        <div className="mt-4 flex items-center justify-between text-xs">
          <button
            onClick={() => onOpenHistory(deal)}
            className="text-slate-200/70 underline-offset-2 hover:text-white hover:underline"
          >
            Price history
          </button>
          {deal.url ? (
            <a
              href={deal.url}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-full border border-white/20 px-3 py-1 text-slate-100/80 transition hover:border-sky-300/50 hover:text-white"
            >
              Open store ↗
            </a>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function DealThumbnail({ url, title, onError }) {
  const [attemptedFallback, setAttemptedFallback] = useState(false);

  if (!url) {
    return (
      <div className="flex h-32 items-center justify-center bg-gradient-to-br from-sky-900/40 via-slate-900 to-indigo-900/40 text-xs uppercase tracking-widest text-slate-200/40">
        No cover
      </div>
    );
  }

  return (
    <img
      src={url}
      alt={title || ""}
      loading="lazy"
      onError={() => {
        // Try the R2 mirror once. If that also fails, render "No cover".
        if (!attemptedFallback) {
          setAttemptedFallback(true);
          onError && onError();
        }
      }}
      className="h-32 w-full object-cover"
    />
  );
}

// ---------------------------------------------------------------------------
// Search view
// ---------------------------------------------------------------------------

function SearchView({
  query,
  results,
  loading,
  error,
  currency,
  fxRate,
  token,
  onOpenHistory,
  onClear,
}) {
  return (
    <section className="space-y-6">
      <div className="glass-card rounded-3xl p-6">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="text-2xl">Search results</h2>
            <p className="text-sm text-slate-200/70">
              {query
                ? `Live CheapShark results for "${query}"`
                : "Start typing in the search bar"}
            </p>
          </div>
          <button
            onClick={onClear}
            className="rounded-full border border-white/20 px-4 py-2 text-sm text-slate-100/80 transition hover:border-sky-300/50 hover:text-white"
          >
            ← Back to deals
          </button>
        </div>
      </div>

      {error ? <Banner kind="error">Search failed: {error}</Banner> : null}

      {loading ? (
        <div className="text-sm text-slate-200/70">Searching...</div>
      ) : results.length === 0 ? (
        <div className="text-sm text-slate-200/70">
          No matches for that title yet.
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {results.map((deal, idx) => (
            <DealCard
              key={dealId(deal) || idx}
              deal={deal}
              free={Number(deal.salePrice) === 0}
              delay={idx * 0.04}
              currency={currency}
              fxRate={fxRate}
              token={token}
              onOpenHistory={onOpenHistory}
            />
          ))}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Price history modal
// ---------------------------------------------------------------------------

function PriceHistoryModal({ deal, token, currency, fxRate, onClose }) {
  const id = dealId(deal);
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchPriceHistory(token, id, 100);
        if (!cancelled) setRows(Array.isArray(data) ? data : []);
      } catch (err) {
        if (!cancelled) setError(err.message || String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, token]);

  const min = useMemo(() => {
    if (!rows || rows.length === 0) return null;
    return rows.reduce((a, b) => (a.price < b.price ? a : b));
  }, [rows]);

  return (
    <div
      className="fixed inset-0 z-30 flex items-center justify-center bg-slate-950/80 px-4 backdrop-blur"
      onClick={onClose}
    >
      <div
        className="glass-card w-full max-w-xl rounded-3xl p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-xl">Price history</h3>
            <p className="text-sm text-slate-200/70">{deal.title}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-full border border-white/20 px-3 py-1 text-sm hover:border-sky-300/50"
          >
            Close
          </button>
        </div>

        {error ? (
          <Banner kind="error" className="mt-4">
            {error}
          </Banner>
        ) : rows === null ? (
          <div className="mt-6 text-sm text-slate-200/70">Loading...</div>
        ) : rows.length === 0 ? (
          <div className="mt-6 text-sm text-slate-200/70">
            No price history recorded yet for this deal.
          </div>
        ) : (
          <div className="mt-6 space-y-4">
            {min ? (
              <div className="rounded-2xl border border-emerald-300/40 bg-emerald-400/10 px-4 py-3 text-sm">
                <span className="text-emerald-200">All-time low:</span>{" "}
                <span className="font-semibold">
                  {formatPrice(min.price, currency, fxRate)}
                </span>{" "}
                <span className="text-slate-200/60">
                  on {new Date(min.recorded_at).toLocaleDateString()}
                </span>
              </div>
            ) : null}
            <div className="max-h-72 overflow-y-auto rounded-xl border border-white/10">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-slate-900/90 text-xs uppercase tracking-widest text-slate-200/60">
                  <tr>
                    <th className="px-4 py-2 text-left">Recorded</th>
                    <th className="px-4 py-2 text-right">Price</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr
                      key={row.id || i}
                      className="border-t border-white/5 even:bg-slate-950/50"
                    >
                      <td className="px-4 py-2 text-slate-200/80">
                        {new Date(row.recorded_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-2 text-right font-semibold">
                        {formatPrice(row.price, currency, fxRate)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Admin panel
// ---------------------------------------------------------------------------

function AdminPanel({ token, me }) {
  const [platforms, setPlatforms] = useState([]);
  const [users, setUsers] = useState([]);
  const [monitor, setMonitor] = useState(null);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [p, u, m] = await Promise.all([
        fetchPlatforms(token),
        fetchUsers(token),
        fetchScraperMonitor(token),
      ]);
      setPlatforms(p);
      setUsers(u);
      setMonitor(m);
    } catch (err) {
      setError(err.message || String(err));
    }
  }, [token]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function onTogglePlatform(name, enabled) {
    await togglePlatform(token, name, enabled);
    refresh();
  }

  async function onToggleAdmin(username, enabled) {
    if (!confirm(`${enabled ? "Promote" : "Demote"} ${username}?`)) return;
    try {
      await setUserAdmin(token, username, enabled);
      refresh();
    } catch (err) {
      alert(err.message || String(err));
    }
  }

  return (
    <section className="space-y-6">
      <div className="glass-card rounded-3xl p-8">
        <h2 className="text-3xl">Admin panel</h2>
        <p className="text-sm text-slate-200/70">
          Logged in as <span className="font-semibold">{me.username}</span>
        </p>
      </div>

      {error ? <Banner kind="error">{error}</Banner> : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="glass-card rounded-3xl p-6">
          <h3 className="text-xl">Platform toggles</h3>
          <p className="text-xs text-slate-200/60">
            Disabled platforms are filtered out of /v1/deals/search responses.
          </p>
          <div className="mt-4 space-y-2">
            {platforms.length === 0 ? (
              <div className="text-sm text-slate-200/70">No platforms.</div>
            ) : (
              platforms.map((p) => (
                <div
                  key={p.id}
                  className="flex items-center justify-between rounded-xl border border-white/10 bg-slate-900/60 px-4 py-3"
                >
                  <div className="font-medium">{p.name}</div>
                  <Toggle
                    on={p.is_enabled}
                    onChange={(v) => onTogglePlatform(p.name, v)}
                  />
                </div>
              ))
            )}
          </div>
        </div>

        <div className="glass-card rounded-3xl p-6">
          <h3 className="text-xl">Users</h3>
          <p className="text-xs text-slate-200/60">
            Promote / demote admin role.
          </p>
          <div className="mt-4 space-y-2">
            {users.length === 0 ? (
              <div className="text-sm text-slate-200/70">No users.</div>
            ) : (
              users.map((u) => (
                <div
                  key={u.id}
                  className="flex items-center justify-between rounded-xl border border-white/10 bg-slate-900/60 px-4 py-3"
                >
                  <div>
                    <div className="font-medium">{u.username}</div>
                    <div className="text-xs text-slate-200/60">
                      {u.is_admin ? "admin" : "user"}
                    </div>
                  </div>
                  <button
                    onClick={() => onToggleAdmin(u.username, !u.is_admin)}
                    disabled={
                      u.username === me.username && u.is_admin /* self-demote */
                    }
                    className="rounded-full border border-white/20 px-3 py-1 text-xs hover:border-sky-300/50 disabled:opacity-40"
                  >
                    {u.is_admin ? "Demote" : "Promote"}
                  </button>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="glass-card rounded-3xl p-6 lg:col-span-2">
          <h3 className="text-xl">Scraper monitor</h3>
          <pre className="mt-4 overflow-x-auto rounded-xl border border-white/10 bg-slate-950/80 p-4 text-xs text-slate-200/80">
            {monitor ? JSON.stringify(monitor, null, 2) : "Loading..."}
          </pre>
        </div>
      </div>
    </section>
  );
}

function Toggle({ on, onChange }) {
  return (
    <button
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition ${
        on ? "bg-emerald-400/80" : "bg-slate-600/80"
      }`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition ${
          on ? "translate-x-6" : "translate-x-1"
        }`}
      />
    </button>
  );
}

// ---------------------------------------------------------------------------
// Banner & login
// ---------------------------------------------------------------------------

function Banner({ kind = "info", children, className = "" }) {
  const palette = {
    info: "border-sky-300/40 bg-sky-400/10 text-sky-100",
    warn: "border-amber-300/40 bg-amber-400/10 text-amber-100",
    error: "border-rose-300/40 bg-rose-400/10 text-rose-100",
  }[kind];
  return (
    <div
      className={`rounded-2xl border px-4 py-3 text-sm ${palette} ${className}`}
    >
      {children}
    </div>
  );
}

function LoginScreen({ onLogin }) {
  const [form, setForm] = useState({ username: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleLogin(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const resp = await login(form.username, form.password);
      onLogin(resp.access_token);
    } catch (err) {
      setError(
        err.status === 401
          ? "Invalid username or password."
          : "Login failed. Is the backend reachable?",
      );
      setBusy(false);
    }
  }

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
              <span className="badge rounded-full px-4 py-1">Lambda ready</span>
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
                autoFocus
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
              className="w-full rounded-xl bg-gradient-to-r from-sky-400 via-cyan-300 to-blue-300 px-4 py-3 font-semibold text-slate-900 transition hover:brightness-110 disabled:opacity-50"
              disabled={busy}
            >
              {busy ? "Signing in..." : "Enter the Vault"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
