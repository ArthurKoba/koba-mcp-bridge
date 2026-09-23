from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastmcp import Client

from koba_mcp_bridge.secrets import (
    InfisicalClient,
    InfisicalConfig,
    SecretError,
    SecretReference,
    SecretResolver,
)
from koba_mcp_bridge.server import mcp


class _InfisicalHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    login_count = 0
    secret_count = 0

    def log_message(self, format, *args):  # noqa: A002
        return

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        self.wfile.flush()

    def do_POST(self):
        if self.path != "/api/v1/auth/universal-auth/login":
            self._json(404, {"message": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length).decode()
        form = parse_qs(body)
        if form.get("clientId") != ["client-id"] or form.get("clientSecret") != [
            "client-secret"
        ]:
            self._json(403, {"message": "invalid credentials"})
            return
        type(self).login_count += 1
        self._json(
            200,
            {
                "accessToken": "short-lived-token",
                "expiresIn": 7200,
                "accessTokenMaxTTL": 7200,
                "tokenType": "Bearer",
            },
        )

    def do_GET(self):
        parsed = urlsplit(self.path)
        if not parsed.path.startswith("/api/v4/secrets/"):
            self._json(404, {"message": "not found"})
            return
        if self.headers.get("Authorization") != "Bearer short-lived-token":
            self._json(401, {"message": "missing bearer token"})
            return
        query = parse_qs(parsed.query)
        assert query["projectId"] == ["project-123"]
        assert query["environment"] == ["prod"]
        assert query["secretPath"] == ["/github/development"]
        type(self).secret_count += 1
        self._json(
            200,
            {
                "secret": {
                    "id": "secret-id",
                    "secretKey": "PRIVATE_KEY_PEM",
                    "secretValue": "super-secret-private-key",
                    "secretPath": "/github/development",
                    "version": 4,
                    "updatedAt": "2026-09-18T00:00:00.000Z",
                }
            },
        )


@pytest.fixture
def infisical_server():
    _InfisicalHandler.login_count = 0
    _InfisicalHandler.secret_count = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _InfisicalHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _client(infisical_server: str) -> InfisicalClient:
    return InfisicalClient(
        InfisicalConfig(
            host=infisical_server,
            project_id="project-123",
            client_id="client-id",
            client_secret="client-secret",
            verify_tls=True,
        )
    )


def test_secret_reference_parsing() -> None:
    env_ref = SecretReference.parse("env://GITHUB_TOKEN")
    assert env_ref.scheme == "env"
    assert env_ref.env_name == "GITHUB_TOKEN"

    file_ref = SecretReference.parse("file:///run/secrets/github.pem")
    assert file_ref.scheme == "file"
    assert file_ref.file_path == "/run/secrets/github.pem"

    inf_ref = SecretReference.parse(
        "infisical://prod/github/development#PRIVATE_KEY_PEM"
    )
    assert inf_ref.scheme == "infisical"
    assert inf_ref.environment == "prod"
    assert inf_ref.secret_path == "/github/development"
    assert inf_ref.secret_name == "PRIVATE_KEY_PEM"


def test_infisical_universal_auth_and_secret_fetch_are_cached(infisical_server) -> None:
    client = _client(infisical_server)

    first, metadata = client.get_secret(
        "PRIVATE_KEY_PEM",
        environment="prod",
        secret_path="/github/development",
    )
    second, _ = client.get_secret(
        "PRIVATE_KEY_PEM",
        environment="prod",
        secret_path="/github/development",
    )

    assert first == "super-secret-private-key"
    assert second == first
    assert metadata["version"] == 4
    assert _InfisicalHandler.login_count == 1
    assert _InfisicalHandler.secret_count == 2


def test_resolver_never_returns_value_from_check(infisical_server) -> None:
    resolver = SecretResolver(_client(infisical_server))
    result = resolver.check(
        "infisical://prod/github/development#PRIVATE_KEY_PEM"
    )

    serialized = json.dumps(result)
    assert result["available"] is True
    assert "value" not in result
    assert "super-secret-private-key" not in serialized


def test_env_and_file_refs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KOBA_TEST_SECRET", "env-value")
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("file-value\n", encoding="utf-8")
    resolver = SecretResolver(_client("http://127.0.0.1:1"))

    assert resolver.resolve("env://KOBA_TEST_SECRET") == "env-value"
    assert resolver.resolve(f"file://{secret_file}") == "file-value"



def test_infisical_config_reads_environment_and_base_path(monkeypatch) -> None:
    monkeypatch.setenv("INFISICAL_HOST", "https://secrets.example.test")
    monkeypatch.setenv("INFISICAL_PROJECT_ID", "project")
    monkeypatch.setenv("INFISICAL_CLIENT_ID", "client-id")
    monkeypatch.setenv("INFISICAL_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("INFISICAL_ENVIRONMENT", "production")
    monkeypatch.setenv("INFISICAL_BASE_PATH", "/koba/platform/")

    config = InfisicalConfig.from_env()

    assert config.environment == "production"
    assert config.base_path == "/koba/platform"
    public = config.public()
    assert public["environment"] == "production"
    assert public["base_path"] == "/koba/platform"


def test_convention_resolver_joins_base_path(monkeypatch) -> None:
    client = InfisicalClient(
        InfisicalConfig(
            host="https://secrets.example.test",
            project_id="project",
            client_id="client-id",
            client_secret="client-secret",
            environment="prod",
            base_path="/koba",
        )
    )
    resolver = SecretResolver(client)
    calls = []

    def fake_get_secret(secret_name, *, environment, secret_path, project_id=""):
        calls.append(
            {
                "secret_name": secret_name,
                "environment": environment,
                "secret_path": secret_path,
                "project_id": project_id,
            }
        )
        return "value", {}

    monkeypatch.setattr(client, "get_secret", fake_get_secret)

    assert resolver.get("github/development", "APP_ID") == "value"
    assert calls == [
        {
            "secret_name": "APP_ID",
            "environment": "prod",
            "secret_path": "/koba/github/development",
            "project_id": "project",
        }
    ]


def test_convention_resolver_root_base_path(monkeypatch) -> None:
    client = InfisicalClient(
        InfisicalConfig(
            host="https://secrets.example.test",
            project_id="project",
            client_id="client-id",
            client_secret="client-secret",
            environment="prod",
            base_path="/",
        )
    )
    resolver = SecretResolver(client)
    captured = {}

    def fake_get_secret(secret_name, *, environment, secret_path, project_id=""):
        captured["name"] = secret_name
        captured["environment"] = environment
        captured["path"] = secret_path
        return "pem", {}

    monkeypatch.setattr(client, "get_secret", fake_get_secret)

    assert resolver.get("github/reviewer", "PRIVATE_KEY_PEM") == "pem"
    assert captured == {
        "name": "PRIVATE_KEY_PEM",
        "environment": "prod",
        "path": "/github/reviewer",
    }

def test_infisical_config_supports_bootstrap_files(tmp_path: Path, monkeypatch) -> None:
    client_id = tmp_path / "client-id"
    client_secret = tmp_path / "client-secret"
    client_id.write_text("id-from-file\n", encoding="utf-8")
    client_secret.write_text("secret-from-file\n", encoding="utf-8")

    monkeypatch.setenv("INFISICAL_HOST", "https://secrets.example.test")
    monkeypatch.setenv("INFISICAL_PROJECT_ID", "project")
    monkeypatch.setenv("INFISICAL_CLIENT_ID_FILE", str(client_id))
    monkeypatch.setenv("INFISICAL_CLIENT_SECRET_FILE", str(client_secret))
    monkeypatch.delenv("INFISICAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("INFISICAL_CLIENT_SECRET", raising=False)

    config = InfisicalConfig.from_env()
    assert config.configured() is True
    assert config.client_id == "id-from-file"
    assert config.client_secret == "secret-from-file"
    public = config.public()
    assert public["client_secret_source"].startswith("file:")
    assert "secret-from-file" not in json.dumps(public)


def test_invalid_secret_reference_is_rejected() -> None:
    with pytest.raises(SecretError, match="scheme"):
        SecretReference.parse("plaintext-secret")


@pytest.mark.asyncio
async def test_secrets_diagnostics_are_registered() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
    names = {tool.name for tool in tools}
    assert "secrets_status" in names
    assert "secrets_check_reference" in names

def test_convention_secret_cache_reuses_value_until_cleared(monkeypatch) -> None:
    client = _client("http://127.0.0.1:1")
    calls = 0

    def fake_get_secret(
        secret_name,
        *,
        environment,
        secret_path,
        project_id="",
    ):
        nonlocal calls
        del secret_name, environment, secret_path, project_id
        calls += 1
        return "cached-value", {}

    monkeypatch.setattr(client, "get_secret", fake_get_secret)
    resolver = SecretResolver(client, cache_ttl_seconds=60)

    assert resolver.get("github/oauth", "ALLOWED_USERS") == "cached-value"
    assert resolver.get("github/oauth", "ALLOWED_USERS") == "cached-value"
    assert calls == 1

    resolver.clear_cache()
    assert resolver.get("github/oauth", "ALLOWED_USERS") == "cached-value"
    assert calls == 2


def test_explicit_infisical_reference_uses_same_cache(monkeypatch) -> None:
    client = _client("http://127.0.0.1:1")
    calls = 0

    def fake_get_secret(
        secret_name,
        *,
        environment,
        secret_path,
        project_id="",
    ):
        nonlocal calls
        del secret_name, environment, secret_path, project_id
        calls += 1
        return "explicit-value", {}

    monkeypatch.setattr(client, "get_secret", fake_get_secret)
    resolver = SecretResolver(client, cache_ttl_seconds=60)
    reference = "infisical://prod/github/development#PRIVATE_KEY_PEM"

    assert resolver.resolve(reference) == "explicit-value"
    assert resolver.resolve(reference) == "explicit-value"
    assert calls == 1


def test_concurrent_secret_cache_miss_is_single_flight(monkeypatch) -> None:
    client = _client("http://127.0.0.1:1")
    calls = 0
    calls_lock = threading.Lock()

    def fake_get_secret(
        secret_name,
        *,
        environment,
        secret_path,
        project_id="",
    ):
        nonlocal calls
        del secret_name, environment, secret_path, project_id
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return "shared-value", {}

    monkeypatch.setattr(client, "get_secret", fake_get_secret)
    resolver = SecretResolver(client, cache_ttl_seconds=60)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda _: resolver.get("github/oauth", "ALLOWED_USERS"),
                range(8),
            )
        )

    assert results == ["shared-value"] * 8
    assert calls == 1


def test_zero_ttl_disables_secret_value_cache(monkeypatch) -> None:
    client = _client("http://127.0.0.1:1")
    calls = 0

    def fake_get_secret(
        secret_name,
        *,
        environment,
        secret_path,
        project_id="",
    ):
        nonlocal calls
        del secret_name, environment, secret_path, project_id
        calls += 1
        return f"value-{calls}", {}

    monkeypatch.setattr(client, "get_secret", fake_get_secret)
    resolver = SecretResolver(client, cache_ttl_seconds=0)

    assert resolver.get("github/oauth", "ALLOWED_USERS") == "value-1"
    assert resolver.get("github/oauth", "ALLOWED_USERS") == "value-2"
    assert calls == 2

