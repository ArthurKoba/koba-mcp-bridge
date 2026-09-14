from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import subprocess
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 16 * 1024
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_REPOSITORY = os.getenv("DEPLOY_REPOSITORY", "ArthurKoba/koba-mcp-bridge")
EXPECTED_REF = os.getenv("DEPLOY_REF", "refs/heads/main")
EXPECTED_IMAGE = os.getenv(
    "DEPLOY_IMAGE", "ghcr.io/arthurkoba/koba-mcp-bridge"
)
DEPLOY_COMMAND = os.getenv(
    "DEPLOY_COMMAND", "/usr/local/sbin/koba-mcp-bridge-deploy"
)
SECRET_FILE = Path(
    os.getenv("DEPLOY_WEBHOOK_SECRET_FILE", "/etc/koba-mcp-deploy/secret")
)

_deploy_lock = threading.Lock()


def load_secret() -> bytes:
    secret = SECRET_FILE.read_bytes().strip()
    if len(secret) < 32:
        raise RuntimeError("deploy webhook secret must contain at least 32 bytes")
    return secret


def verify_signature(body: bytes, signature_header: str | None, secret: bytes) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def validate_payload(payload: object) -> str:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    if payload.get("repository") != EXPECTED_REPOSITORY:
        raise ValueError("unexpected repository")
    if payload.get("ref") != EXPECTED_REF:
        raise ValueError("unexpected ref")
    if payload.get("image") != EXPECTED_IMAGE:
        raise ValueError("unexpected image")

    sha = payload.get("sha")
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise ValueError("invalid sha")
    return sha


class Handler(BaseHTTPRequestHandler):
    server_version = "KobaDeployWebhook/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.client_address[0]} - {fmt % args}", flush=True)

    def _json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/healthz":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        self._json(HTTPStatus.OK, {"status": "ok"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/deploy":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid content length"})
            return

        if length <= 0 or length > MAX_BODY:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "invalid body size"})
            return

        body = self.rfile.read(length)
        try:
            secret = load_secret()
        except OSError:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "secret unavailable"})
            return

        if not verify_signature(body, self.headers.get("X-Hub-Signature-256"), secret):
            self._json(HTTPStatus.FORBIDDEN, {"error": "invalid signature"})
            return

        try:
            payload = json.loads(body)
            sha = validate_payload(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        if not _deploy_lock.acquire(blocking=False):
            self._json(HTTPStatus.CONFLICT, {"error": "deployment already running"})
            return

        try:
            result = subprocess.run(
                ["/usr/bin/sudo", DEPLOY_COMMAND, sha],
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            self._json(HTTPStatus.GATEWAY_TIMEOUT, {"error": "deployment timed out"})
            return
        finally:
            _deploy_lock.release()

        if result.returncode != 0:
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": "deployment failed",
                    "stderr": result.stderr[-4000:],
                },
            )
            return

        self._json(
            HTTPStatus.OK,
            {
                "status": "deployed",
                "sha": sha,
                "output": result.stdout[-4000:],
            },
        )


def main() -> None:
    host = os.getenv("DEPLOY_LISTEN_HOST", "127.0.0.1")
    port = int(os.getenv("DEPLOY_LISTEN_PORT", "9010"))
    load_secret()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"deploy webhook listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
