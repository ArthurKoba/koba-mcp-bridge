from __future__ import annotations

import urllib.parse

from common.models import JsonObject, json_array, json_int, json_str

from .base import GitHubRepositoryClientBase
from .github_agent import GitHubAgentError


class GitHubIssueClient(GitHubRepositoryClientBase):
    def list_issues(
        self,
        repository: str,
        state: str = "open",
        per_page: int = 50,
        page: int = 1,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        if state not in {"open", "closed", "all"}:
            raise GitHubAgentError("state must be open, closed, or all")
        params = urllib.parse.urlencode(
            {
                "state": state,
                "per_page": max(1, min(per_page, 100)),
                "page": max(1, page),
            }
        )
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/issues?{params}",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected issue list response")
        issues = []
        for item in result:
            if not isinstance(item, dict) or "pull_request" in item:
                continue
            issues.append(self._compact_issue(item))
        return {
            "repository": repository,
            "issues": json_array(issues, context="GitHub issues"),
            "page": page,
        }

    @staticmethod
    def _compact_issue(item: JsonObject) -> JsonObject:
        return {
            "number": json_int(item.get("number")),
            "title": json_str(item.get("title")),
            "state": json_str(item.get("state")),
            "body": json_str(item.get("body")),
            "html_url": json_str(item.get("html_url")),
        }

    def get_issue(self, repository: str, number: int) -> JsonObject:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/issues/{number}",
        )
        if not isinstance(result, dict) or "pull_request" in result:
            raise GitHubAgentError("number does not refer to an issue")
        return {"repository": repository, "issue": self._compact_issue(result)}

    def create_issue(
        self,
        repository: str,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        payload: JsonObject = {"title": title, "body": body}
        if labels is not None:
            payload["labels"] = json_array(labels, context="GitHub issue labels")
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/issues",
            payload=payload,
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected issue create response")
        return {"repository": repository, "issue": self._compact_issue(result)}

    def update_issue(
        self,
        repository: str,
        number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        payload: JsonObject = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state is not None:
            if state not in {"open", "closed"}:
                raise GitHubAgentError("state must be open or closed")
            payload["state"] = state
        if labels is not None:
            payload["labels"] = json_array(labels, context="GitHub issue labels")
        if not payload:
            raise GitHubAgentError("no issue fields were supplied")
        _, result = self._repo_request(
            repository,
            "PATCH",
            f"/repos/{repository}/issues/{number}",
            payload=payload,
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected issue update response")
        return {"repository": repository, "issue": self._compact_issue(result)}

    def add_issue_comment(
        self,
        repository: str,
        number: int,
        body: str,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/issues/{number}/comments",
            payload={"body": body},
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected issue comment response")
        return {
            "repository": repository,
            "number": number,
            "comment_id": json_int(result.get("id")),
            "html_url": json_str(result.get("html_url")),
        }
