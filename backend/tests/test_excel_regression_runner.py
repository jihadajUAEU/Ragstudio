from ragstudio.services.excel_regression_runner import ExcelCase, summarize_excel_results


def test_summarize_excel_results_passes_when_expected_text_is_within_required_rank():
    cases = [
        ExcelCase(
            case_id="case-1",
            query="Where is the phrase?",
            expected_text="expected passage",
            required_rank=2,
        )
    ]
    results_by_case = {
        "case-1": [
            {
                "text": "first result",
                "metadata": {"retrieval_explain": {"score": 0.9, "signals": ["lexical"]}},
            },
            {
                "text": "second result with expected passage",
                "metadata": {"retrieval_explain": {"score": 0.8, "signals": ["exact"]}},
            },
        ]
    }

    summaries = summarize_excel_results(cases, results_by_case)

    assert summaries == [
        {
            "case_id": "case-1",
            "query": "Where is the phrase?",
            "expected_text": "expected passage",
            "required_rank": 2,
            "matched_rank": 2,
            "verdict": "PASS",
            "top_debug": [
                {"score": 0.9, "signals": ["lexical"]},
                {"score": 0.8, "signals": ["exact"]},
            ],
        }
    ]


def test_summarize_excel_results_fails_when_expected_text_is_missing():
    cases = [
        ExcelCase(
            case_id="case-2",
            query="Missing phrase?",
            expected_text="missing expected passage",
            required_rank=1,
        )
    ]
    results_by_case = {
        "case-2": [
            {
                "text": "unrelated result",
                "metadata": {"retrieval_explain": {"score": 0.4}},
            }
        ]
    }

    summaries = summarize_excel_results(cases, results_by_case)

    assert summaries[0]["matched_rank"] is None
    assert summaries[0]["verdict"] == "FAIL"
    assert summaries[0]["top_debug"] == [{"score": 0.4}]


def test_summarize_excel_results_fails_when_match_is_beyond_required_rank():
    cases = [
        ExcelCase(
            case_id="case-3",
            query="Late phrase?",
            expected_text="late expected passage",
            required_rank=1,
        )
    ]
    results_by_case = {
        "case-3": [
            {
                "text": "close but wrong",
                "metadata": {"retrieval_explain": {"rank": 1}},
            },
            {
                "text": "late expected passage",
                "metadata": {"retrieval_explain": {"rank": 2}},
            },
        ]
    }

    summaries = summarize_excel_results(cases, results_by_case)

    assert summaries[0]["matched_rank"] == 2
    assert summaries[0]["verdict"] == "FAIL"
    assert summaries[0]["top_debug"] == [{"rank": 1}, {"rank": 2}]


def test_summarize_excel_results_limits_debug_to_top_five_results():
    cases = [
        ExcelCase(
            case_id="case-4",
            query="Debug limit?",
            expected_text="expected",
            required_rank=10,
        )
    ]
    results_by_case = {
        "case-4": [
            {"text": f"result {index}", "metadata": {"retrieval_explain": {"rank": index}}}
            for index in range(1, 7)
        ]
    }

    summaries = summarize_excel_results(cases, results_by_case)

    assert summaries[0]["top_debug"] == [
        {"rank": 1},
        {"rank": 2},
        {"rank": 3},
        {"rank": 4},
        {"rank": 5},
    ]
