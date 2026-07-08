"""Single source of truth for domains that are never real competitors.

Previously this set was copy-pasted into both searcher.py and analyzer.py and had
already drifted (each file was missing entries the other had). Keep it here only.
"""

from urllib.parse import urlparse

# Sites that should never show up as a competitor no matter what the LLM says:
# forums, encyclopaedias, social networks, news, and review/aggregator platforms.
BLOCKED_DOMAINS = {
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
    "wired.com",
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
    "stackshare.io",
    "alternativeto.net",
    "getapp.com",
}


def is_blocked(url: str) -> bool:
    """True if the URL's host is (or is a subdomain of) a blocked domain.

    Matches on the parsed host with a boundary check, not a raw substring —
    otherwise short entries like "x.com" wrongly match "netflix.com".
    """
    host = (urlparse(url).hostname or url).lower()
    return any(host == d or host.endswith("." + d) for d in BLOCKED_DOMAINS)
