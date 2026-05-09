from __future__ import annotations

import importlib
import importlib.metadata as metadata


EXPECTED_VERSIONS = {
    "torch": "2.11.0",
    "PyYAML": "6.0.3",
    "raganything": "1.3.0",
    "mineru": "3.1.9",
    "lightrag-hku": "1.4.16",
    "paddleocr": "3.5.0",
    "paddlex": "3.5.1",
    "PyMuPDF": "1.26.6",
}

MODULES = (
    "torch",
    "yaml",
    "raganything",
    "mineru",
    "lightrag",
    "paddleocr",
    "paddlex",
    "fitz",
)


def main() -> None:
    for package_name, expected in EXPECTED_VERSIONS.items():
        actual = metadata.version(package_name)
        if actual != expected:
            raise RuntimeError(f"{package_name} version mismatch: {actual} != {expected}")

    for module in MODULES:
        importlib.import_module(module)


if __name__ == "__main__":
    main()
