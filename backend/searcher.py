import os

import requests
from tavily import TavilyClient

from blocklist import is_blocked
from security import is_public_url


def get_tavily_client(api_key: str | None = None) -> TavilyClient:
    # BYOK: prefer the per-request key; fall back to env only for local/CLI use.
    api_key = api_key or os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise ValueError("No Tavily API key provided (BYOK) and TAVILY_API_KEY not in env.")
    return TavilyClient(api_key=api_key)


def validate_url(url: str) -> bool:
    """
    Check that a URL is reachable before we try to scrape it.
    Returns False if the site is down, blocklisted, non-public (SSRF), or errors.
    """
    if is_blocked(url):
        return False
    if not is_public_url(url):  # SSRF guard
        return False
    try:
        response = requests.head(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=6,
            allow_redirects=True,
        )
        return response.status_code < 400
    except Exception:  # noqa: BLE001 - unreachable for any reason means skip it
        return False


def get_competitor_search_content(
    company_name: str, industry: str, tavily_key: str | None = None
) -> str:
    """
    Search for competitors using Tavily and return the raw text content.
    We pass the content (not the URLs) to the LLM — search result URLs
    point to articles about competitors, not the competitors themselves.
    """
    client = get_tavily_client(tavily_key)

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
        # ValueError, not RuntimeError: a rejected key or an exhausted quota is
        # the caller's to fix, and the API maps ValueError to 422. RuntimeError
        # reported a user's typo as a server crash, logged a stack trace for it,
        # and told them to check a .env file the deployed app does not have.
        raise ValueError(
            f"Tavily search failed: {e}\n"
            f"Check the Tavily key you entered. If it is correct, you may have "
            f"used up the free monthly search quota."
        ) from e

    results = response.get("results", [])
    if len(results) < 3:
        print(
            f"  [!] Warning: only {len(results)} search result(s) returned. "
            f"Competitor identification may be limited."
        )

    parts = []

    answer = response.get("answer", "")
    if answer:
        parts.append(f"TAVILY SUMMARY:\n{answer}")

    for result in results:
        title = result.get("title", "")
        url = result.get("url", "")
        content = result.get("content", "")
        # Skip blocklisted sources before they even reach the LLM
        if not is_blocked(url):
            parts.append(f"SOURCE: {title}\n{content}")

    combined = "\n\n---\n\n".join(parts)
    print(f"  [searcher] Retrieved {len(results)} search results.")
    return combined
