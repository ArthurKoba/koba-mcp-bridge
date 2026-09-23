from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

import gitlab_mcp.gitlab_client as gitlab_module
import gitlab_mcp.gitlab_tools as gitlab_tools
from gitlab_mcp.gitlab_client import (
    GitLabClient,
    GitLabError,
    GitLabProfileRegistry,
)
from mcp_bridge.server import app


class _GitLabHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002
        return

    def _auth_identity(self) -> str:
        private = self.headers.get("PRIVATE-TOKEN", "")
        bearer = self.headers.get("Authorization", "")
        job = self.headers.get("JOB-TOKEN", "")
        if private == "token-a":
            return "alice"
        if private == "token-b":
            return "bob"
        if bearer == "Bearer oauth-a":
            return "oauth-user"
        if job == "job-a":
            return "job-user"
        return ""

    def _json(self, status: int, payload, headers=None) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for name, value in headers or []:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)
        self.wfile.flush()

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw.decode()) if raw else {}

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/api/v4/user":
            username = self._auth_identity()
            if not username:
                self._json(401, {"message": "401 Unauthorized"})
                return
            self._json(
                200,
                {
                    "id": 1 if username == "alice" else 2,
                    "username": username,
                    "name": username.title(),
                    "state": "active",
                    "web_url": f"http://gitlab.test/{username}",
                },
            )
            return

        if parsed.path == "/api/v4/version":
            self._json(200, {"version": "18.4.0", "revision": "fixture"})
            return

        if parsed.path == "/api/v4/projects":
            self._json(
                200,
                [
                    {
                        "id": 123,
                        "path_with_namespace": "group/project",
                        "default_branch": "main",
                    }
                ],
                headers=[
                    ("X-Next-Page", ""),
                    ("X-Total", "1"),
                    ("X-Total-Pages", "1"),
                ],
            )
            return

        if parsed.path == "/api/v4/projects/group%2Fproject":
            self._json(
                200,
                {
                    "id": 123,
                    "path_with_namespace": "group/project",
                    "default_branch": "main",
                },
            )
            return

        if parsed.path == "/api/v4/projects/group%2Fproject/repository/files/README.md":
            self._json(
                200,
                {
                    "file_path": "README.md",
                    "encoding": "base64",
                    "content": base64.b64encode(b"hello gitlab").decode(),
                    "blob_id": "blob",
                    "commit_id": "commit",
                    "last_commit_id": "last",
                    "size": 12,
                },
            )
            return

        if parsed.path == "/api/v4/projects/group%2Fproject/repository/branches":
            self._json(
                200,
                [
                    {
                        "name": "main",
                        "protected": True,
                        "default": True,
                    },
                    {
                        "name": "feature/test",
                        "protected": False,
                        "default": False,
                    },
                ],
            )
            return

        self._json(404, {"message": "404 Not Found", "path": parsed.path})

    def do_POST(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/api/v4/projects/group%2Fproject/repository/branches":
            self._json(
                201,
                {
                    "name": "feature/new",
                    "protected": False,
                    "default": False,
                },
            )
            return

        if parsed.path == "/api/v4/projects/group%2Fproject/merge_requests":
            body = self._read_json()
            self._json(
                201,
                {
                    "iid": 7,
                    "source_branch": body["source_branch"],
                    "target_branch": body["target_branch"],
                    "title": body["title"],
                    "state": "opened",
                },
            )
            return

        self._json(404, {"message": "404 Not Found"})

    def do_PUT(self):
        parsed = urlsplit(self.path)
        if parsed.path.endswith("/merge_requests/7/merge"):
            body = self._read_json()
            self._json(
                200,
                {
                    "iid": 7,
                    "state": "merged",
                    "sha": body.get("sha", ""),
                },
            )
            return
        self._json(404, {"message": "404 Not Found"})


@pytest.fixture(scope="module")
def gitlab_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GitLabHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def configured_profiles(monkeypatch, gitlab_server):
    gitlab_tools._clear_runtime_cache()

    monkeypatch.setattr(
        gitlab_module,
        "list_config_folders",
        lambda path: [
            {"name": "local-alice"},
            {"name": "local-bob"},
        ]
        if path == "gitlab/accounts"
        else [],
    )

    values = {
        ("gitlab/accounts/local-alice", "BASE_URL"): gitlab_server,
        ("gitlab/accounts/local-alice", "AUTH_TYPE"): "private_token",
        ("gitlab/accounts/local-alice", "LABEL"): "Local Alice",
        ("gitlab/accounts/local-alice", "VERIFY_TLS"): "true",
        ("gitlab/accounts/local-alice", "TOKEN"): "token-a",
        ("gitlab/accounts/local-bob", "BASE_URL"): gitlab_server,
        ("gitlab/accounts/local-bob", "AUTH_TYPE"): "private_token",
        ("gitlab/accounts/local-bob", "LABEL"): "Local Bob",
        ("gitlab/accounts/local-bob", "VERIFY_TLS"): "true",
        ("gitlab/accounts/local-bob", "TOKEN"): "token-b",
    }

    def resolve(path: str, name: str) -> str:
        if (path, name) in values:
            return values[(path, name)]
        raise gitlab_module.SecretError("missing optional secret")

    monkeypatch.setattr(gitlab_module, "resolve_config_secret", resolve)


def test_registry_discovers_infisical_profiles_without_eager_token_read(
    monkeypatch,
    gitlab_server,
) -> None:

    monkeypatch.setattr(
        gitlab_module,
        "list_config_folders",
        lambda path: [{"name": "local-alice"}]
        if path == "gitlab/accounts"
        else [],
    )

    reads = []

    def fake_resolve(path: str, name: str) -> str:
        reads.append((path, name))
        values = {
            ("gitlab/accounts/local-alice", "BASE_URL"): gitlab_server,
            ("gitlab/accounts/local-alice", "AUTH_TYPE"): "private_token",
            ("gitlab/accounts/local-alice", "LABEL"): "Local Alice",
            ("gitlab/accounts/local-alice", "VERIFY_TLS"): "true",
            ("gitlab/accounts/local-alice", "TOKEN"): "token-a",
        }
        if (path, name) in values:
            return values[(path, name)]
        raise gitlab_module.SecretError("missing optional secret")

    monkeypatch.setattr(gitlab_module, "resolve_config_secret", fake_resolve)

    registry = GitLabProfileRegistry.from_infisical()
    result = registry.list()

    assert result["count"] == 1
    profile = registry.get("local-alice")
    assert profile.base_url == gitlab_server
    assert profile.auth_type == "private_token"
    assert profile.label == "Local Alice"
    assert profile.public()["credential_source"] == {
        "type": "infisical_convention",
        "path": "gitlab/accounts/local-alice",
        "secret": "TOKEN",
    }
    assert ("gitlab/accounts/local-alice", "TOKEN") not in reads

    assert profile.token() == "token-a"
    assert ("gitlab/accounts/local-alice", "TOKEN") in reads


def test_registry_lists_multiple_profiles_without_tokens(configured_profiles) -> None:
    result = GitLabProfileRegistry.from_infisical().list()
    assert result["count"] == 2

    profiles = {item["profile_id"]: item for item in result["profiles"]}
    assert profiles["local-alice"]["credential_configured"] is True
    assert profiles["local-bob"]["credential_configured"] is True
    assert "token-a" not in json.dumps(result)
    assert "token-b" not in json.dumps(result)


def test_two_profiles_same_instance_resolve_different_accounts(configured_profiles) -> None:
    registry = GitLabProfileRegistry.from_infisical()
    alice = GitLabClient(registry.get("local-alice")).profile_status()
    bob = GitLabClient(registry.get("local-bob")).profile_status()

    assert alice["authenticated_user"]["username"] == "alice"
    assert bob["authenticated_user"]["username"] == "bob"
    assert alice["profile"]["base_url"] == bob["profile"]["base_url"]


def test_project_selector_accepts_path_with_namespace(configured_profiles) -> None:
    client = GitLabClient(GitLabProfileRegistry.from_infisical().get("local-alice"))
    result = client.project_status("group/project")
    assert result["project"]["id"] == 123
    assert result["project"]["path_with_namespace"] == "group/project"


def test_read_file_decodes_base64(configured_profiles) -> None:
    client = GitLabClient(GitLabProfileRegistry.from_infisical().get("local-alice"))
    result = client.get_file("group/project", "README.md", "main")
    assert result["content"] == "hello gitlab"
    assert result["last_commit_id"] == "last"


def test_project_list_pagination_metadata(configured_profiles) -> None:
    client = GitLabClient(GitLabProfileRegistry.from_infisical().get("local-alice"))
    result = client.list_projects()
    assert result["total"] == 1
    assert result["total_pages"] == 1
    assert result["projects"][0]["path_with_namespace"] == "group/project"


def test_direct_mutation_of_protected_branch_is_blocked(configured_profiles) -> None:
    client = GitLabClient(GitLabProfileRegistry.from_infisical().get("local-alice"))
    with pytest.raises(GitLabError, match="protected branch"):
        client.put_file(
            "group/project",
            "README.md",
            "changed",
            "main",
            "should not be allowed",
        )


def test_feature_branch_creation_is_allowed(configured_profiles) -> None:
    client = GitLabClient(GitLabProfileRegistry.from_infisical().get("local-alice"))
    result = client.create_branch("group/project", "feature/new", "main")
    assert result["branch"]["name"] == "feature/new"


def test_merge_request_flow_allows_protected_target(configured_profiles) -> None:
    client = GitLabClient(GitLabProfileRegistry.from_infisical().get("local-alice"))
    created = client.create_merge_request(
        "group/project",
        "feature/new",
        "main",
        "Test MR",
    )
    assert created["merge_request"]["target_branch"] == "main"

    merged = client.merge_merge_request(
        "group/project",
        7,
        sha="abc123",
    )
    assert merged["merge_request"]["state"] == "merged"
    assert merged["merge_request"]["sha"] == "abc123"


def test_legacy_profile_environment_is_ignored(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "GITLAB_PROFILES_JSON",
        '[{"profile_id":"legacy","token":"should-not-be-read"}]',
    )
    monkeypatch.setattr(gitlab_module, "list_config_folders", lambda path: [])
    registry = GitLabProfileRegistry.from_infisical()
    assert registry.list()["count"] == 0


def test_http_app_mounts_dedicated_gitlab_endpoint() -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/gitlab" in paths

def test_runtime_reuses_registry_and_client(
    configured_profiles,
    monkeypatch,
) -> None:
    gitlab_tools._clear_runtime_cache()
    monkeypatch.setenv("GITLAB_REGISTRY_CACHE_TTL_SECONDS", "60")
    original = GitLabProfileRegistry.from_infisical
    calls = 0

    def counted_from_infisical():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(
        gitlab_tools.GitLabProfileRegistry,
        "from_infisical",
        counted_from_infisical,
    )

    first = gitlab_tools._client("local-alice")
    second = gitlab_tools._client("local-alice")

    assert first is second
    assert calls == 1
    gitlab_tools._clear_runtime_cache()


def test_gitlab_client_reuses_persistent_connection(configured_profiles) -> None:
    client = GitLabClient(GitLabProfileRegistry.from_infisical().get("local-alice"))

    client.project_status("group/project")
    client.project_status("group/project")

    assert client._connection_count == 1
    assert client._connection_pool.qsize() == 1


def test_gitlab_401_has_profile_credential_diagnostic(
    monkeypatch,
    gitlab_server,
) -> None:
    monkeypatch.setattr(
        gitlab_module,
        "resolve_config_secret",
        lambda path, name: "wrong-token"
        if (path, name) == ("gitlab/accounts/bad-auth", "TOKEN")
        else (_ for _ in ()).throw(gitlab_module.SecretError("missing")),
    )
    profile = gitlab_module.GitLabProfile(
        profile_id="bad-auth",
        base_url=gitlab_server,
        auth_type="private_token",
        convention_path="gitlab/accounts/bad-auth",
    )
    client = GitLabClient(profile)

    with pytest.raises(
        GitLabError,
        match="authentication failed.*bad-auth.*private_token",
    ):
        client.profile_status()


def test_infisical_profile_discovery_failure_is_not_silenced(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        gitlab_module,
        "list_config_folders",
        lambda path: (_ for _ in ()).throw(
            gitlab_module.SecretError("Infisical API HTTP 403: denied")
        ),
    )

    with pytest.raises(
        GitLabError,
        match="discover GitLab profiles.*HTTP 403",
    ):
        GitLabProfileRegistry.from_infisical()

