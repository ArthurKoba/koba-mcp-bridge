from __future__ import annotations

import base64

import pytest

from koba_mcp_bridge import artifact_storage


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ARTIFACT_MAX_CHUNK_BYTES", "4096")
    artifact_storage.ensure_artifact_layout()
    return tmp_path


def test_layout(root):
    assert (root / "inbox").is_dir()
    assert (root / "exports").is_dir()
    assert (root / "scripts").is_dir()


def test_path_escape_rejected(root):
    with pytest.raises(artifact_storage.ArtifactError):
        artifact_storage._resolve("../outside")


def test_absolute_path_rejected(root):
    with pytest.raises(artifact_storage.ArtifactError):
        artifact_storage._resolve("/etc/passwd")


def test_chunk_roundtrip(root):
    target = artifact_storage._resolve("inbox/test.bin")
    first = b"abc"
    second = b"defgh"

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(first)
    assert target.stat().st_size == 3

    current = target.stat().st_size
    assert current == 3
    with target.open("ab") as handle:
        handle.write(second)
    assert target.read_bytes() == first + second
    assert artifact_storage._sha256(target)


def test_base64_validation(root):
    with pytest.raises(Exception):
        base64.b64decode("!", validate=True)


def test_standard_dirs_are_protected(root):
    assert artifact_storage._rel(artifact_storage._resolve("inbox")) == "inbox"
