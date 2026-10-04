"""Sensitivity analyses requested by the review (no API calls; cached data only).

1. Verbatim-only scoring: each ground-truth entity keeps only the strings
   (canonical name or alias) that occur verbatim in its 10-K excerpt, i.e.
   the LLM-added aliases that are not in the filing are dropped.
2. Retrieval coverage: share of a company's ground-truth entities with at
   least one verbatim string present in the search text the pipeline saw.
   This is an upper bound on what extraction can find from search, and it
   differs by tier, which confounds the small-vs-large precision comparison.
   Also: a_full P@4 within coverage strata.
3. Thin-scrape claim support: the "<1,000 scraped chars" figure rests on 3
   companies; Wilson CI at claim level and the per-company values.

    python eval_sop/sensitivity.py   -> results/sensitivity.json
"""

import json
import math
import statistics
from collections import defaultdict

from common import ROOT, load_companies
from score import bootstrap, metrics


def verbatim_gt(c: dict) -> list[dict]:
    out = []
    for e in c["competitors"]:
        keep = [a for a in [e["name"], *e["aliases"]] if a in c["excerpt"]]
        out.append({"name": keep[0], "aliases": keep[1:]})
    return out


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def main():
    comps = {c["id"]: c for c in load_companies()}
    runs = [json.loads(x) for x in (ROOT / "raw" / "discovery.jsonl").read_text(encoding="utf-8").splitlines()]
    ret = {i: json.loads((ROOT / "raw" / "retrieval" / f"{i}.json").read_text(encoding="utf-8")) for i in comps}
    out = {"model": runs[0]["model"]}

    # 1. verbatim-only
    vb = defaultdict(list)
    for r in runs:
        if r["temperature"] != 0.0 or r["seed"] != 0:
            continue
        names = [p["name"] for p in r["predictions"]]
        c = comps[r["id"]]
        vb[r["cond"]].append((c["tier"], metrics(names, c["competitors"])["p@4"], metrics(names, verbatim_gt(c))["p@4"]))
    out["verbatim_only_p@4"] = {}
    for cond, rows in sorted(vb.items()):
        for tier in ("all", "large", "mid", "small"):
            sel = [x for x in rows if tier == "all" or x[0] == tier]
            if not sel:
                continue
            m, lo, hi = bootstrap([x[2] for x in sel])
            out["verbatim_only_p@4"][f"{cond}/{tier}"] = {
                "n": len(sel), "with_aliases": round(statistics.fmean(x[1] for x in sel), 4),
                "verbatim_only": round(m, 4), "ci95": [round(lo, 4), round(hi, 4)]}

    # 2. retrieval coverage
    cov = {}
    for i, c in comps.items():
        text = ret[i]["search_content"]
        hits = [any(a in text for a in [e["name"], *e["aliases"]] if a in c["excerpt"]) for e in c["competitors"]]
        cov[i] = sum(hits) / len(hits)
    out["gt_in_search_coverage"] = {}
    for tier in ("all", "large", "mid", "small"):
        vals = [v for i, v in cov.items() if tier == "all" or comps[i]["tier"] == tier]
        m, lo, hi = bootstrap(vals)
        out["gt_in_search_coverage"][tier] = {"n": len(vals), "mean": round(m, 4), "ci95": [round(lo, 4), round(hi, 4)]}
    a_full = {r["id"]: metrics([p["name"] for p in r["predictions"]], comps[r["id"]]["competitors"])["p@4"]
              for r in runs if r["cond"] == "a_full" and r["seed"] == 0}
    med = statistics.median(cov.values())
    out["a_full_p@4_by_coverage"] = {}
    for label, sel in (("coverage<=median", [i for i in cov if cov[i] <= med]),
                       ("coverage>median", [i for i in cov if cov[i] > med])):
        out["a_full_p@4_by_coverage"][label] = {
            "median_coverage": round(med, 4), "n": len(sel),
            "tiers": {t: sum(comps[i]["tier"] == t for i in sel) for t in ("large", "mid", "small")},
            "p@4": round(statistics.fmean(a_full[i] for i in sel), 4)}
    out["per_company_coverage"] = {i: round(v, 4) for i, v in cov.items()}
    # looser variant: any name or alias (incl. LLM-added), case-insensitive
    loose = {}
    for i, c in comps.items():
        text = ret[i]["search_content"].lower()
        loose[i] = statistics.fmean(any(a.lower() in text for a in [e["name"], *e["aliases"]] if len(a) > 2)
                                    for e in c["competitors"])
    out["gt_in_search_coverage_loose"] = {
        t: round(statistics.fmean(v for i, v in loose.items() if t == "all" or comps[i]["tier"] == t), 4)
        for t in ("all", "large", "mid", "small")}

    # 3. thin scrape
    ps = json.loads((ROOT / "results" / "profile_support.json").read_text(encoding="utf-8"))["claims"]
    thin = [x for x in ps if x["scraped_chars"] < 1000]
    thick = [x for x in ps if x["scraped_chars"] >= 1000]
    per_co = defaultdict(list)
    for x in thin:
        per_co[x["id"]].append(x["supported"])
    out["thin_scrape"] = {
        "companies": {i: {"scraped_chars": next(x["scraped_chars"] for x in thin if x["id"] == i),
                          "n_claims": len(v), "support_rate": round(statistics.fmean(v), 4)} for i, v in per_co.items()},
        "claim_level": {"lt_1000": {"k": sum(x["supported"] for x in thin), "n": len(thin),
                                    "rate": round(statistics.fmean(x["supported"] for x in thin), 4),
                                    "wilson95": wilson(sum(x["supported"] for x in thin), len(thin))},
                        "ge_1000": {"k": sum(x["supported"] for x in thick), "n": len(thick),
                                    "rate": round(statistics.fmean(x["supported"] for x in thick), 4),
                                    "wilson95": wilson(sum(x["supported"] for x in thick), len(thick))}},
        "note": "claims within a company are not independent; with 3 thin-scrape companies this is descriptive only",
    }
    (ROOT / "results" / "sensitivity.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "per_company_coverage"}, indent=1))


if __name__ == "__main__":
    main()
