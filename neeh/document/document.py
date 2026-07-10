"""The document: an ordered collection of pages plus metadata.

`to_dict()` is an internal JSON snapshot — versioned for ourselves, no
compatibility promise. Persistence and interchange target the Universal Ink
Model (UIM) via `neeh/adapters` (see ARCHITECTURE.md).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from neeh.document.page import Page
from neeh.ids import new_id

FORMAT_VERSION = "neeh/5.0-draft"


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Document:
    title: str = "Untitled"
    id: str = field(default_factory=lambda: new_id("doc"))
    created_at_ms: int = field(default_factory=_now_ms)
    pages: list[Page] = field(default_factory=lambda: [Page()])

    def new_page(self, **kwargs: Any) -> Page:
        page = Page(**kwargs)
        self.pages.append(page)
        return page

    def page(self, key: Union[int, str]) -> Optional[Page]:
        if isinstance(key, int):
            return self.pages[key] if 0 <= key < len(self.pages) else None
        for page in self.pages:
            if page.id == key:
                return page
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": FORMAT_VERSION,
            "id": self.id,
            "title": self.title,
            "created_at_ms": self.created_at_ms,
            "pages": [page.to_dict() for page in self.pages],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Document":
        fmt = data.get("format", "")
        if not fmt.startswith("neeh/"):
            raise ValueError(f"not a neeh document (format={fmt!r})")
        return cls(
            id=data["id"],
            title=data.get("title", "Untitled"),
            created_at_ms=data.get("created_at_ms", 0),
            pages=[Page.from_dict(p) for p in data.get("pages", [])],
        )

    def to_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "Document":
        return cls.from_dict(json.loads(text))

    def save(self, path: Union[str, Path]) -> None:
        Path(path).write_text(self.to_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Union[str, Path]) -> "Document":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))
