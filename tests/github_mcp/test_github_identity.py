from __future__ import annotations

from typing import Any

from github_mcp.github_identity import GitHubPrettyIdentityClient


class RecordingPrettyClient(GitHubPrettyIdentityClient):
    def __init__(self, *, app_name: str, slug: str, bot_id: int) -> None:
        super().__init__(app_id="4970571", private_key="unused")
        self.app_name = app_name
        self.slug = slug
        self.bot_id = bot_id
        self.requests: list[dict[str, object]] = []

    def _app_jwt(self) -> str:
        return "app-jwt"

    def _installation_token(self, repository: str) -> str:
        del repository
        return "installation-token"

    def _installation_id(self, repository: str) -> int:
        del repository
        return 77

    def _request(
        self,
        method: str,
        url: str,
        *,
        token: str | None = None,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, object]:
        del token
        if method == "GET" and url.endswith("/app"):
            return 200, {"slug": self.slug, "name": self.app_name}
        if method == "GET" and "/users/" in url:
            return 200, {"id": self.bot_id, "login": f"{self.slug}[bot]", "type": "Bot"}

        self.requests.append({"method": method, "url": url, "payload": payload})
        if method == "GET" and "/contents/" in url and allowed_errors == {404}:
            return 404, {}
        if method == "PUT" and "/contents/" in url:
            return 201, {"commit": {"sha": "commit-1"}, "content": {"sha": "blob-1"}}
        if method == "DELETE" and "/contents/" in url:
            return 200, {"commit": {"sha": "commit-2"}}
        if method == "POST" and url.endswith("/git/commits"):
            return 201, {"sha": "commit-3"}
        if method == "POST" and url.endswith("/git/tags"):
            return 201, {"sha": "tag-object"}
        if method == "GET" and url.endswith("/repos/ArthurKoba/example"):
            return 200, {
                "full_name": "ArthurKoba/example",
                "default_branch": "main",
                "private": False,
            }
        raise AssertionError(f"unexpected request: {method} {url}")


def _payload_for(client: RecordingPrettyClient, method: str, suffix: str) -> dict[str, Any]:
    for item in reversed(client.requests):
        if item["method"] == method and str(item["url"]).endswith(suffix):
            payload = item["payload"]
            assert isinstance(payload, dict)
            return payload
    raise AssertionError(f"request not found: {method} {suffix}")


def test_app_identity_separates_display_name_from_actor_login() -> None:
    client = RecordingPrettyClient(
        app_name="Koba AI Agent",
        slug="koba-ai-agent",
        bot_id=330168119,
    )

    identity = client._app_identity()

    assert identity["display_name"] == "Koba AI Agent"
    assert identity["name"] == "Koba AI Agent"
    assert identity["login"] == "koba-ai-agent[bot]"
    assert identity["email"] == (
        "330168119+koba-ai-agent[bot]@users.noreply.github.com"
    )
    assert identity["type"] == "Bot"


def test_contents_commits_receive_pretty_author_and_committer() -> None:
    client = RecordingPrettyClient(
        app_name="Koba AI Agent",
        slug="koba-ai-agent",
        bot_id=330168119,
    )

    result = client.put_file(
        "ArthurKoba/example",
        "README.md",
        "hello",
        "docs: update",
        "feature/test",
    )

    assert result["commit_sha"] == "commit-1"
    payload = _payload_for(client, "PUT", "/contents/README.md")
    expected = {
        "name": "Koba AI Agent",
        "email": "330168119+koba-ai-agent[bot]@users.noreply.github.com",
    }
    assert payload["author"] == expected
    assert payload["committer"] == expected


def test_git_data_commits_and_annotated_tags_receive_pretty_identity() -> None:
    client = RecordingPrettyClient(
        app_name="Koba AI Agent",
        slug="koba-ai-agent",
        bot_id=330168119,
    )
    expected = {
        "name": "Koba AI Agent",
        "email": "330168119+koba-ai-agent[bot]@users.noreply.github.com",
    }

    client._repo_request(
        "ArthurKoba/example",
        "POST",
        "/repos/ArthurKoba/example/git/commits",
        payload={"message": "x", "tree": "tree", "parents": ["parent"]},
    )
    commit_payload = _payload_for(client, "POST", "/git/commits")
    assert commit_payload["author"] == expected
    assert commit_payload["committer"] == expected

    client._repo_request(
        "ArthurKoba/example",
        "POST",
        "/repos/ArthurKoba/example/git/tags",
        payload={"tag": "v1", "message": "release", "object": "sha", "type": "commit"},
    )
    tag_payload = _payload_for(client, "POST", "/git/tags")
    assert tag_payload["tagger"] == expected


def test_explicit_identity_is_not_overwritten() -> None:
    client = RecordingPrettyClient(
        app_name="Koba AI Agent",
        slug="koba-ai-agent",
        bot_id=330168119,
    )
    explicit = {"name": "Explicit", "email": "explicit@example.com"}

    client._repo_request(
        "ArthurKoba/example",
        "POST",
        "/repos/ArthurKoba/example/git/commits",
        payload={
            "message": "x",
            "tree": "tree",
            "parents": ["parent"],
            "author": explicit,
            "committer": explicit,
        },
    )
    payload = _payload_for(client, "POST", "/git/commits")
    assert payload["author"] == explicit
    assert payload["committer"] == explicit


def test_reviewer_display_identity_uses_reviewer_app_name() -> None:
    client = RecordingPrettyClient(
        app_name="Koba AI Reviewer",
        slug="koba-ai-reviewer",
        bot_id=330200000,
    )

    status = client.status("ArthurKoba/example")
    identity = status["app_identity"]

    assert identity["display_name"] == "Koba AI Reviewer"
    assert identity["name"] == "Koba AI Reviewer"
    assert identity["login"] == "koba-ai-reviewer[bot]"
