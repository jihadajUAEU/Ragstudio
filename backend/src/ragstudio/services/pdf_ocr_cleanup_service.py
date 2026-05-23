from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

Runner = Callable[[Sequence[str], float], Awaitable["PdfOcrCleanupRunResult"]]


@dataclass(frozen=True)
class PdfOcrCleanupRunResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class PdfOcrCleanupError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class PdfOcrCleanupService:
    def __init__(
        self,
        *,
        docker_image: str = "ragstudio-ocrmypdf:ara-eng",
        languages: str = "ara+eng",
        timeout_seconds: float = 900,
        docker_binary: str = "docker",
        runner: Runner | None = None,
    ) -> None:
        self.docker_image = docker_image
        self.languages = languages
        self.timeout_seconds = timeout_seconds
        self.docker_binary = docker_binary
        self.runner = runner or _run_command

    async def clean(self, source_path: Path, output_path: Path) -> Path:
        source = source_path.resolve()
        output = output_path.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        command = self._docker_command(source, output)
        try:
            result = await self.runner(command, self.timeout_seconds)
        except FileNotFoundError as exc:
            raise PdfOcrCleanupError(
                "pdf_cleanup_unavailable",
                "OCR cleanup tooling is unavailable.",
            ) from exc
        except TimeoutError as exc:
            raise PdfOcrCleanupError(
                "pdf_cleanup_timeout",
                "OCR cleanup timed out before completion.",
            ) from exc

        if result.returncode != 0:
            raise self._map_failed_result(result)
        if not output.exists():
            raise PdfOcrCleanupError(
                "pdf_cleanup_failed",
                "OCR cleanup finished without producing an output PDF.",
            )
        return output

    async def clean_sample_pages(
        self,
        source_path: Path,
        page_numbers: Sequence[int],
        output_path: Path,
    ) -> Path:
        normalized_pages = sorted(
            {page for page in page_numbers if isinstance(page, int) and page > 0}
        )
        if not normalized_pages:
            raise PdfOcrCleanupError(
                "pdf_cleanup_failed",
                "No sample pages were provided for OCR cleanup.",
            )

        try:
            import fitz  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - dependency is runtime-required
            raise RuntimeError("PyMuPDF is required for sampled PDF cleanup.") from exc

        with tempfile.TemporaryDirectory(prefix="ragstudio-pdf-ocr-sample-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            sample_source = temp_dir / "sample.pdf"
            with fitz.open(source_path) as source_document:
                sample_document = fitz.open()
                try:
                    for page_number in normalized_pages:
                        if page_number > source_document.page_count:
                            continue
                        sample_document.insert_pdf(
                            source_document,
                            from_page=page_number - 1,
                            to_page=page_number - 1,
                        )
                    if sample_document.page_count == 0:
                        raise PdfOcrCleanupError(
                            "pdf_cleanup_failed",
                            "No requested sample pages exist in the source PDF.",
                        )
                    sample_document.save(sample_source)
                finally:
                    sample_document.close()
            return await self.clean(sample_source, output_path)

    def _docker_command(self, source_path: Path, output_path: Path) -> list[str]:
        return [
            self.docker_binary,
            "run",
            "--rm",
            "-v",
            f"{source_path.parent}:/source",
            "-v",
            f"{output_path.parent}:/output",
            self.docker_image,
            "--force-ocr",
            "-l",
            self.languages,
            "--deskew",
            "--clean",
            "--rotate-pages",
            "--optimize",
            "1",
            f"/source/{source_path.name}",
            f"/output/{output_path.name}",
        ]

    def _map_failed_result(self, result: PdfOcrCleanupRunResult) -> PdfOcrCleanupError:
        stderr = (result.stderr or "").strip()
        detail = stderr or (result.stdout or "").strip() or "OCR cleanup failed."
        lowered = detail.casefold()
        if _language_missing(lowered):
            return PdfOcrCleanupError(
                "pdf_cleanup_language_missing",
                "OCR cleanup is missing required language data.",
            )
        return PdfOcrCleanupError("pdf_cleanup_failed", detail)


async def _run_command(
    command: Sequence[str],
    timeout_seconds: float,
) -> PdfOcrCleanupRunResult:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise
    return PdfOcrCleanupRunResult(
        returncode=process.returncode,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


def _language_missing(detail: str) -> bool:
    return any(
        marker in detail
        for marker in (
            "language data for: ara",
            "language data for: eng",
            "failed loading language 'ara'",
            "failed loading language 'eng'",
            "error opening data file",
            "traineddata",
        )
    )
