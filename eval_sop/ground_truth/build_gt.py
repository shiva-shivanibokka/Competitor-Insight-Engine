"""Build companies.json from spec.py + SEC EDGAR.

    set EDGAR_UA="Your Name your@email"     (SEC requires a contact User-Agent)
    python eval_sop/ground_truth/build_gt.py [--cache DIR]

For each ticker: resolve CIK (sec.gov/files/company_tickers.json), take the most
recent 10-K from data.sec.gov/submissions (or the accession pinned in an
existing companies.json), download the primary document, convert to text,
find the ANCHOR, keep [anchor-200 chars, anchor+SPAN], and check that every
labelled competitor's canonical name (or an alias) literally occurs there.
Public float comes from the XBRL frames API (dei:EntityPublicFloat).
Requests are throttled to < 5/s.
"""

import argparse
import html
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from spec import CIK_OVERRIDE, SPEC  # noqa: E402

OUT = HERE / "companies.json"
PRE = 200


def get(url, ua):
    time.sleep(0.25)
    r = requests.get(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, timeout=60)
    r.raise_for_status()
    return r


def html_to_text(r) -> str:
    """Decode from raw bytes. r.text would apply requests' ISO-8859-1 default
    to text/html served without a charset, turning UTF-8 'Nestlé' into
    'NestlÃ©'. A charset declared in the header wins; otherwise BeautifulSoup
    sniffs the bytes (meta charset / BOM / UTF-8)."""
    ctype = r.headers.get("Content-Type", "")
    declared = ctype.split("charset=")[1].split(";")[0].strip() if "charset=" in ctype else None
    soup = BeautifulSoup(r.content, "html.parser", from_encoding=declared)
    return soup.get_text(" ")


def tier(fl):
    return "large" if fl >= 10e9 else "mid" if fl >= 1e9 else "small"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(HERE.parent / "raw" / "edgar_cache"))
    ap.add_argument("--offline", action="store_true",
                    help="no network: reuse CIK, float and 10-K accession pinned in companies.json and the text cache")
    args = ap.parse_args()
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    pinned = {c["id"]: c for c in json.loads(OUT.read_text(encoding="utf-8"))} if OUT.exists() else {}

    if args.offline:
        ua = None
        t2c = {k: v["cik"] for k, v in pinned.items()}
        floats = {v["cik"]: {"usd": v["public_float_usd"], "as_of": v["public_float_as_of"]}
                  for v in pinned.values() if v["public_float_usd"] is not None}
    else:
        ua = os.environ["EDGAR_UA"]
        tk = get("https://www.sec.gov/files/company_tickers.json", ua).json()
        t2c = {v["ticker"]: str(v["cik_str"]).zfill(10) for v in tk.values()}
        floats = {}
        for per in ["CY2024Q2I", "CY2024Q4I", "CY2025Q2I", "CY2025Q4I"]:  # later periods overwrite
            for d in get(f"https://data.sec.gov/api/xbrl/frames/dei/EntityPublicFloat/USD/{per}.json", ua).json()["data"]:
                floats[str(d["cik"]).zfill(10)] = {"usd": d["val"], "as_of": d["end"], "frame": per}

    out, bad = [], []
    for ticker, name, homepage, anchor, span, comps in SPEC:
        cik = CIK_OVERRIDE.get(ticker) or t2c[ticker]
        if ticker in pinned:
            p = pinned[ticker]
            url, adsh, fdate = p["tenk_url"], p["accession"], p["filing_date"]
        else:
            sub = get(f"https://data.sec.gov/submissions/CIK{cik}.json", ua).json()
            rec = sub["filings"]["recent"]
            i = rec["form"].index("10-K")
            adsh, fdate = rec["accessionNumber"][i], rec["filingDate"][i]
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{adsh.replace('-', '')}/{rec['primaryDocument'][i]}"
        cp = cache / f"{cik}.txt"
        if not cp.exists():
            if args.offline:
                raise SystemExit(f"--offline but {cp} is not cached")
            txt = html_to_text(get(url, ua))
            cp.write_text(re.sub(r"\s+", " ", html.unescape(txt)), encoding="utf-8")
        text = cp.read_text(encoding="utf-8")
        excerpt, missing = None, None
        for m in re.finditer(re.escape(anchor), text):
            win = text[max(0, m.start() - PRE): m.start() + span]
            miss = [c[0] for c in comps if not any(a in win for a in c)]
            if not miss:
                excerpt, missing = win, []
                break
            if missing is None or len(miss) < len(missing):
                excerpt, missing = win, miss
        if excerpt is None:
            bad.append((ticker, "anchor not found"))
            continue
        if missing:
            bad.append((ticker, f"not in excerpt: {missing}"))
        fl = floats.get(cik)
        out.append({
            "id": ticker, "name": name, "homepage": homepage, "cik": cik,
            "tier": tier(fl["usd"]) if fl else "unknown",
            "public_float_usd": fl and fl["usd"], "public_float_as_of": fl and fl["as_of"],
            "tenk_url": url, "accession": adsh, "filing_date": fdate,
            "excerpt": excerpt,
            "competitors": [{"name": c[0], "aliases": c[1:]} for c in comps],
            "labels_by": "Claude (LLM) transcription of names in the verbatim excerpt; aliases are LLM-added",
        })
        print(f"{ticker:5s} {out[-1]['tier']:6s} float={fl and round(fl['usd'] / 1e9, 2)}B "
              f"n_gt={len(comps)} missing={missing}")
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("problems:", bad)


if __name__ == "__main__":
    main()
