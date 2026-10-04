"""Claim-level support of step-2 company profiles against the scraped text.

Each line / bullet of the product's structured profile (INDUSTRY, PRODUCT OR
SERVICE, TARGET CUSTOMERS, PRICING MODEL, KEY FEATURES, UNIQUE SELLING POINTS,
TONE & POSITIONING) becomes one claim "<Company> <field>: <value>". Values
that are just "unknown" are skipped. Support = NLI judge (nli.py, validated
on RAGTruth) with the scraped homepage text as the only evidence.

    python eval_sop/profile_support.py   -> results/profile_support.json, results/claims_sample.csv
"""

import csv
import json
import random
import re
import statistics

from common import ROOT, load_companies
from nli import THRESH, entail_prob

FIELDS = ["INDUSTRY", "PRODUCT OR SERVICE", "TARGET CUSTOMERS", "PRICING MODEL", "KEY FEATURES",
          "UNIQUE SELLING POINTS", "TONE & POSITIONING"]


def claims(name: str, profile: str) -> list[tuple[str, str]]:
    out, field = [], None
    for raw in profile.splitlines():
        line = raw.strip().strip("*").strip()
        if not line:
            continue
        hit = next((f for f in FIELDS if line.upper().startswith(f + ":")), None)
        if hit:
            field = hit
            val = line.split(":", 1)[1].strip().strip("*").strip()
        elif field and re.match(r"^[-•*\d.]+\s*", raw.strip()):
            val = re.sub(r"^[-•*\d.]+\s*", "", raw.strip()).strip("*").strip()
        else:
            continue
        if not val or val.lower().startswith("unknown") or field == "COMPANY NAME":
            continue
        out.append((field, f"{name} {field.lower()}: {val}"))
    return out


def main():
    rows = []
    for c in load_companies():
        r = json.loads((ROOT / "raw" / "retrieval" / f"{c['id']}.json").read_text(encoding="utf-8"))
        if not r["profile"]:
            continue
        for field, cl in claims(c["name"], r["profile"]):
            p = entail_prob(r["scraped"], cl)
            rows.append({"id": c["id"], "tier": c["tier"], "scraped_chars": r["scraped_chars"],
                         "field": field, "claim": cl, "p_entail": round(p, 4), "supported": int(p >= THRESH)})
        print(c["id"], flush=True)
    summ = {}
    for tier in ("all", "large", "mid", "small"):
        byc = {}
        for x in rows:
            if tier == "all" or x["tier"] == tier:
                byc.setdefault(x["id"], []).append(x["supported"])
        vals = [statistics.fmean(v) for v in byc.values()]
        rng = random.Random(0)
        bs = sorted(statistics.fmean(rng.choices(vals, k=len(vals))) for _ in range(10000))
        summ[tier] = {"n_companies": len(vals), "n_claims": sum(len(v) for v in byc.values()),
                      "support_rate_mean_over_companies": round(statistics.fmean(vals), 4),
                      "ci95": [round(bs[250], 4), round(bs[9749], 4)]}
    short = [x["supported"] for x in rows if x["scraped_chars"] < 1000]
    long_ = [x["supported"] for x in rows if x["scraped_chars"] >= 1000]
    summ["by_scrape_length_claim_level"] = {
        "lt_1000_chars": {"n_claims": len(short), "support_rate": round(statistics.fmean(short), 4) if short else None},
        "ge_1000_chars": {"n_claims": len(long_), "support_rate": round(statistics.fmean(long_), 4) if long_ else None},
    }
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "profile_support.json").write_text(
        json.dumps({"summary": summ, "claims": rows}, indent=1, ensure_ascii=False), encoding="utf-8")
    sample = random.Random(0).sample(rows, min(100, len(rows)))
    with (ROOT / "results" / "claims_sample.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "tier", "field", "claim", "p_entail", "supported", "human_label"])
        w.writeheader()
        for x in sample:
            w.writerow({k: x.get(k, "") for k in w.fieldnames})
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
