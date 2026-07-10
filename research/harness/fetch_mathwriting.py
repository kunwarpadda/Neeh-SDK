"""Fetch the MathWriting excerpt archive (CC BY 4.0, Google).

The full dataset is ~3 GB; the official excerpt (a few hundred samples) is
enough for the S2 transcription gate. Extracts .inkml files into
research/data/mathwriting/ (gitignored).

    python -m research.harness.fetch_mathwriting
"""
from __future__ import annotations

import argparse
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from research.harness.mathwriting import DATA_DIR

EXCERPT_URL = "https://storage.googleapis.com/mathwriting_data/mathwriting-2024-excerpt.tgz"


def fetch_excerpt(url: str = EXCERPT_URL, data_dir: Path = DATA_DIR) -> int:
    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tgz") as handle:
        with urllib.request.urlopen(url) as response:
            while chunk := response.read(1 << 20):
                handle.write(chunk)
        handle.flush()
        kept = 0
        with tarfile.open(handle.name, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile() or not member.name.endswith(".inkml"):
                    continue
                content = archive.extractfile(member)
                if content is None:
                    continue
                target = data_dir / Path(member.name).name
                target.write_bytes(content.read())
                kept += 1
    return kept


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch the MathWriting excerpt")
    parser.add_argument("--url", default=EXCERPT_URL)
    args = parser.parse_args()
    kept = fetch_excerpt(args.url)
    print(f"{kept} .inkml samples -> {DATA_DIR}")


if __name__ == "__main__":
    main()
