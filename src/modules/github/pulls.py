from __future__ import annotations

import urllib.parse

from common.models import (
    JsonObject,
    json_array,
    json_int,
    json_member_array,
    json_member_object,
    json_str,
)

from .base import GitHubRepositoryClientBase
from .github_agent import GitHubAgentError
from .policy import required_checks_from_env


class GitHubPullClient(GitHubRepositoryClientBase):
    def list_pull_requests(
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
            f"/repos/{repository}/pulls?{params}",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected pull request list response")
        return {
            "repository": repository,
            "pull_requests": [
                self._compact_pull(item)
                for item in result
                if isinstance(item, dict)
            ],
            "page": page,
        }

    def get_pull_request(self, repository: str, number: int) -> JsonObject:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}",
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected pull request response")
        compact = self._compact_pull(result)
        compact["body"] = json_str(result.get("body"))
        compact["mergeable"] = result.get("mergeable")
        compact["mergeable_state"] = json_str(result.get("mergeable_state"))
        return {"repository": repository, "pull_request": compact}

    def create_pull_request(
        self,
        repository: str,
        title: str,
        head: str,
        base: str,
        body: str = "",
        draft: bool = False,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        if ":" in head or ":" in base:
            raise GitHubAgentError("cross-repository pull requests are disabled")
        if head == base:
            raise GitHubAgentError("pull request head and base must differ")
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/pulls",
            payload={
                "title": title,
                "head": head,
                "base": base,
                "body": body,
                "draft": draft,
            },
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected pull request create response")
        return {"repository": repository, "pull_request": self._compact_pull(result)}

    def update_pull_request(
        self,
        repository: str,
        number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        base: str | None = None,
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
        if base is not None:
            if ":" in base:
                raise GitHubAgentError("cross-repository pull requests are disabled")
            payload["base"] = base
        if not payload:
            raise GitHubAgentError("no pull request fields were supplied")
        _, result = self._repo_request(
            repository,
            "PATCH",
            f"/repos/{repository}/pulls/{number}",
            payload=payload,
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected pull request update response")
        return {"repository": repository, "pull_request": self._compact_pull(result)}

    def list_pull_files(self, repository: str, number: int) -> JsonObject:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}/files?per_page=100",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected pull request file response")
        files = [
            {
                "filename": json_str(item.get("filename")),
                "status": json_str(item.get("status")),
                "additions": json_int(item.get("additions")),
                "deletions": json_int(item.get("deletions")),
                "patch": item.get("patch"),
            }
            for item in result
            if isinstance(item, dict)
        ]
        return {
            "repository": repository,
            "number": number,
            "files": json_array(files, context="GitHub pull files"),
        }

    def add_pull_comment(
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
            raise GitHubAgentError("unexpected pull request comment response")
        return {
            "repository": repository,
            "number": number,
            "comment_id": json_int(result.get("id")),
            "html_url": json_str(result.get("html_url")),
        }

    def list_reviews(self, repository: str, number: int) -> JsonObject:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}/reviews?per_page=100",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected pull request review response")
        reviews = []
        for item in result:
            if not isinstance(item, dict):
                continue
            user = json_member_object(item, "user")
            reviews.append(
                {
                    "id": json_int(item.get("id")),
                    "user": json_str(user.get("login")),
                    "state": json_str(item.get("state")),
                    "body": json_str(item.get("body")),
                    "submitted_at": json_str(item.get("submitted_at")),
                }
            )
        return {
            "repository": repository,
            "number": number,
            "reviews": json_array(reviews, context="GitHub reviews"),
        }

    def create_review(
        self,
        repository: str,
        number: int,
        event: str,
        body: str,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        event = event.upper()
        if event not in {"APPROVE", "REQUEST_CHANGES", "COMMENT"}:
            raise GitHubAgentError("event must be APPROVE, REQUEST_CHANGES, or COMMENT")
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/pulls/{number}/reviews",
            payload={"event": event, "body": body},
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected review create response")
        return {
            "repository": repository,
            "number": number,
            "review_id": json_int(result.get("id")),
            "state": json_str(result.get("state")),
        }

    def update_pull_branch(
        self,
        repository: str,
        number: int,
        expected_head_sha: str | None = None,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        payload: JsonObject = {}
        if expected_head_sha:
            payload["expected_head_sha"] = expected_head_sha
        _, result = self._repo_request(
            repository,
            "PUT",
            f"/repos/{repository}/pulls/{number}/update-branch",
            payload=payload,
        )
        return {"repository": repository, "number": number, "result": result}

    def check_runs(self, repository: str, ref: str) -> JsonObject:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self._quote(ref)}/check-runs?per_page=100",
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected check-run response")
        raw = json_member_array(result, "check_runs")
        checks = []
        for item in raw:
            if isinstance(item, dict):
                app = json_member_object(item, "app")
                checks.append(
                    {
                        "name": json_str(item.get("name")),
                        "status": json_str(item.get("status")),
                        "conclusion": item.get("conclusion"),
                        "app": json_str(app.get("slug")),
                        "details_url": json_str(item.get("details_url")),
                    }
                )
        return {
            "repository": repository,
            "ref": ref,
            "check_runs": json_array(checks, context="GitHub check runs"),
        }

    def assert_required_checks(self, repository: str, ref: str) -> JsonObject:
        result = self.check_runs(repository, ref)
        checks = result["check_runs"]
        assert isinstance(checks, list)
        by_name = {
            json_str(item.get("name")): item
            for item in checks
            if isinstance(item, dict)
        }
        required = required_checks_from_env()

        # The bridge can serve multiple repositories whose CI check names are
        # unrelated. GITHUB_AGENT_REQUIRED_CHECKS is therefore only applicable
        # when at least one configured check name is part of this repository's
        # normal CI surface. If the PR head has none of them, inspect the
        # repository's default branch before deciding that they are "missing".
        #
        # This keeps the strict test/docker gate for mcp-bridge while
        # avoiding an impossible merge requirement on repositories such as
        # ghidra-mcp, whose aggregate check is named "Build Status". GitHub's
        # own branch protection/rulesets remain the final merge authority.
        configured_names = set(required)
        if configured_names and not configured_names.intersection(by_name):
            repository_info = self._repository_metadata(repository)
            default_branch = json_str(repository_info.get("default_branch"))
            baseline_names: set[str] = set()
            if default_branch:
                baseline = self.check_runs(repository, default_branch)
                baseline_checks = baseline["check_runs"]
                assert isinstance(baseline_checks, list)
                baseline_names = {
                    json_str(item.get("name"))
                    for item in baseline_checks
                    if isinstance(item, dict)
                }
            if not configured_names.intersection(baseline_names):
                return {
                    "repository": repository,
                    "ref": ref,
                    "required": json_array(required, context="GitHub required checks"),
                    "status": "delegated_to_github",
                }

        missing = [name for name in required if name not in by_name]
        failing = [
            name
            for name in required
            if name in by_name
            and (
                by_name[name].get("status") != "completed"
                or by_name[name].get("conclusion") != "success"
            )
        ]
        if missing or failing:
            raise GitHubAgentError(
                f"required checks not satisfied; missing={missing}, failing={failing}"
            )
        return {
            "repository": repository,
            "ref": ref,
            "required": json_array(required, context="GitHub required checks"),
            "status": "ok",
        }

    def merge_pull_request(
        self,
        repository: str,
        number: int,
        merge_method: str = "squash",
        commit_title: str | None = None,
        commit_message: str | None = None,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        if merge_method not in {"merge", "squash", "rebase"}:
            raise GitHubAgentError("merge_method must be merge, squash, or rebase")
        _, pull = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}",
        )
        if not isinstance(pull, dict):
            raise GitHubAgentError("unexpected pull request response")
        head = json_member_object(pull, "head")
        base = json_member_object(pull, "base")
        head_repo = json_member_object(head, "repo")
        base_repo = json_member_object(base, "repo")
        if json_str(head_repo.get("full_name")).casefold() != repository.casefold():
            raise GitHubAgentError("cross-repository pull request merge is disabled")
        if json_str(base_repo.get("full_name")).casefold() != repository.casefold():
            raise GitHubAgentError("cross-repository pull request merge is disabled")
        head_sha = json_str(head.get("sha"))
        if not head_sha:
            raise GitHubAgentError("pull request head has no sha")
        self.assert_required_checks(repository, head_sha)

        payload: JsonObject = {"merge_method": merge_method}
        if commit_title:
            payload["commit_title"] = commit_title
        if commit_message:
            payload["commit_message"] = commit_message
        _, result = self._repo_request(
            repository,
            "PUT",
            f"/repos/{repository}/pulls/{number}/merge",
            payload=payload,
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected pull request merge response")
        return {
            "repository": repository,
            "number": number,
            "merged": bool(result.get("merged", False)),
            "sha": json_str(result.get("sha")),
            "message": json_str(result.get("message")),
            "merge_method": merge_method,
        }
