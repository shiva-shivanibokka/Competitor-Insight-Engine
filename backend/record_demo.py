"""Record one real pipeline run so visitors without API keys can watch it work.

The deployed app is BYOK, which means a visitor with no keys sees a form and
nothing else. This records an actual run -- the real log stream, the real
timings, the real report -- and the frontend replays it. Nothing is simulated
and nothing is re-enacted; if this file has not been run, there is no recording
and the UI says so rather than inventing one.

    python record_demo.py --set                      # the whole set
    python record_demo.py --company Stripe --url https://stripe.com

Keys come from the environment or a .env, never from the recording: every frame
and the report itself are scrubbed for anything key-shaped before writing.
"""

import argparse
import io
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import FAST_MODEL, SMART_MODEL
from report import run_competitor_intelligence

DEMO_DIR = Path(__file__).resolve().parent.parent / "frontend" / "public" / "demo"

# Five targets across different industries. One Stripe run shows the pipeline
# works; five show it is not tuned to a single site's HTML. Chosen for pages
# that serve real text to a plain HTTP fetch -- a heavily client-rendered site
# scrapes to nothing, which is a true result but a poor demonstration.
DEFAULT_SET = [
    ("Stripe", "https://stripe.com", 4),
    ("Shopify", "https://www.shopify.com", 4),
    ("HubSpot", "https://www.hubspot.com", 4),
    ("Duolingo", "https://www.duolingo.com", 4),
    ("Atlassian", "https://www.atlassian.com", 4),
]

# Anything key-shaped never reaches the recording. The pipeline does not print
# keys, but "does not currently" is not a property worth betting a public file
# on -- this is the last gate before the bytes are committed.
#
# Matched on real key shapes rather than on "sk- and some characters". The
# loose version flagged the word "task-execution" in a generated report, and a
# scanner that cries wolf on ordinary prose is one somebody switches off. The
# leading lookbehind is what stops `risk-`/`task-` matching at all.
#
# The tests import this rather than keeping their own copy: this repo has
# already been bitten once by the same pattern living in two files and drifting
# (see blocklist.py), and a security check is the worst place for that.
SECRET = re.compile(
    r"(?<![A-Za-z0-9])("
    r"sk-ant-[A-Za-z0-9_\-]{20,}"      # Anthropic
    r"|sk-proj-[A-Za-z0-9_\-]{20,}"    # OpenAI project keys
    r"|sk-[A-Za-z0-9]{32,}"            # OpenAI classic
    r"|tvly-[A-Za-z0-9_\-]{16,}"       # Tavily (real keys are tvly-dev-...)
    r"|gsk_[A-Za-z0-9_\-]{20,}"        # Groq
    r"|AIza[A-Za-z0-9_\-]{30,}"        # Google
    r")"
)


def scrub(text: str) -> str:
    return SECRET.sub("[redacted]", text)


class Recorder(io.TextIOBase):
    """Tees stdout, timestamping each complete line.

    Competitors are profiled on a thread pool and all of them write here, so
    the lock is load-bearing: without it two threads interleave mid-line and
    the recording contains text the run never printed.
    """

    def __init__(self, mirror):
        self.mirror = mirror
        self.start = time.time()
        self.frames: list[dict] = []
        self._buf = ""
        self._lock = threading.Lock()

    def write(self, s: str) -> int:
        self.mirror.write(s)
        with self._lock:
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                self.frames.append({"t": round(time.time() - self.start, 2), "line": scrub(line)})
        return len(s)

    def flush(self) -> None:
        self.mirror.flush()


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def write_index() -> None:
    """Rebuild index.json from whatever recordings are on disk.

    Derived rather than hand-maintained: a list of recordings written by hand
    is the same rotting-catalogue problem as the hardcoded model list, one
    directory further along. Deleting a recording is all it takes to retire it.
    """
    runs = []
    for path in sorted(DEMO_DIR.glob("*.json")):
        if path.name == "index.json":
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        runs.append(
            {
                "slug": path.stem,
                "company": d["company"],
                "company_url": d["company_url"],
                "recorded_at": d["recorded_at"],
                "max_competitors": d["max_competitors"],
                "competitors_profiled": d.get("competitors_profiled"),
                "duration_seconds": d["duration_seconds"],
                "smart_model": d["smart_model"],
                "report_chars": len(d["report"]),
            }
        )
    (DEMO_DIR / "index.json").write_text(
        json.dumps({"runs": runs}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"index.json lists {len(runs)} recording(s): {', '.join(r['slug'] for r in runs)}")


def record_one(company: str, url: str, competitors: int) -> bool:
    rec = Recorder(sys.stdout)
    started = time.time()
    real_stdout = sys.stdout
    sys.stdout = rec
    try:
        report = run_competitor_intelligence(
            company_url=url,
            company_name=company,
            fast_model=FAST_MODEL,
            smart_model=SMART_MODEL,
            max_competitors=competitors,
        )
    except Exception as e:  # noqa: BLE001 - one bad target must not lose the others
        sys.stdout = real_stdout
        print(f"\n!! {company}: {type(e).__name__}: {str(e).splitlines()[0]}")
        return False
    finally:
        sys.stdout = real_stdout

    duration = round(time.time() - started, 1)
    # Count from the log rather than assuming: a competitor whose site refuses
    # the scraper is skipped, so "4 competitors" is a request, not a result.
    profiled = sum(1 for f in rec.frames if "Extracting profile for:" in f["line"])
    payload = {
        "recorded_at": time.strftime("%Y-%m-%d"),
        "company": company,
        "company_url": url,
        "max_competitors": competitors,
        "competitors_profiled": profiled,
        "fast_model": FAST_MODEL,
        "smart_model": SMART_MODEL,
        "duration_seconds": duration,
        "frames": rec.frames,
        "report": scrub(report),
    }

    blob = json.dumps(payload, indent=2, ensure_ascii=False)
    assert not SECRET.search(blob), "a key-shaped string survived into the recording"

    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    out = DEMO_DIR / f"{slugify(company)}.json"
    out.write_text(blob + "\n", encoding="utf-8", newline="\n")
    print(
        f"\nWrote {out.name} - {len(rec.frames)} frames, {duration}s, "
        f"{profiled}/{competitors} competitors profiled, {len(report)} chars of report"
    )
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company")
    ap.add_argument("--url")
    ap.add_argument("--competitors", type=int, default=4)
    ap.add_argument(
        "--set",
        action="store_true",
        help="record the whole default set instead of one company",
    )
    ap.add_argument(
        "--index-only",
        action="store_true",
        help="rebuild index.json from the recordings already on disk",
    )
    args = ap.parse_args()

    if args.index_only:
        write_index()
        return 0

    if not os.getenv("TAVILY_API_KEY"):
        print("TAVILY_API_KEY is not set - a recording needs one real search.")
        return 2

    targets = DEFAULT_SET if args.set else [(args.company, args.url, args.competitors)]
    if not args.set and not (args.company and args.url):
        ap.error("give --company and --url, or --set")

    failed = []
    for company, url, competitors in targets:
        print(f"\n{'#' * 62}\n# Recording {company}\n{'#' * 62}")
        if not record_one(company, url, competitors):
            failed.append(company)

    write_index()
    if failed:
        print(f"\nFailed, and deliberately not faked: {', '.join(failed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
