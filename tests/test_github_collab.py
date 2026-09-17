from __future__ import annotations

import pytest

from koba_mcp_bridge.github_agent import GitHubAgentError
from koba_mcp_bridge.github_collab import GitHubCollabClient


class RecordingCollabClient(GitHubCollabClient):
    def __init__(self) -> None:
        super().__init__(
            app_id="123",
            private_key="key-material",
        )
        self.graphql_calls: list[tuple[str, dict[str, object]]] = []

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
        if method == "GET" and "/pulls/" in path:
            return 200, {"node_id": "PR_node_1"}
        raise AssertionError(f"unexpected request: {method} {path}")

    def _graphql(
        self,
        repository: str,
        query: str,
        variables: dict[str, object],
    ) -> dict[str, object]:
        del repository
        self.graphql_calls.append((query, variables))
        if "markPullRequestReadyForReview" in query:
            return {
                "markPullRequestReadyForReview": {
                    "pullRequest": {"number": 7, "isDraft": False}
                }
            }
        if "unresolveReviewThread" in query:
            return {
                "unresolveReviewThread": {
                    "thread": {"id": "THREAD_1", "isResolved": False}
                }
            }
        if "resolveReviewThread" in query:
            return {
                "resolveReviewThread": {
                    "thread": {"id": "THREAD_1", "isResolved": True}
                }
            }
        raise AssertionError("unexpected GraphQL query")


def test_merge_branch_rejects_protected_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_AGENT_PROTECTED_BRANCHES", raising=False)
    with pytest.raises(GitHubAgentError, match="protected branch"):
        RecordingCollabClient().merge_branch(
            "ArthurKoba/koba-mcp-bridge",
            "main",
            "feature/test",
        )


def test_request_reviewers_requires_target() -> None:
    with pytest.raises(GitHubAgentError, match="at least one reviewer"):
        RecordingCollabClient().request_reviewers(
            "ArthurKoba/koba-mcp-bridge",
            7,
        )


def test_resolve_review_thread_uses_graphql_mutation() -> None:
    client = RecordingCollabClient()
    result = client.set_review_thread_resolved(
        "ArthurKoba/koba-mcp-bridge",
        "THREAD_1",
        True,
    )
    assert result == {
        "repository": "ArthurKoba/koba-mcp-bridge",
        "thread_id": "THREAD_1",
        "resolved": True,
    }
    assert client.graphql_calls[0][1] == {"input": {"threadId": "THREAD_1"}}


def test_unresolve_review_thread_uses_graphql_mutation() -> None:
    client = RecordingCollabClient()
    result = client.set_review_thread_resolved(
        "ArthurKoba/koba-mcp-bridge",
        "THREAD_1",
        False,
    )
    assert result["resolved"] is False


def test_mark_pull_ready_for_review() -> None:
    client = RecordingCollabClient()
    result = client.mark_pull_ready_for_review(
        "ArthurKoba/koba-mcp-bridge",
        7,
    )
    assert result == {
        "repository": "ArthurKoba/koba-mcp-bridge",
        "number": 7,
        "draft": False,
    }
