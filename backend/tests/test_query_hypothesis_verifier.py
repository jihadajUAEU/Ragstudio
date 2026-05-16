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
        expanded_terms=["حنانا"],
    )

    assert verification.status == "confirmed"
    assert verification.reference == "19:13"
    assert verification.surah == "Maryam"
    assert verification.matched_terms == ["حنانا"]
    assert verification.evidence_label == "S1"


def test_verifier_prefers_section_reference_over_wrong_chunk_canonical_reference():
    hypothesis = QueryHypothesis(
        original_query="where is hanan",
        target_terms=[QueryTargetTerm(surface="hanan", script="latin")],
        valid=True,
    )
    candidate = EvidenceCandidate(
        candidate_id="metadata:quran-window",
        text="[19:10] Earlier verse\n\n[19:13] وَحَنَانًا مِّن لَّدُنَّا",
        document_id="doc-quran",
        chunk_id="quran-window",
        source_location={},
        metadata={},
        tool="metadata",
        tool_rank=1,
        base_score=10,
        retrieval_pass="lexical_expanded_token",
        match_features={"expanded_token": "حنانا"},
        canonical_reference="19:10",
    )

    verification = QueryHypothesisVerifier().verify(
        hypothesis,
        [candidate],
        document_ids=["doc-quran"],
        expanded_terms=["حنانا"],
    )

    assert verification.status == "confirmed"
    assert verification.reference == "19:13"


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
        expanded_terms=["حنانا"],
    )

    assert verification.status == "rejected"
    assert verification.reason == "target_term_not_confirmed_in_evidence"


def test_verifier_confirms_possible_reference_only_when_evidence_matches():
    hypothesis = QueryHypothesis(
        original_query="Which hadith says about offering sacrifice for eid?",
        intent="reference_lookup",
        target_terms=[QueryTargetTerm(surface="sacrifice", script="latin")],
        possible_references=["book:13:hadith:25", "book:34:hadith:288"],
        domain_hint="hadith",
        answer_shape="reference",
        valid=True,
    )
    candidate = EvidenceCandidate(
        candidate_id="metadata:book-13-hadith-25",
        text="Book 13, Hadith 25. Prayer first, then sacrifice on Eid.",
        document_id="doc-hadith",
        chunk_id="book-13-hadith-25",
        source_location={"reference": "Book 13, Hadith 25"},
        metadata={"reference_metadata": {"references": ["book:13:hadith:25"]}},
        tool="metadata",
        tool_rank=1,
        base_score=10,
        retrieval_pass="reference_exact",
        canonical_reference="book:13:hadith:25",
    )

    verification = QueryHypothesisVerifier().verify(
        hypothesis,
        [candidate],
        document_ids=["doc-hadith"],
    )

    assert verification.status == "confirmed"
    assert verification.reference == "book:13:hadith:25"
    assert verification.evidence_label == "S1"
    assert verification.possible_reference_results == [
        {
            "reference": "book:13:hadith:25",
            "status": "confirmed",
            "reason": "reference_found_in_evidence",
            "evidence_candidate_id": "metadata:book-13-hadith-25",
            "evidence_label": "S1",
        },
        {
            "reference": "book:34:hadith:288",
            "status": "not_found",
            "reason": "reference_not_in_retrieved_evidence",
            "evidence_candidate_id": None,
            "evidence_label": None,
        },
    ]


def test_verifier_rejects_hallucinated_possible_reference_but_allows_term_match():
    hypothesis = QueryHypothesis(
        original_query="Which hadith says about offering sacrifice for eid?",
        intent="reference_lookup",
        target_terms=[QueryTargetTerm(surface="sacrifice", script="latin")],
        possible_references=["book:34:hadith:288"],
        valid=True,
    )
    candidate = EvidenceCandidate(
        candidate_id="metadata:book-13-hadith-25",
        text="Book 13, Hadith 25. Prayer first, then sacrifice on Eid.",
        document_id="doc-hadith",
        chunk_id="book-13-hadith-25",
        source_location={"reference": "Book 13, Hadith 25"},
        metadata={},
        tool="metadata",
        tool_rank=1,
        base_score=10,
        canonical_reference="book:13:hadith:25",
    )

    verification = QueryHypothesisVerifier().verify(
        hypothesis,
        [candidate],
        document_ids=["doc-hadith"],
    )

    assert verification.status == "confirmed"
    assert verification.reference == "book:13:hadith:25"
    assert verification.possible_reference_results[0]["status"] == "not_found"
