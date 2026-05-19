from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from ragstudio.services.canonical_assembly import EvidenceBlockView


@dataclass(frozen=True)
class ReferenceWindow:
    anchor: EvidenceBlockView
    body_blocks: tuple[EvidenceBlockView, ...]
    next_anchor: EvidenceBlockView | None = None
    previous_anchor: EvidenceBlockView | None = None


class EvidenceGraph:
    def __init__(self, blocks: list[EvidenceBlockView]) -> None:
        self.blocks = blocks
        self._index_by_key = {
            block.source_ref.key: index for index, block in enumerate(blocks)
        }
        self._blocks_by_page: dict[int, list[EvidenceBlockView]] = defaultdict(list)
        for block in blocks:
            if block.page_start is not None:
                self._blocks_by_page[block.page_start].append(block)

    @classmethod
    def from_blocks(cls, blocks: list[EvidenceBlockView]) -> EvidenceGraph:
        return cls(list(blocks))

    def index_of(self, block: EvidenceBlockView) -> int | None:
        return self._index_by_key.get(block.source_ref.key)

    def neighborhood(
        self,
        block: EvidenceBlockView,
        *,
        before: int,
        after: int,
    ) -> list[EvidenceBlockView]:
        index = self.index_of(block)
        if index is None:
            return []
        start = max(0, index - before)
        end = min(len(self.blocks), index + after + 1)
        return [
            candidate
            for candidate in self.blocks[start:end]
            if candidate.source_ref.key != block.source_ref.key
        ]

    def page_blocks(self, page: int) -> list[EvidenceBlockView]:
        return list(self._blocks_by_page.get(page, []))

    def blocks_with_script(self, script: str) -> list[EvidenceBlockView]:
        return [block for block in self.blocks if script in block.scripts]

    def visual_window_after_anchor(
        self,
        anchor: EvidenceBlockView,
        *,
        is_anchor: Callable[[EvidenceBlockView], bool],
        accepts_body: Callable[[EvidenceBlockView], bool],
        max_page_gap: int | None,
    ) -> ReferenceWindow:
        anchor_index = self.index_of(anchor)
        if anchor_index is None:
            return ReferenceWindow(anchor=anchor, body_blocks=())

        body_blocks: list[EvidenceBlockView] = []
        next_anchor: EvidenceBlockView | None = None
        for candidate in self.blocks[anchor_index + 1 :]:
            if not candidate.has_text:
                continue
            if is_anchor(candidate):
                next_anchor = candidate
                break
            if not self._within_page_gap(anchor, candidate, max_page_gap=max_page_gap):
                break
            if accepts_body(candidate):
                body_blocks.append(candidate)

        previous_anchor = next(
            (
                candidate
                for candidate in reversed(self.blocks[:anchor_index])
                if candidate.has_text and is_anchor(candidate)
            ),
            None,
        )
        return ReferenceWindow(
            anchor=anchor,
            body_blocks=tuple(body_blocks),
            next_anchor=next_anchor,
            previous_anchor=previous_anchor,
        )

    def visual_window_before_anchor(
        self,
        anchor: EvidenceBlockView,
        *,
        is_anchor: Callable[[EvidenceBlockView], bool],
        accepts_body: Callable[[EvidenceBlockView], bool],
        max_page_gap: int | None,
    ) -> ReferenceWindow:
        anchor_index = self.index_of(anchor)
        if anchor_index is None:
            return ReferenceWindow(anchor=anchor, body_blocks=())

        body_blocks: list[EvidenceBlockView] = []
        previous_anchor: EvidenceBlockView | None = None
        for candidate in reversed(self.blocks[:anchor_index]):
            if not candidate.has_text:
                continue
            if is_anchor(candidate):
                previous_anchor = candidate
                break
            if not self._within_page_gap(anchor, candidate, max_page_gap=max_page_gap):
                break
            if accepts_body(candidate):
                body_blocks.append(candidate)

        next_anchor = next(
            (
                candidate
                for candidate in self.blocks[anchor_index + 1 :]
                if candidate.has_text and is_anchor(candidate)
            ),
            None,
        )
        return ReferenceWindow(
            anchor=anchor,
            body_blocks=tuple(reversed(body_blocks)),
            next_anchor=next_anchor,
            previous_anchor=previous_anchor,
        )

    def _within_page_gap(
        self,
        anchor: EvidenceBlockView,
        candidate: EvidenceBlockView,
        *,
        max_page_gap: int | None,
    ) -> bool:
        if max_page_gap is None:
            return True
        anchor_page = anchor.page_start
        candidate_page = candidate.page_end if candidate.page_end is not None else candidate.page_start
        if anchor_page is None or candidate_page is None:
            return True
        return abs(candidate_page - anchor_page) <= max_page_gap
