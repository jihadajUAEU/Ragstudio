from __future__ import annotations

from collections import defaultdict

from ragstudio.services.canonical_assembly import EvidenceBlockView


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
