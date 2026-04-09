import requests
from bs4 import BeautifulSoup

# Pretend to be a browser so sites don't block the request
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

MAX_CHARS_PER_PAGE = 3000  # cap per page to keep things manageable
MAX_CHARS_TOTAL = 6000  # cap for the combined text passed to the LLM


def scrape_page(url: str) -> str:
    """
    Fetch a single page and return the readable text.
    Strips scripts, styles, images, nav, and footer before extracting.
    Returns an empty string if the page can't be fetched.
    """
    if not url.startswith(("http://", "https://")):
        print(f"  [scraper] Skipped '{url}' — missing URL scheme (expected https://)")
        return ""

    try:
        response = requests.get(url, headers=HEADERS, timeout=(5, 10))
        response.raise_for_status()
    except Exception as e:
        print(f"  [scraper] Could not fetch {url}: {e}")
        return ""

    soup = BeautifulSoup(response.text, "html.parser")

    # Remove everything that isn't useful text
    for tag in soup(["script", "style", "img", "input", "nav", "footer"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    return text[:MAX_CHARS_PER_PAGE]


def scrape_key_pages(base_url: str) -> str:
    """
    Scrape the homepage plus common sub-pages (about, product, pricing, etc.).
    Returns all the text combined into one string, capped at MAX_CHARS_TOTAL.
    """
    if not base_url.startswith(("http://", "https://")):
        print(f"  [scraper] Invalid URL '{base_url}' — missing https://. Skipping.")
        return ""

    print(f"  [scraper] Scraping: {base_url}")

    homepage_text = scrape_page(base_url)
    combined = f"=== Homepage: {base_url} ===\n{homepage_text}\n\n"

    # Pages most likely to have useful company info
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
