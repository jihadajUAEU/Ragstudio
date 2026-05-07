import os
import tempfile
from hashlib import sha256
from pathlib import Path


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root
        self.uploads_dir = root / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    def prepare_upload(self, filename: str, content: bytes) -> tuple[str, Path]:
        digest = sha256(content).hexdigest()
        target = self.uploads_dir / digest
        return digest, target

    def write_upload(self, filename: str, content: bytes) -> tuple[str, Path, bool]:
        digest, target = self.prepare_upload(filename, content)
        if target.exists():
            return digest, target, False

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.uploads_dir, prefix=f".{digest}.", delete=False) as temp_file:
                temp_file.write(content)
                temp_path = Path(temp_file.name)
            os.link(temp_path, target)
            return digest, target, True
        except FileExistsError:
            return digest, target, False
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
