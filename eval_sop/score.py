"""Score discovery runs against the 10-K ground truth.

    python eval_sop/score.py            -> eval_sop/results/*.json + printed tables

Name matching (deterministic, no LLM): lowercase, strip accents/punctuation,
'&'->'and', drop legal suffixes (inc, corp, ltd, llc, plc, holdings, group, ...).
A prediction matches a ground-truth entity if, for any of its names/aliases,
the normalised strings are equal or one is a whole-token prefix of the other
("Google" ~ "Google Cloud"). Single-token aliases of length <= 2 (e.g. "X",
"EA", "GE") must match exactly. Each prediction is credited to at most one
entity and each entity at most once.

Metrics (per company, then averaged over companies; 95% percentile bootstrap
over companies, 10,000 resamples, seed 0):
  P@4   matched in top-4 / number of predictions in top-4   (product default max_competitors=4)
  R@4   matched in top-4 / |GT|
  Hit@4 at least one match in top-4
  R@all matched anywhere in the returned list / |GT|
  empty fraction of runs that returned no competitors (P@4 counts these as 0)
"""

import functools
import json
import random
import re
import statistics
import unicodedata
from collections import Counter, defaultdict

from common import ROOT, load_companies

SUFFIX = {"inc", "corp", "corporation", "co", "company", "ltd", "llc", "lp", "plc", "sa", "ag", "nv",
          "se", "gmbh", "holdings", "holding", "group", "the", "limited", "incorporated", "sas", "spa"}
LEAK_ORIG = ["Adyen", "Braintree", "Square"]
LEAK_FIXED = ["Northwind", "Contoso", "Fabrikam"]
OUTD = ROOT / "results"
OUTD.mkdir(exist_ok=True)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\.com\b", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    toks = [t for t in s.split() if t not in SUFFIX]
    return " ".join(toks)


def _alias_match(p: str, a: str) -> bool:
    if not p or not a:
        return False
    if p == a:
        return True
    if (len(a) <= 2 and " " not in a) or (len(p) <= 2 and " " not in p):
        return False
    return p.startswith(a + " ") or a.startswith(p + " ")


def match(preds: list[str], gt: list[dict]) -> list[int | None]:
    """For each prediction, the index of the GT entity it hits (or None)."""
    used, out = set(), []
    for p in preds:
        np_ = norm(p)
        hit = None
        for i, e in enumerate(gt):
            if i in used:
                continue
            if any(_alias_match(np_, norm(a)) for a in [e["name"], *e["aliases"]]):
                hit = i
                break
        if hit is not None:
            used.add(hit)
        out.append(hit)
    return out


def is_truncated(cache_rec: dict) -> bool:
    """The model hit max_tokens: its JSON is probably cut off and parses to [] — not a real 'no competitors'."""
    return cache_rec.get("stop_reason") == "max_tokens" or cache_rec.get("finish_reason") == "length"


@functools.cache
def cached_responses() -> dict[str, tuple]:
    """Cached responses for every model that has any, as {model: (provider, records)}.

    Read directly from each provider's cache files, not through the active shim.
    Looking them up through `common.shim` meant a record whose model was not the
    provider named by EVAL_PROVIDER got no cached response and so an *unknown*
    truncation flag -- so `results/per_run.json` depended on an environment
    variable, and no single invocation could fill it in for both models. This
    sends nothing and takes no ledger lock; see `common.cached_records`.
    """
    from common import PROVIDERS, cached_records

    return {p.model: (p, cached_records(p)) for p in PROVIDERS.values()}


def response_record(r: dict, ret: dict) -> dict:
    """The cached LLM response behind a discovery record (rebuilt from the exact prompt)."""
    import run_discovery as rd
    from common import cache_key

    entry = cached_responses().get(r["model"])
    if entry is None:
        return {}
    provider, records = entry
    system = rd.prompt_for(r["cond"])
    user = (f"The company being researched is: {r['name']}\n\n"
            f"Search results:\n\n{rd.content_for(r['cond'], r['id'], ret, r.get('evidence_from'))}")
    return records.get(cache_key(provider, system, user, r["temperature"], r["seed"]), {})


def mentions(names: list[str], x: str) -> bool:
    """Whole-word, case-insensitive mention of x in any predicted name."""
    return any(re.search(r"\b" + re.escape(x) + r"\b", n, re.I) for n in names)


def metrics(preds: list[str], gt: list[dict], k: int = 4) -> dict:
    m = match(preds, gt)
    top = m[:k]
    nt = len(top)
    return {
        "p@4": (sum(x is not None for x in top) / nt) if nt else 0.0,
        "r@4": sum(x is not None for x in top) / len(gt),
        "hit@4": float(any(x is not None for x in top)),
        "r@all": sum(x is not None for x in m) / len(gt),
        "empty": float(len(preds) == 0),
        "n_pred": len(preds),
    }


def bootstrap(vals: list[float], n: int = 10000, seed: int = 0):
    rng = random.Random(seed)
    k = len(vals)
    means = sorted(statistics.fmean(rng.choices(vals, k=k)) for _ in range(n))
    return statistics.fmean(vals), means[int(0.025 * n)], means[int(0.975 * n) - 1]


STOP = set("""top best direct competitors competitor alternatives alternative the a an and or of in for to vs versus
with by on at as is are our your their its this that these those from how what why who which when where
inc corp llc ltd company companies market industry software platform solutions services service review reviews
compare comparison guide list analysis report pricing features overview source summary tavily us usa new
global leading largest major key main other more most also all any some here we you it they he she
january february march april may june july august september october november december""".split())


def baseline_capitalised(search_content: str, company: str, k: int = 10) -> list[str]:
    """Non-LLM baseline: most frequent capitalised 1-3 word phrases in the search text."""
    own = set(norm(company).split())
    cnt = Counter()
    for m in re.finditer(r"\b([A-Z][A-Za-z0-9&'\-]+(?:\s[A-Z][A-Za-z0-9&'\-]+){0,2})\b", search_content):
        ph = m.group(1)
        n = norm(ph)
        if not n or n.split()[0] in STOP or set(n.split()) & own or len(n) < 2:
            continue
        cnt[ph] += 1
    out, seen = [], set()
    for ph, _ in cnt.most_common():
        n = norm(ph)
        if any(n.startswith(s + " ") or s.startswith(n + " ") or n == s for s in seen):
            continue
        seen.add(n)
        out.append(ph)
        if len(out) >= k:
            break
    return out


def main():
    comps = {c["id"]: c for c in load_companies()}
    runs = []
    for f in sorted((ROOT / "raw").glob("discovery*.jsonl")):  # one file per model; grouped by model below
        runs += [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    ret = {}
    for cid in comps:
        p = ROOT / "raw" / "retrieval" / f"{cid}.json"
        if p.exists():
            ret[cid] = json.loads(p.read_text(encoding="utf-8"))

    # add the non-LLM baseline as a pseudo-condition
    for cid, r in ret.items():
        runs.append({"id": cid, "tier": comps[cid]["tier"], "cond": "z_baseline_capitalised",
                     "temperature": None, "seed": 0, "model": "none (no LLM)",
                     "predictions": [{"name": n} for n in baseline_capitalised(r["search_content"], comps[cid]["name"])]})

    per = []  # one row per (run)
    for r in runs:
        gt = comps[r["id"]]["competitors"]
        names = [p["name"] for p in r["predictions"]]
        row = {k: r[k] for k in ("id", "tier", "cond", "temperature", "seed", "model")}
        row.update(metrics(names, gt))
        def has(x, names=names):
            return mentions(names, x)
        row["leak_orig_any"] = float(any(has(x) for x in LEAK_ORIG))
        row["leak_orig_n"] = sum(has(x) for x in LEAK_ORIG)
        row["leak_fixed_any"] = float(any(has(x) for x in LEAK_FIXED))
        row["pred_names"] = names
        if r["model"] != "none (no LLM)":
            cr = response_record(r, ret)
            # None = response not in the cache loaded for this provider (score that model's run with its EVAL_PROVIDER)
            row["truncated"] = is_truncated(cr) if cr else None
        per.append(row)
    (OUTD / "per_run.json").write_text(json.dumps(per, indent=1, ensure_ascii=False), encoding="utf-8")

    # aggregate: per (model, cond, temperature) -> average over seeds per company -> bootstrap over companies
    groups = defaultdict(list)
    for row in per:
        groups[(row["model"], row["cond"], row["temperature"])].append(row)
    summary = []
    for (model, cond, temp), rows in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1], str(kv[0][2]))):
        seeds = sorted({r["seed"] for r in rows})
        for tier in ("all", "large", "mid", "small"):
            sel = [r for r in rows if tier == "all" or r["tier"] == tier]
            byc = defaultdict(list)
            for r in sel:
                byc[r["id"]].append(r)
            if not byc:
                continue
            rec = {"model": model, "cond": cond, "temperature": temp, "seeds": seeds, "tier": tier, "n_companies": len(byc),
                   "n_truncated": sum(1 for r in sel if r.get("truncated")),
                   "n_truncation_unknown": sum(1 for r in sel if model != "none (no LLM)" and r.get("truncated") is None)}
            for mname in ("p@4", "r@4", "hit@4", "r@all", "empty", "leak_orig_any", "leak_fixed_any"):
                vals = [statistics.fmean(x[mname] for x in v) for v in byc.values()]
                mean, lo, hi = bootstrap(vals)
                rec[mname] = {"mean": round(mean, 4), "ci95": [round(lo, 4), round(hi, 4)],
                              "sd_companies": round(statistics.pstdev(vals), 4)}
                if len(seeds) > 1:  # sd across seeds of the company-averaged metric
                    per_seed = [statistics.fmean(x[mname] for x in sel if x["seed"] == s) for s in seeds]
                    rec[mname]["sd_seeds"] = round(statistics.pstdev(per_seed), 4)
                    rec[mname]["per_seed"] = [round(v, 4) for v in per_seed]
            summary.append(rec)
    (OUTD / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")

    # paired differences at T=0 (company-level, seed-averaged, paired bootstrap)
    # company-level value = mean over the seeds that exist for that (company, condition)
    acc = defaultdict(list)
    for r in per:
        if r["temperature"] in (0.0, None):
            acc[(r["id"], r["model"], r["cond"])].append(r)
    t0 = {k: {m: statistics.fmean(x[m] for x in v) for m in ("p@4", "r@4", "r@all", "leak_orig_any")}
          for k, v in acc.items()}
    pairs = [("a_full", "b2_prior_knowledge"), ("a_full", "c_shuffled"), ("d_fixed", "e2_fixed_prior_knowledge"),
             ("d_fixed", "a_full"), ("a_full", "z_baseline_capitalised"), ("d_fixed", "z_baseline_capitalised"),
             ("b2_prior_knowledge", "c_shuffled"), ("a_full", "b_prior")]
    diffs = []
    models = sorted({m for (_, m, _) in t0 if m != "none (no LLM)"})
    for model in models:  # never compare across models (the baseline uses no model)
        for x, y in pairs:
            my = "none (no LLM)" if y == "z_baseline_capitalised" else model
            for tier in ("all", "large", "mid", "small"):
                for mname in ("p@4", "r@4", "r@all", "leak_orig_any"):
                    ids = [i for i in comps if (i, model, x) in t0 and (i, my, y) in t0
                           and (tier == "all" or comps[i]["tier"] == tier)]
                    if not ids:
                        continue
                    d = [t0[(i, model, x)][mname] - t0[(i, my, y)][mname] for i in ids]
                    mean, lo, hi = bootstrap(d)
                    diffs.append({"model": model, "a": x, "b": y, "tier": tier, "metric": mname, "n": len(ids),
                                  "mean_diff": round(mean, 4), "ci95": [round(lo, 4), round(hi, 4)]})
    (OUTD / "paired_diffs_T0.json").write_text(json.dumps(diffs, indent=1), encoding="utf-8")

    for rec in summary:
        f = lambda m: f"{rec[m]['mean']:.3f} [{rec[m]['ci95'][0]:.2f},{rec[m]['ci95'][1]:.2f}]"  # noqa: E731
        print(f"{rec['model'][:16]:16s} {rec['cond']:24s} T={rec['temperature']!s:4s} seeds={rec['seeds']} "
              f"{rec['tier']:5s} n={rec['n_companies']:2d} "
              f"P@4 {f('p@4')}  R@4 {f('r@4')}  R@all {f('r@all')}  empty {rec['empty']['mean']:.2f}  "
              f"leak {rec['leak_orig_any']['mean']:.2f}  max_tokens-truncated {rec['n_truncated']}"
              + (f" (unknown {rec['n_truncation_unknown']})" if rec["n_truncation_unknown"] else ""))
    print()
    for d in diffs:
        if d["metric"] in ("p@4", "r@all", "leak_orig_any"):
            print(f"{d['model'][:16]:16s} {d['a']:>14s} - {d['b']:<24s} {d['tier']:5s} {d['metric']:14s} n={d['n']:2d} "
                  f"{d['mean_diff']:+.3f} [{d['ci95'][0]:+.3f},{d['ci95'][1]:+.3f}]")


if __name__ == "__main__":
    main()
