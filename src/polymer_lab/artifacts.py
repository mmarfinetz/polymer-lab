"""Content-addressed artifact storage adapters."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from .errors import DependencyUnavailable


class LocalArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, key: str, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        destination = (self.root / key).resolve()
        if self.root not in destination.parents and destination != self.root:
            raise ValueError("artifact key escapes configured root")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        destination.with_suffix(destination.suffix + ".sha256").write_text(digest + "\n")
        return destination.as_uri()

    def put_file(self, key: str, source: Path) -> str:
        destination = (self.root / key).resolve()
        if self.root not in destination.parents and destination != self.root:
            raise ValueError("artifact key escapes configured root")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        digest = hashlib.sha256()
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        destination.with_suffix(destination.suffix + ".sha256").write_text(digest.hexdigest() + "\n")
        return destination.as_uri()

    def get_bytes(self, uri: str) -> bytes:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            raise ValueError(f"LocalArtifactStore cannot read {parsed.scheme!r} URIs")
        path = Path(parsed.path).resolve()
        if self.root not in path.parents and path != self.root:
            raise ValueError("artifact URI escapes configured root")
        data = path.read_bytes()
        checksum_path = path.with_suffix(path.suffix + ".sha256")
        if checksum_path.exists():
            expected = checksum_path.read_text().strip()
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("local artifact checksum mismatch")
        return data

    def exists(self, uri: str) -> bool:
        parsed = urlparse(uri)
        return parsed.scheme == "file" and Path(parsed.path).exists()


class S3ArtifactStore:
    def __init__(self, bucket: str, *, endpoint_url: str | None = None, prefix: str = "") -> None:
        try:
            import boto3
        except ImportError as exc:
            raise DependencyUnavailable("S3 storage requires polymer-lab[s3]") from exc
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = boto3.client("s3", endpoint_url=endpoint_url)

    def _key(self, key: str) -> str:
        path = PurePosixPath(key)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("invalid S3 artifact key")
        return f"{self.prefix}/{key}" if self.prefix else key

    def _parse_uri(self, uri: str) -> str:
        parsed = urlparse(uri)
        key = parsed.path.lstrip("/")
        if parsed.scheme != "s3" or parsed.netloc != self.bucket:
            raise ValueError("artifact URI does not belong to this store")
        if self.prefix and not key.startswith(f"{self.prefix}/"):
            raise ValueError("artifact URI is outside the configured prefix")
        return key

    def put_bytes(self, key: str, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        object_key = self._key(key)
        self.client.put_object(
            Bucket=self.bucket,
            Key=object_key,
            Body=data,
            Metadata={"sha256": digest},
        )
        return f"s3://{self.bucket}/{object_key}"

    def put_file(self, key: str, source: Path) -> str:
        digest = hashlib.sha256()
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        object_key = self._key(key)
        self.client.upload_file(
            str(source),
            self.bucket,
            object_key,
            ExtraArgs={"Metadata": {"sha256": digest.hexdigest()}},
        )
        return f"s3://{self.bucket}/{object_key}"

    def get_bytes(self, uri: str) -> bytes:
        key = self._parse_uri(uri)
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        data = response["Body"].read()
        expected = response.get("Metadata", {}).get("sha256")
        if not expected or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("S3 artifact checksum mismatch")
        return data

    def exists(self, uri: str) -> bool:
        try:
            key = self._parse_uri(uri)
            self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception:
            return False
        return True
