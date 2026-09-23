from __future__ import annotations

import hashlib
import http.client
import ipaddress
import os
import socket
import urllib.parse
import urllib.request
import uuid
from contextlib import suppress
from typing import IO, cast

from common.models import JsonObject, validated_call

from .file_store import FileError, FileStore, upload_max_bytes
from .models import AttachmentIngestResponse, ClientFile, FileInfo
from .validation import validate_file_name as _validate_name
from .validation import validate_sha256 as _validate_sha256


def _validate_remote_file_url(file: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(file.strip())
    if parsed.scheme.casefold() != "https":
        raise FileError(
            "file must resolve to an HTTPS attachment URL; pass the client attachment/file "
            "argument directly instead of base64 or a server filesystem path"
        )
    if not parsed.hostname:
        raise FileError("attachment URL has no hostname")
    if parsed.username or parsed.password:
        raise FileError("attachment URL must not contain userinfo")

    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or 443,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise FileError("attachment hostname cannot be resolved") from exc
    if not addresses:
        raise FileError("attachment hostname cannot be resolved")

    for item in addresses:
        raw_ip = str(item[4][0]).split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw_ip)
        except ValueError as exc:
            raise FileError("attachment hostname resolved to an invalid address") from exc
        if not address.is_global:
            raise FileError("attachment URL resolves to a non-public address")
    return parsed


class _AttachmentRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        _validate_remote_file_url(str(newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_remote_file(request: urllib.request.Request) -> http.client.HTTPResponse:
    opener = urllib.request.build_opener(_AttachmentRedirectHandler())
    return cast(http.client.HTTPResponse, opener.open(request, timeout=60))


def _attachment_name(parsed: urllib.parse.SplitResult, requested_name: str) -> str:
    if requested_name.strip():
        return _validate_name(requested_name)
    candidate = urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1]).strip()
    return _validate_name(candidate or "attachment.bin")


@validated_call
def ingest_file(
    file: ClientFile,
    name: str = "",
    mime_type: str = "",
    expected_size: int | None = None,
    expected_sha256: str = "",
) -> JsonObject:
    """Stream one client-authorized attachment directly into canonical file storage."""
    store = FileStore()
    store.ensure()

    download_url = file.download_url.strip()
    parsed = _validate_remote_file_url(download_url)

    file_name = (file.file_name or "").strip()
    clean_name = _attachment_name(parsed, name or file_name)
    expected_digest = _validate_sha256(expected_sha256)

    if (
        expected_size is not None
        and (expected_size < 0 or expected_size > upload_max_bytes())
    ):
        raise FileError(
            f"expected_size must be between 0 and {upload_max_bytes()}"
        )

    request = urllib.request.Request(
        download_url,
        headers={"User-Agent": "mcp-bridge/0.1 file-ingress"},
    )
    temporary = store.tmp / f"attachment-{uuid.uuid4().hex}.part"
    digest = hashlib.sha256()
    total = 0
    detected_mime = mime_type.strip() or (file.mime_type or "").strip()

    try:
        try:
            response = _open_remote_file(request)
        except Exception as exc:
            if isinstance(exc, FileError):
                raise
            raise FileError(
                f"attachment download failed: {type(exc).__name__}"
            ) from exc

        with response:
            final_url = str(response.geturl())
            _validate_remote_file_url(final_url)

            declared = response.headers.get("Content-Length")
            if declared:
                try:
                    declared_size = int(declared)
                except ValueError as exc:
                    raise FileError("attachment returned invalid Content-Length") from exc
                if declared_size < 0:
                    raise FileError("attachment returned invalid Content-Length")
                if declared_size > upload_max_bytes():
                    raise FileError("attachment exceeds FILE_UPLOAD_MAX_BYTES")
                if expected_size is not None and declared_size != expected_size:
                    raise FileError(
                        "attachment Content-Length does not match expected_size"
                    )

            if not detected_mime:
                detected_mime = (
                    response.headers.get("Content-Type", "")
                    .split(";", 1)[0]
                    .strip()
                )

            with temporary.open("xb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > upload_max_bytes():
                        raise FileError("attachment exceeds FILE_UPLOAD_MAX_BYTES")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())

        actual_digest = digest.hexdigest()
        if expected_size is not None and total != expected_size:
            raise FileError(
                f"attachment size mismatch: expected {expected_size}, received {total}"
            )
        if expected_digest and actual_digest != expected_digest:
            raise FileError(
                "attachment SHA-256 mismatch: "
                f"expected {expected_digest}, found {actual_digest}"
            )

        stored_file = FileInfo.model_validate(
            store.put_file(
                temporary,
                name=clean_name,
                mime_type=detected_mime,
                source="attachment-ingress",
                consume=True,
            )
        )
        if stored_file.sha256 != actual_digest:
            raise FileError("file store returned an unexpected SHA-256")
        return AttachmentIngestResponse(
            file=stored_file,
            completed=True,
            transport="client-file",
        ).to_json()
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()
