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

type StoredKeys = { llm: Record<string, string>; tavily: string };

function loadKeys(): StoredKeys {
  if (typeof window === "undefined") return { llm: {}, tavily: "" };
  try {
    return { llm: {}, tavily: "", ...JSON.parse(sessionStorage.getItem(KEYS_STORAGE) || "{}") };
  } catch {
    return { llm: {}, tavily: "" };
  }
}

export default function Home() {
  const [providers, setProviders] = useState<Provider[]>([]);
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

  // Load provider catalog + saved keys on mount.
  useEffect(() => {
    const saved = loadKeys();
    setLlmKeys(saved.llm);
    setTavilyKey(saved.tavily);

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
        setError(`Could not reach the backend at ${BACKEND_URL}. Is NEXT_PUBLIC_BACKEND_URL set?`)
      );
  }, []);

  // Persist keys to sessionStorage whenever they change.
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
      setError("Enter both your provider key and your Tavily key.");
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
      if (!res.ok) throw new Error(data.detail || "Request failed.");
      setReport(data.report);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
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
    <main className="wrap">
      <header className="hero">
        <h1>Competitor Intelligence Engine</h1>
        <p>
          One company URL → a full competitive-intelligence report in ~90 seconds. Live web search,
          multi-step LLM pipeline, side-by-side matrix, strategic recommendations.
        </p>
      </header>

      <form className="card" onSubmit={onSubmit}>
        <div className="row">
          <label>
            Company URL
            <input value={companyUrl} onChange={(e) => setCompanyUrl(e.target.value)} required />
          </label>
          <label>
            Company name
            <input value={companyName} onChange={(e) => setCompanyName(e.target.value)} required />
          </label>
        </div>

        <div className="row">
          <label>
            Provider
            <select value={providerId} onChange={(e) => onProviderChange(e.target.value)}>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label} ({p.tier})
                </option>
              ))}
            </select>
          </label>
          <label>
            Model
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              {provider?.models.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name} — {m.tier}
                </option>
              ))}
            </select>
          </label>
          <label className="narrow">
            Competitors
            <input
              type="number"
              min={1}
              max={8}
              value={maxCompetitors}
              onChange={(e) => setMaxCompetitors(Number(e.target.value))}
            />
          </label>
        </div>

        <div className="row">
          <label>
            {provider?.label || "Provider"} API key
            <input
              type="password"
              placeholder="Your key — stays in this browser tab"
              value={llmKey}
              onChange={(e) => setLlmKeys({ ...llmKeys, [providerId]: e.target.value })}
              autoComplete="off"
            />
            {provider?.key_url && (
              <a className="hint" href={provider.key_url} target="_blank" rel="noreferrer">
                Get a {provider.label} key ↗
              </a>
            )}
          </label>
          <label>
            Tavily API key
            <input
              type="password"
              placeholder="For live competitor search"
              value={tavilyKey}
              onChange={(e) => setTavilyKey(e.target.value)}
              autoComplete="off"
            />
            <a className="hint" href="https://app.tavily.com" target="_blank" rel="noreferrer">
              Get a free Tavily key ↗
            </a>
          </label>
        </div>

        <p className="privacy">
          🔒 Your keys are stored only in this browser tab (sessionStorage) and sent directly to the
          analysis backend over HTTPS. They are never stored, logged, or sent to this website&apos;s
          server.
        </p>

        <button type="submit" disabled={loading}>
          {loading ? "Analyzing… (up to ~90s)" : "Generate report"}
        </button>
      </form>

      {error && <div className="error">{error}</div>}

      {report && (
        <section className="card report">
          <div className="report-actions">
            <button type="button" onClick={() => navigator.clipboard.writeText(report)}>
              Copy
            </button>
            <button type="button" onClick={download}>
              Download .md
            </button>
          </div>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{report}</ReactMarkdown>
        </section>
      )}

      <footer>
        <a href="https://github.com/" target="_blank" rel="noreferrer">
          Source on GitHub
        </a>
      </footer>
    </main>
  );
}
