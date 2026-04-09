import os
import requests
from tavily import TavilyClient
from dotenv import load_dotenv

load_dotenv(override=True)

# Sites that should never show up as competitors no matter what.
# Add more here if needed.
BLACKLISTED_DOMAINS = {
    "reddit.com",
    "wikipedia.org",
    "quora.com",
    "linkedin.com",
    "youtube.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "medium.com",
    "substack.com",
    "forbes.com",
    "techcrunch.com",
    "businessinsider.com",
    "g2.com",
    "capterra.com",
    "trustpilot.com",
    "glassdoor.com",
    "crunchbase.com",
    "producthunt.com",
    "ycombinator.com",
    "investopedia.com",
    "nerdwallet.com",
    "bankrate.com",
}


def get_tavily_client() -> TavilyClient:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise ValueError("TAVILY_API_KEY not found in .env file.")
    return TavilyClient(api_key=api_key)


def is_blacklisted(url: str) -> bool:
    """Check if a URL belongs to a site we never want as a competitor."""
    url_lower = url.lower()
    return any(domain in url_lower for domain in BLACKLISTED_DOMAINS)


def validate_url(url: str) -> bool:
    """
    Check that a URL is reachable before we try to scrape it.
    Returns False if the site is down, blacklisted, or returns an error.
    """
    if is_blacklisted(url):
        return False
    try:
        response = requests.head(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=6,
            allow_redirects=True,
        )
        return response.status_code < 400
    except Exception:
        return False


def get_competitor_search_content(company_name: str, industry: str) -> str:
    """
    Search for competitors using Tavily and return the raw text content.
    We pass the content (not the URLs) to the LLM — search result URLs
    point to articles about competitors, not the competitors themselves.
    """
    client = get_tavily_client()

    query = f"top direct competitors of {company_name} in {industry}"
    print(f"  [searcher] Searching: '{query}'")

    try:
        response = client.search(
            query=query,
            search_depth="advanced",
            max_results=10,
            include_answer=True,
        )
    except Exception as e:
        raise RuntimeError(
            f"Tavily search failed: {e}\n"
            f"Check your TAVILY_API_KEY in .env. If the key is correct, "
            f"you may have hit your monthly search limit."
        ) from e

    results = response.get("results", [])
    if len(results) < 3:
        print(
            f"  [!] Warning: only {len(results)} search result(s) returned — competitor identification may be limited."
        )

    parts = []

    answer = response.get("answer", "")
    if answer:
        parts.append(f"TAVILY SUMMARY:\n{answer}")

    for result in results:
        title = result.get("title", "")
        url = result.get("url", "")
        content = result.get("content", "")
        # Skip blacklisted sources before they even reach the LLM
        if not is_blacklisted(url):
            parts.append(f"SOURCE: {title}\n{content}")

    combined = "\n\n---\n\n".join(parts)
    print(f"  [searcher] Retrieved {len(results)} search results.")
    return combined
