from __future__ import annotations

from typing import Any

from .github_agent import GitHubAgentError
from .github_workflow import GitHubDevClient


class GitHubReviewClient(GitHubDevClient):
    """Adds GraphQL rebase/update and richer PR review operations."""

    def _graphql(
        self,
        repository: str,
        query: str,
        variables: dict[str, object],
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        token = self._installation_token(repository)
        _, result = self._request(
            "POST",
            "https://api.github.com/graphql",
            token=token,
            payload={"query": query, "variables": variables},
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected GraphQL response")
        errors = result.get("errors")
        if isinstance(errors, list) and errors:
            raise GitHubAgentError(f"GitHub GraphQL error: {errors}")
        data = result.get("data")
        if not isinstance(data, dict):
            raise GitHubAgentError("GitHub GraphQL response has no data")
        return data

    def update_pull_branch_graphql(
        self,
        repository: str,
        number: int,
        method: str = "MERGE",
        expected_head_sha: str | None = None,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        method = method.upper()
        if method not in {"MERGE", "REBASE"}:
            raise GitHubAgentError("method must be MERGE or REBASE")

        _, pull = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}",
        )
        if not isinstance(pull, dict):
            raise GitHubAgentError("unexpected pull request response")
        node_id = str(pull.get("node_id", ""))
        head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
        head_repo = head.get("repo") if isinstance(head.get("repo"), dict) else {}
        if str(head_repo.get("full_name", "")).casefold() != repository.casefold():
            raise GitHubAgentError("cross-repository pull request update is disabled")
        if not node_id:
            raise GitHubAgentError("pull request has no GraphQL node id")

        current_head = str(head.get("sha", ""))
        if expected_head_sha and current_head != expected_head_sha:
            raise GitHubAgentError(
                f"pull request head changed: expected {expected_head_sha}, found {current_head}"
            )

        mutation = """
        mutation UpdatePullRequestBranch($input: UpdatePullRequestBranchInput!) {
          updatePullRequestBranch(input: $input) {
            pullRequest {
              number
              headRefName
              headRefOid
              baseRefName
              mergeable
            }
          }
        }
        """
        input_data: dict[str, object] = {
            "pullRequestId": node_id,
            "updateMethod": method,
        }
        if expected_head_sha:
            input_data["expectedHeadOid"] = expected_head_sha
        data = self._graphql(repository, mutation, {"input": input_data})
        update = data.get("updatePullRequestBranch")
        if not isinstance(update, dict) or not isinstance(update.get("pullRequest"), dict):
            raise GitHubAgentError("GraphQL updatePullRequestBranch returned no pull request")
        result = update["pullRequest"]
        return {
            "repository": repository,
            "number": int(result.get("number", number)),
            "head": str(result.get("headRefName", "")),
            "head_sha": str(result.get("headRefOid", "")),
            "base": str(result.get("baseRefName", "")),
            "mergeable": str(result.get("mergeable", "")),
            "method": method,
        }

    def create_review_with_comments(
        self,
        repository: str,
        number: int,
        event: str,
        body: str,
        comments: list[dict[str, Any]] | None = None,
        commit_id: str | None = None,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        event = event.upper()
        if event not in {"APPROVE", "REQUEST_CHANGES", "COMMENT"}:
            raise GitHubAgentError("event must be APPROVE, REQUEST_CHANGES, or COMMENT")
        payload: dict[str, object] = {"event": event, "body": body}
        if commit_id:
            payload["commit_id"] = commit_id
        if comments:
            normalized: list[dict[str, object]] = []
            allowed = {"path", "body", "line", "side", "start_line", "start_side", "position"}
            for comment in comments:
                if not comment.get("path") or not comment.get("body"):
                    raise GitHubAgentError("each review comment requires path and body")
                normalized.append(
                    {
                        key: value
                        for key, value in comment.items()
                        if key in allowed and value is not None
                    }
                )
            payload["comments"] = normalized
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/pulls/{number}/reviews",
            payload=payload,
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected review create response")
        return {
            "repository": repository,
            "number": number,
            "review_id": int(result.get("id", 0)),
            "state": str(result.get("state", "")),
            "commit_id": str(result.get("commit_id", "")),
        }

    def list_conversation_comments(
        self,
        repository: str,
        number: int,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/issues/{number}/comments?per_page=100",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected conversation comment response")
        comments = []
        for item in result:
            if not isinstance(item, dict):
                continue
            user = item.get("user") if isinstance(item.get("user"), dict) else {}
            comments.append(
                {
                    "id": int(item.get("id", 0)),
                    "user": str(user.get("login", "")),
                    "body": str(item.get("body", "") or ""),
                    "created_at": str(item.get("created_at", "")),
                    "updated_at": str(item.get("updated_at", "")),
                    "html_url": str(item.get("html_url", "")),
                }
            )
        return {"repository": repository, "number": number, "comments": comments}

    def list_review_comments(
        self,
        repository: str,
        number: int,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}/comments?per_page=100",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected review comment response")
        comments = []
        for item in result:
            if not isinstance(item, dict):
                continue
            user = item.get("user") if isinstance(item.get("user"), dict) else {}
            comments.append(
                {
                    "id": int(item.get("id", 0)),
                    "user": str(user.get("login", "")),
                    "path": str(item.get("path", "")),
                    "line": item.get("line"),
                    "side": item.get("side"),
                    "body": str(item.get("body", "") or ""),
                    "commit_id": str(item.get("commit_id", "")),
                    "html_url": str(item.get("html_url", "")),
                }
            )
        return {"repository": repository, "number": number, "comments": comments}
