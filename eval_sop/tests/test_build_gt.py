"""Offline tests for ground-truth building helpers (no EDGAR calls)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ground_truth"))

import build_gt  # noqa: E402


class FakeResp:
    def __init__(self, content: bytes, content_type: str):
        self.content = content
        self.headers = {"Content-Type": content_type}
        self.encoding = None
        if "charset=" in content_type:
            self.encoding = content_type.split("charset=")[1]
        else:  # what requests does for text/* without a charset (RFC 2616 default)
            self.encoding = "ISO-8859-1"

    @property
    def text(self):
        return self.content.decode(self.encoding, errors="replace")


def test_utf8_page_without_charset_header_is_not_mojibake():
    html = "<html><head><meta charset='utf-8'></head><body>Nestlé, Deutsche Börse, Telefónica</body></html>"
    r = FakeResp(html.encode("utf-8"), "text/html")
    txt = build_gt.html_to_text(r)
    assert "Nestlé" in txt and "Börse" in txt and "Telefónica" in txt, txt


def test_declared_latin1_is_respected():
    r = FakeResp("<p>Nestlé</p>".encode("latin-1"), "text/html; charset=ISO-8859-1")
    assert "Nestlé" in build_gt.html_to_text(r)
