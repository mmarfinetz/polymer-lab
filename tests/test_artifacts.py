from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest

from polymer_lab.artifacts import LocalArtifactStore


def test_local_artifacts_are_scoped_and_checksum_verified(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    uri = store.put_bytes("campaigns/c1/result.json", b"evidence")
    assert store.get_bytes(uri) == b"evidence"
    Path(urlparse(uri).path).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum mismatch"):
        store.get_bytes(uri)
    with pytest.raises(ValueError, match="escapes"):
        store.put_bytes("../outside", b"no")
    source = tmp_path / "large-output.log"
    source.write_bytes(b"streamed evidence")
    streamed_uri = store.put_file("campaigns/c1/large-output.log", source)
    assert store.get_bytes(streamed_uri) == b"streamed evidence"
