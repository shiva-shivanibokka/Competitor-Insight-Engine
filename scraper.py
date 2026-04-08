import requests
from bs4 import BeautifulSoup

# Headers to mimic a real browser — some sites block plain Python requests
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

MAX_CHARS_PER_PAGE = 3000  # max characters scraped per page
MAX_CHARS_TOTAL = 6000  # max characters passed to the LLM per company


def scrape_page(url: str) -> str:
    """
    Fetch a single URL and return clean text.
    Strips scripts, styles, images, and inputs — same approach as day 5.
    Returns an empty string if the page cannot be fetched.
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"  [scraper] Could not fetch {url}: {e}")
        return ""

    soup = BeautifulSoup(response.content, "html.parser")

    # Remove noisy tags
    for tag in soup(["script", "style", "img", "input", "nav", "footer"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    return text[:MAX_CHARS_PER_PAGE]


def scrape_key_pages(base_url: str) -> str:
    """
    Scrape the homepage of a company and any relevant sub-pages found
    (about, product, pricing, careers).
    Returns a single combined text blob capped at MAX_CHARS_TOTAL.
    """
    print(f"  [scraper] Scraping: {base_url}")

    # Always start with the homepage
    homepage_text = scrape_page(base_url)
    combined = f"=== Homepage: {base_url} ===\n{homepage_text}\n\n"

    # Try common sub-pages that are likely to contain useful signal
    candidate_paths = [
        "/about",
        "/about-us",
        "/company",
        "/product",
        "/products",
        "/solutions",
        "/pricing",
        "/plans",
        "/customers",
        "/case-studies",
    ]

    for path in candidate_paths:
        if len(combined) >= MAX_CHARS_TOTAL:
            break

        url = base_url.rstrip("/") + path
        text = scrape_page(url)
        if text:
            combined += f"=== {path} ===\n{text}\n\n"

    return combined[:MAX_CHARS_TOTAL]
