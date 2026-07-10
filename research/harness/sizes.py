"""Offline context-size exhibit: exact chars + exact visual tokens per arm.

Text-token costs must come from model-reported usage (protocol §6); this
module measures only what is exact without a model — context characters,
PNG bytes, and Claude visual tokens (ceil(w/28) * ceil(h/28) per attached
image) — enough to test the "ICF v0 vector costs more than its own PNG"
conjecture at the character level while the pilot sweep supplies real tokens.
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Optional

from research.harness.corpus_s0 import CorpusPage, generate_corpus
from research.harness.encoders import ALL_ARMS, ENCODERS
from research.harness.ledger import DEFAULT_LEDGER

SIZES_PATH = DEFAULT_LEDGER.parent / "context-sizes.md"
PAGE_VISUAL_TOKENS = math.ceil(1000 / 28) * math.ceil(1414 / 28)  # 36 * 51 = 1836


def context_size_table(pages: Optional[list[CorpusPage]] = None) -> str:
    pages = pages or generate_corpus()
    rows: dict[tuple[str, str], list[dict[str, float]]] = defaultdict(list)
    for page in pages:
        for arm in ALL_ARMS:
            encoded = ENCODERS[arm](page.page)
            rows[(arm, page.kind)].append({
                "chars": len(encoded.text or ""),
                "png_bytes": len(encoded.image_png or b""),
                "visual_tokens": PAGE_VISUAL_TOKENS if encoded.image_png else 0,
                "strokes": sum(len(l.strokes) for l in page.page.layers),
            })
    lines = [
        "# Context sizes (offline, exact)",
        "",
        f"S0 corpus, {len(pages)} pages. Visual tokens use Claude's 28x28-patch rule",
        f"({PAGE_VISUAL_TOKENS} per full-page PNG). Text-token costs come from the live",
        "sweep ledger, not from characters — this table is the model-free exhibit.",
        "",
        "| arm | page kind | pages | mean strokes | mean context chars | mean PNG bytes | visual tokens |",
        "|---|---|---|---|---|---|---|",
    ]
    for (arm, kind) in sorted(rows):
        cells = rows[(arm, kind)]
        lines.append(
            f"| {arm} | {kind} | {len(cells)} "
            f"| {mean(c['strokes'] for c in cells):.0f} "
            f"| {mean(c['chars'] for c in cells):,.0f} "
            f"| {mean(c['png_bytes'] for c in cells):,.0f} "
            f"| {cells[0]['visual_tokens']:.0f} |"
        )
    lines += [
        "",
        "Reading: E1a/E1b carry the ICF v0 JSON — compare their context chars against",
        "E0's zero chars + 1836 visual tokens, and against E2/E4's compressed text.",
        "A conservative 4-chars-per-token reading is indicative only; the ledger's",
        "model-reported input tokens are the number that counts.",
    ]
    return "\n".join(lines) + "\n"


def write_sizes(path: Path = SIZES_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(context_size_table(), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_sizes())
