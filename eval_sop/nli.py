"""NLI support judge + its validation on a public human-labelled benchmark.

Judge: cross-encoder/nli-deberta-v3-large (HF cache, local). A claim is
"supported" if max over evidence chunks of P(entailment) >= 0.5. The 0.5
threshold was fixed before looking at any results and is not tuned.

Validation (no human labelling by us): RAGTruth test split (Niu et al., 2024;
human span-level hallucination annotations of LLM outputs given a context).
Local copy, parquet sha256 2fc4fb70...3bbd, 2700 responses. Each response is
split into sentences; a sentence is labelled UNSUPPORTED by the RAGTruth
annotators if it overlaps any annotated hallucination span, else SUPPORTED.
We draw a balanced sample (seed 0) of 150 + 150 sentences, 100 per task type.

    set RAGTRUTH_PARQUET=path	o	est.parquet
    python eval_sop/nli.py validate      -> results/nli_ragtruth.json
"""

import json
import os
import sys

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")

import torch  # noqa: E402
from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402

from common import ROOT  # noqa: E402

MODEL = "cross-encoder/nli-deberta-v3-large"
THRESH = 0.5
_tok = _mdl = None
_ENT = None


def _load():
    global _tok, _mdl, _ENT
    if _mdl is None:
        _tok = AutoTokenizer.from_pretrained(MODEL)
        _mdl = AutoModelForSequenceClassification.from_pretrained(MODEL).eval()
        _ENT = [i for i, lab in _mdl.config.id2label.items() if lab.lower().startswith("entail")][0]
        torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "2")))


def chunks(text: str, words: int = 220, stride: int = 160) -> list[str]:
    w = text.split()
    if len(w) <= words:
        return [text] if text.strip() else []
    return [" ".join(w[i:i + words]) for i in range(0, max(1, len(w) - words + stride), stride)]


@torch.inference_mode()
def entail_prob(evidence: str, claim: str) -> float:
    """max_chunk P(entailment | chunk, claim); 0.0 if there is no evidence."""
    _load()
    cs = chunks(evidence)
    if not cs:
        return 0.0
    best = 0.0
    for i in range(0, len(cs), 8):
        batch = cs[i:i + 8]
        enc = _tok(batch, [claim] * len(batch), truncation="only_first", max_length=512,
                   padding=True, return_tensors="pt")
        p = torch.softmax(_mdl(**enc).logits, dim=-1)[:, _ENT]
        best = max(best, float(p.max()))
    return best


def _sentences(text: str) -> list[tuple[int, int]]:
    import re

    out, start = [], 0
    for m in re.finditer(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])|\n+", text):
        if m.start() > start:
            out.append((start, m.start()))
        start = m.end()
    if start < len(text):
        out.append((start, len(text)))
    return [(a, b) for a, b in out if len(text[a:b].split()) >= 4]


def validate():
    import random

    import pandas as pd
    from sklearn.metrics import balanced_accuracy_score, cohen_kappa_score, f1_score, roc_auc_score

    df = pd.read_parquet(os.environ["RAGTRUTH_PARQUET"])
    pool = {(t, lab): [] for t in ("Summary", "QA", "Data2txt") for lab in (0, 1)}
    for _, r in df.iterrows():
        spans = [(h["start"], h["end"]) for h in json.loads(r["hallucination_labels"] or "[]")]
        for a, b in _sentences(r["output"]):
            unsup = any(a < e and s_ < b for s_, e in spans)
            pool[(r["task_type"], int(not unsup))].append((r["id"], r["context"], r["output"][a:b].strip()))
    rng = random.Random(0)
    sample = []
    for (task, lab), items in sorted(pool.items()):
        for it in rng.sample(items, 50):
            sample.append((task, lab, *it))
    y, s, per = [], [], []
    for i, (task, lab, rid, ctx, claim) in enumerate(sample):
        p = entail_prob(ctx, claim)
        y.append(lab)
        s.append(p)
        per.append({"ragtruth_id": rid, "task": task, "human_supported": lab, "claim": claim, "p_entail": round(p, 4)})
        if i % 25 == 0:
            print(i, flush=True)
    pred = [int(v >= THRESH) for v in s]

    def boot(fn, n=2000):
        rng2 = random.Random(0)
        idx = list(range(len(y)))
        vals = []
        for _ in range(n):
            b = rng2.choices(idx, k=len(idx))
            yy = [y[j] for j in b]
            if len(set(yy)) < 2:
                continue
            vals.append(fn(yy, [pred[j] for j in b]))
        vals.sort()
        return [round(vals[int(0.025 * len(vals))], 4), round(vals[int(0.975 * len(vals)) - 1], 4)]

    out = {
        "benchmark": "RAGTruth test (local parquet sha256 2fc4fb703ea4...), sentence-level, balanced 300",
        "judge": MODEL, "threshold": THRESH, "n": len(y), "n_supported": sum(y),
        "accuracy": round(sum(int(a == b) for a, b in zip(y, pred, strict=True)) / len(y), 4),
        "balanced_accuracy": round(balanced_accuracy_score(y, pred), 4),
        "balanced_accuracy_ci95": boot(balanced_accuracy_score),
        "macro_f1": round(f1_score(y, pred, average="macro"), 4),
        "cohen_kappa": round(cohen_kappa_score(y, pred), 4),
        "cohen_kappa_ci95": boot(cohen_kappa_score),
        "auroc": round(roc_auc_score(y, s), 4),
        "precision_unsupported": None,
        "by_task": {},
        "per_item": per,
    }
    tp = sum(1 for a, b in zip(y, pred, strict=True) if a == 0 and b == 0)
    out["precision_unsupported"] = round(tp / max(1, sum(1 for b in pred if b == 0)), 4)
    out["recall_unsupported"] = round(tp / max(1, sum(1 for a in y if a == 0)), 4)
    for task in ("Summary", "QA", "Data2txt"):
        idx = [i for i, p in enumerate(per) if p["task"] == task]
        out["by_task"][task] = {"n": len(idx), "balanced_accuracy": round(
            balanced_accuracy_score([y[i] for i in idx], [pred[i] for i in idx]), 4)}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "nli_ragtruth.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print({k: v for k, v in out.items() if k != "per_item"})


if __name__ == "__main__":
    if sys.argv[1:] == ["validate"]:
        validate()
