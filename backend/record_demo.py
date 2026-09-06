"""Record one real pipeline run so visitors without API keys can watch it work.

The deployed app is BYOK, which means a visitor with no keys sees a form and
nothing else. This records an actual run -- the real log stream, the real
timings, the real report -- and the frontend replays it. Nothing is simulated
and nothing is re-enacted; if this file has not been run, there is no recording
and the UI says so rather than inventing one.

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

OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "demo" / "run.json"

# Anything key-shaped never reaches the recording. The pipeline does not print
# keys, but "does not currently" is not a property worth betting a public file
# on -- this is the last gate before the bytes are committed.
SECRET = re.compile(r"\b(sk-[A-Za-z0-9_\-]{8,}|tvly-[A-Za-z0-9_\-]{8,}|gsk_[A-Za-z0-9_\-]{8,})")


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", default="Stripe")
    ap.add_argument("--url", default="https://stripe.com")
    ap.add_argument("--competitors", type=int, default=4)
    args = ap.parse_args()

    if not os.getenv("TAVILY_API_KEY"):
        print("TAVILY_API_KEY is not set - a recording needs one real search.")
        return 2

    rec = Recorder(sys.stdout)
    started = time.time()
    real_stdout = sys.stdout
    sys.stdout = rec
    try:
        report = run_competitor_intelligence(
            company_url=args.url,
            company_name=args.company,
            fast_model=FAST_MODEL,
            smart_model=SMART_MODEL,
            max_competitors=args.competitors,
        )
    finally:
        sys.stdout = real_stdout

    duration = round(time.time() - started, 1)
    payload = {
        "recorded_at": time.strftime("%Y-%m-%d"),
        "company": args.company,
        "company_url": args.url,
        "max_competitors": args.competitors,
        "fast_model": FAST_MODEL,
        "smart_model": SMART_MODEL,
        "duration_seconds": duration,
        "frames": rec.frames,
        "report": scrub(report),
    }

    blob = json.dumps(payload, indent=2, ensure_ascii=False)
    assert not SECRET.search(blob), "a key-shaped string survived into the recording"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(blob + "\n", encoding="utf-8", newline="\n")
    print(f"\nWrote {OUT} - {len(rec.frames)} frames, {duration}s, {len(report)} chars of report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
