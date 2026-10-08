"""Strip third-party page text from raw/retrieval/*.json (NOT run; the user decides).

Replaces the scraped homepage text and the search text with their SHA-256 and
length, keeping URLs, the query, the industry and the LLM-written profile, so
the files can be shared without republishing web page excerpts. After
stripping, retrieve.py cannot replay discovery from these files; keep an
unstripped private copy if the run must stay reproducible.

    python eval_sop/strip_retrieval.py --out eval_sop/raw/retrieval_stripped   # writes a copy
    python eval_sop/strip_retrieval.py --in-place                               # overwrites
"""

import argparse
import hashlib
import json
from pathlib import Path

SRC = Path(__file__).resolve().parent / "raw" / "retrieval"
TEXT_FIELDS = ("scraped", "search_content")


def strip(rec: dict) -> dict:
    out = dict(rec)
    for f in TEXT_FIELDS:
        txt = rec.get(f) or ""
        out[f] = None
        out[f + "_sha256"] = hashlib.sha256(txt.encode("utf-8")).hexdigest()
        out[f + "_chars"] = len(txt)
    out["stripped"] = True
    return out


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--out")
    g.add_argument("--in-place", action="store_true")
    a = ap.parse_args()
    dst = SRC if a.in_place else Path(a.out)
    dst.mkdir(parents=True, exist_ok=True)
    for p in sorted(SRC.glob("*.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        (dst / p.name).write_text(json.dumps(strip(rec), indent=1, ensure_ascii=False), encoding="utf-8")
        print(p.name)


if __name__ == "__main__":
    main()
