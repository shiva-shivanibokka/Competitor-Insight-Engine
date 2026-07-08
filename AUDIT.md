# Repo Audit Report — Competitor-Insight-Engine

**Date:** 2026-07-08
**Stack detected:** Python 3.11 / FastAPI backend (`backend/`) + Next.js 14 / TypeScript frontend (`frontend/`)
**Scope:** All tracked source in `backend/` and `frontend/app/`. Excluded: `competitor_intel.ipynb` (notebook, not on the serving path), `node_modules`, `.next`.

## Summary

- Total findings: 5 bugs + 5 notes
- Auto-fixed (trivial-safe): 0 (no dead code / unused imports found — nothing to safely remove without a behavior decision)
- Needs review (see PLAN.md): 5
- Critical: 1 | Major: 3 | Minor: 1 | Notes: 5

## Production-readiness scorecard

| Category | Status | Notes |
|---|---|---|
| Correctness | ❌ | Blocklist substring match drops legit competitors; dead empty-scrape guard |
| Silent failures | ⚠️ | Broad `except` blocks are OK, but one JSON path crashes instead of degrading |
| Security | ❌ | SSRF guard is bypassable via HTTP redirect |
| Concurrency | ✅ | Sync pipeline in FastAPI threadpool — no shared-state races |
| Performance | ❌ | `max_competitors=20` runs ~220 sequential fetches → Cloud Run 300s timeout risk |
| Architecture | ✅ | Clean module boundaries, single blocklist source of truth |
| Production-readiness | ⚠️ | `print()` instead of structured logging; permissive default CORS (acknowledged) |
| Test coverage | ⚠️ | Good coverage of pure helpers; the 5 bugs below have no tests |

## Auto-fixed (trivial-safe)

None. The codebase has no unused imports, unreachable blocks, or exact-duplicate logic that could be removed without a behavior judgment. All five real findings change behavior and are in PLAN.md.

## Findings requiring review

### Security (Pass 8)

**F1 — SSRF guard bypassable via HTTP redirect** · `backend/scraper.py:35`, `backend/searcher.py:26`, `backend/report.py:22`
- **Severity:** Critical
- **What's wrong:** `assert_public_url()` / `is_public_url()` resolve and validate only the *initial* hostname. The subsequent `requests.get`/`requests.head` calls use the default `allow_redirects=True`, so a target that responds `302 Location: http://169.254.169.254/…` (or `http://10.0.0.5/`) is followed **without re-validation**. The company URL and every LLM-supplied competitor URL are attacker-influenced.
- **Why it matters in production:** The whole `security.py` module exists to stop this service being an SSRF pivot. A malicious homepage can redirect the scraper at GCP metadata (`169.254.169.254`) or internal Cloud Run networking. Confirmed by inspection: `requests` follows redirects by default and the guard never runs on redirect hops.
- **Suggested fix:** Fetch with `allow_redirects=False` and follow hops manually, calling `assert_public_url()` on each `Location`. See PLAN Task 1.

### Correctness (Passes 1, 3)

**F2 — Blocklist uses naive substring match; silently drops legitimate competitors** · `backend/blocklist.py:44`
- **Severity:** Major
- **What's wrong:** `any(domain in url_lower for domain in BLOCKED_DOMAINS)`. Short entries match inside unrelated domains. **Confirmed:** `is_blocked("https://www.netflix.com")` returns `True` because `"x.com"` is a substring of `"netflix.com"`. Any domain ending in `x.com`, and `premium…`/`medium.com`-style collisions, are affected.
- **Why it matters in production:** A real competitor (e.g. Netflix in a streaming analysis) is silently removed from the report with no error — the user sees a quietly incomplete result and can't tell why.
- **Suggested fix:** Match on the parsed host with a boundary check (`host == domain or host.endswith("." + domain)`). See PLAN Task 2.

**F3 — Non-dict LLM output crashes the request** · `backend/analyzer.py:156`
- **Severity:** Major
- **What's wrong:** After `json.loads` succeeds and `isinstance(list)` passes, the loop does `c.get("name", …)` on each element. If the model returns a JSON array of **strings** (`["Adyen","Square"]`) instead of objects, `c.get` raises `AttributeError`, which is outside the try/except. **Confirmed:** crashes with `AttributeError: 'str' object has no attribute 'get'`.
- **Why it matters in production:** LLM output is untrusted. This shape is a realistic model mistake, and it turns the graceful "could not identify competitors" path into an uncaught 500. Defeats the purpose of the parse guard directly above it.
- **Suggested fix:** `if not isinstance(c, dict): continue` at the top of the loop. See PLAN Task 3.

**F4 — Dead "could not extract any text" guard** · `backend/report.py:90` + `backend/scraper.py:63`
- **Severity:** Minor
- **What's wrong:** `scrape_key_pages` always prepends `=== Homepage: {url} ===`, so it never returns an empty/whitespace-only string even when every page yields zero text. **Confirmed:** with all scrapes empty it returns `'=== Homepage: https://example.com ===\n\n\n'`, so `not main_scraped.strip()` in `report.py` is always `False`. The fail-fast guard is unreachable.
- **Why it matters in production:** A bot-walled or JS-only site proceeds through several paid LLM calls producing an all-"unknown" profile instead of failing fast with the intended clear message.
- **Suggested fix:** Only append the homepage header when there's text, and return `""` when nothing was scraped. See PLAN Task 4.

### Performance (Pass 10)

**F5 — `max_competitors=20` × sequential multi-page scrape risks Cloud Run timeout** · `backend/app.py:51`, `backend/report.py:152`
- **Severity:** Major
- **What's wrong:** The cap was just raised to 20. Each competitor is scraped sequentially, and `scrape_key_pages` fetches up to 11 pages (homepage + 10 candidate paths) each with a 10s read timeout, plus one LLM call per competitor. Worst case ≈ 20 × 11 = 220 sequential HTTP requests + ~23 LLM calls in a single request.
- **Why it matters in production:** Cloud Run caps the request at 300s. At 20 competitors this will frequently exceed it, returning a 5xx after the user waited minutes. The dropdown offers a value the backend can't reliably serve.
- **Suggested fix:** Parallelize the per-competitor scrape/profile loop with a bounded thread pool (and/or trim candidate paths). See PLAN Task 5.

## Notes (not bugs — maintainability/observations)

- **N1** `backend/app.py` configures `logging` but the entire pipeline uses `print()`. Inconsistent; fine on Cloud Run stdout, but no levels/structure.
- **N2** Default `ALLOWED_ORIGINS="*"` (`app.py:32`) lets any origin call the backend. Acknowledged in-code as safe for a BYOK demo (no cookies, user supplies own keys) — left as a deliberate tradeoff.
- **N3** `frontend/app/page.tsx` `download()` creates an object URL via `URL.createObjectURL` and never calls `revokeObjectURL` — tiny memory leak per download.
- **N4** `_is_valid_competitor_url` (`analyzer.py:113`) uses the same substring approach to exclude the company itself; short names (e.g. "HP", "Ada") can over-filter. Lower impact than F2 but same root cause.
- **N5** `validate_url` (searcher.py) and `_check_url_reachable` (report.py) are near-duplicate reachability checks with slightly different timeouts — candidate to consolidate.

## Clean areas

- **`security.py`** — logic itself is correct and well-tested (the bypass is at the *call sites*, not in the guard).
- **`config.py`** — provider/model registry validates default model names at import; no issues.
- **`blocklist.py`** — dedup-to-single-source refactor is sound; only the match algorithm (F2) is wrong.
- **Concurrency** — no shared mutable state across requests; BYOK keys are per-request locals.
- **Frontend** — `===` throughout, all fetches have `.catch`, React state updated immutably. Only N3 noted.
