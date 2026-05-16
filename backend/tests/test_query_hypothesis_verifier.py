from ragstudio.services.query_hypothesis_service import (
    ProbableAnswer,
    QueryHypothesis,
    QueryTargetTerm,
)
from ragstudio.services.query_hypothesis_verifier import QueryHypothesisVerifier
from ragstudio.services.retrieval_evidence import EvidenceCandidate


def test_verifier_confirms_probable_reference_and_matched_arabic_term():
    hypothesis = QueryHypothesis(
        original_query="in which surah the word hanan is mentioned",
        intent="find_word_occurrence",
        target_terms=[
            QueryTargetTerm(
                surface="hanan",
                script="latin",
                language_hint="arabic",
                term_type="transliteration",
            )
        ],
        domain_hint="quran",
        answer_shape="surah_and_verse",
        probable_answer=ProbableAnswer(
            surah="Maryam",
            surah_number=19,
            ayah=13,
            matched_term="حنانا",
        ),
        confidence=0.82,
        valid=True,
    )
    candidate = EvidenceCandidate(
        candidate_id="metadata:quran-19-13",
        text="[19:10] Earlier verse\n\n[19:13] وَحَنَانًا مِّن لَّدُنَّا",
        document_id="doc-quran",
        chunk_id="quran-19-13",
        source_location={},
        metadata={},
        tool="metadata",
        tool_rank=1,
        base_score=10,
        retrieval_pass="lexical_expanded_token",
        match_features={
            "lexical_expanded": True,
            "expanded_token": "حنانا",
            "match_type": "transliteration",
        },
        canonical_reference="19:13",
    )

    verification = QueryHypothesisVerifier().verify(
        hypothesis,
        [candidate],
        document_ids=["doc-quran"],
    )

    assert verification.status == "confirmed"
    assert verification.reference == "19:13"
    assert verification.surah == "Maryam"
    assert verification.matched_terms == ["حنانا"]
    assert verification.evidence_label == "S1"


def test_verifier_rejects_when_reference_does_not_match_probable_answer():
    hypothesis = QueryHypothesis(
        original_query="where is hanan",
        target_terms=[QueryTargetTerm(surface="hanan", script="latin")],
        probable_answer=ProbableAnswer(surah_number=19, ayah=13, matched_term="حنانا"),
        valid=True,
    )
    candidate = EvidenceCandidate(
        candidate_id="metadata:other",
        text="وحنانا appears in a copied note",
        document_id="doc-quran",
        chunk_id="other",
        source_location={"reference": "20:1"},
        metadata={},
        tool="metadata",
        tool_rank=1,
        base_score=10,
        match_features={"expanded_token": "حنانا"},
        canonical_reference="20:1",
    )

    verification = QueryHypothesisVerifier().verify(
        hypothesis,
        [candidate],
        document_ids=["doc-quran"],
    )

    assert verification.status == "rejected"
    assert verification.reason == "target_term_not_confirmed_in_evidence"
