"""Fetch a slice of the Quick, Draw! simplified dataset (CC BY 4.0, Google).

Streams only the first `--lines` sketches of each category file — the full
files run to tens of megabytes and the harness needs a few dozen sketches.
Downloads land in research/data/quickdraw/ (gitignored; NC-free but there is
no reason to version corpus bytes).

    python -m research.harness.fetch_quickdraw
    python -m research.harness.fetch_quickdraw --categories cat house tree --lines 200
"""
from __future__ import annotations

import argparse
import urllib.parse
import urllib.request

from research.harness.quickdraw import DATA_DIR

BASE_URL = "https://storage.googleapis.com/quickdraw_dataset/full/simplified/"
DEFAULT_CATEGORIES = ["cat", "house", "tree", "car", "star", "clock", "fish", "chair"]


def fetch_category(category: str, lines: int) -> int:
    url = BASE_URL + urllib.parse.quote(category) + ".ndjson"
    target = DATA_DIR / f"{category}.ndjson"
    kept = 0
    with urllib.request.urlopen(url) as response, target.open("wb") as out:
        for raw in response:
            out.write(raw)
            kept += 1
            if kept >= lines:
                break
    return kept


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Quick, Draw! category slices")
    parser.add_argument("--categories", nargs="*", default=DEFAULT_CATEGORIES)
    parser.add_argument("--lines", type=int, default=200,
                        help="sketches to keep per category")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for category in args.categories:
        kept = fetch_category(category, args.lines)
        print(f"{category}: {kept} sketches -> {DATA_DIR / (category + '.ndjson')}")


if __name__ == "__main__":
    main()
