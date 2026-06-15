from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


def safe_object_key(prefix: str, filename: str, object_id: str = "") -> str:
    name = Path(str(filename or "upload.bin")).name.strip() or "upload.bin"
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]", "_", name)
    clean_prefix = re.sub(r"[^0-9A-Za-z._\-/]", "", str(prefix or "uploads")).strip("/") or "uploads"
    if not object_id:
        return f"{clean_prefix}/{name}"
    clean_object_id = re.sub(r"[^0-9A-Za-z._\-]", "_", str(object_id or "object"))
    return f"{clean_prefix}/{clean_object_id}-{name}"


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    content_type: str

    @property
    def size(self) -> int:
        return self.size_bytes


class ObjectStorage:
    def put_bytes(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> StoredObject:
        raise NotImplementedError

    def read_bytes(self, key: str) -> bytes:
        raise NotImplementedError


class LocalObjectStorage(ObjectStorage):
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve_key(self, key: str) -> Path:
        key_text = str(key or "").lstrip("/")
        relative = Path(key_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("object key escapes storage root")
        target = (self.root / relative).resolve()
        if self.root != target and self.root not in target.parents:
            raise ValueError("object key escapes storage root")
        return target

    def put_bytes(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> StoredObject:
        target = self.resolve_key(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return StoredObject(key=key, size_bytes=len(content), content_type=content_type)

    def read_bytes(self, key: str) -> bytes:
        return self.resolve_key(key).read_bytes()

    def get_bytes(self, key: str) -> bytes:
        return self.read_bytes(key)
