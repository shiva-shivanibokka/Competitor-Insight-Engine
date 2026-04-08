from scraper import scrape_key_pages
from searcher import find_competitor_urls
from analyzer import (
    extract_company_profile,
    extract_competitor_profile,
    generate_intelligence_report,
)
from config import FAST_MODEL, SMART_MODEL


def run_competitor_intelligence(
    company_url: str,
    company_name: str,
    fast_model: str = FAST_MODEL,
    smart_model: str = SMART_MODEL,
    max_competitors: int = 4,
) -> str:
    """
    Full pipeline — given a company URL and name, returns a complete
    Competitive Intelligence Report as a Markdown string.

    Steps:
        1. Scrape the main company's website
        2. LLM 1 (fast_model): Extract structured company profile
        3. Tavily: Find top competitor URLs
        4. Scrape each competitor's website
        5. LLM 2 (fast_model): Extract structured profile per competitor
        6. LLM 3 (smart_model): Generate full report with comparison + recommendations
    """

    print(f"\n{'=' * 60}")
    print(f" Competitor Intelligence Report for: {company_name}")
    print(f"{'=' * 60}\n")

    # ------------------------------------------------------------------
    # STEP 1 — Scrape the main company
    # ------------------------------------------------------------------
    print("[Step 1] Scraping main company website...")
    main_scraped = scrape_key_pages(company_url)
    if not main_scraped.strip():
        raise ValueError(
            f"Could not scrape any content from {company_url}. Check the URL."
        )

    # ------------------------------------------------------------------
    # STEP 2 — Extract main company profile (LLM 1)
    # ------------------------------------------------------------------
    print("\n[Step 2] Extracting main company profile...")
    main_profile = extract_company_profile(main_scraped, model=fast_model)
    print(f"\n  Profile extracted:\n{main_profile[:300]}...\n")

    # Pull the industry out of the profile to improve the Tavily search query
    industry = _extract_field(main_profile, "INDUSTRY")

    # ------------------------------------------------------------------
    # STEP 3 — Find competitors via Tavily
    # ------------------------------------------------------------------
    print("[Step 3] Finding competitors via Tavily...")
    competitors = find_competitor_urls(
        company_name, industry, max_results=max_competitors
    )
    if not competitors:
        raise ValueError(
            "Tavily returned no competitors. Try a different company or URL."
        )

    print(f"\n  Competitors found:")
    for c in competitors:
        print(f"    - {c['name']} ({c['url']})")

    # ------------------------------------------------------------------
    # STEP 4 + 5 — Scrape each competitor and extract their profile
    # ------------------------------------------------------------------
    print("\n[Step 4 & 5] Scraping and profiling competitors...")
    competitor_profiles = []

    for comp in competitors:
        print(f"\n  Processing: {comp['name']}")
        scraped = scrape_key_pages(comp["url"])
        if not scraped.strip():
            print(f"  [!] Skipping {comp['name']} — could not scrape content.")
            continue

        profile = extract_competitor_profile(comp["name"], scraped, model=fast_model)
        competitor_profiles.append(
            {
                "name": comp["name"],
                "url": comp["url"],
                "profile": profile,
            }
        )

    if not competitor_profiles:
        raise ValueError(
            "No competitor profiles could be extracted. All scrapes failed."
        )

    # ------------------------------------------------------------------
    # STEP 6 — Generate the full intelligence report (LLM 3)
    # ------------------------------------------------------------------
    print(f"\n[Step 6] Generating full report using {smart_model}...")
    report = generate_intelligence_report(
        company_name=company_name,
        main_profile=main_profile,
        competitor_profiles=competitor_profiles,
        model=smart_model,
    )

    print("\n[Done] Report generated successfully.\n")
    return report


def _extract_field(profile_text: str, field_name: str) -> str:
    """
    Pull the value of a field from the structured profile text.
    E.g. _extract_field(text, "INDUSTRY") -> "Payments / Fintech"
    Returns "technology" as a safe fallback if not found.
    """
    for line in profile_text.splitlines():
        if line.upper().startswith(field_name + ":"):
            return line.split(":", 1)[-1].strip()
    return "technology"
