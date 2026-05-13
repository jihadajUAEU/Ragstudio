# Document-Specific Quality Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve indexing quality by letting AI autosuggest produce document-specific structure and script policies, then using those policies to reduce false parser quality warnings.

**Architecture:** Extend `custom_json` with reusable sections: `domain_structure` for primary anchors versus inline cross-references, `quality_policy` for required versus optional scripts, and `layout_quality_policy` for acceptable parser block recovery. The vision autosuggest prompt sends up to 10 pages and asks for these policies; chunk assembly, the quality gate, and an intelligent parser warning gate consume them so commentary-style documents can be indexed without false Arabic-missing or acceptable-recovery warnings while strict primary-source checks remain strict.

**Tech Stack:** FastAPI, Pydantic models, PyMuPDF page sampling, OpenAI-compatible chat/vision API payloads, SQLAlchemy-backed ingestion pipeline, pytest.

---

## Scope Check

This plan changes one subsystem: domain-aware indexing quality. It touches autosuggest, metadata validation, reference unit assembly, and quality warnings because those files participate in the same contract. It does not change embeddings, retrieval ranking, graph projection storage, MinerU sidecar code, or frontend layout.

## File Structure

- Modify `backend/src/ragstudio/services/metadata_json_schema.py`
  - Validate `custom_json.domain_structure`, `custom_json.quality_policy`, and `custom_json.layout_quality_policy`.
  - Keep regex validation bounded by the existing safe regex rules.
- Modify `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`
  - Ask the vision model for document-specific structure and script quality policy.
  - Preserve sanitized `domain_structure`, `quality_policy`, and `layout_quality_policy` in AI responses and baseline merges.
  - Send up to 10 sampled pages to the model.
- Modify `backend/src/ragstudio/api/routes/domain_profiles.py`
  - Instantiate `PageSampler(max_pages=10)` for autosuggest.
- Modify `backend/src/ragstudio/services/page_sampler.py`
  - Keep the class default at 4 for existing callers; the route opts into 10.
- Modify `backend/src/ragstudio/services/reference_metadata.py`
  - Teach `ReferenceSemantics` about primary anchor regex and inline-reference policy.
- Modify `backend/src/ragstudio/services/reference_unit_assembler.py`
  - Start new canonical units from primary anchors when configured.
  - Keep inline references as cross-reference metadata inside the current unit.
- Modify `backend/src/ragstudio/services/domain_metadata_quality_gate.py`
  - Use `quality_policy.required_scripts` for missing-script warnings.
  - Treat `quality_policy.optional_scripts` as enrichment that does not warn when absent.
- Create `backend/src/ragstudio/services/parser_quality_intelligent_gate.py`
  - Classify parser recovery warnings as `info`, `warn`, or `block` from document policy.
  - Mark accepted recovery warnings as excluded from quality-warning counts.
- Modify `backend/tests/test_domain_metadata.py`
  - Cover schema validation, autosuggest prompt, normalization, and merge behavior.
- Create `backend/tests/test_parser_quality_intelligent_gate.py`
  - Cover policy-driven classification for recovered text warnings.
- Modify `backend/tests/test_chunk_splitter.py`
  - Cover Tafseer-style primary anchors with inline Quran references.
- Modify `backend/tests/test_domain_metadata_quality_gate.py`
  - Cover required versus optional scripts and strict fallback behavior.
- Modify `docs/workflows.md`
  - Document the new warning semantics.

---

### Task 1: Validate And Preserve Document-Specific Policy Metadata

**Files:**
- Modify: `backend/src/ragstudio/services/metadata_json_schema.py`
- Modify: `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`
- Test: `backend/tests/test_domain_metadata.py`

- [ ] **Step 1: Write failing schema tests**

Add these tests to `backend/tests/test_domain_metadata.py` near the other `validate_custom_json` tests:

```python
def test_validate_custom_json_accepts_domain_structure_and_quality_policy():
    payload = {
        "domain_structure": {
            "primary_anchor": {
                "type": "chapter_verse",
                "regex": r"\bVerse\s+(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})\b",
                "unit": "verse_section",
            },
            "inline_references": {
                "type": "chapter_verse",
                "regex": r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})",
                "policy": "cross_reference_only",
            },
        },
        "quality_policy": {
            "document_role": "commentary",
            "observed_scripts": ["arabic", "latin"],
            "required_scripts": ["latin"],
            "optional_scripts": ["arabic"],
            "required_scripts_by_unit_role": {
                "primary_anchor": ["latin"],
                "commentary_body": ["latin"],
                "inline_cross_reference": [],
            },
            "optional_scripts_by_unit_role": {
                "primary_anchor": ["arabic"],
                "commentary_body": ["arabic"],
            },
            "missing_required_script_action": "warn",
            "missing_optional_script_action": "no_warning",
            "materialization_policy": "allow_if_required_scripts_present",
            "evidence": [
                {
                    "page": 809,
                    "observation": "Verse sections contain English Tafseer commentary; Arabic is optional enrichment.",
                }
            ],
            "confidence": 0.91,
        },
    }

    assert validate_custom_json(payload) == payload


def test_validate_custom_json_rejects_invalid_domain_structure_policy():
    with pytest.raises(ValueError, match=r"domain_structure\.inline_references\.policy"):
        validate_custom_json(
            {
                "domain_structure": {
                    "inline_references": {"policy": "make_answerable_chunks"}
                }
            }
        )


def test_validate_custom_json_rejects_invalid_quality_policy_action():
    with pytest.raises(ValueError, match=r"quality_policy\.missing_optional_script_action"):
        validate_custom_json(
            {"quality_policy": {"missing_optional_script_action": "silently_delete"}}
        )
```

- [ ] **Step 2: Write failing autosuggest normalization test**

Add this test to `backend/tests/test_domain_metadata.py` near `test_ai_metadata_merge_prunes_partial_graph_without_baseline`:

```python
def test_ai_metadata_normalizes_domain_structure_and_quality_policy():
    suggester = DomainMetadataAiSuggester()

    normalized = suggester._normalize_custom_json(
        {
            "domain_structure": {
                "primary_anchor": {
                    "type": "chapter_verse",
                    "regex": r"\bVerse\s+(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})\b",
                    "unit": "verse_section",
                    "ignored": 42,
                },
                "inline_references": {
                    "type": "chapter_verse",
                    "regex": r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})",
                    "policy": "cross_reference_only",
                },
            },
            "quality_policy": {
                "document_role": "commentary",
                "observed_scripts": ["arabic", "latin", 7],
                "required_scripts": ["latin"],
                "optional_scripts": ["arabic"],
                "missing_required_script_action": "warn",
                "missing_optional_script_action": "no_warning",
                "materialization_policy": "allow_if_required_scripts_present",
                "confidence": 0.91,
                "evidence": [
                    {"page": 809, "observation": "Arabic is optional for commentary."},
                    {"page": "bad", "observation": 42},
                ],
            },
        }
    )

    assert normalized == {
        "domain_structure": {
            "primary_anchor": {
                "type": "chapter_verse",
                "regex": r"\bVerse\s+(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})\b",
                "unit": "verse_section",
            },
            "inline_references": {
                "type": "chapter_verse",
                "regex": r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})",
                "policy": "cross_reference_only",
            },
        },
        "quality_policy": {
            "document_role": "commentary",
            "observed_scripts": ["arabic", "latin"],
            "required_scripts": ["latin"],
            "optional_scripts": ["arabic"],
            "missing_required_script_action": "warn",
            "missing_optional_script_action": "no_warning",
            "materialization_policy": "allow_if_required_scripts_present",
            "evidence": [{"page": 809, "observation": "Arabic is optional for commentary."}],
            "confidence": 0.91,
        },
    }
    validate_custom_json(normalized)
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
pytest backend/tests/test_domain_metadata.py::test_validate_custom_json_accepts_domain_structure_and_quality_policy backend/tests/test_domain_metadata.py::test_validate_custom_json_rejects_invalid_domain_structure_policy backend/tests/test_domain_metadata.py::test_validate_custom_json_rejects_invalid_quality_policy_action backend/tests/test_domain_metadata.py::test_ai_metadata_normalizes_domain_structure_and_quality_policy -v
```

Expected: tests fail because `domain_structure` and `quality_policy` are not validated or normalized yet.

- [ ] **Step 4: Implement schema validation**

In `backend/src/ragstudio/services/metadata_json_schema.py`, add constants near the existing regex constants:

```python
DOMAIN_STRUCTURE_INLINE_POLICIES = {
    "cross_reference_only",
    "starts_unit",
    "ignore",
}
QUALITY_SCRIPT_ACTIONS = {
    "no_warning",
    "info",
    "warn",
    "block",
}
QUALITY_MATERIALIZATION_POLICIES = {
    "allow",
    "allow_if_required_scripts_present",
    "warn_if_required_scripts_missing",
    "block_if_required_scripts_missing",
}
```

In `validate_custom_json`, call the new validators after `_validate_chunking`:

```python
    _validate_domain_structure(value.get("domain_structure"))
    _validate_quality_policy(value.get("quality_policy"))
```

Add these helper functions before `_validate_reference_resolution`:

```python
def _validate_domain_structure(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.domain_structure must be an object.")

    primary_anchor = value.get("primary_anchor")
    if primary_anchor is not None:
        _validate_anchor_policy(primary_anchor, "domain_structure.primary_anchor")

    inline_references = value.get("inline_references")
    if inline_references is not None:
        _validate_anchor_policy(inline_references, "domain_structure.inline_references")
        policy = inline_references.get("policy") if isinstance(inline_references, dict) else None
        if policy is not None and policy not in DOMAIN_STRUCTURE_INLINE_POLICIES:
            raise ValueError(
                "custom_json.domain_structure.inline_references.policy must be one of: "
                f"{', '.join(sorted(DOMAIN_STRUCTURE_INLINE_POLICIES))}."
            )


def _validate_anchor_policy(value: Any, path: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"custom_json.{path} must be an object.")
    for key in ("type", "unit", "pattern", "display"):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            raise ValueError(f"custom_json.{path}.{key} must be a string.")
    regex = value.get("regex")
    if regex is not None:
        _validate_reference_pattern(regex, f"{path}.regex")


def _validate_quality_policy(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.quality_policy must be an object.")

    document_role = value.get("document_role")
    if document_role is not None and not isinstance(document_role, str):
        raise ValueError("custom_json.quality_policy.document_role must be a string.")

    for key in ("observed_scripts", "required_scripts", "optional_scripts"):
        item = value.get(key)
        if item is not None and (
            not isinstance(item, list) or any(not isinstance(entry, str) for entry in item)
        ):
            raise ValueError(f"custom_json.quality_policy.{key} must be a list of strings.")

    for key in ("required_scripts_by_unit_role", "optional_scripts_by_unit_role"):
        item = value.get(key)
        if item is None:
            continue
        if not isinstance(item, dict):
            raise ValueError(f"custom_json.quality_policy.{key} must be an object.")
        for role, scripts in item.items():
            if not isinstance(role, str) or not isinstance(scripts, list):
                raise ValueError(
                    f"custom_json.quality_policy.{key} must map strings to script lists."
                )
            if any(not isinstance(script, str) for script in scripts):
                raise ValueError(
                    f"custom_json.quality_policy.{key} must map strings to script lists."
                )

    for key in ("missing_required_script_action", "missing_optional_script_action"):
        action = value.get(key)
        if action is not None and action not in QUALITY_SCRIPT_ACTIONS:
            raise ValueError(
                f"custom_json.quality_policy.{key} must be one of: "
                f"{', '.join(sorted(QUALITY_SCRIPT_ACTIONS))}."
            )

    materialization_policy = value.get("materialization_policy")
    if (
        materialization_policy is not None
        and materialization_policy not in QUALITY_MATERIALIZATION_POLICIES
    ):
        raise ValueError(
            "custom_json.quality_policy.materialization_policy must be one of: "
            f"{', '.join(sorted(QUALITY_MATERIALIZATION_POLICIES))}."
        )

    evidence = value.get("evidence")
    if evidence is not None:
        if not isinstance(evidence, list):
            raise ValueError("custom_json.quality_policy.evidence must be a list.")
        for entry in evidence:
            if not isinstance(entry, dict):
                raise ValueError("custom_json.quality_policy.evidence entries must be objects.")
            page = entry.get("page")
            observation = entry.get("observation")
            if page is not None and (isinstance(page, bool) or not isinstance(page, int)):
                raise ValueError("custom_json.quality_policy.evidence.page must be an integer.")
            if observation is not None and not isinstance(observation, str):
                raise ValueError("custom_json.quality_policy.evidence.observation must be a string.")

    confidence = value.get("confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, int | float):
            raise ValueError("custom_json.quality_policy.confidence must be a number.")
        if confidence < 0 or confidence > 1:
            raise ValueError("custom_json.quality_policy.confidence must be between 0 and 1.")
```

- [ ] **Step 5: Implement autosuggest normalization and merge support**

In `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`, include the new sections in `_merge_custom_json`:

```python
        for key in (
            "reference_schema",
            "relationships",
            "chunking",
            "domain_structure",
            "quality_policy",
            "reference_resolution",
            "provenance",
            "parser_normalization",
            "mineru_parse_options",
            "retrieval",
            "graph",
        ):
```

In `_normalize_custom_json`, add these calls after the `chunking` block:

```python
        domain_structure_values = self._normalize_domain_structure(value.get("domain_structure"))
        if domain_structure_values:
            normalized["domain_structure"] = domain_structure_values

        quality_policy_values = self._normalize_quality_policy(value.get("quality_policy"))
        if quality_policy_values:
            normalized["quality_policy"] = quality_policy_values
```

Add these methods to `DomainMetadataAiSuggester` before `_has_required_graph_policy`:

```python
    def _normalize_domain_structure(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, object] = {}
        for key in ("primary_anchor", "inline_references"):
            section = value.get(key)
            if not isinstance(section, dict):
                continue
            section_values: dict[str, object] = {}
            for string_key in ("type", "unit", "pattern", "display"):
                item = section.get(string_key)
                if isinstance(item, str) and item.strip():
                    section_values[string_key] = item.strip()
            regex = section.get("regex")
            if isinstance(regex, str) and self._is_valid_domain_structure_regex(regex):
                section_values["regex"] = regex
            policy = section.get("policy")
            if key == "inline_references" and policy in {
                "cross_reference_only",
                "starts_unit",
                "ignore",
            }:
                section_values["policy"] = policy
            if section_values:
                normalized[key] = section_values
        return normalized

    def _normalize_quality_policy(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, object] = {}
        document_role = value.get("document_role")
        if isinstance(document_role, str) and document_role.strip():
            normalized["document_role"] = document_role.strip()
        for key in ("observed_scripts", "required_scripts", "optional_scripts"):
            items = value.get(key)
            if isinstance(items, list):
                scripts = [item.strip().casefold() for item in items if isinstance(item, str) and item.strip()]
                if scripts:
                    normalized[key] = list(dict.fromkeys(scripts))
        for key in ("required_scripts_by_unit_role", "optional_scripts_by_unit_role"):
            role_map = value.get(key)
            if not isinstance(role_map, dict):
                continue
            clean_map: dict[str, list[str]] = {}
            for role, scripts in role_map.items():
                if not isinstance(role, str) or not isinstance(scripts, list):
                    continue
                clean_scripts = [
                    script.strip().casefold()
                    for script in scripts
                    if isinstance(script, str) and script.strip()
                ]
                clean_map[role.strip()] = list(dict.fromkeys(clean_scripts))
            if clean_map:
                normalized[key] = clean_map
        for key in ("missing_required_script_action", "missing_optional_script_action"):
            action = value.get(key)
            if action in {"no_warning", "info", "warn", "block"}:
                normalized[key] = action
        materialization_policy = value.get("materialization_policy")
        if materialization_policy in {
            "allow",
            "allow_if_required_scripts_present",
            "warn_if_required_scripts_missing",
            "block_if_required_scripts_missing",
        }:
            normalized["materialization_policy"] = materialization_policy
        evidence = value.get("evidence")
        if isinstance(evidence, list):
            clean_evidence: list[dict[str, object]] = []
            for entry in evidence:
                if not isinstance(entry, dict):
                    continue
                page = entry.get("page")
                observation = entry.get("observation")
                if isinstance(page, int) and not isinstance(page, bool) and isinstance(observation, str) and observation.strip():
                    clean_evidence.append({"page": page, "observation": observation.strip()[:300]})
            if clean_evidence:
                normalized["evidence"] = clean_evidence[:10]
        confidence = value.get("confidence")
        if isinstance(confidence, int | float) and not isinstance(confidence, bool):
            normalized["confidence"] = min(max(float(confidence), 0.0), 1.0)
        return normalized

    def _is_valid_domain_structure_regex(self, value: str) -> bool:
        try:
            validate_custom_json(
                {"domain_structure": {"primary_anchor": {"regex": value}}}
            )
        except ValueError:
            return False
        return True
```

- [ ] **Step 6: Run tests and commit**

Run:

```bash
pytest backend/tests/test_domain_metadata.py::test_validate_custom_json_accepts_domain_structure_and_quality_policy backend/tests/test_domain_metadata.py::test_validate_custom_json_rejects_invalid_domain_structure_policy backend/tests/test_domain_metadata.py::test_validate_custom_json_rejects_invalid_quality_policy_action backend/tests/test_domain_metadata.py::test_ai_metadata_normalizes_domain_structure_and_quality_policy -v
```

Expected: all four tests pass.

Commit:

```bash
git add backend/src/ragstudio/services/metadata_json_schema.py backend/src/ragstudio/services/domain_metadata_ai_suggester.py backend/tests/test_domain_metadata.py
git commit -m "feat: accept document quality policy metadata"
```

---

### Task 2: Ask Vision Autosuggest For Document-Specific Quality Policy

**Files:**
- Modify: `backend/src/ragstudio/api/routes/domain_profiles.py`
- Modify: `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`
- Test: `backend/tests/test_domain_metadata.py`

- [ ] **Step 1: Write failing autosuggest prompt test**

Update the existing autosuggest test in `backend/tests/test_domain_metadata.py` that currently asserts page 5 is absent. Change the assertions at the end of that test to:

```python
    assert "custom_json.domain_structure" in prompt
    assert "custom_json.quality_policy" in prompt
    assert "custom_json.layout_quality_policy" in prompt
    assert "primary answerable units" in prompt
    assert "inline cross-references" in prompt
    assert "missing optional script" in prompt
    assert "misclassified as equations" in prompt
    assert "Page 5 text excerpt" in prompt
    assert len(calls[0]["json"]["messages"][0]["content"]) == 6
```

Then add this new test near the same autosuggest tests:

```python
@pytest.mark.asyncio
async def test_ai_domain_metadata_suggester_preserves_document_specific_quality_policy(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """{
                              "domain_metadata": {
                                "domain": "quran_tafseer",
                                "document_type": "commentary",
                                "language": "mixed",
                                "tags": ["quran", "tafseer", "english"],
                                "citation_style": "surah_ayah",
                                "content_role": "tafseer",
                                "custom_json": {
                                  "domain_structure": {
                                    "primary_anchor": {
                                      "type": "chapter_verse",
                                      "regex": "\\\\bVerse\\\\s+(?P<chapter>\\\\d{1,4})\\\\s*:\\\\s*(?P<verse>\\\\d{1,4})\\\\b",
                                      "unit": "verse_section"
                                    },
                                    "inline_references": {
                                      "type": "chapter_verse",
                                      "regex": "(?P<chapter>\\\\d{1,4})\\\\s*:\\\\s*(?P<verse>\\\\d{1,4})",
                                      "policy": "cross_reference_only"
                                    }
                                  },
                                  "quality_policy": {
                                    "document_role": "commentary",
                                    "observed_scripts": ["arabic", "latin"],
                                    "required_scripts": ["latin"],
                                    "optional_scripts": ["arabic"],
                                    "missing_required_script_action": "warn",
                                    "missing_optional_script_action": "no_warning",
                                    "materialization_policy": "allow_if_required_scripts_present",
                                    "evidence": [
                                      {
                                        "page": 809,
                                        "observation": "Verse sections are English Tafseer commentary with Arabic optional."
                                      }
                                    ],
                                    "confidence": 0.93
                                  },
                                  "layout_quality_policy": {
                                    "misclassified_block_policy": {
                                      "equation_with_recovered_text": {
                                        "treat_as": "prose_or_verse_text",
                                        "action": "recover_as_text",
                                        "warning_level": "info"
                                      }
                                    },
                                    "disallowed_block_policy": {
                                      "text_bearing_disallowed_block": {
                                        "action": "recover_as_text",
                                        "warning_level": "info"
                                      }
                                    }
                                  }
                                }
                              },
                              "confidence": 0.93,
                              "evidence_pages": [809],
                              "rationale": "Samples show Tafseer organized by verse labels.",
                              "warnings": []
                            }"""
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.domain_metadata_ai_suggester.httpx.AsyncClient",
        FakeClient,
    )

    result = await DomainMetadataAiSuggester().suggest(
        settings_profile=SettingsProfile(
            id="default",
            provider="openai-compatible",
            llm_model="vision-capable-model",
            llm_base_url="http://llm.test/v1",
            llm_capabilities=["vision"],
            embedding_model="embedding-model",
            storage_backend="postgres",
        ),
        filename="tafseer_ibn_kathir.pdf",
        content_type="application/pdf",
        pages=[SampledPage(page_number=809, text="Verse 18:30\\nIndeed, those who believed...")],
        sampler_warnings=[],
    )

    assert result.domain_metadata.content_role == "tafseer"
    assert result.domain_metadata.custom_json["domain_structure"]["inline_references"][
        "policy"
    ] == "cross_reference_only"
    assert result.domain_metadata.custom_json["quality_policy"]["required_scripts"] == [
        "latin"
    ]
    assert result.domain_metadata.custom_json["quality_policy"]["optional_scripts"] == [
        "arabic"
    ]
    assert result.domain_metadata.custom_json["layout_quality_policy"][
        "misclassified_block_policy"
    ]["equation_with_recovered_text"]["warning_level"] == "info"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest backend/tests/test_domain_metadata.py::test_ai_domain_metadata_suggester_includes_reference_semantics_in_prompt backend/tests/test_domain_metadata.py::test_ai_domain_metadata_suggester_preserves_document_specific_quality_policy -v
```

Expected: first test fails because the prompt still says 3-4 pages and omits the new policy guidance; second test fails until Task 1 normalization exists and the prompt shape is updated.

- [ ] **Step 3: Send 10 pages from the route**

In `backend/src/ragstudio/api/routes/domain_profiles.py`, change:

```python
    sampler = PageSampler()
```

to:

```python
    sampler = PageSampler(max_pages=10)
```

- [ ] **Step 4: Send 10 pages inside the LLM payload**

In `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`, change `_payload`:

```python
        sampled_pages = pages[:4]
```

to:

```python
        sampled_pages = pages[:10]
```

Change the payload token limit:

```python
            "max_tokens": 1400,
```

- [ ] **Step 5: Update the autosuggest prompt**

In `_prompt`, replace this sentence:

```python
Review the 3-4 sampled pages/images when available. If the samples show structured
references that users may need to edit or tune, propose generic reference semantics
in custom_json instead of relying on a hardcoded local strategy.
```

with:

```python
Review up to 10 sampled pages/images when available. If the samples show structured
references that users may need to edit or tune, propose generic reference semantics
in custom_json instead of relying on a hardcoded local strategy. Separate primary
answerable units from inline cross-references, and provide a document-specific
quality/script policy and layout/block recovery policy instead of only broad
domain metadata.
```

In the JSON shape inside the same prompt, change the `custom_json` block to:

```text
    "custom_json": {
      "reference_schema": null,
      "relationships": null,
      "chunking": null,
      "domain_structure": {
        "primary_anchor": {
          "type": null,
          "regex": null,
          "unit": null
        },
        "inline_references": {
          "type": null,
          "regex": null,
          "policy": "cross_reference_only|starts_unit|ignore"
        }
      },
      "quality_policy": {
        "document_role": null,
        "observed_scripts": [],
        "required_scripts": [],
        "optional_scripts": [],
        "required_scripts_by_unit_role": {},
        "optional_scripts_by_unit_role": {},
        "missing_required_script_action": "warn|block|info|no_warning",
        "missing_optional_script_action": "no_warning|info|warn|block",
        "materialization_policy": "allow_if_required_scripts_present",
        "evidence": [{"page": 1, "observation": "short evidence"}],
        "confidence": 0.0
      },
      "layout_quality_policy": {
        "expected_block_roles": {},
        "misclassified_block_policy": {
          "equation_with_recovered_text": {
            "treat_as": null,
            "action": "recover_as_text|ignore|block",
            "warning_level": "info|warn|block"
          }
        },
        "disallowed_block_policy": {
          "text_bearing_disallowed_block": {
            "action": "recover_as_text|ignore|block",
            "warning_level": "info|warn|block"
          }
        },
        "failure_policy": {
          "required_text_not_recovered": "info|warn|block",
          "unreadable_primary_anchor": "info|warn|block"
        }
      },
      "mineru_parse_options": null,
      "retrieval": null
    },
```

After the existing `For custom_json.chunking...` paragraph, add:

```python
For custom_json.domain_structure, identify the text pattern that starts a primary
answerable unit and distinguish it from inline citations. For example, a Tafseer
page may use "Verse 18:30" as the section anchor while "25:75-76" inside the
commentary is only a cross-reference.
For custom_json.quality_policy, identify which scripts are visible, which scripts
are required for answerable chunks, which scripts are optional enrichment, whether
missing optional script should warn, and page-level evidence for each decision.
For custom_json.layout_quality_policy, identify expected layout/block roles and
whether recovered text from blocks misclassified as equations or disallowed block
types is acceptable recovery, degraded quality, or a true blocker. For Arabic
religious prose, stylized Arabic verse images may be misclassified as equations;
classify that as info only when the visible page evidence supports it.
If the document is commentary, translation, explanation, legal analysis, or another
secondary-source role, do not require a primary-source script unless the sampled
pages show that every answerable unit depends on that script.
```

- [ ] **Step 6: Run tests and commit**

Run:

```bash
pytest backend/tests/test_domain_metadata.py::test_ai_domain_metadata_suggester_includes_reference_semantics_in_prompt backend/tests/test_domain_metadata.py::test_ai_domain_metadata_suggester_preserves_document_specific_quality_policy -v
```

Expected: both tests pass.

Commit:

```bash
git add backend/src/ragstudio/api/routes/domain_profiles.py backend/src/ragstudio/services/domain_metadata_ai_suggester.py backend/tests/test_domain_metadata.py
git commit -m "feat: request document quality policy from autosuggest"
```

---

### Task 3: Keep Inline References Inside Primary Anchor Units

**Files:**
- Modify: `backend/src/ragstudio/services/reference_metadata.py`
- Modify: `backend/src/ragstudio/services/reference_unit_assembler.py`
- Test: `backend/tests/test_chunk_splitter.py`

- [ ] **Step 1: Write failing Tafseer structure test**

Add this test to `backend/tests/test_chunk_splitter.py` near the canonical reference unit tests:

```python
def test_chunk_splitter_keeps_tafseer_inline_cross_references_inside_primary_anchor(tmp_path: Path):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "Verse 18:30", "page_idx": 808},
                {
                    "type": "text",
                    "text": "Indeed, those who have believed and done righteous deeds.",
                    "page_idx": 808,
                },
                {
                    "type": "text",
                    "text": (
                        "The Reward of those Who believe and do Righteous Deeds. "
                        "In a similar way, He contrasts the two in 25:75-76."
                    ),
                    "page_idx": 808,
                },
                {"type": "text", "text": "Verse 18:32", "page_idx": 808},
                {
                    "type": "text",
                    "text": "And present to them an example of two men.",
                    "page_idx": 808,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/ocr/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )
    metadata = DomainMetadata(
        domain="quran_tafseer",
        document_type="commentary",
        language="mixed",
        content_role="tafseer",
        tags=["quran", "tafseer", "english"],
        citation_style="surah_ayah",
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "canonical_ref_template": "{chapter}:{verse}",
            },
            "chunking": {"unit": "verse", "preserve_parallel_text": True},
            "domain_structure": {
                "primary_anchor": {
                    "type": "chapter_verse",
                    "regex": r"\bVerse\s+(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})\b",
                    "unit": "verse_section",
                },
                "inline_references": {
                    "type": "chapter_verse",
                    "regex": r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})",
                    "policy": "cross_reference_only",
                },
            },
            "reference_resolution": {
                "enabled": True,
                "build_canonical_units": True,
                "carry_forward_body_blocks": True,
                "header_only_policy": "provenance_only",
                "continuation_policy": "until_next_reference",
                "max_page_gap": 1,
                "require_single_reference_per_answerable_chunk": True,
            },
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=metadata,
        parser_mode="mineru_strict",
    )

    answerable = [piece for piece in split if piece.content_type != "reference_provenance"]
    assert [piece.preview_ref for piece in answerable] == ["18:30", "18:32"]
    assert "25:75-76" in answerable[0].text
    assert "The Reward of those Who believe" in answerable[0].text
    assert not any(piece.preview_ref == "25:75" for piece in split)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest backend/tests/test_chunk_splitter.py::test_chunk_splitter_keeps_tafseer_inline_cross_references_inside_primary_anchor -v
```

Expected: fail because `25:75` becomes its own canonical unit or splits the current unit.

- [ ] **Step 3: Extend ReferenceSemantics**

In `backend/src/ragstudio/services/reference_metadata.py`, add fields to the `ReferenceSemantics` dataclass:

```python
    primary_anchor_pattern: str | None = None
    primary_anchor_unit: str | None = None
    inline_reference_pattern: str | None = None
    inline_reference_policy: str = "starts_unit"
```

In `from_metadata`, read `domain_structure` after `provenance_value`:

```python
        domain_structure_value = custom.get("domain_structure")
        domain_structure: dict[str, Any] = (
            domain_structure_value if isinstance(domain_structure_value, dict) else {}
        )
        primary_anchor = domain_structure.get("primary_anchor")
        primary_anchor = primary_anchor if isinstance(primary_anchor, dict) else {}
        inline_references = domain_structure.get("inline_references")
        inline_references = inline_references if isinstance(inline_references, dict) else {}
```

Add these constructor arguments in the returned `cls(...)` call:

```python
            primary_anchor_pattern=cls._string_value(
                primary_anchor.get("regex"),
                default=None,
            ),
            primary_anchor_unit=cls._string_value(
                primary_anchor.get("unit"),
                default=None,
            ),
            inline_reference_pattern=cls._string_value(
                inline_references.get("regex"),
                default=None,
            ),
            inline_reference_policy=cls._string_value(
                inline_references.get("policy"),
                default="starts_unit",
            ),
```

Add these methods after `extract_chunk_references`:

```python
    def extract_primary_anchor_references(self, text: str) -> list[dict[str, int | str]]:
        pattern = self._primary_anchor_regex()
        if pattern is None:
            return self.extract_chunk_references(text)
        stripped = text.strip()
        if not stripped:
            return []
        first_line = stripped.splitlines()[0]
        match = pattern.search(first_line)
        if match is None:
            return []
        prefix = first_line[: match.start()].strip()
        if prefix:
            return []
        return [self._match_to_reference(match)]

    def split_primary_anchor_units(self, text: str) -> list[str]:
        pattern = self._primary_anchor_regex()
        if pattern is None:
            return self.split_reference_units(text)
        matches = list(pattern.finditer(text))
        if not matches:
            return []
        units: list[str] = []
        leading = text[: matches[0].start()].strip()
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            unit = text[start:end].strip()
            if index == 0 and leading:
                unit = f"{leading}\n\n{unit}".strip()
            if unit:
                units.append(unit)
        return units

    def _primary_anchor_regex(self) -> re.Pattern[str] | None:
        if not self.primary_anchor_pattern:
            return None
        try:
            return re.compile(self.primary_anchor_pattern, flags=re.IGNORECASE)
        except re.error:
            return None
```

- [ ] **Step 4: Use primary anchors in the assembler**

In `backend/src/ragstudio/services/reference_unit_assembler.py`, change the start of the loop in `assemble` from:

```python
            references = semantics.extract_chunk_references(text) if text else []
```

to:

```python
            references = semantics.extract_primary_anchor_references(text) if text else []
```

In `_expand_multi_reference_blocks`, replace the function body with:

```python
        expanded: list[ReferenceSourceBlock] = []
        for block in blocks:
            if semantics.inline_reference_policy == "cross_reference_only":
                units = semantics.split_primary_anchor_units(block.text)
            else:
                if len(semantics.extract_chunk_references(block.text)) <= 1:
                    expanded.append(block)
                    continue
                units = semantics.split_reference_units(block.text)
            if len(units) <= 1:
                expanded.append(block)
                continue
            for index, text in enumerate(units):
                source_block_ref = block.source_block_ref
                if source_block_ref:
                    source_block_ref = f"{source_block_ref}:ref{index}"
                expanded.append(
                    replace(
                        block,
                        text=text,
                        source_block_ref=source_block_ref,
                    )
                )
        return expanded
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
pytest backend/tests/test_chunk_splitter.py::test_chunk_splitter_keeps_tafseer_inline_cross_references_inside_primary_anchor -v
```

Expected: test passes.

Run nearby regressions:

```bash
pytest backend/tests/test_chunk_splitter.py -k "canonical_reference or tafseer_inline_cross" -v
```

Expected: selected tests pass.

Commit:

```bash
git add backend/src/ragstudio/services/reference_metadata.py backend/src/ragstudio/services/reference_unit_assembler.py backend/tests/test_chunk_splitter.py
git commit -m "feat: separate primary anchors from inline references"
```

---

### Task 4: Apply Required And Optional Script Policy In Quality Gate

**Files:**
- Modify: `backend/src/ragstudio/services/domain_metadata_quality_gate.py`
- Test: `backend/tests/test_domain_metadata_quality_gate.py`

- [ ] **Step 1: Write failing optional-script quality test**

Add these tests to `backend/tests/test_domain_metadata_quality_gate.py`:

```python
def _tafseer_quality_policy_metadata() -> DomainMetadata:
    return DomainMetadata(
        domain="quran_tafseer",
        document_type="commentary",
        language="mixed",
        content_role="tafseer",
        tags=["quran", "tafseer", "english"],
        citation_style="surah_ayah",
        expected_structure="surah_ayah_sections",
        reference_pattern="surah_number:verse_number",
        script="mixed",
        custom_json={
            "reference_schema": {"type": "chapter_verse", "display": "{chapter}:{verse}"},
            "chunking": {"unit": "verse", "preserve_parallel_text": True},
            "quality_policy": {
                "document_role": "commentary",
                "observed_scripts": ["arabic", "latin"],
                "required_scripts": ["latin"],
                "optional_scripts": ["arabic"],
                "missing_required_script_action": "warn",
                "missing_optional_script_action": "no_warning",
                "materialization_policy": "allow_if_required_scripts_present",
            },
        },
    )


def test_domain_quality_gate_allows_tafseer_commentary_when_optional_arabic_is_missing():
    chunks = [
        AdapterChunk(
            text="Verse 18:30 Indeed, those who have believed and done righteous deeds.",
            source_location={"page": 809},
            metadata={"reference_metadata": {"references": ["18:30"]}},
        )
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=_tafseer_quality_policy_metadata(),
    )

    assert report["status"] == "passed"
    assert report["index_quality_report"]["summary"][
        "reference_units_missing_expected_script"
    ] == 0
    assert "extraction_quality" not in chunks[0].metadata
    assert chunks[0].metadata["quality_action_policy"]["index_vector"] is True
    assert chunks[0].metadata["quality_action_policy"]["project_graph"] is True


def test_domain_quality_gate_still_warns_when_required_latin_is_missing():
    chunks = [
        AdapterChunk(
            text="Verse 18:30",
            source_location={"page": 809},
            metadata={"reference_metadata": {"references": ["18:30"]}},
        )
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=_tafseer_quality_policy_metadata(),
    )

    assert report["status"] == "passed_with_warnings"
    warnings = chunks[0].metadata["extraction_quality"]["parser_warnings"]
    assert warnings[0]["code"] == "reference_unit_missing_expected_script"
    assert warnings[0]["expected_script"] == "latin"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest backend/tests/test_domain_metadata_quality_gate.py::test_domain_quality_gate_allows_tafseer_commentary_when_optional_arabic_is_missing backend/tests/test_domain_metadata_quality_gate.py::test_domain_quality_gate_still_warns_when_required_latin_is_missing -v
```

Expected: first test fails because Arabic is still treated as required; second may fail on expected script.

- [ ] **Step 3: Extend MetadataQualityProfile**

In `backend/src/ragstudio/services/domain_metadata_quality_gate.py`, change the `MetadataQualityProfile` dataclass:

```python
@dataclass(frozen=True)
class MetadataQualityProfile:
    domain: str
    expected_scripts: frozenset[str]
    required_scripts: frozenset[str]
    optional_scripts: frozenset[str]
    reference_patterns: tuple[str, ...]
    parser_strictness: str
    preserve_parallel_text: bool
    reference_unit: str | None
    reference_type: str | None
    equation_blocks_allowed: bool
    structured_references: bool
    missing_required_script_action: str
    missing_optional_script_action: str
    materialization_policy: str
```

In `profile_for`, after `custom_json` is assigned, add:

```python
        quality_policy = _dict_value(custom_json, "quality_policy") or {}
        expected_scripts = frozenset(
            script
            for script in expected_profile.expected_scripts
            if script in SCRIPT_PATTERNS
        )
        required_scripts = _script_policy_set(quality_policy.get("required_scripts"))
        optional_scripts = _script_policy_set(quality_policy.get("optional_scripts"))
        if not required_scripts:
            required_scripts = expected_scripts
```

In the `MetadataQualityProfile(...)` return, replace `expected_scripts=...` with:

```python
            expected_scripts=frozenset(sorted(required_scripts | optional_scripts)),
            required_scripts=frozenset(sorted(required_scripts)),
            optional_scripts=frozenset(sorted(optional_scripts)),
```

and add:

```python
            missing_required_script_action=_quality_action(
                quality_policy.get("missing_required_script_action"),
                default="warn",
            ),
            missing_optional_script_action=_quality_action(
                quality_policy.get("missing_optional_script_action"),
                default="warn",
            ),
            materialization_policy=_materialization_policy(
                quality_policy.get("materialization_policy")
            ),
```

Add helper functions near `_dict_value`:

```python
def _script_policy_set(value: Any) -> frozenset[str]:
    if not isinstance(value, list | tuple | set | frozenset):
        return frozenset()
    return frozenset(
        str(item).strip().casefold()
        for item in value
        if isinstance(item, str) and str(item).strip().casefold() in SCRIPT_PATTERNS
    )


def _quality_action(value: Any, *, default: str) -> str:
    if value in {"no_warning", "info", "warn", "block"}:
        return str(value)
    return default


def _materialization_policy(value: Any) -> str:
    if value in {
        "allow",
        "allow_if_required_scripts_present",
        "warn_if_required_scripts_missing",
        "block_if_required_scripts_missing",
    }:
        return str(value)
    return "block_if_required_scripts_missing"
```

- [ ] **Step 4: Check only required scripts for warnings**

In `warnings_for_text`, change:

```python
        if not profile.expected_scripts:
```

to:

```python
        if not profile.required_scripts:
```

Change:

```python
        for script in sorted(profile.expected_scripts):
```

to:

```python
        for script in sorted(profile.required_scripts):
```

In `_reference_record`, change:

```python
        expected_scripts = sorted(profile.expected_scripts)
        observed_scripts = [
            script for script in expected_scripts if SCRIPT_PATTERNS[script].search(text)
        ]
        missing_scripts = [
            script for script in expected_scripts if script not in set(observed_scripts)
        ]
```

to:

```python
        expected_scripts = sorted(profile.expected_scripts)
        required_scripts = sorted(profile.required_scripts)
        observed_scripts = [
            script for script in expected_scripts if SCRIPT_PATTERNS[script].search(text)
        ]
        missing_scripts = [
            script for script in required_scripts if script not in set(observed_scripts)
        ]
```

- [ ] **Step 5: Respect materialization policy for missing required scripts**

In `_reference_record`, replace the `action = ...` block with:

```python
        action = self._missing_script_action(missing_scripts, profile)
```

Add this method before `_reference_materialization_policy`:

```python
    def _missing_script_action(
        self,
        missing_scripts: list[str],
        profile: MetadataQualityProfile,
    ) -> str:
        if not missing_scripts:
            return "allow_materialization"
        if profile.materialization_policy == "allow":
            return "warn_reference_quality"
        if profile.materialization_policy == "allow_if_required_scripts_present":
            return "warn_reference_quality"
        if profile.materialization_policy == "warn_if_required_scripts_missing":
            return "warn_reference_quality"
        if profile.missing_required_script_action == "block":
            return "block_reference_materialization"
        if profile.preserve_parallel_text and profile.materialization_policy != "allow_if_required_scripts_present":
            return "block_reference_materialization"
        return "warn_reference_quality"
```

In `_requires_reference_quality`, change:

```python
            and profile.expected_scripts
```

to:

```python
            and profile.required_scripts
```

In `_requires_document_arabic`, change:

```python
        return normalized_language in {"arabic", "quran"} or "arabic" in profile.expected_scripts
```

to:

```python
        return normalized_language in {"arabic", "quran"} or "arabic" in profile.required_scripts
```

- [ ] **Step 6: Run quality gate tests and commit**

Run:

```bash
pytest backend/tests/test_domain_metadata_quality_gate.py -v
```

Expected: all tests in the file pass.

Commit:

```bash
git add backend/src/ragstudio/services/domain_metadata_quality_gate.py backend/tests/test_domain_metadata_quality_gate.py
git commit -m "feat: apply document-specific script policy"
```

---

### Task 5: Add End-To-End Tafseer Regression For Warning Reduction

**Files:**
- Modify: `backend/tests/test_chunk_splitter.py`
- Modify: `backend/tests/test_domain_metadata_quality_gate.py`

- [ ] **Step 1: Add combined chunking and quality regression**

Add this test to `backend/tests/test_chunk_splitter.py` after the Task 3 test:

```python
def test_tafseer_policy_reduces_false_missing_arabic_warnings(tmp_path: Path):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "Verse 18:30", "page_idx": 808},
                {
                    "type": "text",
                    "text": "Indeed, those who have believed and done righteous deeds.",
                    "page_idx": 808,
                },
                {
                    "type": "text",
                    "text": "The Tafseer explains the reward and references 25:75-76.",
                    "page_idx": 808,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/ocr/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )
    metadata = DomainMetadata(
        domain="quran_tafseer",
        document_type="commentary",
        language="mixed",
        content_role="tafseer",
        tags=["quran", "tafseer", "english"],
        citation_style="surah_ayah",
        script="mixed",
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "canonical_ref_template": "{chapter}:{verse}",
            },
            "chunking": {"unit": "verse", "preserve_parallel_text": True},
            "domain_structure": {
                "primary_anchor": {
                    "type": "chapter_verse",
                    "regex": r"\bVerse\s+(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})\b",
                    "unit": "verse_section",
                },
                "inline_references": {
                    "type": "chapter_verse",
                    "regex": r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})",
                    "policy": "cross_reference_only",
                },
            },
            "quality_policy": {
                "document_role": "commentary",
                "observed_scripts": ["arabic", "latin"],
                "required_scripts": ["latin"],
                "optional_scripts": ["arabic"],
                "missing_required_script_action": "warn",
                "missing_optional_script_action": "no_warning",
                "materialization_policy": "allow_if_required_scripts_present",
            },
            "reference_resolution": {
                "enabled": True,
                "build_canonical_units": True,
                "carry_forward_body_blocks": True,
                "header_only_policy": "provenance_only",
                "continuation_policy": "until_next_reference",
                "max_page_gap": 1,
                "require_single_reference_per_answerable_chunk": True,
            },
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=metadata,
        parser_mode="mineru_strict",
    )
    report = DomainMetadataQualityGate().validate_adapter_chunks(
        split,
        domain_metadata=metadata,
    )

    assert [piece.preview_ref for piece in split if piece.content_type != "reference_provenance"] == [
        "18:30"
    ]
    assert report["status"] == "passed"
    assert report["parser_quality"]["warning_counts"] == {}
    assert report["index_quality_report"]["summary"][
        "reference_units_missing_expected_script"
    ] == 0
```

- [ ] **Step 2: Run regression test**

Run:

```bash
pytest backend/tests/test_chunk_splitter.py::test_tafseer_policy_reduces_false_missing_arabic_warnings -v
```

Expected: test passes after Tasks 3 and 4.

- [ ] **Step 3: Run targeted warning suite**

Run:

```bash
pytest backend/tests/test_chunk_splitter.py -k "missing_expected_script or tafseer_policy or inline_cross" -v
pytest backend/tests/test_domain_metadata_quality_gate.py -v
```

Expected: all selected tests pass.

- [ ] **Step 4: Commit regression coverage**

Commit:

```bash
git add backend/tests/test_chunk_splitter.py backend/tests/test_domain_metadata_quality_gate.py
git commit -m "test: cover tafseer quality warning reduction"
```

---

### Task 6: Add Intelligent Parser Warning Gate

**Files:**
- Create: `backend/src/ragstudio/services/parser_quality_intelligent_gate.py`
- Modify: `backend/src/ragstudio/services/metadata_json_schema.py`
- Modify: `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`
- Modify: `backend/src/ragstudio/services/domain_metadata_quality_gate.py`
- Test: `backend/tests/test_parser_quality_intelligent_gate.py`
- Test: `backend/tests/test_domain_metadata.py`

- [ ] **Step 1: Write failing schema and normalization tests for layout quality policy**

Add this test to `backend/tests/test_domain_metadata.py` near the `quality_policy` tests from Task 1:

```python
def test_validate_custom_json_accepts_layout_quality_policy():
    payload = {
        "layout_quality_policy": {
            "expected_block_roles": {
                "primary_anchor": ["heading", "text"],
                "verse_text": ["text", "image_text", "equation_recovered"],
                "commentary_body": ["text"],
            },
            "misclassified_block_policy": {
                "equation_with_recovered_text": {
                    "treat_as": "prose_or_verse_text",
                    "action": "recover_as_text",
                    "warning_level": "info",
                }
            },
            "disallowed_block_policy": {
                "text_bearing_disallowed_block": {
                    "action": "recover_as_text",
                    "warning_level": "info",
                }
            },
            "failure_policy": {
                "required_text_not_recovered": "warn",
                "unreadable_primary_anchor": "block",
            },
        }
    }

    assert validate_custom_json(payload) == payload


def test_ai_metadata_normalizes_layout_quality_policy():
    normalized = DomainMetadataAiSuggester()._normalize_custom_json(
        {
            "layout_quality_policy": {
                "expected_block_roles": {
                    "primary_anchor": ["heading", "text", 3],
                    "verse_text": ["text", "image_text", "equation_recovered"],
                },
                "misclassified_block_policy": {
                    "equation_with_recovered_text": {
                        "treat_as": "prose_or_verse_text",
                        "action": "recover_as_text",
                        "warning_level": "info",
                        "ignored": 42,
                    }
                },
                "disallowed_block_policy": {
                    "text_bearing_disallowed_block": {
                        "action": "recover_as_text",
                        "warning_level": "info",
                    }
                },
                "failure_policy": {
                    "required_text_not_recovered": "warn",
                    "unreadable_primary_anchor": "block",
                },
            }
        }
    )

    assert normalized["layout_quality_policy"] == {
        "expected_block_roles": {
            "primary_anchor": ["heading", "text"],
            "verse_text": ["text", "image_text", "equation_recovered"],
        },
        "misclassified_block_policy": {
            "equation_with_recovered_text": {
                "treat_as": "prose_or_verse_text",
                "action": "recover_as_text",
                "warning_level": "info",
            }
        },
        "disallowed_block_policy": {
            "text_bearing_disallowed_block": {
                "action": "recover_as_text",
                "warning_level": "info",
            }
        },
        "failure_policy": {
            "required_text_not_recovered": "warn",
            "unreadable_primary_anchor": "block",
        },
    }
```

- [ ] **Step 2: Write failing intelligent gate tests**

Create `backend/tests/test_parser_quality_intelligent_gate.py`:

```python
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.parser_quality_intelligent_gate import ParserQualityIntelligentGate


def _metadata_with_layout_policy() -> DomainMetadata:
    return DomainMetadata(
        domain="quran_tafseer",
        document_type="commentary",
        content_role="tafseer",
        custom_json={
            "layout_quality_policy": {
                "misclassified_block_policy": {
                    "equation_with_recovered_text": {
                        "treat_as": "prose_or_verse_text",
                        "action": "recover_as_text",
                        "warning_level": "info",
                    }
                },
                "disallowed_block_policy": {
                    "text_bearing_disallowed_block": {
                        "action": "recover_as_text",
                        "warning_level": "info",
                    }
                },
            }
        },
    )


def test_intelligent_gate_marks_misclassified_equation_recovery_as_info():
    warning = {
        "code": "recovered_text_from_misclassified_block",
        "block_type": "equation",
        "message": "Used parser-provided recovered text for a block misclassified as an equation.",
    }

    classified = ParserQualityIntelligentGate().classify_warning(
        warning,
        domain_metadata=_metadata_with_layout_policy(),
    )

    assert classified == {
        **warning,
        "severity": "info",
        "quality_gate_action": "accepted_recovery",
        "suppressed_from_counts": True,
        "quality_gate_reason": "layout_quality_policy.equation_with_recovered_text",
    }


def test_intelligent_gate_marks_disallowed_text_recovery_as_info():
    warning = {
        "code": "recovered_text_from_disallowed_block",
        "block_type": "image",
        "message": "Used parser-provided recovered text for a disallowed block type.",
    }

    classified = ParserQualityIntelligentGate().classify_warning(
        warning,
        domain_metadata=_metadata_with_layout_policy(),
    )

    assert classified["severity"] == "info"
    assert classified["quality_gate_action"] == "accepted_recovery"
    assert classified["suppressed_from_counts"] is True
    assert classified["quality_gate_reason"] == (
        "layout_quality_policy.text_bearing_disallowed_block"
    )


def test_intelligent_gate_defaults_unknown_warning_to_warn():
    warning = {"code": "reference_unit_unresolved", "message": "Could not resolve reference."}

    classified = ParserQualityIntelligentGate().classify_warning(
        warning,
        domain_metadata=_metadata_with_layout_policy(),
    )

    assert classified["severity"] == "warn"
    assert classified["quality_gate_action"] == "review_warning"
    assert classified["suppressed_from_counts"] is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
pytest backend/tests/test_domain_metadata.py::test_validate_custom_json_accepts_layout_quality_policy backend/tests/test_domain_metadata.py::test_ai_metadata_normalizes_layout_quality_policy backend/tests/test_parser_quality_intelligent_gate.py -v
```

Expected: tests fail because `layout_quality_policy` validation, normalization, and the gate service do not exist yet.

- [ ] **Step 4: Implement layout policy validation and normalization**

In `backend/src/ragstudio/services/metadata_json_schema.py`, add:

```python
LAYOUT_WARNING_LEVELS = {"info", "warn", "block"}
LAYOUT_RECOVERY_ACTIONS = {"recover_as_text", "ignore", "block"}
```

Call the validator from `validate_custom_json` after `_validate_quality_policy`:

```python
    _validate_layout_quality_policy(value.get("layout_quality_policy"))
```

Add this helper:

```python
def _validate_layout_quality_policy(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.layout_quality_policy must be an object.")

    expected_block_roles = value.get("expected_block_roles")
    if expected_block_roles is not None:
        if not isinstance(expected_block_roles, dict):
            raise ValueError("custom_json.layout_quality_policy.expected_block_roles must be an object.")
        for role, block_types in expected_block_roles.items():
            if not isinstance(role, str) or not isinstance(block_types, list):
                raise ValueError(
                    "custom_json.layout_quality_policy.expected_block_roles must map strings to lists."
                )
            if any(not isinstance(block_type, str) for block_type in block_types):
                raise ValueError(
                    "custom_json.layout_quality_policy.expected_block_roles must map strings to lists."
                )

    for section_name in ("misclassified_block_policy", "disallowed_block_policy"):
        section = value.get(section_name)
        if section is None:
            continue
        if not isinstance(section, dict):
            raise ValueError(f"custom_json.layout_quality_policy.{section_name} must be an object.")
        for policy_name, policy in section.items():
            if not isinstance(policy_name, str) or not isinstance(policy, dict):
                raise ValueError(
                    f"custom_json.layout_quality_policy.{section_name} must map strings to objects."
                )
            action = policy.get("action")
            if action is not None and action not in LAYOUT_RECOVERY_ACTIONS:
                raise ValueError(
                    f"custom_json.layout_quality_policy.{section_name}.{policy_name}.action is invalid."
                )
            warning_level = policy.get("warning_level")
            if warning_level is not None and warning_level not in LAYOUT_WARNING_LEVELS:
                raise ValueError(
                    f"custom_json.layout_quality_policy.{section_name}.{policy_name}.warning_level is invalid."
                )
            treat_as = policy.get("treat_as")
            if treat_as is not None and not isinstance(treat_as, str):
                raise ValueError(
                    f"custom_json.layout_quality_policy.{section_name}.{policy_name}.treat_as must be a string."
                )

    failure_policy = value.get("failure_policy")
    if failure_policy is not None:
        if not isinstance(failure_policy, dict):
            raise ValueError("custom_json.layout_quality_policy.failure_policy must be an object.")
        for failure_name, action in failure_policy.items():
            if not isinstance(failure_name, str) or action not in LAYOUT_WARNING_LEVELS:
                raise ValueError(
                    "custom_json.layout_quality_policy.failure_policy must map strings to info, warn, or block."
                )
```

In `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`, include `"layout_quality_policy"` in the `_merge_custom_json` section tuple after `"quality_policy"`.

In `_normalize_custom_json`, add after `quality_policy_values`:

```python
        layout_quality_policy_values = self._normalize_layout_quality_policy(
            value.get("layout_quality_policy")
        )
        if layout_quality_policy_values:
            normalized["layout_quality_policy"] = layout_quality_policy_values
```

Add this method near `_normalize_quality_policy`:

```python
    def _normalize_layout_quality_policy(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, object] = {}
        expected_block_roles = value.get("expected_block_roles")
        if isinstance(expected_block_roles, dict):
            role_values: dict[str, list[str]] = {}
            for role, block_types in expected_block_roles.items():
                if not isinstance(role, str) or not isinstance(block_types, list):
                    continue
                clean_types = [
                    block_type.strip().casefold()
                    for block_type in block_types
                    if isinstance(block_type, str) and block_type.strip()
                ]
                if clean_types:
                    role_values[role.strip()] = list(dict.fromkeys(clean_types))
            if role_values:
                normalized["expected_block_roles"] = role_values

        for section_name in ("misclassified_block_policy", "disallowed_block_policy"):
            section = value.get(section_name)
            if not isinstance(section, dict):
                continue
            section_values: dict[str, dict[str, str]] = {}
            for policy_name, policy in section.items():
                if not isinstance(policy_name, str) or not isinstance(policy, dict):
                    continue
                policy_values: dict[str, str] = {}
                treat_as = policy.get("treat_as")
                if isinstance(treat_as, str) and treat_as.strip():
                    policy_values["treat_as"] = treat_as.strip()
                action = policy.get("action")
                if action in {"recover_as_text", "ignore", "block"}:
                    policy_values["action"] = action
                warning_level = policy.get("warning_level")
                if warning_level in {"info", "warn", "block"}:
                    policy_values["warning_level"] = warning_level
                if policy_values:
                    section_values[policy_name.strip()] = policy_values
            if section_values:
                normalized[section_name] = section_values

        failure_policy = value.get("failure_policy")
        if isinstance(failure_policy, dict):
            clean_failures = {
                key.strip(): action
                for key, action in failure_policy.items()
                if isinstance(key, str) and action in {"info", "warn", "block"}
            }
            if clean_failures:
                normalized["failure_policy"] = clean_failures
        return normalized
```

- [ ] **Step 5: Implement the intelligent gate service**

Create `backend/src/ragstudio/services/parser_quality_intelligent_gate.py`:

```python
from __future__ import annotations

from typing import Any

from ragstudio.schemas.parsing import DomainMetadata

INFO_LEVELS = {"info"}
EQUATION_BLOCK_TYPES = {"equation", "equation_interline", "interline_equation"}


class ParserQualityIntelligentGate:
    def classify_warnings(
        self,
        warnings: list[dict[str, Any]],
        *,
        domain_metadata: DomainMetadata | None,
    ) -> list[dict[str, Any]]:
        return [
            self.classify_warning(warning, domain_metadata=domain_metadata)
            for warning in warnings
            if isinstance(warning, dict)
        ]

    def classify_warning(
        self,
        warning: dict[str, Any],
        *,
        domain_metadata: DomainMetadata | None,
    ) -> dict[str, Any]:
        code = warning.get("code")
        block_type = str(warning.get("block_type") or "").strip().casefold()
        layout_policy = self._layout_policy(domain_metadata)

        if code == "recovered_text_from_misclassified_block" and block_type in EQUATION_BLOCK_TYPES:
            policy = self._policy_item(
                layout_policy,
                "misclassified_block_policy",
                "equation_with_recovered_text",
            )
            if policy:
                return self._classified(
                    warning,
                    policy=policy,
                    reason="layout_quality_policy.equation_with_recovered_text",
                )

        if code == "recovered_text_from_disallowed_block":
            policy = self._policy_item(
                layout_policy,
                "disallowed_block_policy",
                "text_bearing_disallowed_block",
            )
            if policy:
                return self._classified(
                    warning,
                    policy=policy,
                    reason="layout_quality_policy.text_bearing_disallowed_block",
                )

        return {
            **warning,
            "severity": str(warning.get("severity") or "warn"),
            "quality_gate_action": str(warning.get("quality_gate_action") or "review_warning"),
            "suppressed_from_counts": bool(warning.get("suppressed_from_counts", False)),
        }

    def _classified(
        self,
        warning: dict[str, Any],
        *,
        policy: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        warning_level = str(policy.get("warning_level") or "warn")
        action = str(policy.get("action") or "recover_as_text")
        return {
            **warning,
            "severity": warning_level,
            "quality_gate_action": "accepted_recovery" if action == "recover_as_text" else action,
            "suppressed_from_counts": warning_level in INFO_LEVELS,
            "quality_gate_reason": reason,
        }

    def _layout_policy(self, domain_metadata: DomainMetadata | None) -> dict[str, Any]:
        custom_json = (
            domain_metadata.custom_json
            if domain_metadata is not None and isinstance(domain_metadata.custom_json, dict)
            else {}
        )
        layout_policy = custom_json.get("layout_quality_policy")
        return layout_policy if isinstance(layout_policy, dict) else {}

    def _policy_item(
        self,
        layout_policy: dict[str, Any],
        section_name: str,
        item_name: str,
    ) -> dict[str, Any]:
        section = layout_policy.get(section_name)
        if not isinstance(section, dict):
            return {}
        item = section.get(item_name)
        return item if isinstance(item, dict) else {}
```

- [ ] **Step 6: Wire the gate into parser quality summaries**

In `backend/src/ragstudio/services/domain_metadata_quality_gate.py`, add the import:

```python
from ragstudio.services.parser_quality_intelligent_gate import ParserQualityIntelligentGate
```

In `validate_adapter_chunks`, before `quality_summary = self.parser_quality_summary(chunks)`, add:

```python
        self._apply_intelligent_parser_gate(chunks, domain_metadata=domain_metadata)
```

Add this method before `parser_quality_summary`:

```python
    def _apply_intelligent_parser_gate(
        self,
        chunks: list[Any],
        *,
        domain_metadata: DomainMetadata | None,
    ) -> None:
        gate = ParserQualityIntelligentGate()
        for chunk in chunks:
            metadata = self._chunk_metadata(chunk)
            extraction_quality = metadata.get("extraction_quality")
            if not isinstance(extraction_quality, dict):
                extraction_quality = getattr(chunk, "extraction_quality", None)
            if not isinstance(extraction_quality, dict):
                continue
            warnings = extraction_quality.get("parser_warnings")
            if not isinstance(warnings, list):
                continue
            classified = gate.classify_warnings(
                [warning for warning in warnings if isinstance(warning, dict)],
                domain_metadata=domain_metadata,
            )
            extraction_quality["parser_warnings"] = classified
            metadata["extraction_quality"] = extraction_quality
            if hasattr(chunk, "metadata") and isinstance(chunk.metadata, dict):
                chunk.metadata["extraction_quality"] = extraction_quality
```

In `parser_quality_summary`, skip informational accepted recoveries:

```python
            codes = sorted(
                {
                    warning.get("code")
                    for warning in self.parser_warnings_for_chunk(chunk)
                    if isinstance(warning.get("code"), str)
                    and not bool(warning.get("suppressed_from_counts"))
                }
            )
```

- [ ] **Step 7: Run intelligent gate tests and commit**

Run:

```bash
pytest backend/tests/test_domain_metadata.py::test_validate_custom_json_accepts_layout_quality_policy backend/tests/test_domain_metadata.py::test_ai_metadata_normalizes_layout_quality_policy backend/tests/test_parser_quality_intelligent_gate.py backend/tests/test_domain_metadata_quality_gate.py -v
```

Expected: all tests pass.

Commit:

```bash
git add backend/src/ragstudio/services/metadata_json_schema.py backend/src/ragstudio/services/domain_metadata_ai_suggester.py backend/src/ragstudio/services/domain_metadata_quality_gate.py backend/src/ragstudio/services/parser_quality_intelligent_gate.py backend/tests/test_domain_metadata.py backend/tests/test_parser_quality_intelligent_gate.py
git commit -m "feat: add intelligent parser quality gate"
```

---

### Task 7: Document And Verify The Policy Contract

**Files:**
- Modify: `docs/workflows.md`
- Verify: backend test suite slices

- [ ] **Step 1: Update warning documentation**

In `docs/workflows.md`, update the `reference_unit_missing_expected_script` explanation to include this text:

```markdown
`reference_unit_missing_expected_script`: a reference-bearing chunk is missing a script that is required by the active domain policy. When `custom_json.quality_policy` is present, only `required_scripts` trigger this warning. `optional_scripts` are enrichment signals and do not warn when absent if `missing_optional_script_action` is `no_warning`.

For commentary, translation, legal analysis, manuals, and other secondary-source documents, autosuggest can mark a primary-source script as optional. For example, an English Tafseer organized by `Verse 18:30` may require Latin text for answerable chunks while treating Arabic as optional enrichment. Inline citations such as `25:75-76` can be stored as cross-references instead of separate answerable chunks when `custom_json.domain_structure.inline_references.policy` is `cross_reference_only`.

`recovered_text_from_misclassified_block` and `recovered_text_from_disallowed_block`: parser recovery warnings are passed through the intelligent parser quality gate. When `custom_json.layout_quality_policy` says recovered text from equation-like or disallowed blocks is acceptable for the document, these warnings are marked `severity=info`, `quality_gate_action=accepted_recovery`, and excluded from warning counts. They remain visible in detailed metadata for auditability.
```

- [ ] **Step 2: Run focused test suite**

Run:

```bash
pytest backend/tests/test_domain_metadata.py backend/tests/test_domain_metadata_quality_gate.py backend/tests/test_chunk_splitter.py backend/tests/test_parser_quality_intelligent_gate.py -k "domain_structure or quality_policy or layout_quality_policy or reference_unit_missing_expected_script or tafseer or intelligent_gate" -v
```

Expected: all selected tests pass.

- [ ] **Step 3: Run lint for touched backend files**

Run:

```bash
ruff check backend/src/ragstudio/services/metadata_json_schema.py backend/src/ragstudio/services/domain_metadata_ai_suggester.py backend/src/ragstudio/services/reference_metadata.py backend/src/ragstudio/services/reference_unit_assembler.py backend/src/ragstudio/services/domain_metadata_quality_gate.py backend/src/ragstudio/services/parser_quality_intelligent_gate.py backend/src/ragstudio/api/routes/domain_profiles.py backend/tests/test_domain_metadata.py backend/tests/test_domain_metadata_quality_gate.py backend/tests/test_chunk_splitter.py backend/tests/test_parser_quality_intelligent_gate.py
```

Expected: exit code 0.

- [ ] **Step 4: Commit docs and verification cleanup**

Commit:

```bash
git add docs/workflows.md
git commit -m "docs: explain document-specific quality policy"
```

---

## Final Verification

- [ ] Run all affected tests:

```bash
pytest backend/tests/test_domain_metadata.py backend/tests/test_domain_metadata_quality_gate.py backend/tests/test_chunk_splitter.py backend/tests/test_parser_quality_intelligent_gate.py -v
```

Expected: all tests pass.

- [ ] Run backend lint on touched files:

```bash
ruff check backend/src/ragstudio/services/metadata_json_schema.py backend/src/ragstudio/services/domain_metadata_ai_suggester.py backend/src/ragstudio/services/reference_metadata.py backend/src/ragstudio/services/reference_unit_assembler.py backend/src/ragstudio/services/domain_metadata_quality_gate.py backend/src/ragstudio/services/parser_quality_intelligent_gate.py backend/src/ragstudio/api/routes/domain_profiles.py backend/tests/test_domain_metadata.py backend/tests/test_domain_metadata_quality_gate.py backend/tests/test_chunk_splitter.py backend/tests/test_parser_quality_intelligent_gate.py
```

Expected: exit code 0.

- [ ] Manually re-upload `tafseer_ibn_kathir.pdf` in the development environment with autosuggest enabled.

Expected visible outcome:

```text
MinerU: Validated · MinerU artifacts ready.
Ready · Indexed chunks.
Parser quality warnings do not include false Arabic-missing warnings for English Tafseer sections where Arabic is optional.
Accepted recovered-text warnings are marked as info and excluded from warning counts when the vision policy says the recovery is expected for this document.
```

Expected metadata shape for the upload:

```json
{
  "content_role": "tafseer",
  "custom_json": {
    "domain_structure": {
      "primary_anchor": {
        "type": "chapter_verse",
        "unit": "verse_section"
      },
      "inline_references": {
        "policy": "cross_reference_only"
      }
    },
    "quality_policy": {
      "document_role": "commentary",
      "required_scripts": ["latin"],
      "optional_scripts": ["arabic"],
      "missing_optional_script_action": "no_warning",
      "materialization_policy": "allow_if_required_scripts_present"
    },
    "layout_quality_policy": {
      "misclassified_block_policy": {
        "equation_with_recovered_text": {
          "action": "recover_as_text",
          "warning_level": "info"
        }
      },
      "disallowed_block_policy": {
        "text_bearing_disallowed_block": {
          "action": "recover_as_text",
          "warning_level": "info"
        }
      }
    }
  }
}
```

## Self-Review

- Spec coverage: The plan covers richer vision autosuggest, up to 10 sampled pages, document-specific quality/script policy, layout/block recovery policy, an intelligent parser warning gate, primary-anchor versus inline-reference semantics, optional Arabic for Tafseer commentary, warning reduction, docs, and end-to-end regression coverage.
- Placeholder scan: No implementation step relies on an unspecified function name or file path. Every code-changing step includes the exact code shape to add or replace.
- Type consistency: The new custom JSON keys are consistently named `domain_structure`, `quality_policy`, and `layout_quality_policy`; the inline policy value is consistently `cross_reference_only`; script lists use lower-case script names such as `latin` and `arabic`; recovery severity uses `info`, `warn`, and `block`.
