"""Automatic scorers (protocol §4). All scores are in [0, 1], higher is better."""
from __future__ import annotations

import re

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s-]")


def normalize(text: str) -> str:
    return _WS.sub(" ", _PUNCT.sub("", text.strip().lower())).strip()


def _levenshtein(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(
                previous[j] + 1,        # deletion
                current[j - 1] + 1,     # insertion
                previous[j - 1] + (ca != cb),  # substitution
            ))
        previous = current
    return previous[-1]


def score_cer(answer: str, truth: str) -> float:
    """1 - character error rate, clamped to [0, 1], on normalized strings."""
    answer_n, truth_n = normalize(answer), normalize(truth)
    if not truth_n:
        return 1.0 if not answer_n else 0.0
    cer = _levenshtein(answer_n, truth_n) / len(truth_n)
    return max(0.0, 1.0 - cer)


def score_exact(answer: str, truth: str) -> float:
    return 1.0 if normalize(answer) == normalize(truth) else 0.0


def score_cer_raw(answer: str, truth: str) -> float:
    """CER preserving case and punctuation (LaTeX truths); whitespace collapsed.

    Also tolerates a markdown/LaTeX-fenced reply: strips one layer of $...$,
    $$...$$, \\(...\\), \\[...\\], or backticks before scoring.
    """
    answer_n = _WS.sub(" ", _strip_math_fence(answer.strip())).strip()
    truth_n = _WS.sub(" ", truth.strip()).strip()
    if not truth_n:
        return 1.0 if not answer_n else 0.0
    cer = _levenshtein(answer_n, truth_n) / len(truth_n)
    return max(0.0, 1.0 - cer)


def _strip_math_fence(text: str) -> str:
    for open_fence, close_fence in (
        ("$$", "$$"), ("$", "$"), ("\\(", "\\)"), ("\\[", "\\]"), ("`", "`"),
    ):
        if (
            text.startswith(open_fence)
            and text.endswith(close_fence)
            and len(text) > len(open_fence) + len(close_fence)
        ):
            return text[len(open_fence):-len(close_fence)].strip()
    return text


_ID = re.compile(r"st_[A-Za-z0-9_]+")


def score_set_f1(answer: str, truth: list[str]) -> float:
    """F1 between the stroke ids found in the answer and the truth set."""
    predicted = set(_ID.findall(answer))
    expected = set(truth)
    if not predicted and not expected:
        return 1.0
    if not predicted or not expected:
        return 0.0
    hits = len(predicted & expected)
    if hits == 0:
        return 0.0
    precision = hits / len(predicted)
    recall = hits / len(expected)
    return 2 * precision * recall / (precision + recall)


def score(scorer: str, answer: str, truth) -> float:
    if scorer == "cer":
        return score_cer(answer, truth)
    if scorer == "cer_raw":
        return score_cer_raw(answer, truth)
    if scorer == "exact":
        return score_exact(answer, truth)
    if scorer == "set_f1":
        return score_set_f1(answer, truth)
    raise ValueError(f"unknown scorer {scorer!r}")
