"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, "") || "http://localhost:7860";

type Model = { name: string; tier: string };
type Provider = {
  id: string;
  label: string;
  tier: string;
  key_url: string | null;
  models: Model[];
};

// BYOK: keys live ONLY in this browser tab (sessionStorage) and are sent
// directly to the backend over HTTPS. They never touch the Vercel server.
const KEYS_STORAGE = "cie_keys_v1";

function loadKeys(): { llm: Record<string, string>; tavily: string } {
  if (typeof window === "undefined") return { llm: {}, tavily: "" };
  try {
    return { llm: {}, tavily: "", ...JSON.parse(sessionStorage.getItem(KEYS_STORAGE) || "{}") };
  } catch {
    return { llm: {}, tavily: "" };
  }
}

export default function Home() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [online, setOnline] = useState<boolean | null>(null);
  const [providerId, setProviderId] = useState("");
  const [model, setModel] = useState("");
  const [llmKeys, setLlmKeys] = useState<Record<string, string>>({});
  const [tavilyKey, setTavilyKey] = useState("");

  const [companyUrl, setCompanyUrl] = useState("https://stripe.com");
  const [companyName, setCompanyName] = useState("Stripe");
  const [maxCompetitors, setMaxCompetitors] = useState(4);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState("");

  useEffect(() => {
    const saved = loadKeys();
    setLlmKeys(saved.llm);
    setTavilyKey(saved.tavily);

    fetch(`${BACKEND_URL}/health`)
      .then((r) => setOnline(r.ok))
      .catch(() => setOnline(false));

    fetch(`${BACKEND_URL}/providers`)
      .then((r) => r.json())
      .then((d) => {
        const provs: Provider[] = d.providers;
        setProviders(provs);
        if (provs.length) {
          setProviderId(provs[0].id);
          setModel(provs[0].models[0].name);
        }
      })
      .catch(() =>
        setError(`Can't reach the engine at ${BACKEND_URL}. Check NEXT_PUBLIC_BACKEND_URL.`)
      );
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    sessionStorage.setItem(KEYS_STORAGE, JSON.stringify({ llm: llmKeys, tavily: tavilyKey }));
  }, [llmKeys, tavilyKey]);

  const provider = providers.find((p) => p.id === providerId);
  const llmKey = llmKeys[providerId] || "";

  function onProviderChange(id: string) {
    setProviderId(id);
    const p = providers.find((x) => x.id === id);
    if (p) setModel(p.models[0].name);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setReport("");
    if (!llmKey || !tavilyKey) {
      setError("Enter both your provider key and your Tavily key to run the analysis.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${BACKEND_URL}/report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company_url: companyUrl,
          company_name: companyName,
          provider: providerId,
          model,
          llm_key: llmKey,
          tavily_key: tavilyKey,
          max_competitors: maxCompetitors,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "The analysis failed. Try again.");
      setReport(data.report);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Try again.");
    } finally {
      setLoading(false);
    }
  }

  function download() {
    const blob = new Blob([report], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${companyName.replace(/\W+/g, "_").toLowerCase()}_competitor_report.md`;
    a.click();
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="wordmark">
          <span className="mark" aria-hidden>
            ◆
          </span>
          <span className="mark-name">Competitor Intelligence Engine</span>
        </div>
        <div className="status" data-state={online === null ? "wait" : online ? "up" : "down"}>
          <span className="led" aria-hidden />
          {online === null ? "Connecting" : online ? "Engine online" : "Engine offline"}
        </div>
      </header>

      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">Competitive reconnaissance</p>
          <h1>Map the competitive terrain of any company.</h1>
          <p className="lede">
            Enter one URL. The engine scrapes the market, finds real competitors in real time, and
            returns a full intelligence report — profiles, a side-by-side matrix, and strategic
            moves. Bring your own model key; it never leaves your browser.
          </p>
        </div>
        <div className="radar" data-scanning={loading} aria-hidden>
          <svg className="radar-grid" viewBox="0 0 200 200">
            <circle cx="100" cy="100" r="94" />
            <circle cx="100" cy="100" r="64" />
            <circle cx="100" cy="100" r="34" />
            <line x1="100" y1="6" x2="100" y2="194" />
            <line x1="6" y1="100" x2="194" y2="100" />
            <circle className="blip b1" cx="140" cy="72" r="3.5" />
            <circle className="blip b2" cx="70" cy="132" r="3.5" />
            <circle className="blip b3" cx="120" cy="140" r="3.5" />
          </svg>
          <div className="radar-sweep" />
        </div>
      </section>

      <main className="console">
        <form className="inputs" onSubmit={onSubmit}>
          <section className="panel target">
            <span className="panel-tab">Target</span>
            <div className="field-row">
              <label>
                <span className="fl">Company name</span>
                <input
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  required
                />
              </label>
              <label>
                <span className="fl">Company URL</span>
                <input
                  value={companyUrl}
                  onChange={(e) => setCompanyUrl(e.target.value)}
                  required
                />
              </label>
              <label className="narrow">
                <span className="fl">Competitors</span>
                <select
                  value={maxCompetitors}
                  onChange={(e) => setMaxCompetitors(Number(e.target.value))}
                >
                  {Array.from({ length: 20 }, (_, i) => i + 1).map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </section>

          <section className="panel source">
            <span className="panel-tab">Model &amp; access</span>
            <div className="field-row">
              <label>
                <span className="fl">Provider</span>
                <select value={providerId} onChange={(e) => onProviderChange(e.target.value)}>
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span className="fl">Model</span>
                <select value={model} onChange={(e) => setModel(e.target.value)}>
                  {provider?.models.map((m) => (
                    <option key={m.name} value={m.name}>
                      {m.name} · {m.tier}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="field-row">
              <label>
                <span className="fl">
                  {provider?.label || "Provider"} key
                  {provider?.key_url && (
                    <a className="get" href={provider.key_url} target="_blank" rel="noreferrer">
                      get key ↗
                    </a>
                  )}
                </span>
                <input
                  type="password"
                  placeholder="Stays in this browser tab"
                  value={llmKey}
                  onChange={(e) => setLlmKeys({ ...llmKeys, [providerId]: e.target.value })}
                  autoComplete="off"
                />
              </label>
              <label>
                <span className="fl">
                  Tavily key
                  <a className="get" href="https://app.tavily.com" target="_blank" rel="noreferrer">
                    get key ↗
                  </a>
                </span>
                <input
                  type="password"
                  placeholder="For live competitor search"
                  value={tavilyKey}
                  onChange={(e) => setTavilyKey(e.target.value)}
                  autoComplete="off"
                />
              </label>
            </div>

            <p className="privacy">
              <span className="lock" aria-hidden>
                ▚
              </span>
              Keys stay in this browser tab and go straight to the engine over HTTPS. Never stored,
              logged, or sent to this site&apos;s server.
            </p>
          </section>

          <button className="run" type="submit" disabled={loading}>
            {loading ? "Scanning the market…" : "Generate report"}
          </button>
        </form>

        <section className="panel output result">
          {error ? (
            <div className="alert">
              <span className="panel-tab err">Signal lost</span>
              <p>{error}</p>
            </div>
          ) : report ? (
            <>
              <span className="panel-tab">Field briefing</span>
              <div className="out-actions">
                <button type="button" onClick={() => navigator.clipboard.writeText(report)}>
                  Copy
                </button>
                <button type="button" onClick={download}>
                  Download .md
                </button>
              </div>
              <div className="briefing">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{report}</ReactMarkdown>
              </div>
            </>
          ) : loading ? (
            <div className="await">
              <span className="panel-tab">Analyzing</span>
              <p className="await-line">Scraping target, searching the market, profiling rivals…</p>
              <p className="await-sub">This takes up to ~90 seconds. Keep the tab open.</p>
            </div>
          ) : (
            <div className="await">
              <span className="panel-tab">Standing by</span>
              <p className="await-line">Awaiting parameters.</p>
              <p className="await-sub">
                Set a target and your keys, then generate a report. The briefing lands here.
              </p>
            </div>
          )}
        </section>
      </main>

      <footer className="foot">
        <span>Competitor Intelligence Engine</span>
        <a href="https://github.com/shiva-shivanibokka/Competitor-Insight-Engine" target="_blank" rel="noreferrer">
          Source ↗
        </a>
      </footer>
    </div>
  );
}
