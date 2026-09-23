from __future__ import annotations

import os

from common.models import (
    json_bool,
    json_int,
    json_member_array,
    json_member_object,
    json_object,
    json_str,
)

from common.models import json_int, json_member_object, json_str

from .github_agent import GitHubAgentError
from .github_review import GitHubReviewClient


def required_reviewer_logins_from_env() -> list[str]:
    raw = os.getenv("GITHUB_AGENT_REQUIRED_REVIEWERS", "")
    return [item.strip().casefold() for item in raw.split(",") if item.strip()]


class GitHubCollabClient(GitHubReviewClient):
    """Collaboration operations for branch/PR review loops."""

    def assert_required_reviews(
        self,
        repository: str,
        number: int,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        required = required_reviewer_logins_from_env()
        if not required:
            return {
                "repository": repository,
                "number": number,
                "required_reviewers": [],
                "status": "not_configured",
            }

        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}/reviews?per_page=100",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected pull request review response")

        decisive_state: dict[str, str] = {}
        for item in result:
            if not isinstance(item, dict):
                continue
            user = json_member_object(item, "user")
            login = json_str(user.get("login")).casefold()
            state = json_str(item.get("state")).upper()
            if login and state in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
                decisive_state[login] = state

        missing = [login for login in required if decisive_state.get(login) != "APPROVED"]
        if missing:
            states = {login: decisive_state.get(login, "MISSING") for login in required}
            raise GitHubAgentError(
                f"required independent reviews not satisfied; missing={missing}, states={states}"
            )
        return {
            "repository": repository,
            "number": number,
            "required_reviewers": required,
            "status": "ok",
        }

    def merge_pull_request(
        self,
        repository: str,
        number: int,
        merge_method: str = "squash",
        commit_title: str | None = None,
        commit_message: str | None = None,
    ) -> dict[str, object]:
        self.assert_required_reviews(repository, number)
        return super().merge_pull_request(
            repository,
            number,
            merge_method,
            commit_title,
            commit_message,
        )

    def merge_branch(
        self,
        repository: str,
        base: str,
        head: str,
        commit_message: str | None = None,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        base = self._assert_mutable_branch(base)
        payload: dict[str, object] = {"base": base, "head": head}
        if commit_message:
            payload["commit_message"] = commit_message
        status, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/merges",
            payload=payload,
            allowed_errors={204, 409},
        )
        if status == 204:
            return {
                "repository": repository,
                "base": base,
                "head": head,
                "status": status,
                "merged": False,
                "message": "base already contains head",
            }
        if status == 409:
            raise GitHubAgentError("branch merge conflict")
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected branch merge response")
        return {
            "repository": repository,
            "base": base,
            "head": head,
            "status": status,
            "merged": True,
            "commit_sha": json_str(result.get("sha")),
        }

    def request_reviewers(
        self,
        repository: str,
        number: int,
        reviewers: list[str] | None = None,
        team_reviewers: list[str] | None = None,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        if not reviewers and not team_reviewers:
            raise GitHubAgentError("at least one reviewer or team reviewer is required")
        payload: dict[str, object] = {}
        if reviewers:
            payload["reviewers"] = reviewers
        if team_reviewers:
            payload["team_reviewers"] = team_reviewers
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/pulls/{number}/requested_reviewers",
            payload=payload,
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected reviewer request response")
        users = result.get("requested_reviewers")
        teams = result.get("requested_teams")
        return {
            "repository": repository,
            "number": number,
            "reviewers": [
                json_str(item.get("login"))
                for item in users
                if isinstance(item, dict)
            ]
            if isinstance(users, list)
            else [],
            "teams": [
                json_str(item.get("slug"))
                for item in teams
                if isinstance(item, dict)
            ]
            if isinstance(teams, list)
            else [],
        }

    def remove_requested_reviewers(
        self,
        repository: str,
        number: int,
        reviewers: list[str] | None = None,
        team_reviewers: list[str] | None = None,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        if not reviewers and not team_reviewers:
            raise GitHubAgentError("at least one reviewer or team reviewer is required")
        payload: dict[str, object] = {}
        if reviewers:
            payload["reviewers"] = reviewers
        if team_reviewers:
            payload["team_reviewers"] = team_reviewers
        self._repo_request(
            repository,
            "DELETE",
            f"/repos/{repository}/pulls/{number}/requested_reviewers",
            payload=payload,
        )
        return {"repository": repository, "number": number, "removed": True}

    def update_review_comment(
        self,
        repository: str,
        comment_id: int,
        body: str,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "PATCH",
            f"/repos/{repository}/pulls/comments/{comment_id}",
            payload={"body": body},
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected review comment update response")
        return {
            "repository": repository,
            "comment_id": json_int(result.get("id"), default=comment_id),
            "body": json_str(result.get("body")),
            "html_url": json_str(result.get("html_url")),
        }

    def reply_to_review_comment(
        self,
        repository: str,
        number: int,
        comment_id: int,
        body: str,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/pulls/{number}/comments/{comment_id}/replies",
            payload={"body": body},
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected review comment reply response")
        return {
            "repository": repository,
            "number": number,
            "comment_id": json_int(result.get("id")),
            "in_reply_to_id": json_int(result.get("in_reply_to_id"), default=comment_id),
            "html_url": json_str(result.get("html_url")),
        }

    def list_review_threads(
        self,
        repository: str,
        number: int,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        owner, name = repository.split("/", 1)
        query = """
        query PullReviewThreads($owner: String!, $name: String!, $number: Int!) {
          repository(owner: $owner, name: $name) {
            pullRequest(number: $number) {
              reviewThreads(first: 100) {
                nodes {
                  id
                  isResolved
                  isOutdated
                  path
                  line
                  startLine
                  comments(first: 100) {
                    nodes {
                      id
                      databaseId
                      body
                      author { login }
                      createdAt
                      url
                    }
                  }
                }
              }
            }
          }
        }
        """
        data = self._graphql(
            repository,
            query,
            {"owner": owner, "name": name, "number": number},
        )
        repo = data.get("repository")
        if not isinstance(repo, dict) or not isinstance(repo.get("pullRequest"), dict):
            raise GitHubAgentError("pull request was not found in GraphQL response")
        pull = repo["pullRequest"]
        review_threads = pull.get("reviewThreads")
        if not isinstance(review_threads, dict):
            raise GitHubAgentError("GraphQL response has no reviewThreads")
        nodes = review_threads.get("nodes")
        threads = []
        if isinstance(nodes, list):
            for thread in nodes:
                if not isinstance(thread, dict):
                    continue
                comments_data = thread.get("comments")
                comment_nodes = (
                    comments_data.get("nodes")
                    if isinstance(comments_data, dict)
                    else []
                )
                comments = []
                if isinstance(comment_nodes, list):
                    for comment in comment_nodes:
                        if not isinstance(comment, dict):
                            continue
                        author = (
                            comment.get("author")
                            if isinstance(comment.get("author"), dict)
                            else {}
                        )
                        comments.append(
                            {
                                "id": json_str(comment.get("id")),
                                "database_id": comment.get("databaseId"),
                                "author": json_str(author.get("login")),
                                "body": json_str(comment.get("body")),
                                "created_at": json_str(comment.get("createdAt")),
                                "url": json_str(comment.get("url")),
                            }
                        )
                threads.append(
                    {
                        "id": json_str(thread.get("id")),
                        "resolved": bool(thread.get("isResolved", False)),
                        "outdated": bool(thread.get("isOutdated", False)),
                        "path": json_str(thread.get("path")),
                        "line": thread.get("line"),
                        "start_line": thread.get("startLine"),
                        "comments": comments,
                    }
                )
        return {"repository": repository, "number": number, "threads": threads}

    def set_review_thread_resolved(
        self,
        repository: str,
        thread_id: str,
        resolved: bool,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        if resolved:
            field = "resolveReviewThread"
            input_type = "ResolveReviewThreadInput!"
        else:
            field = "unresolveReviewThread"
            input_type = "UnresolveReviewThreadInput!"
        mutation = f"""
        mutation ReviewThreadState($input: {input_type}) {{
          {field}(input: $input) {{
            thread {{ id isResolved }}
          }}
        }}
        """
        data = self._graphql(
            repository,
            mutation,
            {"input": {"threadId": thread_id}},
        )
        payload = data.get(field)
        if not isinstance(payload, dict) or not isinstance(payload.get("thread"), dict):
            raise GitHubAgentError("GraphQL review thread mutation returned no thread")
        thread = payload["thread"]
        return {
            "repository": repository,
            "thread_id": str(thread.get("id", thread_id)),
            "resolved": bool(thread.get("isResolved", False)),
        }

    def mark_pull_ready_for_review(
        self,
        repository: str,
        number: int,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        _, pull = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}",
        )
        if not isinstance(pull, dict):
            raise GitHubAgentError("unexpected pull request response")
        node_id = json_str(pull.get("node_id"))
        if not node_id:
            raise GitHubAgentError("pull request has no GraphQL node id")
        mutation = """
        mutation MarkReady($input: MarkPullRequestReadyForReviewInput!) {
          markPullRequestReadyForReview(input: $input) {
            pullRequest { number isDraft }
          }
        }
        """
        data = self._graphql(repository, mutation, {"input": {"pullRequestId": node_id}})
        payload = data.get("markPullRequestReadyForReview")
        if not isinstance(payload, dict) or not isinstance(payload.get("pullRequest"), dict):
            raise GitHubAgentError("GraphQL ready-for-review mutation returned no pull request")
        result = payload["pullRequest"]
        return {
            "repository": repository,
            "number": int(result.get("number", number)),
            "draft": bool(result.get("isDraft", False)),
        }
