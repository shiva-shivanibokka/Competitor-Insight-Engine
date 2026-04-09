import requests
from scraper import scrape_key_pages
from searcher import get_competitor_search_content, validate_url
from analyzer import (
    extract_company_profile,
    extract_competitor_profile,
    extract_competitors_from_search,
    generate_intelligence_report,
)
from config import FAST_MODEL, SMART_MODEL

MIN_CONTENT_LENGTH = 200  # minimum characters before we consider a scrape meaningful


def _check_url_reachable(url: str) -> bool:
    """Quick check before we start — saves time if the URL is wrong."""
    try:
        r = requests.head(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
            allow_redirects=True,
        )
        return r.status_code < 400
    except Exception:
        return False


def _normalise_url(url: str) -> str:
    """Prepend https:// if the user forgot to include a scheme."""
    url = url.strip()
    if url and not url.startswith(("http://", "https://")):
        print(f"  [!] No URL scheme detected — prepending https:// to '{url}'")
        url = "https://" + url
    return url


def run_competitor_intelligence(
    company_url: str,
    company_name: str,
    fast_model: str = FAST_MODEL,
    smart_model: str = SMART_MODEL,
    max_competitors: int = 4,
) -> str:
    """
    Main pipeline. Give it a company URL and name, get back a full
    Competitive Intelligence Report as a Markdown string.

    To change the models used, either:
      - Edit FAST_MODEL / SMART_MODEL in config.py (changes the default everywhere)
      - Pass fast_model / smart_model when calling this function (one-time override)
      - Change FAST_MODEL_OVERRIDE / SMART_MODEL_OVERRIDE in the notebook Cell 3
    """

    # Input validation — catch obvious mistakes before doing anything
    if not company_url or not isinstance(company_url, str):
        raise ValueError(
            "company_url must be a non-empty string (e.g. 'https://stripe.com')."
        )
    if not company_name or not isinstance(company_name, str):
        raise ValueError("company_name must be a non-empty string (e.g. 'Stripe').")
    if max_competitors < 1:
        raise ValueError("max_competitors must be at least 1.")

    # Auto-fix missing URL scheme
    company_url = _normalise_url(company_url)

    print(f"\n{'=' * 60}")
    print(f" Competitor Intelligence Report for: {company_name}")
    print(f"{'=' * 60}\n")

    # Step 1 — make sure the URL works before doing anything else
    print("[Step 1] Checking and scraping main company website...")
    if not _check_url_reachable(company_url):
        raise ValueError(
            f"Cannot reach '{company_url}'.\n"
            f"Please check:\n"
            f"  - The URL is correct and includes https://\n"
            f"  - The website is publicly accessible\n"
            f"  - You have an active internet connection"
        )

    main_scraped = scrape_key_pages(company_url)
    if not main_scraped.strip():
        raise ValueError(
            f"Reached '{company_url}' but could not extract any text.\n"
            f"The site may be heavily JavaScript-rendered.\n"
            f"Try a specific sub-page like /about or /product instead."
        )
    if len(main_scraped.strip()) < MIN_CONTENT_LENGTH:
        print(
            f"  [!] Warning: only {len(main_scraped.strip())} characters scraped from main company. "
            f"The profile quality may be low."
        )

    # Step 2 — extract what the company does (used to improve the search query)
    print("\n[Step 2] Extracting main company profile...")
    main_profile = extract_company_profile(main_scraped, model=fast_model)

    if not main_profile.strip():
        raise ValueError(
            "Failed to extract a profile for the main company.\n"
            "Check that the URL points to the company homepage, not a login or error page."
        )

    print(f"\n  Profile extracted:\n{main_profile[:300]}...\n")
    industry = _extract_field(main_profile, "INDUSTRY")

    # Step 3 — search for competitors in real time
    print("[Step 3] Searching for competitors via Tavily...")
    search_content = get_competitor_search_content(company_name, industry)

    if not search_content.strip():
        raise ValueError(
            f"Tavily returned no results for '{company_name}'.\n"
            f"Check your TAVILY_API_KEY in .env and try again."
        )

    # Step 4 — LLM reads search content and picks out real competitor companies
    print("\n[Step 4] Identifying and ranking competitors...")
    all_competitors = extract_competitors_from_search(
        company_name=company_name,
        search_content=search_content,
        model=fast_model,
    )

    if not all_competitors:
        raise ValueError(
            f"Could not identify any valid competitors for '{company_name}'.\n"
            f"Try a more specific name (e.g. 'Stripe payments' instead of 'Stripe')."
        )

    # Take the top N — already ranked most-relevant first by the LLM
    competitors = all_competitors[:max_competitors]

    print(f"\n  Top {len(competitors)} competitor(s) selected:")
    for i, c in enumerate(competitors, 1):
        print(f"    {i}. {c['name']} ({c['url']})")

    # Steps 5 & 6 — scrape each competitor and extract their profile
    print("\n[Step 5 & 6] Scraping and profiling competitors...")
    competitor_profiles = []
    skipped = []

    for comp in competitors:
        name = comp["name"]
        url = comp["url"]
        print(f"\n  Processing: {name} ({url})")

        if not validate_url(url):
            print(f"  [!] Skipping {name} — URL unreachable or invalid.")
            skipped.append(name)
            continue

        scraped = scrape_key_pages(url)
        if not scraped.strip():
            print(f"  [!] Skipping {name} — page returned no readable text.")
            skipped.append(name)
            continue
        if len(scraped.strip()) < MIN_CONTENT_LENGTH:
            print(
                f"  [!] Warning: only {len(scraped.strip())} characters scraped for {name}. "
                f"Profile quality may be low."
            )

        profile = extract_competitor_profile(name, scraped, model=fast_model)
        competitor_profiles.append({"name": name, "url": url, "profile": profile})

    if skipped:
        print(f"\n  [!] Skipped: {', '.join(skipped)}")

    if not competitor_profiles:
        raise ValueError(
            "All competitor websites failed to scrape.\n"
            "Try running again — Tavily may return different results."
        )

    if len(competitor_profiles) < max_competitors:
        print(
            f"\n  [!] {len(competitor_profiles)} of {max_competitors} "
            f"competitors were successfully profiled."
        )

    # Step 7 — generate the full report
    print(f"\n[Step 7] Generating full report using {smart_model}...")
    report = generate_intelligence_report(
        company_name=company_name,
        main_profile=main_profile,
        competitor_profiles=competitor_profiles,
        model=smart_model,
    )

    print("\n[Done] Report generated successfully.\n")
    return report


def _extract_field(profile_text: str, field_name: str) -> str:
    """Pull a single field value out of the structured profile text."""
    for line in profile_text.splitlines():
        # Strip leading whitespace and markdown bold markers before matching
        clean = line.strip().lstrip("*").strip()
        if clean.upper().startswith(field_name + ":"):
            return clean.split(":", 1)[-1].strip()
    print(
        f"  [!] Could not find '{field_name}' in profile — using 'technology' as fallback."
    )
    return "technology"
