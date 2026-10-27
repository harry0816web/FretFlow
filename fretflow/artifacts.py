"""Artifact storage abstractions and the local filesystem implementation."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from fretflow.domain import validate_artifact_key


class ArtifactStore(Protocol):
    def put_file(self, source: Path, key: str, *, overwrite: bool = False) -> str: ...

    def materialize(self, key: str) -> Path: ...

    def exists(self, key: str) -> bool: ...

    def delete_prefix(self, prefix: str) -> int: ...


class LocalArtifactStore:
    """Store artifacts below one controlled root using atomic replacements."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_file(self, source: Path, key: str, *, overwrite: bool = False) -> str:
        source_path = source.expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"artifact source does not exist: {source_path}")
        destination = self._path_for(key)
        if destination.exists() and not overwrite:
            raise FileExistsError(f"artifact already exists: {key}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.part")
        try:
            with source_path.open("rb") as source_handle, temporary.open("xb") as output:
                shutil.copyfileobj(source_handle, output)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return key

    def materialize(self, key: str) -> Path:
        path = self._path_for(key)
        if not path.is_file():
            raise FileNotFoundError(f"artifact does not exist: {key}")
        return path

    def exists(self, key: str) -> bool:
        return self._path_for(key).is_file()

    def delete_prefix(self, prefix: str) -> int:
        path = self._path_for(prefix.rstrip("/"))
        if not path.exists():
            return 0
        if not path.is_dir():
            raise ValueError("artifact prefix must identify a directory")
        files = [candidate for candidate in path.rglob("*") if candidate.is_file()]
        shutil.rmtree(path)
        return len(files)

    def _path_for(self, key: str) -> Path:
        validate_artifact_key(key)
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("artifact key escapes the configured root")
        return path
