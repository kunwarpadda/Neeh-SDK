"""Offline recognizer-vs-oracle evaluation on the T9 argument corpus.

H9 proved oracle graphs are a 0->1 capability at +2.4% tokens; the open
question is whether the edges can be *computed* from real geometry. This
scores `neeh.semantics.build_semantics` against the T9 ground truth — no
model calls, pure geometry.

Metrics per page, aggregated over N pages:
- cluster recovery: fraction of truth entities (claims + statements) whose
  stroke set is exactly one recognized cluster (purity AND completeness)
- link precision / recall / F1: a recognized link is correct iff its
  from/to clusters map (by majority stroke overlap) to a truth
  (statement -> claim) pair with the right direction

Run:  python -m research.harness.eval_recognizer --pages 20
"""
from __future__ import annotations

import argparse

from neeh.semantics import build_semantics

from research.harness.corpus_s0 import make_argument_page


def evaluate(pages: int, seed: int = 0) -> dict[str, float]:
    ent_total = ent_exact = 0
    tp = fp = fn = 0
    for i in range(pages):
        cpage = make_argument_page(i, seed=seed)
        arg = cpage.argument
        truth_entities = [frozenset(c["stroke_ids"]) for c in arg["claims"]]
        truth_entities += [frozenset(s["stroke_ids"]) for s in arg["statements"]]
        truth_links = {
            (frozenset(s["stroke_ids"]),
             frozenset(next(c for c in arg["claims"]
                            if c["id"] == s["supports"])["stroke_ids"]))
            for s in arg["statements"]
        }

        items = build_semantics(cpage.page)
        clusters = {i["id"]: frozenset(i["stroke_ids"])
                    for i in items if i["kind"] == "cluster"}
        links = [(i["edges"]["from"], i["edges"]["to"])
                 for i in items if i["kind"] == "link"]

        ent_total += len(truth_entities)
        ent_exact += sum(1 for e in truth_entities if e in clusters.values())

        def entity_of(cluster_id: str):
            got = clusters.get(cluster_id, frozenset())
            best, best_overlap = None, 0
            for e in truth_entities:
                overlap = len(e & got)
                if overlap > best_overlap:
                    best, best_overlap = e, overlap
            return best

        seen = set()
        for src_id, dst_id in links:
            pair = (entity_of(src_id), entity_of(dst_id))
            if pair in truth_links and pair not in seen:
                tp += 1
                seen.add(pair)
            else:
                fp += 1
        fn += len(truth_links) - len(seen)

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if precision + recall else 0.0)
    return {
        "pages": pages,
        "cluster_recovery": ent_exact / ent_total if ent_total else 0.0,
        "link_precision": precision,
        "link_recall": recall,
        "link_f1": f1,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    metrics = evaluate(args.pages, args.seed)
    for k, v in metrics.items():
        print(f"{k}: {v:.3f}" if isinstance(v, float) else f"{k}: {v}")


if __name__ == "__main__":
    main()
