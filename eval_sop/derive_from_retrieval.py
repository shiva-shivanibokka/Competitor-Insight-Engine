"""Precompute everything the scorer and the sensitivity analysis need from the
scraped search text, so that text does not have to be redistributed.

`raw/retrieval/*.json` holds verbatim excerpts of third-party commercial pages
(Gartner, Craft.co, Tracxn, Owler and others) with no licence granting
redistribution. `strip_retrieval.py` replaces those two fields with a SHA-256 and
a length. Everything downstream that needed the text is served from the two files
written here instead:

  results/prompt_keys.json        (cond, id, temperature, seed) -> response-cache key,
                                  per model. The cache key is a hash of the exact
                                  prompt, so without it the scorer cannot find a
                                  cached response once the prompt cannot be rebuilt.
  results/retrieval_coverage.json per-company retrieval coverage, strict and loose,
                                  plus the per-entity booleans behind each figure so
                                  the numbers stay auditable rather than asserted.

Run this BEFORE stripping, and commit both outputs. Re-running it after a fresh
retrieve.py regenerates both from the new text.

    python eval_sop/derive_from_retrieval.py
"""

import json
import statistics
from pathlib import Path

from common import PROVIDERS, ROOT, cache_key, load_companies

import run_discovery as rd

RET = ROOT / "raw" / "retrieval"
OUT = ROOT / "results"


def _prompt_pair(cond: str, cid: str, name: str, ret: dict, evidence_from):
    """The exact (system, user) the run sent, rebuilt the way score.py does."""
    system = rd.prompt_for(cond)
    user = (f"The company being researched is: {name}\n\n"
            f"Search results:\n\n{rd.content_for(cond, cid, ret, evidence_from)}")
    return system, user


def prompt_keys(ret: dict) -> dict:
    """One cache key per committed discovery record, keyed by model."""
    out: dict[str, dict[str, str]] = {}
    for path in sorted((ROOT / "raw").glob("discovery*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            provider = next((p for p in PROVIDERS.values() if p.model == r["model"]), None)
            if provider is None:          # the no-LLM baseline has no cache
                continue
            system, user = _prompt_pair(r["cond"], r["id"], r["name"], ret, r.get("evidence_from"))
            key = cache_key(provider, system, user, r["temperature"], r["seed"])
            slot = out.setdefault(r["model"], {})
            slot[f"{r['cond']}|{r['id']}|{r['temperature']}|{r['seed']}"] = key
    return out


def coverage(ret: dict, comps: dict) -> dict:
    """Share of each company's ground-truth entities present in its search text.

    Strict: a name or alias that also appears verbatim in the 10-K excerpt must
    appear verbatim in the search text. Loose: any name or alias longer than two
    characters, case-insensitively. Both definitions are the ones in
    sensitivity.py; the per-entity booleans are kept so a reader can recheck the
    arithmetic without the text.
    """
    out = {}
    for cid, c in comps.items():
        text = ret[cid]["search_content"] or ""
        low = text.lower()
        strict, loose, names = [], [], []
        for e in c["competitors"]:
            forms = [e["name"], *e["aliases"]]
            verbatim = [a for a in forms if a in c["excerpt"]]
            strict.append(any(a in text for a in verbatim))
            loose.append(any(a.lower() in low for a in forms if len(a) > 2))
            names.append(e["name"])
        out[cid] = {
            "tier": c["tier"],
            "entities": names,
            "strict_hits": strict,
            "loose_hits": loose,
            # Deliberately unrounded. Rounding these to 6 dp moved the bootstrap
            # CIs in sensitivity.json by ~0.002, because the bootstrap resamples
            # these very numbers -- so a stripped tree stopped reproducing the
            # committed file. The per-entity booleans above let a reader recompute
            # them exactly anyway.
            "strict": statistics.fmean(strict),
            "loose": statistics.fmean(loose),
        }
    return out


def baseline_predictions(ret: dict, comps: dict) -> dict:
    """The no-LLM baseline's output per company.

    `score.py:baseline_capitalised` mines the most frequent capitalised phrases
    straight out of the search text, so the `z_baseline_capitalised` condition --
    a reported row, P@4 0.099 -- cannot be computed at all once that text is
    stripped. Its *output* is a short list of candidate company names, which is
    derived data rather than third-party prose, so it is precomputed here.
    """
    from score import baseline_capitalised

    return {cid: baseline_capitalised(ret[cid]["search_content"], comps[cid]["name"])
            for cid in comps}


def main() -> None:
    comps = {c["id"]: c for c in load_companies()}
    ret = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in RET.glob("*.json")}
    missing = [cid for cid, r in ret.items() if not r.get("search_content")]
    if missing:
        raise SystemExit(
            "search_content is already stripped for: " + ", ".join(sorted(missing)[:5])
            + " -- run this before strip_retrieval.py, or restore the private copy first")

    OUT.mkdir(parents=True, exist_ok=True)
    keys = prompt_keys(ret)
    (OUT / "prompt_keys.json").write_text(json.dumps(keys, indent=1, sort_keys=True), encoding="utf-8")
    cov = coverage(ret, comps)
    (OUT / "retrieval_coverage.json").write_text(json.dumps(cov, indent=1, sort_keys=True), encoding="utf-8")
    base = baseline_predictions(ret, comps)
    (OUT / "baseline_predictions.json").write_text(json.dumps(base, indent=1, sort_keys=True), encoding="utf-8")
    print(f"prompt_keys.json: {sum(len(v) for v in keys.values())} keys over {len(keys)} model(s)")
    print(f"retrieval_coverage.json: {len(cov)} companies")
    print(f"baseline_predictions.json: {len(base)} companies, "
          f"{sum(len(v) for v in base.values())} predicted names")


if __name__ == "__main__":
    main()
