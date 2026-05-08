import math
import os
from typing import Any


def sanitize_db_text(value: str) -> str:
    return value.replace("\x00", "")


def sanitize_db_value(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return sanitize_db_text(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, bytes):
        return sanitize_db_text(value.decode("utf-8", errors="replace"))
    if isinstance(value, os.PathLike):
        return sanitize_db_text(os.fspath(value))
    if isinstance(value, dict):
        return {
            sanitize_db_text(str(key)): sanitize_db_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_db_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_db_value(item) for item in value]
    return sanitize_db_text(str(value))
