from __future__ import annotations

import argparse
import base64
import hashlib
import tempfile
import zipfile
from pathlib import Path


PINNED_REQUIREMENT = "Requires-Dist: PyYAML==6.0.2"
PATCHED_REQUIREMENT = "Requires-Dist: PyYAML>=6.0.3,<7"


def patch_wheel(source_dir: Path, output_dir: Path) -> Path:
    wheels = sorted(source_dir.glob("paddlex-3.5.1-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"Expected one paddlex wheel in {source_dir}, found {len(wheels)}")

    wheel_path = wheels[0]
    output_dir.mkdir(parents=True, exist_ok=True)
    patched_path = output_dir / wheel_path.name

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(wheel_path) as wheel:
            wheel.extractall(tmp_path)

        dist_info_dirs = list(tmp_path.glob("paddlex-3.5.1.dist-info"))
        if len(dist_info_dirs) != 1:
            raise RuntimeError("Could not locate paddlex dist-info directory")

        dist_info = dist_info_dirs[0]
        metadata_path = dist_info / "METADATA"
        metadata = metadata_path.read_text()
        if PINNED_REQUIREMENT not in metadata:
            raise RuntimeError("PaddleX wheel did not contain the expected PyYAML pin")
        metadata_path.write_text(metadata.replace(PINNED_REQUIREMENT, PATCHED_REQUIREMENT))

        record_path = dist_info / "RECORD"
        record_path.write_text("")
        rows: list[str] = []
        for path in sorted(item for item in tmp_path.rglob("*") if item.is_file()):
            relative = path.relative_to(tmp_path).as_posix()
            if relative.endswith(".dist-info/RECORD"):
                rows.append(f"{relative},,")
                continue
            digest = hashlib.sha256(path.read_bytes()).digest()
            encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
            rows.append(f"{relative},sha256={encoded},{path.stat().st_size}")
        record_path.write_text("\n".join(rows) + "\n")

        with zipfile.ZipFile(patched_path, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
            for path in sorted(item for item in tmp_path.rglob("*") if item.is_file()):
                wheel.write(path, path.relative_to(tmp_path).as_posix())

    return patched_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    patched = patch_wheel(args.source_dir, args.output_dir)
    print(patched)


if __name__ == "__main__":
    main()
