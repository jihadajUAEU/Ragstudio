import json

import pytest
from ragstudio.services.evaluation_importer import EvaluationImportError, parse_evaluation_cases


def test_import_csv_normalizes_pipe_delimited_list_fields():
    content = (
        b"id,query,documents,expected_sources,must_include,must_avoid,expected_answer\n"
        b"pricing,What is pricing?,doc-a|doc-b,source-a|source-b,alpha| beta,bad|worse,Use tiers\n"
    )

    cases = parse_evaluation_cases("cases.csv", content)

    assert cases[0].documents == ["doc-a", "doc-b"]
    assert cases[0].expected_sources == ["source-a", "source-b"]
    assert cases[0].must_include == ["alpha", "beta"]
    assert cases[0].must_avoid == ["bad", "worse"]


def test_import_json_supports_cases_wrapper_and_aliases():
    content = json.dumps(
        {
            "cases": [
                {
                    "question": "What changed?",
                    "expected_output": "The import format changed.",
                    "sources": ["release-notes"],
                }
            ]
        }
    ).encode()

    cases = parse_evaluation_cases("cases.json", content)

    assert cases[0].id == "case-1"
    assert cases[0].query == "What changed?"
    assert cases[0].expected_answer == "The import format changed."
    assert cases[0].expected_sources == ["release-notes"]


def test_import_jsonl_reads_one_case_per_line():
    content = b"""
{"id":"one","query":"Q1","expected_answer":"A1"}
{"id":"two","query":"Q2","must_include":"alpha|beta"}
"""

    cases = parse_evaluation_cases("cases.jsonl", content)

    assert [case.id for case in cases] == ["one", "two"]
    assert cases[1].must_include == ["alpha", "beta"]


def test_import_yaml_reads_case_list():
    content = b"""
- id: yaml-case
  query: What is supported?
  documents: doc-a|doc-b
  must_include: yaml|json
"""

    cases = parse_evaluation_cases("cases.yaml", content)

    assert cases[0].id == "yaml-case"
    assert cases[0].documents == ["doc-a", "doc-b"]
    assert cases[0].must_include == ["yaml", "json"]


def test_import_yaml_reads_native_lists_and_maps():
    content = b"""
cases:
  - id: yaml-native
    query: What is supported?
    must_include:
      - yaml
      - nested lists
    expected_structure:
      answer:
        type: string
      citations:
        min_items: 1
    rubric:
      accuracy: Mentions native YAML structures.
"""

    cases = parse_evaluation_cases("cases.yaml", content)

    assert cases[0].id == "yaml-native"
    assert cases[0].must_include == ["yaml", "nested lists"]
    assert cases[0].expected_structure == {
        "answer": {"type": "string"},
        "citations": {"min_items": 1},
    }
    assert cases[0].rubric == {"accuracy": "Mentions native YAML structures."}


def test_import_rejects_cases_without_expected_output_signal():
    content = b'[{"id":"empty","query":"What now?","documents":"doc-a|doc-b"}]'

    with pytest.raises(EvaluationImportError, match="expected-output signal"):
        parse_evaluation_cases("cases.json", content)


@pytest.mark.asyncio
async def test_import_evaluation_set_endpoint_and_list(client):
    files = {
        "file": (
            "cases.csv",
            b"id,query,expected_answer,must_include\none,What?,Answer,alpha|beta\n",
            "text/csv",
        )
    }

    import_response = await client.post("/api/evaluation-sets/import?name=Smoke", files=files)

    assert import_response.status_code == 201
    evaluation_set = import_response.json()
    assert evaluation_set["name"] == "Smoke"
    assert evaluation_set["cases"][0]["must_include"] == ["alpha", "beta"]

    list_response = await client.get("/api/evaluation-sets")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == evaluation_set["id"]


@pytest.mark.asyncio
async def test_import_evaluation_set_endpoint_rejects_malformed_json(client):
    files = {
        "file": (
            "cases.json",
            b'{"cases": [{"id": "broken", "query": "What?", "expected_answer": "Answer",}]}',
            "application/json",
        )
    }

    response = await client.post("/api/evaluation-sets/import?name=Broken", files=files)

    assert response.status_code == 400
