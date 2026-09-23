from __future__ import annotations

import json
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from koba_mcp_bridge.file_store import FileStore
from koba_mcp_bridge.curl_tools import (
    DEFAULT_CURL_PRESET,
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
def file_root(tmp_path, monkeypatch):
    monkeypatch.setenv("FILE_ROOT", str(tmp_path / "files"))


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


def test_download_streams_into_file_store(http_server) -> None:
    result = curl_download_impl(f"{http_server}/download")
    file = result["file"]

    assert result["status"] == 200
    assert file["name"] == "fixture.bin"
    stored = FileStore().path_for(file["file_id"]).read_bytes()
    assert stored == b"\x00KobaBinary\xff" * 64
    assert result["body_is_text"] is False
    assert result["body_preview_hex"]


def test_file_can_be_sent_as_raw_request_body(http_server) -> None:
    store = FileStore()
    source = store.put_bytes(
        b"file-payload",
        name="payload.bin",
        mime_type="application/octet-stream",
        source="test",
    )

    result = curl_request_impl(
        f"{http_server}/echo",
        method="POST",
        body_file_id=source["file_id"],
    )
    payload = json.loads(result["body_text"])
    assert payload["body"] == "file-payload"
    assert payload["headers"]["content-type"].startswith(
        "application/octet-stream"
    )


def test_stream_capture_commits_partial_stream_to_file(http_server) -> None:
    result = curl_stream_capture_impl(
        f"{http_server}/stream",
        duration_seconds=0.35,
        max_bytes=1024 * 1024,
        file_name="events.txt",
    )

    assert result["status"] == 200
    assert result["captured_bytes"] > 0
    assert result["stop_reason"] in {"duration", "eof"}
    file = result["file"]
    captured = FileStore().path_for(file["file_id"]).read_bytes()
    assert captured.startswith(b"data:")
    assert file["name"] == "events.txt"


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




def test_chrome_desktop_is_the_default_preset(http_server) -> None:
    assert DEFAULT_CURL_PRESET == "chrome-desktop"
    presets = curl_presets_impl()
    assert presets["default_preset"] == "chrome-desktop"

    result = curl_request_impl(f"{http_server}/echo")
    payload = json.loads(result["body_text"])
    headers = payload["headers"]

    assert "Chrome/153.0.0.0" in headers["user-agent"]
    assert '"Google Chrome";v="153"' in headers["sec-ch-ua"]
    assert headers["sec-ch-ua-mobile"] == "?0"
    assert headers["sec-ch-ua-platform"] == '"Windows"'
    assert headers["sec-fetch-mode"] == "navigate"
    assert headers["sec-fetch-dest"] == "document"
    assert result["request"]["preset"] == "chrome-desktop"


def test_explicit_native_curl_preset_still_overrides_default(http_server) -> None:
    result = curl_request_impl(f"{http_server}/echo", preset="curl")
    payload = json.loads(result["body_text"])

    assert result["request"]["preset"] == "curl"
    assert "Chrome/" not in payload["headers"].get("user-agent", "")
