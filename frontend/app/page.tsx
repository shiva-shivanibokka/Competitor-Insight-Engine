"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Same-origin by default: the API is a service in this same Vercel project,
// reachable at /api/*. NEXT_PUBLIC_BACKEND_URL only exists for running the
// backend separately in local dev (uvicorn on :7860).
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, "") ?? "";
const API = `${BACKEND_URL}/api`;

type Model = { name: string; tier: string };
type Recording = {
  recorded_at: string;
  company: string;
  company_url: string;
  max_competitors: number;
  competitors_profiled?: number;
  fast_model: string;
  smart_model: string;
  duration_seconds: number;
  frames: { t: number; line: string }[];
  report: string;
};
type RunSummary = {
  slug: string;
  company: string;
  company_url: string;
  recorded_at: string;
  max_competitors: number;
  competitors_profiled?: number;
  duration_seconds: number;
  smart_model: string;
  report_chars: number;
};
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
  const [liveModels, setLiveModels] = useState<Record<string, string[]>>({});
  const [recording, setRecording] = useState<Recording | null>(null);
  const [replaying, setReplaying] = useState(false);
  const [replayLines, setReplayLines] = useState<string[]>([]);
  const logRef = useRef<HTMLPreElement | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [playing, setPlaying] = useState("");
  // Recorded runs are the default view: they are the half a visitor can use
  // without going and fetching two API keys first.
  const [tab, setTab] = useState<"replay" | "live">("replay");

  const [companyUrl, setCompanyUrl] = useState("https://stripe.com");
  const [companyName, setCompanyName] = useState("Stripe");
  const [maxCompetitors, setMaxCompetitors] = useState(4);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState("");

  const provider = providers.find((p) => p.id === providerId);
  const llmKey = llmKeys[providerId] || "";
  const live = liveModels[providerId];
  const modelNames = live ?? provider?.models.map((m) => m.name) ?? [];

  useEffect(() => {
    const saved = loadKeys();
    setLlmKeys(saved.llm);
    setTavilyKey(saved.tavily);

    fetch(`${API}/health`)
      .then((r) => setOnline(r.ok))
      .catch(() => setOnline(false));

    fetch(`${API}/providers`)
      .then((r) => r.json())
      .then((d) => {
        const provs: Provider[] = d.providers;
        setProviders(provs);
        if (provs.length) {
          setProviderId(provs[0].id);
          setModel(provs[0].models[0].name);
        }
      })
      .catch(() => setError("Can't reach the engine. It may still be starting — reload in a moment."));

    // The index is generated from whatever recordings are on disk, so an empty
    // or missing one means there are none and the tab says so.
    fetch("/demo/index.json")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setRuns(d?.runs ?? []))
      .catch(() => setRuns([]));
  }, []);

  // Replace the built-in catalogue with the provider's live list as soon as
  // there's a key to ask with. A hardcoded list is how a retired model ended
  // up in this dropdown, 404-ing for anyone who picked it.
  useEffect(() => {
    if (!providerId || !llmKey) return;
    const timer = setTimeout(() => {
      const controller = new AbortController();
      fetch(`${API}/models`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: providerId, llm_key: llmKey }),
        signal: controller.signal,
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (!d?.models?.length) return;
          setLiveModels((m) => ({ ...m, [providerId]: d.models }));
          // If the selected model isn't in the provider's real list, move to
          // one that is. A <select> whose value matches no option falls back
          // to showing the first one, while state keeps the old name — so the
          // dropdown would show one model and the run would use another.
          setModel((current) => (d.models.includes(current) ? current : d.models[0]));
        })
        .catch(() => {
          /* an unusable key just leaves the built-in list in place */
        });
    }, 700); // debounce: the key arrives one keystroke at a time
    return () => clearTimeout(timer);
  }, [providerId, llmKey]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    sessionStorage.setItem(KEYS_STORAGE, JSON.stringify({ llm: llmKeys, tavily: tavilyKey }));
  }, [llmKeys, tavilyKey]);

  // Follow the log as it streams. Without this the pane holds the first few
  // lines while the run scrolls on underneath, so the replay looks stuck.
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [replayLines]);

  function onProviderChange(id: string) {
    setProviderId(id);
    const names = liveModels[id] ?? providers.find((x) => x.id === id)?.models.map((m) => m.name);
    if (names?.length) setModel(names[0]);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setReport("");
    setRecording(null);
    setReplayLines([]);
    setPlaying("");
    if (!llmKey || !tavilyKey) {
      setError("Enter both your provider key and your Tavily key to run the analysis.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API}/report`, {
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

  // A visitor with no keys would otherwise see a form and nothing else. This
  // plays back a recording of an actual run -- its real log stream at its real
  // pacing, compressed -- and then shows the report that run produced. It is
  // labelled as a replay throughout; nothing here pretends to be executing.
  async function playRecording(slug: string) {
    if (replaying) return;
    setError("");
    setReport("");
    setReplayLines([]);
    setPlaying(slug);
    let run: Recording;
    try {
      const res = await fetch(`/demo/${slug}.json`);
      if (!res.ok) throw new Error();
      run = await res.json();
    } catch {
      // No recording committed. Say so rather than showing a fabricated one.
      setError("That recording is not in this build.");
      setPlaying("");
      return;
    }
    setRecording(run);
    setReplaying(true);
    const SPEEDUP = 6; // the real run took ~70s; that is too long to sit through
    let previous = 0;
    for (const frame of run.frames) {
      // frame.t is absolute seconds from the start of the run, so wait the gap
      // to the previous frame rather than the timestamp itself.
      const gap = Math.min(((frame.t - previous) * 1000) / SPEEDUP, 900);
      previous = frame.t;
      if (gap > 0) await new Promise((r) => setTimeout(r, gap));
      setReplayLines((prev) => [...prev, frame.line]);
    }
    setReport(run.report);
    setReplaying(false);
    setPlaying("");
  }

  function download() {
    const blob = new Blob([report], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    // Name the file after what the report is about. When a recording is on
    // screen that is the recorded company, not whatever is in the form.
    const subject = recording?.company ?? companyName;
    a.download = `${subject.replace(/\W+/g, "_").toLowerCase()}_competitor_report.md`;
    a.click();
    URL.revokeObjectURL(url); // otherwise every download leaks the blob for the tab's lifetime
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
        <div className="tabs" role="tablist">
          <button
            role="tab"
            aria-selected={tab === "replay"}
            onClick={() => setTab("replay")}
            disabled={replaying}
          >
            Recorded runs <span className="tab-hint">no keys needed</span>
          </button>
          <button
            role="tab"
            aria-selected={tab === "live"}
            onClick={() => setTab("live")}
            disabled={replaying}
          >
            Run it live <span className="tab-hint">bring your own keys</span>
          </button>
        </div>

        {tab === "replay" && (
          <section className="panel choose">
            <span className="panel-tab replay">Select a run</span>
            <p className="choose-lede">
              Each of these is a recording of the pipeline actually running — its real log
              output at its real pacing, and the report that run produced. Pick one to watch.
            </p>
            {runs.length === 0 ? (
              <p className="choose-empty">
                No recordings are committed in this build.
              </p>
            ) : (
              <div className="picker">
                {runs.map((r) => (
                  <button
                    key={r.slug}
                    type="button"
                    aria-pressed={playing === r.slug}
                    disabled={replaying}
                    onClick={() => playRecording(r.slug)}
                  >
                    <span className="t">{r.company}</span>
                    <span className="s">
                      {r.competitors_profiled ?? r.max_competitors} competitors ·{" "}
                      {Math.round(r.duration_seconds)}s · {(r.report_chars / 1000).toFixed(1)}k
                      chars
                    </span>
                    <span className="u">{r.company_url.replace(/^https?:\/\//, "")}</span>
                  </button>
                ))}
              </div>
            )}
          </section>
        )}

        <form
          className="inputs"
          onSubmit={onSubmit}
          hidden={tab !== "live"}
        >
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
                  {modelNames.map((name) => (
                    <option key={name} value={name}>
                      {name} · {provider?.tier}
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

          <button className="run" type="submit" disabled={loading || replaying}>
            {loading ? "Scanning the market…" : "Generate report"}
          </button>
        </form>

        <section className="panel output result">
          {error ? (
            <div className="alert">
              <span className="panel-tab err">Signal lost</span>
              <p>{error}</p>
            </div>
          ) : replaying ? (
            <div className="await">
              <span className="panel-tab replay">Replay</span>
              <p className="replay-note">
                Recorded {recording?.recorded_at} against {recording?.company_url} —{" "}
                {recording?.competitors_profiled ?? recording?.max_competitors} of{" "}
                {recording?.max_competitors} competitors profiled, {recording?.fast_model} for
                extraction and{" "}
                {recording?.smart_model} for the report. It took{" "}
                {Math.round(recording?.duration_seconds ?? 0)}s; this plays at 6×. Nothing is
                executing now.
              </p>
              <pre className="replay-log" ref={logRef}>
                {replayLines.join("\n")}
              </pre>
            </div>
          ) : report ? (
            <>
              <span className="panel-tab">{recording ? "Recorded briefing" : "Field briefing"}</span>
              {recording && (
                <p className="replay-note">
                  This is the report from a real run recorded {recording.recorded_at} —{" "}
                  {recording.company}, {recording.competitors_profiled ?? recording.max_competitors}{" "}
                  of {recording.max_competitors} competitors profiled,{" "}
                  {Math.round(recording.duration_seconds)}s, {recording.smart_model}. Enter your own
                  keys above to run it live against any company.
                </p>
              )}
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
                {tab === "replay"
                  ? "Pick one of the recorded runs above and it will play here."
                  : "Set a target and your keys, then generate a report. The briefing lands here."}
              </p>
            </div>
          )}
        </section>
      </main>

      <footer className="foot">
        <span className="byline">Built by Shivani Bokka</span>
        <a href="https://github.com/shiva-shivanibokka/Competitor-Insight-Engine" target="_blank" rel="noreferrer">
          Source ↗
        </a>
      </footer>
    </div>
  );
}
