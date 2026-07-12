"""Compare context representations ("arms") for the ink agent, by token footprint.

Motivated by how web/GUI agents represent a screen for an LLM: a structured,
labeled index (an accessibility tree / Set-of-Marks) is an order of magnitude
cheaper than a raster and grounds *better*, with the image kept as a secondary,
on-demand channel. This script builds the same three arms over sample ink and
measures them, so the choice is made on data rather than intuition:

  A. raster + geometry   — a page PNG plus SVG stroke paths (perception-first)
  B. structured index    — build_ink_index: marks with ids, shape, position, bbox
  C. structured + ASCII  — the index plus a token-cheap ASCII Set-of-Marks gestalt

Text is estimated at ~4 chars/token; a raster at ~(width*height)/750 tokens
(the Anthropic vision-token rule of thumb). Run with --show to print each arm.

    python examples/compare_context_arms.py [--show]
"""
from __future__ import annotations

import argparse
import json

from neeh import (
    Canvas,
    build_ink_index,
    build_ink_paths,
    render_page_ascii,
)
from neeh.ink import Author


def _text_tokens(text: str) -> int:
    return round(len(text) / 4)


def _png_tokens(canvas: Canvas) -> tuple[int, str]:
    """Estimated vision tokens for the cropped page raster, or a note if Pillow
    (the optional PNG extra) is not installed."""
    try:
        import io

        from PIL import Image

        from neeh.rendering.png import render_page_png
    except ImportError:
        return 0, "PNG extra not installed (pip install 'neeh[png]')"
    region = canvas.page.content_bbox
    png = render_page_png(canvas.page, region=region)
    w, h = Image.open(io.BytesIO(png)).size
    return round(w * h / 750), f"{w}x{h}px raster"


def _marks_xy(index: dict) -> dict[str, tuple[float, float]]:
    """Single-character Set-of-Marks labels at each mark's centroid."""
    out = {}
    for i, mark in enumerate(index["marks"][:35]):
        label = "123456789abcdefghijklmnopqrstuvwxyz"[i]
        x0, y0, x1, y1 = mark["bbox"]
        out[label] = ((x0 + x1) / 2, (y0 + y1) / 2)
    return out


def arms(canvas: Canvas) -> dict[str, dict]:
    """The three representations and their estimated token footprints."""
    index = build_ink_index(canvas)
    index_json = json.dumps(index, separators=(",", ":"))
    svg = build_ink_paths(canvas.page)
    ascii_art = render_page_ascii(canvas.page, marks=_marks_xy(index))
    img_tokens, img_note = _png_tokens(canvas)

    return {
        "A. raster + geometry": {
            "tokens": img_tokens + _text_tokens(svg),
            "detail": f"{img_note} (~{img_tokens} tok) + SVG paths (~{_text_tokens(svg)} tok)",
            "show": svg,
        },
        "B. structured index": {
            "tokens": _text_tokens(index_json),
            "detail": f"{index['mark_count']} marks, {index['handwriting_stroke_count']} handwriting strokes summarized",
            "show": json.dumps(index, indent=1),
        },
        "C. structured + ASCII": {
            "tokens": _text_tokens(index_json) + _text_tokens(ascii_art),
            "detail": f"index (~{_text_tokens(index_json)} tok) + ASCII gestalt (~{_text_tokens(ascii_art)} tok)",
            "show": ascii_art,
        },
    }


def _tyred_logo() -> Canvas:
    c = Canvas()
    c.add_stroke([(160, 150), (285, 150), (285, 175), (160, 175), (160, 150)], author=Author.USER)
    c.add_stroke([(218, 175), (215, 300)], author=Author.USER)
    c.add_stroke([(185, 300), (245, 305), (240, 330), (185, 328), (185, 300)], author=Author.USER)
    return c


def _sidebar_with_question() -> Canvas:
    c = Canvas()
    c.add_stroke([(60, 120), (300, 120), (300, 560), (60, 560), (60, 120)], author=Author.USER)
    for y in (170, 210, 250, 290):
        c.add_stroke([(150, y), (220, y)], author=Author.USER)
    c.add_stroke([(80, 520), (96, 520), (104, 528), (80, 528)], author=Author.USER)
    for i in range(40):  # a handwritten question
        x = 80 + i * 12
        c.add_stroke([(x, 650), (x + 6, 660), (x + 3, 675)], author=Author.USER)
    return c


SCENES = {"tyred_logo": _tyred_logo, "sidebar_with_question": _sidebar_with_question}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", action="store_true", help="print each representation")
    args = parser.parse_args()

    for name, build in SCENES.items():
        print(f"\n=== {name} ===")
        result = arms(build())
        baseline = result["A. raster + geometry"]["tokens"]
        for arm, info in result.items():
            ratio = f"{baseline / info['tokens']:.1f}x cheaper" if info["tokens"] else "n/a"
            print(f"  {arm:24} ~{info['tokens']:>5} tok   {ratio:>14}   {info['detail']}")
        if args.show:
            for arm, info in result.items():
                print(f"\n  --- {arm} ---")
                print("\n".join("  " + line for line in info["show"].split("\n")))


if __name__ == "__main__":
    main()
