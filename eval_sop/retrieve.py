"""Step 1-3 of the product pipeline, cached per company.

  step 1  scrape the company homepage + /about /product /pricing  (product's scraper)
  step 2  extract the company profile with the LLM, pull INDUSTRY  (product's prompt)
  step 3  web search for "top direct competitors of {name} in {industry}"

Step 3 SUBSTITUTION: the product uses Tavily (search_depth="advanced",
max_results=10, include_answer=True). No Tavily key exists on this machine, so
this uses the free `ddgs` metasearch package (backend=auto) with the identical query
string, then fetches the text of the top non-blocklisted result pages with the
product's own scrape_page() (capped to 600 chars each, at most 6 pages, 6000 chars in total) to approximate Tavily's
"advanced" page content. Results from sec.gov are dropped so the 10-K used as
ground truth cannot be retrieved verbatim. Output format mirrors
searcher.get_competitor_search_content ("SOURCE: title\\ncontent" blocks).

    python eval_sop/retrieve.py
"""

import json
import time

from common import MODEL, ROOT, install_shim, load_companies, shim

import analyzer  # noqa: E402
from blocklist import is_blocked  # noqa: E402
from report import _extract_field  # noqa: E402
from scraper import scrape_key_pages, scrape_page  # noqa: E402

OUT = ROOT / "raw" / "retrieval"
OUT.mkdir(parents=True, exist_ok=True)
PER_PAGE = 600
MAX_TOTAL = 6000  # cap on the combined search text (~1.5k tokens) to fit the free-tier token budget
EXCLUDE = ("sec.gov",)


def search(query: str) -> list[dict]:
    from ddgs import DDGS

    for attempt in range(4):
        try:
            return DDGS().text(query, max_results=10)  # backend="auto" (ddgs metasearch)
        except Exception as e:  # noqa: BLE001
            print(f"  [ddgs] retry {attempt}: {e}")
            time.sleep(15 * (attempt + 1))
    return []


def build(c: dict) -> dict:
    path = OUT / f"{c['id']}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    print(f"== {c['name']}")
    scraped = scrape_key_pages(c["homepage"])
    shim.seed, shim.tag = 0, f"profile:{c['id']}"
    # The product aborts here when the homepage yields no text (report.py raises
    # ValueError). Record that, but keep going with the product's own fallback
    # industry so discovery can still be scored conditional on proceeding.
    profile = analyzer.extract_company_profile(scraped, model=MODEL) if scraped.strip() else ""
    industry = _extract_field(profile, "INDUSTRY") if profile else "technology"
    query = f"top direct competitors of {c['name']} in {industry}"
    hits = search(query)
    time.sleep(3)  # be polite to the free search backend
    parts, sources = [], []
    for h in hits:
        url = h.get("href", "")
        if is_blocked(url) or any(x in url for x in EXCLUDE):
            sources.append({"url": url, "used": False})
            continue
        body = h.get("body", "")
        page = scrape_page(url)[:PER_PAGE] if len([s for s in sources if s["used"]]) < 6 else ""
        parts.append(f"SOURCE: {h.get('title', '')}\n{body}\n{page}".strip())
        sources.append({"url": url, "used": True, "page_chars": len(page)})
    rec = {
        "id": c["id"],
        "homepage": c["homepage"],
        "scraped_chars": len(scraped.strip()),
        "product_would_abort": not scraped.strip(),
        "scraped": scraped,
        "profile": profile,
        "industry": industry,
        "query": query,
        "search_backend": "ddgs 9.13.1 backend=auto — substitute for Tavily",
        "sources": sources,
        "search_content": "\n\n---\n\n".join(parts)[:MAX_TOTAL],
        "retrieved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    path.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    return rec


if __name__ == "__main__":
    install_shim()  # the product's analyzer.llm_call now goes through the eval transport
    for c in load_companies():
        r = build(c)
        print(f"  {c['id']}: scraped={r['scraped_chars']} search={len(r['search_content'])} "
              f"industry={r['industry'][:50]!r}", flush=True)
