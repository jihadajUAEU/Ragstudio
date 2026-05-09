from ragstudio.services.page_sampler import PageSampler


def test_sample_text_file_uses_start_middle_end_excerpts():
    lines = [f"line {index}" for index in range(120)]
    pages = PageSampler().sample(
        b"\n".join(line.encode("utf-8") for line in lines),
        filename="notes.txt",
        content_type="text/plain",
    )

    assert [page.page_number for page in pages] == [1, 2, 3]
    assert "line 0" in pages[0].text
    assert "line 60" in pages[1].text
    assert "line 119" in pages[2].text
    assert all(page.image_data_url is None for page in pages)


def test_sample_pdf_returns_warning_for_invalid_pdf_bytes():
    sampler = PageSampler()

    pages = sampler.sample(
        b"%PDF invalid bytes",
        filename="broken.pdf",
        content_type="application/pdf",
    )

    assert pages == []
    assert sampler.warnings
    assert "Could not sample PDF pages" in sampler.warnings[0]
