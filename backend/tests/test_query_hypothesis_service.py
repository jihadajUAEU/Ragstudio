import httpx
import pytest
from ragstudio.services.query_hypothesis_service import (
    ProbableAnswer,
    QueryHypothesis,
    QueryHypothesisService,
    QueryTargetTerm,
)


def quran_domain_metadata() -> list[dict[str, object]]:
    return [
        {
            "domain": "quran_tafseer",
            "document_type": "tafseer",
            "content_role": "quran",
            "tags": ["quran", "tafseer", "arabic"],
            "custom_json": {
                "reference_schema": {
                    "type": "chapter_verse",
                    "fields": {"chapter": "chapter_number", "verse": "verse_number"},
                },
                "quality_policy": {
                    "required_scripts_by_unit_role": {"verse": ["arabic"]},
                },
            },
        }
    ]


def test_parse_hypothesis_extracts_transliteration_target_and_probable_answer():
    raw = {
        "intent": "find_word_occurrence",
        "target_terms": [
            {
                "surface": "hanan",
                "script": "latin",
                "language_hint": "arabic",
                "term_type": "transliteration",
            }
        ],
        "domain_hint": "quran",
        "answer_shape": "surah_and_verse",
        "probable_answer": {
            "surah": "Maryam",
            "surah_number": 19,
            "ayah": 13,
            "matched_term": "حنانا",
        },
        "confidence": 0.82,
        "needs_clarification": False,
    }

    hypothesis = QueryHypothesisService.parse_hypothesis(raw, original_query="where is hanan")

    assert hypothesis.intent == "find_word_occurrence"
    assert hypothesis.target_terms == [
        QueryTargetTerm(
            surface="hanan",
            script="latin",
            language_hint="arabic",
            term_type="transliteration",
        )
    ]
    assert hypothesis.domain_hint == "quran"
    assert hypothesis.answer_shape == "surah_and_verse"
    assert hypothesis.probable_answer == ProbableAnswer(
        surah="Maryam",
        surah_number=19,
        ayah=13,
        matched_term="حنانا",
    )
    assert hypothesis.confidence == pytest.approx(0.82)
    assert hypothesis.needs_clarification is False
    assert hypothesis.valid is True


def test_parse_hypothesis_drops_unsafe_and_oversized_terms():
    raw = {
        "intent": "find_word_occurrence",
        "target_terms": [
            {"surface": "/Users/meet/private.pdf", "script": "latin", "term_type": "exact_text"},
            {"surface": "http://example.com", "script": "latin", "term_type": "exact_text"},
            {"surface": "x" * 81, "script": "latin", "term_type": "exact_text"},
            {"surface": "حنانا", "script": "arabic", "term_type": "exact_text"},
        ],
        "domain_hint": "quran",
        "answer_shape": "surah_and_verse",
        "confidence": 2,
        "needs_clarification": False,
    }

    hypothesis = QueryHypothesisService.parse_hypothesis(raw, original_query="where is حنانا")

    assert [term.surface for term in hypothesis.target_terms] == ["حنانا"]
    assert hypothesis.confidence == 1.0
    assert hypothesis.valid is True


def test_parse_hypothesis_sanitizes_unsafe_probable_answer_strings():
    raw = {
        "intent": "find_word_occurrence",
        "target_terms": [{"surface": "hanan", "script": "latin", "term_type": "transliteration"}],
        "domain_hint": "quran",
        "answer_shape": "surah_and_verse",
        "probable_answer": {
            "surah": "Maryam\nInjected",
            "surah_number": 19,
            "ayah": 13,
            "matched_term": "http://example.com",
            "reference": "/Users/meet/private",
        },
        "confidence": 0.8,
    }

    hypothesis = QueryHypothesisService.parse_hypothesis(raw, original_query="where is hanan")

    assert hypothesis.probable_answer == ProbableAnswer(
        surah="Maryam Injected",
        surah_number=19,
        ayah=13,
    )


def test_parse_hypothesis_accepts_live_hadith_retrieval_plan_with_terms():
    raw = {
        "intent": "retrieval",
        "target_terms": [
            "hadith",
            "eid",
            "sacrifice",
            "hadith_bukhari",
        ],
        "domain_hint": "hadith",
        "answer_shape": "citation",
        "probable_answer": (
            "The hadith in Sahih al-Bukhari (Book 34, Hadith 288) states this."
        ),
        "confidence": "medium",
        "needs_clarification": True,
    }

    hypothesis = QueryHypothesisService.parse_hypothesis(
        raw,
        original_query=(
            "Which is the hadith saying about offering sacrifice for eid from hadith_bukhari"
        ),
    )

    assert hypothesis.valid is True
    assert hypothesis.intent == "semantic_question"
    assert hypothesis.answer_shape == "reference"
    assert hypothesis.needs_clarification is False
    assert [term.surface for term in hypothesis.target_terms] == [
        "hadith",
        "eid",
        "sacrifice",
        "hadith_bukhari",
    ]


def test_parse_hypothesis_normalizes_possible_hadith_references():
    raw = {
        "intent": "reference_lookup",
        "target_terms": ["offering", "sacrifice", "eid"],
        "domain_hint": "hadith",
        "answer_shape": "reference",
        "possible_references": [
            "Book 13, Hadith 25",
            {"reference": "book:34:hadith:288"},
            {"book": 13, "hadith": 25},
            "/Users/meet/private.pdf",
        ],
        "probable_answer": {"reference": "Book 13, Hadith 25"},
        "confidence": "high",
        "needs_clarification": False,
    }

    hypothesis = QueryHypothesisService.parse_hypothesis(
        raw,
        original_query="Which hadith says about offering sacrifice for eid?",
    )

    assert hypothesis.valid is True
    assert hypothesis.possible_references == [
        "book:13:hadith:25",
        "book:34:hadith:288",
    ]
    assert hypothesis.probable_answer == ProbableAnswer(reference="book:13:hadith:25")
    assert hypothesis.confidence == pytest.approx(0.9)


def test_parse_hypothesis_accepts_reference_only_search_plan():
    hypothesis = QueryHypothesisService.parse_hypothesis(
        {
            "intent": "reference_lookup",
            "possible_references": ["Book 13 Hadith 25"],
            "domain_hint": "hadith",
            "answer_shape": "reference",
        },
        original_query="find the Eid sacrifice hadith",
    )

    assert hypothesis.valid is True
    assert hypothesis.target_terms == []
    assert hypothesis.possible_references == ["book:13:hadith:25"]


@pytest.mark.parametrize(
    ("possible_references", "expected"),
    [
        ("Book 13, Hadith 25", ["book:13:hadith:25"]),
        ({"reference": "Book 13, Hadith 25"}, ["book:13:hadith:25"]),
        ({"book": "13", "hadith": "25"}, ["book:13:hadith:25"]),
    ],
)
def test_parse_hypothesis_accepts_single_possible_reference_shapes(
    possible_references,
    expected,
):
    hypothesis = QueryHypothesisService.parse_hypothesis(
        {
            "intent": "reference_lookup",
            "possible_references": possible_references,
            "domain_hint": "hadith",
            "answer_shape": "reference",
        },
        original_query="find the Eid sacrifice hadith",
    )

    assert hypothesis.valid is True
    assert hypothesis.possible_references == expected


def test_parse_hypothesis_returns_invalid_for_non_dict():
    hypothesis = QueryHypothesisService.parse_hypothesis(["bad"], original_query="hello")

    assert hypothesis == QueryHypothesis.empty("hello", reason="invalid_hypothesis_shape")


def test_deterministic_hypothesis_extracts_latin_word_target_from_sentence():
    hypothesis = QueryHypothesisService().deterministic_hypothesis(
        "in which surah the word hanan is mentioned",
        domain_metadata=quran_domain_metadata(),
    )

    assert hypothesis.valid is True
    assert hypothesis.source == "deterministic"
    assert hypothesis.target_terms == [
        QueryTargetTerm(
            surface="hanan",
            script="latin",
            language_hint="arabic",
            term_type="transliteration",
        )
    ]


def test_deterministic_hypothesis_extracts_arabic_term_from_mixed_sentence():
    hypothesis = QueryHypothesisService().deterministic_hypothesis(
        "where is حنانا mentioned",
        domain_metadata=quran_domain_metadata(),
    )

    assert hypothesis.valid is True
    assert hypothesis.target_terms[0].surface == "حنانا"
    assert hypothesis.target_terms[0].script == "arabic"


def test_deterministic_hypothesis_extracts_arabic_term_after_word_marker():
    hypothesis = QueryHypothesisService().deterministic_hypothesis(
        "اين ذكرت كلمة حنانا",
        domain_metadata=quran_domain_metadata(),
    )

    assert hypothesis.valid is True
    assert [term.surface for term in hypothesis.target_terms] == ["حنانا"]


def test_deterministic_hypothesis_skips_ambiguous_arabic_wrapper_without_marker():
    hypothesis = QueryHypothesisService().deterministic_hypothesis(
        "اين ذكرت حنانا",
        domain_metadata=quran_domain_metadata(),
    )

    assert hypothesis.valid is False
    assert hypothesis.reason == "no_target_terms"


class FakeResponse:
    def __init__(self, body, *, status_code=200):
        self.body = body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad status", request=None, response=None)

    def json(self):
        return self.body


class FakeClient:
    def __init__(self, response=None, *, exc=None):
        self.response = response
        self.exc = exc
        self.timeout = None
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, *, headers, json):
        self.requests.append({"url": url, "headers": headers, "json": json})
        if self.exc is not None:
            raise self.exc
        return self.response


def profile():
    return type(
        "Profile",
        (),
        {
            "llm_base_url": "http://llm.example/v1",
            "llm_api_key": "secret",
            "llm_model": "test-model",
        },
    )()


@pytest.mark.asyncio
async def test_hypothesize_returns_llm_json_hypothesis(monkeypatch):
    fake_client = FakeClient(
        FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"intent":"find_word_occurrence",'
                                '"target_terms":[{"surface":"hanan","script":"latin",'
                                '"term_type":"transliteration"}],'
                                '"domain_hint":"quran","answer_shape":"surah_and_verse",'
                                '"confidence":0.8}'
                            )
                        }
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(
        "ragstudio.services.query_hypothesis_service.httpx.AsyncClient",
        lambda *, timeout: fake_client,
    )

    hypothesis = await QueryHypothesisService().hypothesize(
        "find hanan",
        profile=profile(),
        domain_metadata=[],
        timeout_ms=500,
    )

    assert hypothesis.valid is True
    assert hypothesis.source == "llm"
    assert fake_client.requests[0]["url"] == "http://llm.example/v1/chat/completions"


@pytest.mark.asyncio
async def test_hypothesize_returns_invalid_on_llm_timeout(monkeypatch):
    fake_client = FakeClient(exc=httpx.ReadTimeout("timeout"))
    monkeypatch.setattr(
        "ragstudio.services.query_hypothesis_service.httpx.AsyncClient",
        lambda *, timeout: fake_client,
    )

    hypothesis = await QueryHypothesisService().hypothesize(
        "find hanan",
        profile=profile(),
        domain_metadata=[],
        timeout_ms=500,
    )

    assert hypothesis.valid is False
    assert hypothesis.reason == "llm_ReadTimeout"


@pytest.mark.asyncio
async def test_hypothesize_returns_invalid_on_bad_json(monkeypatch):
    fake_client = FakeClient(
        FakeResponse({"choices": [{"message": {"content": "not json"}}]})
    )
    monkeypatch.setattr(
        "ragstudio.services.query_hypothesis_service.httpx.AsyncClient",
        lambda *, timeout: fake_client,
    )

    hypothesis = await QueryHypothesisService().hypothesize(
        "find hanan",
        profile=profile(),
        domain_metadata=[],
        timeout_ms=500,
    )

    assert hypothesis.valid is False
    assert hypothesis.reason == "no_valid_search_plan"
