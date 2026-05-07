from hashlib import sha256
from pathlib import Path


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root
        self.uploads_dir = root / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    def write_upload(self, filename: str, content: bytes) -> tuple[str, Path]:
        digest = sha256(content).hexdigest()
        safe_name = filename.replace("/", "_").replace("\\", "_")
        target = self.uploads_dir / f"{digest}-{safe_name}"
        target.write_bytes(content)
        return digest, target
