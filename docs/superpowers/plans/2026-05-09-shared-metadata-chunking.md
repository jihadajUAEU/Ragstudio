# Shared Metadata Chunking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a shared metadata-driven chunking layer so MinerU, local fallback, and runtime parser output cannot persist oversized single chunks.

**Architecture:** Create a focused `ChunkSplitter` service that accepts parser `AdapterChunk`s plus `DomainMetadata` and returns retrieval-sized `AdapterChunk`s with preserved metadata. Wire it into `ChunkService.index_document()` immediately after parser normalization and before database persistence. Keep MinerU artifact parsing in `MinerUClient`, but enrich MinerU chunks with artifact extraction context so the splitter can use `source_content_list` hints when available.

**Tech Stack:** Python 3.12, FastAPI service layer, SQLAlchemy async tests, pytest, existing `AdapterChunk` runtime type, Docker Compose backend test runner.

---

## File Structure

- Create: `backend/src/ragstudio/services/chunk_splitter.py`
  - Owns deterministic metadata-driven chunk profiles.
  - Splits text by markdown headings, page/verse markers, paragraph boundaries, then hard word caps.
  - Preserves parser/domain metadata and appends split metadata.
  - Optionally reads MinerU `source_content_list.json`/`source_content_list_v2.json` via safe artifact paths.
- Create: `backend/tests/test_chunk_splitter.py`
  - Unit tests for profile selection, hard caps, metadata preservation, and invalid content-list fallback.
- Modify: `backend/src/ragstudio/services/chunk_service.py`
  - Calls `ChunkSplitter.split()` after `_adapter_chunks()` and before deleting/persisting existing chunks.
  - Applies shared splitting to local fallback and MinerU paths.
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py`
  - Calls `ChunkSplitter.split()` after runtime chunks are normalized to `AdapterChunk`s and before database persistence.
  - Applies the same shared hard-cap protection to runtime indexing.
- Modify: `backend/src/ragstudio/services/mineru_client.py`
  - Adds safe extraction metadata to MinerU parser metadata: `artifact_extract_dir` and `content_list_ref` when present.
  - Keeps existing artifact safety checks.
- Modify: `backend/tests/test_mineru_client.py`
  - Adds regression coverage for one huge MinerU markdown artifact becoming many chunks when passed through the splitter context.
- Modify: `backend/tests/test_chunks.py`
  - Adds integration coverage that `ChunkService` persists multiple chunks from one oversized adapter chunk and carries domain metadata.
- Modify: `backend/tests/test_index_lifecycle_service.py`
  - Adds runtime indexing coverage for oversized runtime chunks.

No frontend changes are required.

---

### Task 1: Add ChunkSplitter Unit Tests

**Files:**
- Create: `backend/tests/test_chunk_splitter.py`

- [ ] **Step 1: Write failing unit tests**

Create `backend/tests/test_chunk_splitter.py` with:

```python
from pathlib import Path

from ragstudio.schemas.parsing import DomainMetadata, ParserMode
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_splitter import ChunkSplitter


def words(count: int, prefix: str = "word") -> str:
    return " ".join(f"{prefix}{index}" for index in range(count))


def test_chunk_splitter_splits_tafseer_book_markdown_under_hard_cap():
    text = "\n\n".join(
        [
            "# Tafsir Ibn Kathir",
            "## Surah 1",
            f"Verse 1:1\n\n{words(900, 'alpha')}",
            f"Verse 1:2\n\n{words(900, 'beta')}",
            "## Surah 2",
            f"Verse 2:1\n\n{words(900, 'gamma')}",
        ]
    )
    chunk = AdapterChunk(
        text=text,
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "parser_mode": "mineru_strict",
                "artifact_ref": "source/auto/source.md",
                "chunk_index": 0,
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="tafseer", document_type="book"),
        parser_mode="mineru_strict",
    )

    assert len(split) == 3
    assert all(len(item.text.split()) <= 1500 for item in split)
    assert split[0].text.startswith("# Tafsir Ibn Kathir")
    assert split[1].text.startswith("Verse 1:2")
    parser_metadata = split[0].metadata["parser_metadata"]
    assert parser_metadata["backend"] == "mineru"
    assert parser_metadata["split_strategy"] == "metadata_profile"
    assert parser_metadata["split_profile"] == "tafseer_book"
    assert parser_metadata["parent_artifact_ref"] == "source/auto/source.md"
    assert parser_metadata["parent_chunk_index"] == 0
    assert parser_metadata["split_index"] == 0
    assert parser_metadata["split_count"] == 3


def test_chunk_splitter_hard_splits_single_oversized_paragraph():
    chunk = AdapterChunk(
        text=words(3100),
        source_location={"artifact": "plain.txt"},
        metadata={"parser_metadata": {"backend": "fallback", "chunk_index": 4}},
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="generic", document_type="document"),
        parser_mode="local_fallback",
    )

    assert [len(item.text.split()) for item in split] == [1500, 1500, 100]
    assert split[2].metadata["parser_metadata"]["split_index"] == 2
    assert split[2].metadata["parser_metadata"]["split_count"] == 3
    assert split[2].metadata["parser_metadata"]["split_profile"] == "generic"


def test_chunk_splitter_preserves_small_chunks_unchanged():
    chunk = AdapterChunk(
        text="short text",
        source_location={"page": 1},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 2}},
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="tafseer", document_type="book"),
        parser_mode="mineru_strict",
    )

    assert len(split) == 1
    assert split[0].text == "short text"
    assert split[0].source_location == {"page": 1}
    assert split[0].metadata["parser_metadata"]["chunk_index"] == 2
    assert "split_strategy" not in split[0].metadata["parser_metadata"]


def test_chunk_splitter_uses_mineru_content_list_when_available(tmp_path: Path):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        """
        [
          {"type":"text","text":"Page one heading","page_idx":0},
          {"type":"text","text":"Page one body","page_idx":0},
          {"type":"text","text":"Page two heading","page_idx":1},
          {"type":"text","text":"Page two body","page_idx":1}
        ]
        """,
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_ref": "source/auto/source.md",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "chunk_index": 0,
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="tafseer", document_type="book"),
        parser_mode="mineru_strict",
    )

    assert [item.text for item in split] == [
        "Page one heading\n\nPage one body",
        "Page two heading\n\nPage two body",
    ]
    assert split[0].source_location["page_start"] == 1
    assert split[0].source_location["page_end"] == 1
    assert split[1].source_location["page_start"] == 2
    assert split[1].source_location["page_end"] == 2


def test_chunk_splitter_invalid_content_list_falls_back_to_markdown(tmp_path: Path):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text("{not json", encoding="utf-8")
    chunk = AdapterChunk(
        text=f"## Section\n\n{words(1600)}",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "chunk_index": 0,
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="tafseer", document_type="book"),
        parser_mode="mineru_strict",
    )

    assert len(split) == 2
    assert all(len(item.text.split()) <= 1500 for item in split)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
docker compose run --rm -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_chunk_splitter.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.chunk_splitter'`.

- [ ] **Step 3: Leave failing tests uncommitted**

Run:

```bash
git status --short backend/tests/test_chunk_splitter.py
```

Expected: `?? backend/tests/test_chunk_splitter.py`.

---

### Task 2: Implement ChunkSplitter

**Files:**
- Create: `backend/src/ragstudio/services/chunk_splitter.py`
- Test: `backend/tests/test_chunk_splitter.py`

- [ ] **Step 1: Create the splitter implementation**

Create `backend/src/ragstudio/services/chunk_splitter.py` with:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata, ParserMode
from ragstudio.services.adapter import AdapterChunk


@dataclass(frozen=True)
class ChunkProfile:
    name: str
    target_words: int
    hard_max_words: int


class ChunkSplitter:
    def __init__(self, *, max_words: int = 1500):
        self.max_words = max_words

    def split(
        self,
        chunks: list[AdapterChunk],
        *,
        domain_metadata: DomainMetadata,
        parser_mode: ParserMode,
    ) -> list[AdapterChunk]:
        profile = self._profile(domain_metadata)
        output: list[AdapterChunk] = []
        for chunk in chunks:
            pieces = self._split_chunk(chunk, profile)
            if len(pieces) == 1 and pieces[0].text == chunk.text:
                output.append(chunk)
                continue
            split_count = len(pieces)
            for split_index, piece in enumerate(pieces):
                output.append(
                    self._with_split_metadata(
                        piece,
                        parent=chunk,
                        profile=profile,
                        split_index=split_index,
                        split_count=split_count,
                    )
                )
        return [item for item in output if item.text.strip()]

    def _profile(self, metadata: DomainMetadata) -> ChunkProfile:
        domain = (metadata.domain or "").casefold()
        document_type = (metadata.document_type or "").casefold()
        if domain == "tafseer" or document_type == "book":
            return ChunkProfile("tafseer_book", target_words=1000, hard_max_words=self.max_words)
        if domain == "quran":
            return ChunkProfile("quran_verse", target_words=500, hard_max_words=900)
        if document_type == "paper":
            return ChunkProfile("paper_section", target_words=800, hard_max_words=1200)
        if document_type == "table":
            return ChunkProfile("table_block", target_words=400, hard_max_words=800)
        return ChunkProfile("generic", target_words=1000, hard_max_words=self.max_words)

    def _split_chunk(self, chunk: AdapterChunk, profile: ChunkProfile) -> list[AdapterChunk]:
        content_list_chunks = self._chunks_from_content_list(chunk, profile)
        if content_list_chunks:
            return content_list_chunks
        sections = self._markdown_sections(chunk.text)
        pieces = self._pack_sections(sections, profile)
        return [
            AdapterChunk(text=text, source_location=dict(chunk.source_location), metadata=dict(chunk.metadata))
            for text in pieces
            if text.strip()
        ]

    def _chunks_from_content_list(
        self,
        chunk: AdapterChunk,
        profile: ChunkProfile,
    ) -> list[AdapterChunk]:
        parser_metadata = self._parser_metadata(chunk)
        extract_dir = parser_metadata.get("artifact_extract_dir")
        content_ref = parser_metadata.get("content_list_ref")
        if not isinstance(extract_dir, str) or not isinstance(content_ref, str):
            return []
        root = Path(extract_dir).resolve()
        target = (root / content_ref).resolve()
        if root not in target.parents and target != root:
            return []
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        page_parts: dict[int, list[str]] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            page_idx = item.get("page_idx")
            if not isinstance(text, str) or not text.strip() or not isinstance(page_idx, int):
                continue
            page_parts.setdefault(page_idx + 1, []).append(text.strip())
        chunks: list[AdapterChunk] = []
        for page in sorted(page_parts):
            text = "\n\n".join(page_parts[page])
            for part in self._hard_split_text(text, profile.hard_max_words):
                source_location = dict(chunk.source_location)
                source_location["page_start"] = page
                source_location["page_end"] = page
                chunks.append(
                    AdapterChunk(
                        text=part,
                        source_location=source_location,
                        metadata=dict(chunk.metadata),
                    )
                )
        return chunks

    def _markdown_sections(self, text: str) -> list[str]:
        blocks = [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]
        sections: list[str] = []
        current: list[str] = []
        for block in blocks:
            starts_boundary = bool(
                re.match(r"^#{1,6}\s+", block) or re.match(r"^Verse\s+\d+:\d+", block)
            )
            if starts_boundary and current:
                sections.append("\n\n".join(current).strip())
                current = []
            current.append(block)
        if current:
            sections.append("\n\n".join(current).strip())
        return sections or [text.strip()]

    def _pack_sections(self, sections: list[str], profile: ChunkProfile) -> list[str]:
        packed: list[str] = []
        current: list[str] = []
        current_words = 0
        for section in sections:
            section_parts = self._hard_split_text(section, profile.hard_max_words)
            for part in section_parts:
                part_words = self._word_count(part)
                if current and current_words + part_words > profile.target_words:
                    packed.append("\n\n".join(current).strip())
                    current = []
                    current_words = 0
                current.append(part)
                current_words += part_words
                if current_words >= profile.hard_max_words:
                    packed.append("\n\n".join(current).strip())
                    current = []
                    current_words = 0
        if current:
            packed.append("\n\n".join(current).strip())
        return packed

    def _hard_split_text(self, text: str, hard_max_words: int) -> list[str]:
        words = text.split()
        if len(words) <= hard_max_words:
            return [text.strip()] if text.strip() else []
        return [
            " ".join(words[index : index + hard_max_words])
            for index in range(0, len(words), hard_max_words)
        ]

    def _with_split_metadata(
        self,
        piece: AdapterChunk,
        *,
        parent: AdapterChunk,
        profile: ChunkProfile,
        split_index: int,
        split_count: int,
    ) -> AdapterChunk:
        metadata = dict(piece.metadata)
        parser_metadata = dict(self._parser_metadata(piece))
        parent_parser_metadata = self._parser_metadata(parent)
        parser_metadata.update(
            {
                "split_strategy": "metadata_profile",
                "split_profile": profile.name,
                "parent_artifact_ref": parent_parser_metadata.get("artifact_ref")
                or parent.source_location.get("artifact"),
                "parent_chunk_index": parent_parser_metadata.get("chunk_index"),
                "split_index": split_index,
                "split_count": split_count,
                "chunk_index": split_index,
            }
        )
        metadata["parser_metadata"] = parser_metadata
        return AdapterChunk(
            text=piece.text,
            source_location=dict(piece.source_location),
            metadata=metadata,
        )

    def _parser_metadata(self, chunk: AdapterChunk) -> dict[str, Any]:
        value = chunk.metadata.get("parser_metadata")
        return dict(value) if isinstance(value, dict) else {}

    def _word_count(self, text: str) -> int:
        return len(text.split())
```

- [ ] **Step 2: Run splitter tests**

Run:

```bash
docker compose run --rm -v "$PWD/backend/src:/app/backend/src" -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_chunk_splitter.py -q
```

Expected: PASS.

- [ ] **Step 3: Commit splitter unit**

Run:

```bash
git add backend/src/ragstudio/services/chunk_splitter.py backend/tests/test_chunk_splitter.py
git commit -m "feat: add metadata driven chunk splitter"
```

Expected: commit succeeds.

---

### Task 3: Wire Splitter Into ChunkService

**Files:**
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Modify: `backend/tests/test_chunks.py`

- [ ] **Step 1: Add integration test for oversized local adapter chunk**

Append this test near `test_index_mineru_strict_uses_adapter_chunks` in `backend/tests/test_chunks.py`:

```python
@pytest.mark.asyncio
async def test_index_document_splits_oversized_adapter_chunk(client, monkeypatch):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("large.txt", b"seed", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    async def fake_adapter_chunks(self, document, options, *, on_mineru_status=None):
        from ragstudio.services.adapter import AdapterChunk

        return [
            AdapterChunk(
                text=" ".join(f"token{index}" for index in range(3100)),
                source_location={"artifact": "large.txt"},
                metadata={"parser_metadata": {"backend": "fallback", "chunk_index": 0}},
            )
        ]

    monkeypatch.setattr(
        "ragstudio.services.chunk_service.ChunkService._adapter_chunks",
        fake_adapter_chunks,
    )

    app = client._transport.app
    async with app.state.session_factory() as session:
        chunks = await ChunkService(session, app.state.settings.data_dir).index_document(
            document_id,
            options=IndexDocumentIn(
                parser_mode="local_fallback",
                domain_metadata={"domain": "generic", "document_type": "document"},
            ),
        )

    assert chunks is not None
    assert len(chunks) == 3
    assert [len(chunk.text.split()) for chunk in chunks] == [1500, 1500, 100]
    assert chunks[0].metadata["domain_metadata"]["domain"] == "generic"
    assert chunks[0].metadata["parser_metadata"]["split_strategy"] == "metadata_profile"
    assert chunks[0].metadata["parser_metadata"]["split_profile"] == "generic"
```

- [ ] **Step 2: Run integration test to verify failure**

Run:

```bash
docker compose run --rm -v "$PWD/backend/src:/app/backend/src" -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_chunks.py::test_index_document_splits_oversized_adapter_chunk -q
```

Expected: FAIL because `ChunkService` still persists one oversized adapter chunk.

- [ ] **Step 3: Wire `ChunkSplitter` into `ChunkService`**

In `backend/src/ragstudio/services/chunk_service.py`, add import:

```python
from ragstudio.services.chunk_splitter import ChunkSplitter
```

Then replace:

```python
        adapter_chunks = await self._adapter_chunks(
            document,
            options,
            on_mineru_status=on_mineru_status,
        )
```

with:

```python
        raw_adapter_chunks = await self._adapter_chunks(
            document,
            options,
            on_mineru_status=on_mineru_status,
        )
        adapter_chunks = ChunkSplitter().split(
            raw_adapter_chunks,
            domain_metadata=options.domain_metadata,
            parser_mode=options.parser_mode,
        )
```

- [ ] **Step 4: Run integration test**

Run:

```bash
docker compose run --rm -v "$PWD/backend/src:/app/backend/src" -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_chunks.py::test_index_document_splits_oversized_adapter_chunk -q
```

Expected: PASS.

- [ ] **Step 5: Commit service wiring**

Run:

```bash
git add backend/src/ragstudio/services/chunk_service.py backend/tests/test_chunks.py
git commit -m "feat: apply shared chunk splitting during indexing"
```

Expected: commit succeeds.

---

### Task 4: Add MinerU Artifact Hint Metadata

**Files:**
- Modify: `backend/src/ragstudio/services/mineru_client.py`
- Modify: `backend/tests/test_mineru_client.py`

- [ ] **Step 1: Add failing MinerU metadata test**

Append this test to `backend/tests/test_mineru_client.py`:

```python
def test_mineru_client_adds_extract_dir_and_content_list_refs(tmp_path):
    artifact_zip = tmp_path / "artifact.zip"
    with ZipFile(artifact_zip, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "files": [
                        {"path": "source/auto/source.md", "kind": "markdown"},
                        {"path": "source/auto/source_content_list.json", "kind": "json"},
                    ]
                }
            ),
        )
        archive.writestr("source/auto/source.md", "Alpha")
        archive.writestr("source/auto/source_content_list.json", "[]")

    client = MinerUClient(base_url="http://mineru.test", timeout_ms=1000, poll_interval_ms=100)
    extract_dir = tmp_path / "extract"
    chunks = client.normalize_artifact_zip(
        artifact_zip=artifact_zip,
        extract_dir=extract_dir,
        document_id="doc-1",
        parser_mode="mineru_strict",
        parse_job_id="job-1",
    )

    parser_metadata = chunks[0].metadata["parser_metadata"]
    assert parser_metadata["artifact_extract_dir"] == str(extract_dir.resolve())
    assert parser_metadata["content_list_ref"] == "source/auto/source_content_list.json"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
docker compose run --rm -v "$PWD/backend/src:/app/backend/src" -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_mineru_client.py::test_mineru_client_adds_extract_dir_and_content_list_refs -q
```

Expected: FAIL with missing `artifact_extract_dir` or `content_list_ref`.

- [ ] **Step 3: Implement content-list discovery**

In `backend/src/ragstudio/services/mineru_client.py`, add this helper method inside `MinerUClient`:

```python
    def _content_list_ref(self, manifest: dict[str, Any], extract_dir: Path) -> str | None:
        candidates: list[str] = []
        for item in [*self._raw_manifest_entries(manifest, "files"), *self._raw_manifest_entries(manifest, "items")]:
            path = str(item.get("path") or "")
            if path.endswith(("source_content_list.json", "source_content_list_v2.json")):
                candidates.append(path)
        if not candidates:
            candidates = [
                path.relative_to(extract_dir).as_posix()
                for path in sorted(extract_dir.rglob("source_content_list*.json"))
            ]
        for candidate in candidates:
            safe_path = self._safe_manifest_path(extract_dir, candidate)
            if safe_path.exists() and safe_path.is_file():
                return safe_path.relative_to(extract_dir.resolve()).as_posix()
        return None
```

Then in `normalize_artifact_zip()`, after `related_artifacts = ...`, add:

```python
        content_list_ref = self._content_list_ref(manifest, extract_dir)
```

Inside the `parser_metadata` dict, add:

```python
                            "artifact_extract_dir": str(extract_dir.resolve()),
                            "content_list_ref": content_list_ref,
```

- [ ] **Step 4: Run MinerU tests**

Run:

```bash
docker compose run --rm -v "$PWD/backend/src:/app/backend/src" -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_mineru_client.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit MinerU hint metadata**

Run:

```bash
git add backend/src/ragstudio/services/mineru_client.py backend/tests/test_mineru_client.py
git commit -m "feat: expose mineru content list hints for chunking"
```

Expected: commit succeeds.

---

### Task 5: Add MinerU Huge Markdown Regression Test

**Files:**
- Modify: `backend/tests/test_chunks.py`

- [ ] **Step 1: Add regression test for huge MinerU markdown through `ChunkService`**

Append this test in `backend/tests/test_chunks.py` after `test_index_mineru_strict_uses_adapter_chunks`:

```python
@pytest.mark.asyncio
async def test_index_mineru_strict_splits_single_huge_markdown_artifact(client, monkeypatch):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("tafseer.pdf", b"%PDF fake", "application/pdf")},
    )
    document_id = upload_response.json()["id"]

    async def fake_mineru_adapter_chunks(self, document_id, *, options, on_mineru_status=None):
        from ragstudio.services.adapter import AdapterChunk

        text = "\n\n".join(
            [
                "# Tafsir Ibn Kathir",
                "## Surah 1",
                "Verse 1:1\n\n" + " ".join(f"alpha{index}" for index in range(900)),
                "Verse 1:2\n\n" + " ".join(f"beta{index}" for index in range(900)),
                "## Surah 2",
                "Verse 2:1\n\n" + " ".join(f"gamma{index}" for index in range(900)),
            ]
        )
        return [
            AdapterChunk(
                text=text,
                source_location={"artifact": "source/auto/source.md"},
                metadata={
                    "parser_metadata": {
                        "backend": "mineru",
                        "parser_mode": "mineru_strict",
                        "artifact_ref": "source/auto/source.md",
                        "chunk_index": 0,
                    }
                },
            )
        ]

    monkeypatch.setattr(
        "ragstudio.services.chunk_service.ChunkService._mineru_adapter_chunks",
        fake_mineru_adapter_chunks,
    )

    app = client._transport.app
    async with app.state.session_factory() as session:
        chunks = await ChunkService(session, app.state.settings.data_dir).index_document(
            document_id,
            options=IndexDocumentIn(
                parser_mode="mineru_strict",
                domain_metadata={
                    "domain": "tafseer",
                    "document_type": "book",
                    "tags": ["tafseer", "quran"],
                },
            ),
        )

    assert chunks is not None
    assert len(chunks) == 3
    assert all(len(chunk.text.split()) <= 1500 for chunk in chunks)
    assert chunks[0].metadata["domain_metadata"]["domain"] == "tafseer"
    assert chunks[0].metadata["parser_metadata"]["backend"] == "mineru"
    assert chunks[0].metadata["parser_metadata"]["split_profile"] == "tafseer_book"
    assert chunks[0].metadata["parser_metadata"]["parent_artifact_ref"] == "source/auto/source.md"
```

- [ ] **Step 2: Run regression test**

Run:

```bash
docker compose run --rm -v "$PWD/backend/src:/app/backend/src" -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_chunks.py::test_index_mineru_strict_splits_single_huge_markdown_artifact -q
```

Expected: PASS.

- [ ] **Step 3: Run chunk-related tests**

Run:

```bash
docker compose run --rm -v "$PWD/backend/src:/app/backend/src" -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_chunk_splitter.py backend/tests/test_mineru_client.py backend/tests/test_chunks.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit regression test**

Run:

```bash
git add backend/tests/test_chunks.py
git commit -m "test: cover mineru huge markdown chunk splitting"
```

Expected: commit succeeds.

---

### Task 6: Wire Splitter Into Runtime Index Lifecycle

**Files:**
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py`
- Modify: `backend/tests/test_index_lifecycle_service.py`

- [ ] **Step 1: Add failing runtime lifecycle test**

Append this test to `backend/tests/test_index_lifecycle_service.py` after `test_lifecycle_deletes_existing_chunks_and_mirrors_runtime_chunks`:

```python
@pytest.mark.asyncio
async def test_lifecycle_splits_oversized_runtime_chunks(client):
    app = client._transport.app
    runtime = FakeRuntime(
        [
            RuntimeChunk(
                text=" ".join(f"runtime{index}" for index in range(3100)),
                source_location={"artifact": "runtime.md"},
                metadata={"backend": "runtime", "chunk_index": 0},
                runtime_source_id="runtime-large",
                content_type="text",
                preview_ref="preview://runtime-large",
            )
        ]
    )
    artifact_path = app.state.settings.data_dir / "large-runtime.txt"
    artifact_path.write_text("runtime text", encoding="utf-8")

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="large-runtime.txt",
            content_type="text/plain",
            sha256="runtime-large",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.commit()

        chunks = await IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
        ).reindex_document(
            document.id,
            options=IndexDocumentIn(
                parser_mode="local_fallback",
                domain_metadata={"domain": "generic", "document_type": "document"},
            ),
        )

        stored = (
            await session.execute(select(Chunk).where(Chunk.document_id == document.id))
        ).scalars().all()
        record = (
            await session.execute(select(IndexRecord).where(IndexRecord.document_id == document.id))
        ).scalar_one()

    assert chunks is not None
    assert len(chunks) == 3
    assert len(stored) == 3
    assert record.chunk_count == 3
    assert [len(chunk.text.split()) for chunk in chunks] == [1500, 1500, 100]
    assert chunks[0].metadata["domain_metadata"]["domain"] == "generic"
    assert chunks[0].metadata["parser_metadata"]["split_strategy"] == "metadata_profile"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
docker compose run --rm -v "$PWD/backend/src:/app/backend/src" -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_index_lifecycle_service.py::test_lifecycle_splits_oversized_runtime_chunks -q
```

Expected: FAIL because `IndexLifecycleService` still persists one oversized runtime chunk.

- [ ] **Step 3: Wire `ChunkSplitter` into `IndexLifecycleService`**

In `backend/src/ragstudio/services/index_lifecycle_service.py`, add imports:

```python
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_splitter import ChunkSplitter
```

Replace the loop that normalizes and appends chunks:

```python
        chunks: list[Chunk] = []
        for runtime_chunk in runtime_chunks:
            adapter_chunk = self.normalizer.chunk_to_adapter_chunk(
                runtime_chunk,
                document_id=document.id,
                runtime_profile_id=profile.id,
                index_shape=profile.index_shape,
            )
            chunks.append(
                Chunk(
                    document_id=document.id,
                    text=sanitize_db_text(adapter_chunk.text),
                    source_location=sanitize_db_value(adapter_chunk.source_location),
                    metadata_json=sanitize_db_value(
                        self._merge_options_metadata(adapter_chunk.metadata, options)
                    ),
                    runtime_profile_id=profile.id,
                    runtime_source_id=sanitize_db_value(
                        adapter_chunk.metadata.get("runtime_source_id")
                    ),
                    content_type=sanitize_db_text(
                        str(adapter_chunk.metadata.get("content_type") or "text")
                    ),
                    preview_ref=sanitize_db_value(adapter_chunk.metadata.get("preview_ref")),
                    indexed_at=indexed_at,
                )
            )
```

with:

```python
        normalized_chunks: list[AdapterChunk] = [
            self.normalizer.chunk_to_adapter_chunk(
                runtime_chunk,
                document_id=document.id,
                runtime_profile_id=profile.id,
                index_shape=profile.index_shape,
            )
            for runtime_chunk in runtime_chunks
        ]
        adapter_chunks = ChunkSplitter().split(
            normalized_chunks,
            domain_metadata=options.domain_metadata,
            parser_mode=options.parser_mode,
        )
        chunks: list[Chunk] = []
        for adapter_chunk in adapter_chunks:
            chunks.append(
                Chunk(
                    document_id=document.id,
                    text=sanitize_db_text(adapter_chunk.text),
                    source_location=sanitize_db_value(adapter_chunk.source_location),
                    metadata_json=sanitize_db_value(
                        self._merge_options_metadata(adapter_chunk.metadata, options)
                    ),
                    runtime_profile_id=profile.id,
                    runtime_source_id=sanitize_db_value(
                        adapter_chunk.metadata.get("runtime_source_id")
                    ),
                    content_type=sanitize_db_text(
                        str(adapter_chunk.metadata.get("content_type") or "text")
                    ),
                    preview_ref=sanitize_db_value(adapter_chunk.metadata.get("preview_ref")),
                    indexed_at=indexed_at,
                )
            )
```

- [ ] **Step 4: Run runtime lifecycle tests**

Run:

```bash
docker compose run --rm -v "$PWD/backend/src:/app/backend/src" -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_index_lifecycle_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit runtime wiring**

Run:

```bash
git add backend/src/ragstudio/services/index_lifecycle_service.py backend/tests/test_index_lifecycle_service.py
git commit -m "feat: apply shared chunk splitting to runtime indexing"
```

Expected: commit succeeds.

---

### Task 7: Update Documentation and Excel Finding Notes

**Files:**
- Modify: `docs/workflows.md`
- Modify: `docs/user-guide.md`

- [ ] **Step 1: Add documentation note to `docs/workflows.md`**

Add this paragraph near the document indexing/MinerU workflow section:

```markdown
MinerU output is passed through Ragstudio's shared metadata-driven chunking layer before persistence. Large markdown artifacts are split by metadata profile, headings, pages, verse markers, paragraph boundaries, and a hard word cap so a successful MinerU parse cannot persist as a single oversized retrieval chunk.
```

- [ ] **Step 2: Add user-facing note to `docs/user-guide.md`**

Add this paragraph near the Documents or chunking guidance:

```markdown
For large parsed documents, Ragstudio applies metadata-driven chunk profiles. Tafseer/book uploads are split into semantic retrieval chunks, Quran-style text favors verse-aware chunks, papers favor section chunks, and every parser path has a hard cap to prevent oversized single chunks.
```

- [ ] **Step 3: Commit docs**

Run:

```bash
git add docs/workflows.md docs/user-guide.md
git commit -m "docs: describe metadata driven chunking"
```

Expected: commit succeeds.

---

## Final Verification

Run focused backend tests:

```bash
docker compose run --rm -v "$PWD/backend/src:/app/backend/src" -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_chunk_splitter.py backend/tests/test_mineru_client.py backend/tests/test_chunks.py backend/tests/test_index_lifecycle_service.py -q
```

Expected: PASS.

Run document lifecycle tests because background jobs report chunk counts:

```bash
docker compose run --rm -v "$PWD/backend/src:/app/backend/src" -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_documents.py -q
```

Expected: PASS.

Run git review:

```bash
git status --short
git log --oneline -5
```

Expected: only unrelated pre-existing workspace changes remain unstaged; new chunking commits are present.
