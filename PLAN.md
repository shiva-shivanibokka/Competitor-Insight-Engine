# Fix Plan — Competitor-Insight-Engine

Generated from repo-bug-audit on 2026-07-08. 8 tasks (5 fixes + 3 tests), ordered by severity. Tests for a bug are placed immediately before their fix (write test → watch it fail → fix).

---

## Task 1: Close the SSRF redirect bypass

- **File:** `backend/security.py` (new helper), `backend/scraper.py` (use it)
- **Category:** Security (Pass 8)
- **Severity:** Critical
- **Finding:** `scrape_page` calls `requests.get(url, …)` with the default `allow_redirects=True`. `assert_public_url` only validated the original host, so a redirect to `169.254.169.254` / internal IPs is followed unchecked.
- **Why it matters:** SSRF pivot to cloud metadata / internal services from an attacker-controlled homepage or competitor URL.
- **Proposed change:** Add a redirect-validating fetch to `security.py` and route `scrape_page` through it.
  ```python
  # security.py — add:
  import requests

  def fetch_validated(url: str, headers: dict, timeout, max_redirects: int = 5):
      """GET that re-runs the SSRF guard on every redirect hop before following it."""
      for _ in range(max_redirects + 1):
          assert_public_url(url)                       # guard EACH hop
          resp = requests.get(url, headers=headers, timeout=timeout,
                              allow_redirects=False)
          if resp.is_redirect and "location" in resp.headers:
              url = requests.compat.urljoin(url, resp.headers["location"])
              continue
          return resp
      raise BlockedURLError(f"Too many redirects fetching {url!r}")
  ```
  ```python
  # scraper.py — replace the requests.get block in scrape_page:
  from security import assert_public_url, BlockedURLError, fetch_validated
  ...
  try:
      response = fetch_validated(url, headers=HEADERS, timeout=(5, 10))
      response.raise_for_status()
  except BlockedURLError as e:
      print(f"  [scraper] Blocked '{url}': {e}")
      return ""
  except Exception as e:
      print(f"  [scraper] Could not fetch {url}: {e}")
      return ""
  ```
  Also set `allow_redirects=False` on the HEAD checks in `searcher.validate_url` and `report._check_url_reachable` (a 3xx there should not count as "reachable"; treat `< 400 and not is_redirect`), or drop those pre-checks since `scrape_page` now guards fully.
- **Verification:** `python -m pytest backend/tests/test_backend.py::test_ssrf_redirect_blocked -q` (Task added in the pre-task below), plus `python backend/security.py` self-check still passes.
- **Depends on:** none.

## Task 1a (test, before Task 1): redirect-SSRF regression test

- **File:** `backend/tests/test_backend.py`
- **Category:** Test coverage (Pass 13)
- **Proposed change:** Add a test that monkeypatches `requests.get` to return a fake `302 → http://169.254.169.254/` and asserts `fetch_validated` raises `BlockedURLError`. Watch it fail against current code (no `fetch_validated` yet), then implement Task 1.
- **Verification:** test fails before Task 1, passes after.

## Task 2: Fix blocklist to match on host boundary, not substring

- **File:** `backend/blocklist.py:42`
- **Category:** Correctness (Pass 3)
- **Severity:** Major
- **Finding:** `any(domain in url_lower …)` — `"x.com"` matches `"netflix.com"`; confirmed `is_blocked("https://www.netflix.com") == True`.
- **Why it matters:** Legitimate competitors silently dropped from the report.
- **Proposed change:**
  ```python
  from urllib.parse import urlparse

  def is_blocked(url: str) -> bool:
      """True if the URL's host is (or is a subdomain of) a blocked domain."""
      host = (urlparse(url).hostname or url).lower()
      return any(host == d or host.endswith("." + d) for d in BLOCKED_DOMAINS)
  ```
- **Verification:** `python -m pytest backend/tests/test_backend.py -k blocklist -q` — existing assertions still pass and the new `not is_blocked("https://www.netflix.com")` passes (Task 2a).
- **Depends on:** none.

## Task 2a (test, before Task 2): blocklist false-positive test

- **File:** `backend/tests/test_backend.py::test_blocklist`
- **Proposed change:** Add `assert not is_blocked("https://www.netflix.com")` and `assert not is_blocked("https://fox.com")`. Fails now, passes after Task 2.

## Task 3: Guard against non-dict LLM competitor entries

- **File:** `backend/analyzer.py:156`
- **Category:** Silent failure / correctness (Pass 2)
- **Severity:** Major
- **Finding:** `c.get("name", …)` raises `AttributeError` when the model returns a JSON array of strings; uncaught → 500.
- **Why it matters:** A realistic malformed LLM response crashes the request instead of degrading to the "no competitors identified" path.
- **Proposed change:**
  ```python
  for c in competitors:
      if not isinstance(c, dict):        # LLM sometimes returns bare strings
          print(f"  [!] Skipped non-object entry: {c!r}")
          continue
      name = c.get("name", "").strip()
      ...
  ```
- **Verification:** `python -m pytest backend/tests/test_backend.py::test_extract_competitors_ignores_non_dict -q` (Task 3a).
- **Depends on:** none.

## Task 3a (test, before Task 3): non-dict LLM output test

- **File:** `backend/tests/test_backend.py`
- **Proposed change:** monkeypatch `analyzer.llm_call` to return `'["Adyen", "Square"]'`; assert `extract_competitors_from_search(...) == []` (no crash). Fails now (AttributeError), passes after Task 3.

## Task 4: Make the empty-scrape guard reachable

- **File:** `backend/scraper.py:62`
- **Category:** Correctness / dead code (Pass 3/4)
- **Severity:** Minor
- **Finding:** `scrape_key_pages` always prepends a non-empty header, so `report.py:90`'s `not main_scraped.strip()` never fires.
- **Why it matters:** Fully-unscrapable sites waste several paid LLM calls instead of failing fast with the intended message.
- **Proposed change:**
  ```python
  print(f"  [scraper] Scraping: {base_url}")
  combined = ""
  homepage_text = scrape_page(base_url)
  if homepage_text:
      combined += f"=== Homepage: {base_url} ===\n{homepage_text}\n\n"
  # ...existing sub-page loop unchanged (already appends only when text)...
  return combined[:MAX_CHARS_TOTAL]
  ```
  Now an all-empty scrape returns `""` and the `report.py` guard fires correctly. No change needed in `report.py`.
- **Verification:** `python -c "import scraper; scraper.scrape_page=lambda u:''; assert scraper.scrape_key_pages('https://x.com')==''"`.
- **Depends on:** none.

## Task 5: Prevent Cloud Run timeout at high `max_competitors`

- **File:** `backend/report.py:152`
- **Category:** Performance / production-readiness (Pass 10/12)
- **Severity:** Major
- **Finding:** Up to 20 competitors scraped sequentially (≤11 pages each, 10s timeouts) + per-competitor LLM calls → likely exceeds the 300s request limit.
- **Why it matters:** The UI offers 20 but the backend can't reliably deliver it within the platform timeout; user waits minutes for a 5xx.
- **Proposed change (recommended — parallelize the scrape/profile loop):**
  ```python
  from concurrent.futures import ThreadPoolExecutor

  def _profile_one(comp):
      name, url = comp["name"], comp["url"]
      if not validate_url(url):
          return ("skip", name)
      scraped = scrape_key_pages(url)
      if not scraped.strip():
          return ("skip", name)
      profile = extract_competitor_profile(name, scraped, model=fast_model, api_keys=api_keys)
      return ("ok", {"name": name, "url": url, "profile": profile})

  with ThreadPoolExecutor(max_workers=5) as pool:
      results = list(pool.map(_profile_one, competitors))
  competitor_profiles = [r[1] for r in results if r[0] == "ok"]
  skipped = [r[1] for r in results if r[0] == "skip"]
  ```
  (Loses the ordered progress `print`s; acceptable, or log per-future on completion.)
- **Alternative (lower effort):** keep it sequential but cap `max_competitors` at 8 in `app.py` and the frontend dropdown, and/or trim `candidate_paths` to 3–4 highest-value pages.
- **Decision needed from you:** parallelize (keeps 20) vs. cap back to 8. I'd recommend parallelize with `max_workers=5` + trimming candidate paths to `/about`, `/product`, `/pricing`.
- **Verification:** time a real 8–10 competitor run end-to-end under 300s; confirm report still generates.
- **Depends on:** none (but interacts with the `max_competitors=20` you just shipped).
