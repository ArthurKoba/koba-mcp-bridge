from __future__ import annotations

import base64
import hashlib

import pytest

from koba_mcp_bridge.github_actions import GitHubActionsClient
from koba_mcp_bridge.github_agent import GitHubAgentError


class RecordingActionsClient(GitHubActionsClient):
    def __init__(self) -> None:
        super().__init__(
            app_id="123",
            private_key="key-material",
        )
        self.calls: list[tuple[str, str]] = []
        self.download_payload = b"line-1\nline-2\nlast-error\n"
        self.head_sha = "current-head"
        self.reviews: list[dict[str, object]] = []

    def _repo_request(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, object]:
        del repository, payload, allowed_errors
        self.calls.append((method, path))
        if method == "GET" and path.endswith("/pulls/7"):
            return 200, {"head": {"sha": self.head_sha}}
        if method == "GET" and path.endswith("/pulls/7/reviews?per_page=100"):
            return 200, self.reviews
        if method == "GET" and "/artifacts?" in path:
            return (
                200,
                {
                    "total_count": 1,
                    "artifacts": [
                        {
                            "id": 9,
                            "name": "coverage",
                            "size_in_bytes": 123,
                            "expired": False,
                            "created_at": "2026-09-16T00:00:00Z",
                            "expires_at": "2026-12-15T00:00:00Z",
                        }
                    ],
                },
            )
        if method == "POST":
            return 201, {}
        raise AssertionError(f"unexpected request: {method} {path}")

    def _download_redirect_bytes(
        self,
        repository: str,
        endpoint: str,
        max_bytes: int,
    ) -> bytes:
        del repository, endpoint
        assert len(self.download_payload) <= max_bytes
        return self.download_payload


def test_job_log_returns_tail() -> None:
    client = RecordingActionsClient()
    result = client.get_workflow_job_log(
        "ArthurKoba/koba-mcp-bridge",
        42,
        max_chars=11,
    )
    assert result["log"] == "last-error\n"
    assert result["truncated"] is True


def test_list_workflow_artifacts_normalizes_payload() -> None:
    client = RecordingActionsClient()
    result = client.list_workflow_artifacts(
        "ArthurKoba/koba-mcp-bridge",
        77,
    )
    assert result["total_count"] == 1
    assert result["artifacts"] == [
        {
            "id": 9,
            "name": "coverage",
            "size_in_bytes": 123,
            "expired": False,
            "created_at": "2026-09-16T00:00:00Z",
            "expires_at": "2026-12-15T00:00:00Z",
        }
    ]


def test_download_artifact_returns_base64_and_hash() -> None:
    client = RecordingActionsClient()
    client.download_payload = b"PK\x03\x04artifact"
    result = client.download_workflow_artifact(
        "ArthurKoba/koba-mcp-bridge",
        9,
    )
    assert result["content_base64"] == base64.b64encode(client.download_payload).decode()
    assert result["sha256"] == hashlib.sha256(client.download_payload).hexdigest()


def test_rerun_and_cancel_endpoints() -> None:
    client = RecordingActionsClient()
    repository = "ArthurKoba/koba-mcp-bridge"

    client.rerun_workflow_job(repository, 10)
    client.rerun_failed_workflow_jobs(repository, 20)
    client.rerun_workflow_run(repository, 20)
    client.cancel_workflow_run(repository, 20)

    assert client.calls == [
        ("POST", "/repos/ArthurKoba/koba-mcp-bridge/actions/jobs/10/rerun"),
        (
            "POST",
            "/repos/ArthurKoba/koba-mcp-bridge/actions/runs/20/rerun-failed-jobs",
        ),
        ("POST", "/repos/ArthurKoba/koba-mcp-bridge/actions/runs/20/rerun"),
        ("POST", "/repos/ArthurKoba/koba-mcp-bridge/actions/runs/20/cancel"),
    ]


def test_required_reviewer_approval_must_match_current_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_REQUIRED_REVIEWERS", "koba-ai-reviewer[bot]")
    client = RecordingActionsClient()
    client.reviews = [
        {
            "user": {"login": "koba-ai-reviewer[bot]"},
            "state": "APPROVED",
            "commit_id": "old-head",
        }
    ]

    with pytest.raises(GitHubAgentError, match="STALE_APPROVAL"):
        client.assert_required_reviews("ArthurKoba/koba-mcp-bridge", 7)


def test_required_reviewer_approval_on_current_head_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_REQUIRED_REVIEWERS", "koba-ai-reviewer[bot]")
    client = RecordingActionsClient()
    client.reviews = [
        {
            "user": {"login": "koba-ai-reviewer[bot]"},
            "state": "APPROVED",
            "commit_id": "current-head",
        }
    ]

    result = client.assert_required_reviews("ArthurKoba/koba-mcp-bridge", 7)
    assert result["status"] == "ok"
    assert result["head_sha"] == "current-head"


def test_required_reviewer_changes_requested_blocks_current_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_REQUIRED_REVIEWERS", "koba-ai-reviewer[bot]")
    client = RecordingActionsClient()
    client.reviews = [
        {
            "user": {"login": "koba-ai-reviewer[bot]"},
            "state": "CHANGES_REQUESTED",
            "commit_id": "current-head",
        }
    ]

    with pytest.raises(GitHubAgentError, match="CHANGES_REQUESTED"):
        client.assert_required_reviews("ArthurKoba/koba-mcp-bridge", 7)
