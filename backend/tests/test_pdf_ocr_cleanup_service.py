import pytest
from ragstudio.services.pdf_ocr_cleanup_service import (
    PdfOcrCleanupError,
    PdfOcrCleanupRunResult,
    PdfOcrCleanupService,
)


class FakeRunner:
    def __init__(
        self,
        *,
        result: PdfOcrCleanupRunResult | None = None,
        exc: Exception | None = None,
    ):
        self.result = result or PdfOcrCleanupRunResult(returncode=0)
        self.exc = exc
        self.calls: list[dict[str, object]] = []

    async def __call__(self, command, timeout_seconds):
        self.calls.append({"command": list(command), "timeout_seconds": timeout_seconds})
        if self.exc is not None:
            raise self.exc
        return self.result


@pytest.mark.asyncio
async def test_cleanup_language_missing_maps_stable_error(tmp_path):
    runner = FakeRunner(
        result=PdfOcrCleanupRunResult(
            returncode=2,
            stderr="OCR engine does not have language data for: ara",
        )
    )
    service = PdfOcrCleanupService(runner=runner)

    with pytest.raises(PdfOcrCleanupError) as exc_info:
        await service.clean(tmp_path / "in.pdf", tmp_path / "out.pdf")

    assert exc_info.value.code == "pdf_cleanup_language_missing"


@pytest.mark.asyncio
async def test_cleanup_timeout_maps_stable_error(tmp_path):
    runner = FakeRunner(exc=TimeoutError())
    service = PdfOcrCleanupService(runner=runner)

    with pytest.raises(PdfOcrCleanupError) as exc_info:
        await service.clean(tmp_path / "in.pdf", tmp_path / "out.pdf")

    assert exc_info.value.code == "pdf_cleanup_timeout"


@pytest.mark.asyncio
async def test_cleanup_unavailable_maps_stable_error(tmp_path):
    runner = FakeRunner(exc=FileNotFoundError("docker"))
    service = PdfOcrCleanupService(runner=runner)

    with pytest.raises(PdfOcrCleanupError) as exc_info:
        await service.clean(tmp_path / "in.pdf", tmp_path / "out.pdf")

    assert exc_info.value.code == "pdf_cleanup_unavailable"


@pytest.mark.asyncio
async def test_cleanup_nonzero_exit_maps_failed_error(tmp_path):
    runner = FakeRunner(
        result=PdfOcrCleanupRunResult(returncode=1, stderr="ocrmypdf crashed unexpectedly")
    )
    service = PdfOcrCleanupService(runner=runner)

    with pytest.raises(PdfOcrCleanupError) as exc_info:
        await service.clean(tmp_path / "in.pdf", tmp_path / "out.pdf")

    assert exc_info.value.code == "pdf_cleanup_failed"
    assert "crashed unexpectedly" in str(exc_info.value)
