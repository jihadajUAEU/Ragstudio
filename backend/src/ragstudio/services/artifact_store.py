from hashlib import sha256
from pathlib import Path


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root
        self.uploads_dir = root / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    def prepare_upload(self, filename: str, content: bytes) -> tuple[str, Path]:
        digest = sha256(content).hexdigest()
        safe_name = Path(filename.replace("\\", "/")).name.replace("..", "_")
        if not safe_name or safe_name in {".", "_"}:
            safe_name = "upload.bin"
        target = self.uploads_dir / f"{digest}-{safe_name}"
        return digest, target

    def write_upload(self, filename: str, content: bytes) -> tuple[str, Path]:
        digest, target = self.prepare_upload(filename, content)
        target.write_bytes(content)
        return digest, target
