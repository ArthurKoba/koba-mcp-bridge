from __future__ import annotations

import pytest

from koba_mcp_bridge.github_agent import GitHubAgentError
from koba_mcp_bridge.github_review import GitHubReviewClient


class RecordingClient(GitHubReviewClient):
    def __init__(self) -> None:
        super().__init__(
            app_id="123",
            private_key="key-material",
            allowed_repositories={"arthurkoba/koba-mcp-bridge"},
        )
        self.graphql_calls: list[tuple[str, dict[str, object]]] = []
        self.review_payloads: list[dict[str, object]] = []
        self.pull_head_repo = "ArthurKoba/koba-mcp-bridge"

    def _repo_request(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, object]:
        del allowed_errors
        if method == "GET" and "/pulls/" in path and not path.endswith("/comments?per_page=100"):
            return (
                200,
                {
                    "node_id": "PR_node_1",
                    "head": {
                        "sha": "abc123",
                        "repo": {"full_name": self.pull_head_repo},
                    },
                },
            )
        if method == "POST" and path.endswith("/reviews"):
            assert isinstance(payload, dict)
            self.review_payloads.append(payload)
            return 200, {"id": 42, "state": "COMMENTED", "commit_id": "abc123"}
        raise AssertionError(f"unexpected request: {method} {path}")

    def _graphql(
        self,
        repository: str,
        query: str,
        variables: dict[str, object],
    ) -> dict[str, object]:
        del repository, query
        self.graphql_calls.append(("updatePullRequestBranch", variables))
        return {
            "updatePullRequestBranch": {
                "pullRequest": {
                    "number": 7,
                    "headRefName": "feature/test",
                    "headRefOid": "def456",
                    "baseRefName": "main",
                    "mergeable": "MERGEABLE",
                }
            }
        }


def test_update_pull_branch_accepts_true_rebase() -> None:
    client = RecordingClient()
    result = client.update_pull_branch_graphql(
        "ArthurKoba/koba-mcp-bridge",
        7,
        method="REBASE",
        expected_head_sha="abc123",
    )

    assert result["method"] == "REBASE"
    assert result["head_sha"] == "def456"
    variables = client.graphql_calls[0][1]
    assert variables == {
        "input": {
            "pullRequestId": "PR_node_1",
            "updateMethod": "REBASE",
            "expectedHeadOid": "abc123",
        }
    }


def test_update_pull_branch_rejects_invalid_method() -> None:
    with pytest.raises(GitHubAgentError, match="MERGE or REBASE"):
        RecordingClient().update_pull_branch_graphql(
            "ArthurKoba/koba-mcp-bridge",
            7,
            method="CHERRY_PICK",
        )


def test_update_pull_branch_rejects_cross_repository_head() -> None:
    client = RecordingClient()
    client.pull_head_repo = "someone/fork"
    with pytest.raises(GitHubAgentError, match="cross-repository"):
        client.update_pull_branch_graphql(
            "ArthurKoba/koba-mcp-bridge",
            7,
            method="REBASE",
        )


def test_update_pull_branch_checks_expected_head() -> None:
    with pytest.raises(GitHubAgentError, match="head changed"):
        RecordingClient().update_pull_branch_graphql(
            "ArthurKoba/koba-mcp-bridge",
            7,
            method="MERGE",
            expected_head_sha="stale",
        )


def test_rich_review_normalizes_inline_comments() -> None:
    client = RecordingClient()
    result = client.create_review_with_comments(
        "ArthurKoba/koba-mcp-bridge",
        7,
        "comment",
        "overall",
        comments=[
            {
                "path": "src/example.py",
                "body": "Check this line",
                "line": 12,
                "side": "RIGHT",
                "ignored": "not-sent",
            }
        ],
        commit_id="abc123",
    )

    assert result["review_id"] == 42
    assert client.review_payloads == [
        {
            "event": "COMMENT",
            "body": "overall",
            "commit_id": "abc123",
            "comments": [
                {
                    "path": "src/example.py",
                    "body": "Check this line",
                    "line": 12,
                    "side": "RIGHT",
                }
            ],
        }
    ]


def test_rich_review_requires_comment_path_and_body() -> None:
    client = RecordingClient()
    with pytest.raises(GitHubAgentError, match="requires path and body"):
        client.create_review_with_comments(
            "ArthurKoba/koba-mcp-bridge",
            7,
            "COMMENT",
            "overall",
            comments=[{"path": "src/example.py"}],
        )


def test_rich_review_rejects_invalid_event() -> None:
    with pytest.raises(GitHubAgentError, match="event must be"):
        RecordingClient().create_review_with_comments(
            "ArthurKoba/koba-mcp-bridge",
            7,
            "LGTM",
            "body",
        )
