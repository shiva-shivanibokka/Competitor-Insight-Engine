"""SSRF guard for a public URL-fetching service.

This tool scrapes arbitrary user-supplied URLs. Deployed publicly, that is a
Server-Side Request Forgery vector: a caller could aim it at cloud metadata
(169.254.169.254), localhost, or an internal 10.x/192.168.x service.

Every outbound fetch in the pipeline routes through requests to a hostname.
Call `assert_public_url()` before each one. It resolves the host and rejects
if ANY resolved IP is private / loopback / link-local / reserved — which also
blocks DNS names that point at internal ranges, not just raw-IP URLs.
"""

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from urllib.parse import urljoin, urlparse

import requests


class BlockedURLError(ValueError):
    """Raised when a URL resolves to a non-public address."""


def _ip_is_public(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


DNS_TIMEOUT = 5.0

# One executor for the process. getaddrinfo releases the GIL, so a stuck lookup
# occupies a worker rather than the request thread.
_resolver = ThreadPoolExecutor(max_workers=8, thread_name_prefix="dns")


def _resolve(host: str):
    """getaddrinfo with a deadline.

    `socket.getaddrinfo` takes no timeout and ignores `setdefaulttimeout`, so a
    host whose DNS server simply never answers blocks the calling thread for as
    long as the resolver wants. On a platform that caps a request at 300s that
    is the whole budget spent on a name lookup, and it presents as the service
    hanging rather than as a bad URL.
    """
    try:
        return _resolver.submit(socket.getaddrinfo, host, None).result(timeout=DNS_TIMEOUT)
    except FuturesTimeout as e:
        # The worker thread stays blocked until the OS gives up; that is the
        # cost of a resolver with no cancellation. The request does not wait.
        raise TimeoutError(f"DNS lookup for {host!r} exceeded {DNS_TIMEOUT}s") from e


def assert_public_url(url: str) -> None:
    """Raise BlockedURLError unless url is http(s) to a publicly-routable host."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BlockedURLError(f"Only http/https URLs are allowed, got: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise BlockedURLError(f"URL has no host: {url!r}")

    try:
        # Resolve every address the host maps to and check all of them.
        infos = _resolve(host)
    except socket.gaierror as e:
        raise BlockedURLError(f"Could not resolve host {host!r}: {e}") from e
    except TimeoutError as e:
        raise BlockedURLError(f"Timed out resolving host {host!r}") from e

    for info in infos:
        ip_str = info[4][0]
        if not _ip_is_public(ip_str):
            raise BlockedURLError(
                f"Refusing to fetch {url!r}: host resolves to non-public address {ip_str}."
            )


def is_public_url(url: str) -> bool:
    """Boolean form for call sites that skip rather than raise."""
    try:
        assert_public_url(url)
        return True
    except BlockedURLError:
        return False


def fetch_validated(url: str, headers: dict, timeout, max_redirects: int = 5):
    """GET that re-runs the SSRF guard on EVERY redirect hop before following it.

    requests' default allow_redirects=True would follow a 302 to an internal
    address without re-checking. We disable auto-redirect and validate each hop.
    """
    for _ in range(max_redirects + 1):
        assert_public_url(url)  # guard before every request, including redirects
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=False)
        if resp.is_redirect and resp.headers.get("location"):
            url = urljoin(url, resp.headers["location"])
            continue
        return resp
    raise BlockedURLError(f"Too many redirects fetching {url!r}")


if __name__ == "__main__":
    # ponytail: one runnable check that fails if the guard breaks.
    assert is_public_url("https://stripe.com")
    assert not is_public_url("http://169.254.169.254/latest/meta-data/")  # cloud metadata
    assert not is_public_url("http://localhost:8000")
    assert not is_public_url("http://127.0.0.1")
    assert not is_public_url("http://10.0.0.5")
    assert not is_public_url("http://[::1]/")
    assert not is_public_url("ftp://example.com")
    assert not is_public_url("file:///etc/passwd")
    print("security.py self-check passed")
