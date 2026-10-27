from pathlib import Path

import pytest

from fretflow.artifacts import LocalArtifactStore
from fretflow.domain import DomainValidationError


def test_local_artifact_store_puts_materializes_and_overwrites_atomically(
    tmp_path: Path,
):
    source = tmp_path / "source.bin"
    source.write_bytes(b"first")
    store = LocalArtifactStore(tmp_path / "artifacts")
    key = "songs/song/source/source.bin"

    assert store.put_file(source, key) == key
    assert store.exists(key)
    assert store.materialize(key).read_bytes() == b"first"

    source.write_bytes(b"second")
    with pytest.raises(FileExistsError):
        store.put_file(source, key)
    store.put_file(source, key, overwrite=True)
    assert store.materialize(key).read_bytes() == b"second"
    assert list((tmp_path / "artifacts").rglob("*.part")) == []


def test_local_artifact_store_rejects_missing_sources_and_unsafe_keys(tmp_path: Path):
    store = LocalArtifactStore(tmp_path / "artifacts")
    with pytest.raises(FileNotFoundError):
        store.put_file(tmp_path / "missing", "songs/song/source.bin")
    with pytest.raises(DomainValidationError):
        store.exists("../outside")
    with pytest.raises(FileNotFoundError):
        store.materialize("songs/song/missing.bin")


def test_local_artifact_store_rejects_symlink_escape(tmp_path: Path):
    root = tmp_path / "artifacts"
    outside = tmp_path / "outside"
    outside.mkdir()
    store = LocalArtifactStore(root)
    (root / "songs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="escapes"):
        store.exists("songs/escaped.bin")


def test_local_artifact_store_deletes_only_a_validated_prefix(tmp_path: Path):
    store = LocalArtifactStore(tmp_path / "artifacts")
    source = tmp_path / "source.bin"
    source.write_bytes(b"data")
    store.put_file(source, "songs/one/source/source.bin")
    store.put_file(source, "songs/one/tabs/tab.bin")
    store.put_file(source, "songs/two/source/source.bin")

    assert store.delete_prefix("songs/one/") == 2
    assert not store.exists("songs/one/source/source.bin")
    assert store.exists("songs/two/source/source.bin")
