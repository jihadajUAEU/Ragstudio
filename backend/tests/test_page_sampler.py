import fitz
from ragstudio.services.page_sampler import PageSampler


def test_sample_pdf_renders_valid_pdf_pages():
    document = fitz.open()
    for index in range(5):
        page = document.new_page()
        page.insert_text((72, 72), f"Sample page {index + 1}")
    pdf_bytes = document.tobytes()
    document.close()

    pages = PageSampler().sample(
        pdf_bytes,
        filename="sample.pdf",
        content_type="application/pdf",
    )

    assert [page.page_number for page in pages] == [1, 2, 3, 5]
    assert "Sample page 1" in pages[0].text
    assert pages[0].image_data_url is not None
    assert pages[0].image_data_url.startswith("data:image/png;base64,")


def test_sample_pdf_uses_broader_samples_when_more_pages_are_requested():
    document = fitz.open()
    for index in range(20):
        page = document.new_page()
        page.insert_text((72, 72), f"Sample page {index + 1}")
    pdf_bytes = document.tobytes()
    document.close()

    pages = PageSampler(max_pages=10).sample(
        pdf_bytes,
        filename="sample.pdf",
        content_type="application/pdf",
    )

    assert [page.page_number for page in pages] == [1, 2, 3, 4, 5, 6, 11, 16, 19, 20]
    assert "Sample page 20" in pages[-1].text


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


def test_sample_unsupported_binary_file_returns_warning():
    sampler = PageSampler()

    pages = sampler.sample(
        b"PK\x03\x04 fake office document",
        filename="document.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert pages == []
    assert sampler.warnings == [
        "Unsupported file type for AI metadata autosuggest: "
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document."
    ]


def test_sample_rejects_binary_content_mislabeled_as_text():
    sampler = PageSampler()

    pages = sampler.sample(
        b"plain prefix\x00binary tail",
        filename="notes.txt",
        content_type="text/plain",
    )

    assert pages == []
    assert sampler.warnings == ["Text sample contains null bytes and appears to be binary."]


def test_sample_rejects_invalid_utf8_mislabeled_as_text():
    sampler = PageSampler()

    pages = sampler.sample(
        b"\xff\xfe\xfa" * 10,
        filename="notes.txt",
        content_type="text/plain",
    )

    assert pages == []
    assert sampler.warnings == [
        "Text sample contains too many invalid or control characters."
    ]


def test_sample_pdf_omits_oversized_images_with_warning():
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Large image page")
    pdf_bytes = document.tobytes()
    document.close()

    sampler = PageSampler(max_image_bytes=10)
    pages = sampler.sample(pdf_bytes, filename="large.pdf", content_type="application/pdf")

    assert len(pages) == 1
    assert pages[0].image_data_url is None
    assert sampler.warnings == ["Skipped page 1 image because it exceeded 10 bytes."]


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
