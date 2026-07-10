"""Selection: a set of stroke ids, resolvable against a page."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from neeh.document import Page
from neeh.ink import BoundingBox


@dataclass
class Selection:
    stroke_ids: set[str] = field(default_factory=set)

    def __bool__(self) -> bool:
        return bool(self.stroke_ids)

    def __len__(self) -> int:
        return len(self.stroke_ids)

    def __contains__(self, stroke_id: str) -> bool:
        return stroke_id in self.stroke_ids

    def replace(self, ids: Iterable[str]) -> None:
        self.stroke_ids = set(ids)

    def add(self, ids: Iterable[str]) -> None:
        self.stroke_ids.update(ids)

    def discard(self, ids: Iterable[str]) -> None:
        self.stroke_ids.difference_update(ids)

    def clear(self) -> None:
        self.stroke_ids.clear()

    def bounds(self, page: Page) -> Optional[BoundingBox]:
        boxes = []
        for stroke_id in self.stroke_ids:
            found = page.find(stroke_id)
            if found is not None:
                boxes.append(found[1].bbox)
        return BoundingBox.union_all(boxes)
