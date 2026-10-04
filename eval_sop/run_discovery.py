"""Step 4 of the pipeline (competitor discovery) under several conditions.

Calls the product's analyzer.extract_competitors_from_search unchanged (prompt,
JSON parsing, blocklist, dedup), with only the system prompt and the search
content varied:

  a_full        original prompt (commit c3eac2d) + retrieved search content
  b_prior       original prompt + NO search content (LLM prior only)
  c_shuffled    original prompt + another company's search content (derangement, seed 0)
  d_fixed       candidate fixed prompt (fictional few-shot examples, eval_sop/fixed_prompt.py) + retrieved search content
  e_fixed_prior fixed prompt + NO search content
  b2_prior_knowledge  original prompt, search slot says "use your own knowledge" (LLM prior only)
  e2_fixed_prior_knowledge  fixed prompt, same "use your own knowledge" slot

b_/e_ were the first operationalisation of "prior only"; the model answered []
for all 48 companies (it abstains when told no search ran), so b2_/e2_ add an
explicit invitation to answer from parametric knowledge. Both are reported.

    python eval_sop/run_discovery.py --temps 0 --seeds 0 1 2

Seeds are passed to the provider (Groq `seed`); the temperature is the
product's own 0.0 unless --temps overrides it.
"""

import argparse
import json
import random
import subprocess

from common import MODEL, ROOT, load_companies, shim
from fixed_prompt import FIXED_COMPETITOR_EXTRACTION_PROMPT

import analyzer  # noqa: E402

RET = ROOT / "raw" / "retrieval"
OUT_DIR = ROOT / "raw"
BASE_COMMIT = "c3eac2d"


def original_prompt() -> str:
    src = subprocess.run(
        ["git", "show", f"{BASE_COMMIT}:backend/analyzer.py"],
        cwd=ROOT.parent, capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    ns: dict = {}
    start = src.index("COMPETITOR_EXTRACTION_PROMPT = ")
    end = src.index('"""\n', src.index('"""', start) + 3) + 4
    exec(src[start:end], ns)  # noqa: S102 - our own repo's source at a pinned commit
    return ns["COMPETITOR_EXTRACTION_PROMPT"]


ORIGINAL = original_prompt()
FIXED = FIXED_COMPETITOR_EXTRACTION_PROMPT  # candidate fix, kept in eval_sop/, not shipped
NO_SEARCH = "(none — no web search was run for this request)"
OWN_KNOWLEDGE = ("(No search results are available for this request. "
                 "Answer from your own knowledge of the company and its market.)")
ORIGINAL_PROMPT_CONDS = ("a_full", "b_prior", "c_shuffled", "b2_prior_knowledge")


def prompt_for(cond: str) -> str:
    return ORIGINAL if cond in ORIGINAL_PROMPT_CONDS else FIXED


def content_for(cond: str, cid: str, ret: dict, donor_id: str | None) -> str:
    if cond in ("a_full", "d_fixed"):
        return ret[cid]["search_content"]
    if cond == "c_shuffled":
        return ret[donor_id]["search_content"]
    if cond in ("b2_prior_knowledge", "e2_fixed_prior_knowledge"):
        return OWN_KNOWLEDGE
    return NO_SEARCH


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--temps", type=float, nargs="+", default=[0.0])
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--conds", nargs="+",
                    default=["a_full", "b_prior", "c_shuffled", "d_fixed", "e_fixed_prior",
                             "b2_prior_knowledge", "e2_fixed_prior_knowledge"])
    args = ap.parse_args()
    assert FIXED != ORIGINAL

    comps = [c for c in load_companies() if (RET / f"{c['id']}.json").exists()]
    ret = {c["id"]: json.loads((RET / f"{c['id']}.json").read_text(encoding="utf-8")) for c in comps}
    ids = [c["id"] for c in comps]
    rng = random.Random(0)
    while True:  # derangement: nobody keeps their own evidence
        perm = ids[:]
        rng.shuffle(perm)
        if all(a != b for a, b in zip(ids, perm, strict=True)):
            break
    donor = dict(zip(ids, perm, strict=True))

    out = OUT_DIR / "discovery.jsonl"
    done = set()
    for f in [out] if out.exists() else []:
        for line in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done.add((r["id"], r["cond"], r["temperature"], r["seed"]))

    tasks = [(temp, seed, cond, c) for temp in args.temps for seed in args.seeds
             for cond in args.conds for c in comps]
    for temp, seed, cond, c in tasks:
        key = (c["id"], cond, temp, seed)
        if key in done:
            continue
        src = c["id"] if cond in ("a_full", "d_fixed") else donor[c["id"]] if cond == "c_shuffled" else None
        content, prompt = content_for(cond, c["id"], ret, src), prompt_for(cond)
        analyzer.COMPETITOR_EXTRACTION_PROMPT = prompt
        shim.seed, shim.tag = seed, f"{cond}:{c['id']}"
        # the product hardcodes temperature=0.0 for this step
        shim.force_temperature = temp
        try:
            preds = analyzer.extract_competitors_from_search(c["name"], content, model=MODEL)
        finally:
            shim.force_temperature = None
        rec = {"id": c["id"], "name": c["name"], "tier": c["tier"], "cond": cond,
               "temperature": temp, "seed": seed, "evidence_from": src,
               "model": MODEL, "predictions": preds}
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"{cond:14s} T={temp} s={seed} {c['name'][:28]:28s} -> "
              f"{[p['name'] for p in preds][:6]}", flush=True)


if __name__ == "__main__":
    main()
