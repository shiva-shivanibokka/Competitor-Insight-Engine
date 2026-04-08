import os
from tavily import TavilyClient
from dotenv import load_dotenv

load_dotenv(override=True)


def get_tavily_client() -> TavilyClient:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise ValueError("TAVILY_API_KEY not found in .env file.")
    return TavilyClient(api_key=api_key)


def find_competitor_urls(
    company_name: str, industry: str, max_results: int = 5
) -> list[dict]:
    """
    Use Tavily to search for top competitors of a company.
    Returns a list of dicts: [{"name": ..., "url": ...}, ...]
    """
    client = get_tavily_client()

    query = f"top competitors of {company_name} in {industry} industry"
    print(f"  [searcher] Searching: '{query}'")

    response = client.search(
        query=query,
        search_depth="basic",
        max_results=max_results,
        include_answer=False,
    )

    competitors = []
    seen_domains = set()

    for result in response.get("results", []):
        url = result.get("url", "")
        title = result.get("title", "Unknown")

        # Extract base domain to avoid scraping multiple pages from same site
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            domain = f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            domain = url

        # Skip duplicates and the original company itself
        if domain in seen_domains:
            continue
        if company_name.lower().replace(" ", "") in domain.lower().replace(" ", ""):
            continue

        seen_domains.add(domain)
        competitors.append(
            {
                "name": title,
                "url": domain,
            }
        )

        if len(competitors) >= max_results:
            break

    print(f"  [searcher] Found {len(competitors)} competitor(s).")
    return competitors
