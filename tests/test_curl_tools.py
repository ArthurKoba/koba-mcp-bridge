from __future__ import annotations

import json
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from koba_mcp_bridge.artifact_store import ArtifactStore
from koba_mcp_bridge.curl_tools import (
    CurlError,
    _curl_failure_diagnostic,
    _http_status_diagnostic,
    curl_download_impl,
    curl_presets_impl,
    curl_request_impl,
    curl_stream_capture_impl,
)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002
        return

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or "0")
        return self.rfile.read(length) if length else b""

    def _json(self, status: int, payload: dict, extra_headers=None) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for name, value in extra_headers or []:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)
        self.wfile.flush()

    def _echo(self) -> None:
        body = self._body()
        self._json(
            200,
            {
                "method": self.command,
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "body": body.decode("utf-8", errors="replace"),
            },
            extra_headers=[
                ("Set-Cookie", "server_cookie=one; Path=/"),
                ("Set-Cookie", "server_cookie_two=two; Path=/"),
            ],
        )

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/echo":
            self._echo()
            return
        if parsed.path == "/unauthorized":
            self._json(401, {"error": "bad credentials"})
            return
        if parsed.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/echo?via=redirect")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if parsed.path == "/download":
            data = b"\x00KobaBinary\xff" * 64
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header(
                "Content-Disposition",
                'attachment; filename="fixture.bin"',
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            self.wfile.flush()
            return
        if parsed.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                for index in range(200):
                    self.wfile.write(f"data: {index}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(0.03)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        self._echo()

    def do_PATCH(self):
        self._echo()


@pytest.fixture(scope="module")
def http_server():
    if shutil.which("curl") is None:
        pytest.skip("curl is not installed")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture(autouse=True)
def artifact_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path / "artifacts"))


def test_presets_expose_browser_and_api_options() -> None:
    names = {item["name"] for item in curl_presets_impl()["presets"]}
    assert {"curl", "chrome-desktop", "chrome-mobile", "json-api", "none"} <= names


def test_request_supports_method_query_headers_cookies_and_json(http_server) -> None:
    result = curl_request_impl(
        f"{http_server}/echo?existing=1",
        method="POST",
        query={"q": ["one", "two"], "flag": True},
        headers={"X-Koba-Test": "yes"},
        cookies={"session": "abc"},
        body_json={"hello": "world"},
        preset="json-api",
    )

    assert result["status"] == 200
    assert result["ok"] is True
    assert result["body_is_text"] is True
    payload = json.loads(result["body_text"])
    assert payload["method"] == "POST"
    assert "existing=1" in payload["path"]
    assert "q=one" in payload["path"]
    assert "q=two" in payload["path"]
    assert "flag=true" in payload["path"]
    assert payload["headers"]["x-koba-test"] == "yes"
    assert payload["headers"]["cookie"] == "session=abc"
    assert payload["headers"]["content-type"].startswith("application/json")
    assert json.loads(payload["body"]) == {"hello": "world"}
    assert len(result["set_cookies"]) == 2


def test_request_supports_arbitrary_method_and_form_body(http_server) -> None:
    result = curl_request_impl(
        f"{http_server}/echo",
        method="PATCH",
        body_form={"alpha": "1", "beta": ["x", "y"]},
    )
    payload = json.loads(result["body_text"])
    assert payload["method"] == "PATCH"
    assert payload["body"] == "alpha=1&beta=x&beta=y"
    assert payload["headers"]["content-type"].startswith(
        "application/x-www-form-urlencoded"
    )


def test_browser_preset_can_be_overridden(http_server) -> None:
    result = curl_request_impl(
        f"{http_server}/echo",
        preset="chrome-desktop",
        headers={"Accept-Language": "lv-LV,lv;q=0.9"},
    )
    payload = json.loads(result["body_text"])
    assert "Chrome/" in payload["headers"]["user-agent"]
    assert payload["headers"]["accept-language"] == "lv-LV,lv;q=0.9"


def test_redirects_follow_without_sensitive_headers(http_server) -> None:
    result = curl_request_impl(f"{http_server}/redirect")
    assert result["status"] == 200
    assert result["redirect_count"] == 1
    assert "via=redirect" in result["final_url"]
    assert result["redirect_follow_blocked_sensitive"] is False


def test_sensitive_headers_block_automatic_redirect_by_default(http_server) -> None:
    result = curl_request_impl(
        f"{http_server}/redirect",
        headers={"Authorization": "Bearer secret"},
    )
    assert result["status"] == 302
    assert result["redirect_follow_blocked_sensitive"] is True
    request_headers = {item["name"].lower(): item["value"] for item in result["request"]["headers"]}
    assert request_headers["authorization"] == "<redacted>"


def test_sensitive_redirect_can_be_explicitly_enabled(http_server) -> None:
    result = curl_request_impl(
        f"{http_server}/redirect",
        headers={"Authorization": "Bearer secret"},
        forward_sensitive_headers_on_redirect=True,
    )
    assert result["status"] == 200
    assert result["redirect_count"] == 1


def test_download_streams_into_artifact_store(http_server) -> None:
    result = curl_download_impl(f"{http_server}/download")
    artifact = result["artifact"]

    assert result["status"] == 200
    assert artifact["name"] == "fixture.bin"
    stored = ArtifactStore().path_for(artifact["artifact_id"]).read_bytes()
    assert stored == b"\x00KobaBinary\xff" * 64
    assert result["body_is_text"] is False
    assert result["body_preview_hex"]


def test_artifact_can_be_sent_as_raw_request_body(http_server) -> None:
    store = ArtifactStore()
    source = store.put_bytes(
        b"artifact-payload",
        name="payload.bin",
        mime_type="application/octet-stream",
        source="test",
    )

    result = curl_request_impl(
        f"{http_server}/echo",
        method="POST",
        body_artifact_id=source["artifact_id"],
    )
    payload = json.loads(result["body_text"])
    assert payload["body"] == "artifact-payload"
    assert payload["headers"]["content-type"].startswith(
        "application/octet-stream"
    )


def test_stream_capture_commits_partial_stream_to_artifact(http_server) -> None:
    result = curl_stream_capture_impl(
        f"{http_server}/stream",
        duration_seconds=0.35,
        max_bytes=1024 * 1024,
        artifact_name="events.txt",
    )

    assert result["status"] == 200
    assert result["captured_bytes"] > 0
    assert result["stop_reason"] in {"duration", "eof"}
    artifact = result["artifact"]
    captured = ArtifactStore().path_for(artifact["artifact_id"]).read_bytes()
    assert captured.startswith(b"data:")
    assert artifact["name"] == "events.txt"


def test_rejects_header_injection() -> None:
    with pytest.raises(CurlError, match="control characters"):
        curl_request_impl(
            "http://127.0.0.1/",
            headers={"X-Test": "good\r\nInjected: yes"},
        )


def test_rejects_multiple_body_sources(http_server) -> None:
    with pytest.raises(CurlError, match="only one body source"):
        curl_request_impl(
            f"{http_server}/echo",
            method="POST",
            body_text="a",
            body_json={"b": 1},
        )

def test_http_auth_failure_is_classified(http_server) -> None:
    result = curl_request_impl(f"{http_server}/unauthorized")

    assert result["status"] == 401
    assert result["ok"] is False
    assert result["error"]["error_type"] == "http_authentication"
    assert "HTTP 401" in result["error"]["error_hint"]


def test_curl_transport_failure_categories_are_actionable() -> None:
    assert _curl_failure_diagnostic(6, "resolve failed")["error_type"] == "dns"
    assert _curl_failure_diagnostic(7, "connect failed")["error_type"] == "connect"
    assert _curl_failure_diagnostic(28, "timed out")["error_type"] == "timeout"
    assert _curl_failure_diagnostic(60, "certificate problem")["error_type"] == (
        "tls_certificate"
    )
    assert _http_status_diagnostic(403)["error_type"] == "http_forbidden"
    assert _http_status_diagnostic(429)["error_type"] == "http_rate_limit"

