from __future__ import annotations

import urllib.parse
from typing import Protocol, cast

from common.models import (
    JsonContainer,
    JsonObject,
    json_array,
    json_bool,
    json_int,
    json_member_array,
    json_member_object,
    json_object,
    json_str,
)

from .github_agent import GitHubAgentError
from .policy import protected_branches_from_env

_GITHUB_API = "https://api.github.com"


class _GitHubHistoryHost(Protocol):
    app_id: str

    def _assert_allowed(self, repository: str) -> str: ...

    def _app_jwt(self) -> str: ...

    def _installation_id(self, repository: str) -> int: ...

    def _request(
        self,
        method: str,
        url: str,
        *,
        token: str | None = None,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, JsonContainer]: ...

    def _repo_request(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, JsonContainer]: ...

    def _assert_branch_mutation_allowed(self, repository: str, branch: str) -> str: ...


class GitHubHistoryMixin:
    """Identity-aware history and branch-policy operations for GitHub App clients."""

    app_id: str

    def _history_host(self) -> _GitHubHistoryHost:
        return cast(_GitHubHistoryHost, self)

    def _agent_app_identity(self) -> JsonObject:
        _, app = self._history_host()._request(
            "GET",
            f"{_GITHUB_API}/app",
            token=self._history_host()._app_jwt(),
        )
        if not isinstance(app, dict):
            raise GitHubAgentError("unexpected GitHub App response")
        slug = json_str(app.get("slug"))
        if not slug:
            raise GitHubAgentError("GitHub App response has no slug")

        login = f"{slug}[bot]"
        _, bot = self._history_host()._request(
            "GET",
            f"{_GITHUB_API}/users/{urllib.parse.quote(login, safe='')}",
        )
        if not isinstance(bot, dict):
            raise GitHubAgentError("unable to resolve GitHub App bot identity")
        try:
            bot_id = json_int(bot.get("id"), field="bot.id")
        except ValueError as exc:
            raise GitHubAgentError("unable to resolve GitHub App bot identity") from exc
        return {
            "source": "current_agent_app",
            "app_id": self.app_id,
            "slug": slug,
            "login": login,
            "id": bot_id,
            "name": login,
            "email": f"{bot_id}+{login}@users.noreply.github.com",
        }

    def _installation_permissions(self, repository: str) -> dict[str, str]:
        installation_id = self._history_host()._installation_id(repository)
        _, token_payload = self._history_host()._request(
            "POST",
            f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens",
            token=self._history_host()._app_jwt(),
        )
        if not isinstance(token_payload, dict):
            raise GitHubAgentError("unexpected installation token response")
        permissions = json_member_object(token_payload, "permissions")
        return {key: json_str(value) for key, value in permissions.items()}

    def capabilities(
        self,
        repository: str,
        *,
        reviewer_available: bool = False,
    ) -> JsonObject:
        repository = self._history_host()._assert_allowed(repository)
        _, repo = self._history_host()._repo_request(
            repository,
            "GET",
            f"/repos/{repository}",
        )
        if not isinstance(repo, dict):
            raise GitHubAgentError("unexpected repository response")

        permissions = self._installation_permissions(repository)
        contents_write = permissions.get("contents") == "write"
        return {
            "repository": repository,
            "allowed_repository": True,
            "app_id": self.app_id,
            "installation_id": self._history_host()._installation_id(repository),
            "agent_identity": self._agent_app_identity(),
            "repository_metadata": {
                "default_branch": json_str(repo.get("default_branch")),
                "fork": json_bool(repo.get("fork")),
                "archived": json_bool(repo.get("archived")),
            },
            "permissions": {
                "contents": permissions.get("contents", "none"),
                "workflows": permissions.get("workflows", "none"),
                "pull_requests": permissions.get("pull_requests", "none"),
                "issues": permissions.get("issues", "none"),
                "actions": permissions.get("actions", "none"),
                "checks": permissions.get("checks", "none"),
            },
            "capabilities": {
                "branch_delete": contents_write,
                "force_ref_update": contents_write,
                "history_identity_rewrite": contents_write,
            },
            "bridge_policy": {
                "reserved_branches": json_array(
                    sorted(protected_branches_from_env()),
                    context="GitHub reserved branches",
                ),
                "reserved_branch_mutation_allowed": False,
            },
            "reviewer_available": reviewer_available,
        }

    def _git_commit_object(self, repository: str, sha: str) -> JsonObject:
        _, result = self._history_host()._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/commits/{urllib.parse.quote(sha, safe='')}",
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected git commit response")
        return result

    @staticmethod
    def _identity_matches(commit: JsonObject, name: str, email: str) -> bool:
        author = json_member_object(commit, "author")
        committer = json_member_object(commit, "committer")
        return (
            json_str(author.get("name")) == name
            and json_str(author.get("email")) == email
            and json_str(committer.get("name")) == name
            and json_str(committer.get("email")) == email
        )

    def rewrite_branch_identity(
        self,
        repository: str,
        branch: str,
        expected_head_sha: str,
        *,
        identity_source: str = "current_agent_app",
        preserve_messages: bool = True,
        preserve_trees: bool = True,
        preserve_author_dates: bool = True,
        base_sha: str | None = None,
        max_commits: int = 100,
        dry_run: bool = True,
    ) -> JsonObject:
        repository = self._history_host()._assert_allowed(repository)
        branch = self._history_host()._assert_branch_mutation_allowed(repository, branch)
        if identity_source != "current_agent_app":
            raise GitHubAgentError("identity_source must be current_agent_app")
        if not expected_head_sha.strip():
            raise GitHubAgentError("expected_head_sha is required")
        if not preserve_messages or not preserve_trees:
            raise GitHubAgentError(
                "identity rewrite is identity-only; preserve_messages and "
                "preserve_trees must be true"
            )

        max_commits = max(1, min(max_commits, 500))
        branch_q = urllib.parse.quote(branch, safe="")
        _, ref = self._history_host()._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_q}",
        )
        if not isinstance(ref, dict):
            raise GitHubAgentError("unable to resolve branch head")
        old_head = json_str(
            json_member_object(ref, "object", required=True).get("sha")
        )
        if old_head != expected_head_sha:
            raise GitHubAgentError(
                f"branch head changed: expected {expected_head_sha}, found {old_head}"
            )

        chain_newest_first: list[JsonObject] = []
        current = old_head
        reached_base = base_sha is None
        for _ in range(max_commits):
            if base_sha is not None and current == base_sha:
                reached_base = True
                break
            commit = self._git_commit_object(repository, current)
            parents = json_member_array(commit, "parents")
            if len(parents) > 1:
                raise GitHubAgentError(
                    f"history rewrite supports linear history only; merge commit found: {current}"
                )
            chain_newest_first.append(commit)
            if not parents:
                reached_base = base_sha is None
                break
            parent = json_object(parents[0], context="GitHub commit parent")
            current = json_str(parent.get("sha"))
            if not current:
                raise GitHubAgentError("git commit parent has no sha")
        else:
            raise GitHubAgentError(
                f"rewrite range exceeds max_commits={max_commits}; "
                "provide base_sha or raise the limit"
            )

        if base_sha is not None and not reached_base:
            raise GitHubAgentError("base_sha is not a first-parent ancestor of branch head")
        if not chain_newest_first:
            raise GitHubAgentError("rewrite range contains no commits")

        chain = list(reversed(chain_newest_first))
        identity = self._agent_app_identity()
        git_name = str(identity["name"])
        git_email = str(identity["email"])
        parent_sha = base_sha
        mapping: dict[str, str] = {}
        plan: list[JsonObject] = []

        for original in chain:
            old_sha = json_str(original.get("sha"))
            tree = json_member_object(original, "tree", required=True)
            tree_sha = json_str(tree.get("sha"))
            message = json_str(original.get("message"))
            author = json_member_object(original, "author")
            committer = json_member_object(original, "committer")

            author_payload: JsonObject = {
                "name": git_name,
                "email": git_email,
            }
            committer_payload: JsonObject = {
                "name": git_name,
                "email": git_email,
            }
            if preserve_author_dates:
                author_date = json_str(author.get("date"))
                committer_date = json_str(committer.get("date"))
                if author_date:
                    author_payload["date"] = author_date
                if committer_date:
                    committer_payload["date"] = committer_date

            payload: JsonObject = {
                "message": message,
                "tree": tree_sha,
                "parents": [parent_sha] if parent_sha else [],
                "author": author_payload,
                "committer": committer_payload,
            }
            _, created = self._history_host()._repo_request(
                repository,
                "POST",
                f"/repos/{repository}/git/commits",
                payload=payload,
            )
            if not isinstance(created, dict):
                raise GitHubAgentError("GitHub did not return rewritten commit sha")
            new_sha = json_str(created.get("sha"))
            if not new_sha:
                raise GitHubAgentError("GitHub did not return rewritten commit sha")

            created_tree = json_member_object(created, "tree", required=True)
            if json_str(created_tree.get("sha")) != tree_sha:
                raise GitHubAgentError(
                    f"rewritten commit tree mismatch for {old_sha}: "
                    f"expected {tree_sha}, found {json_str(created_tree.get('sha'))}"
                )
            if json_str(created.get("message")) != message:
                raise GitHubAgentError(f"rewritten commit message mismatch for {old_sha}")
            if not self._identity_matches(created, git_name, git_email):
                raise GitHubAgentError(
                    f"rewritten commit identity mismatch for {old_sha}"
                )

            mapping[old_sha] = new_sha
            plan.append(
                {
                    "old_sha": old_sha,
                    "new_sha": new_sha,
                    "tree_sha": tree_sha,
                    "message": message,
                    "old_author_date": json_str(author.get("date")),
                    "old_committer_date": json_str(committer.get("date")),
                    "new_parent_sha": parent_sha,
                }
            )
            parent_sha = new_sha

        if len(mapping) != len(chain):
            raise GitHubAgentError("rewritten commit count does not match source commit count")

        new_head = parent_sha or ""
        old_head_tree_obj = json_member_object(
            chain_newest_first[0],
            "tree",
            required=True,
        )
        old_head_tree = json_str(old_head_tree_obj.get("sha"))
        new_head_commit = self._git_commit_object(repository, new_head)
        new_head_tree_obj = json_member_object(
            new_head_commit,
            "tree",
            required=True,
        )
        new_head_tree = json_str(new_head_tree_obj.get("sha"))
        if not old_head_tree or new_head_tree != old_head_tree:
            raise GitHubAgentError(
                f"final tree mismatch: expected {old_head_tree}, found {new_head_tree}"
            )

        result: JsonObject = {
            "repository": repository,
            "branch": branch,
            "dry_run": dry_run,
            "dry_run_creates_unreferenced_commit_objects": dry_run,
            "identity_source": identity_source,
            "identity": identity,
            "old_head_sha": old_head,
            "new_head_sha": new_head,
            "base_sha": base_sha,
            "commit_count": len(chain),
            "preserve_messages": preserve_messages,
            "preserve_trees": preserve_trees,
            "preserve_author_dates": preserve_author_dates,
            "final_tree_sha": new_head_tree,
            "mapping": json_object(mapping, context="GitHub history rewrite mapping"),
            "plan": json_array(plan, context="GitHub history rewrite plan"),
            "old_shas_reachable_from_new_head": False,
            "ref_updated": False,
        }
        if dry_run:
            return result

        _, ref_before_update = self._history_host()._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_q}",
        )
        if not isinstance(ref_before_update, dict):
            raise GitHubAgentError("unable to re-check branch head before rewrite")
        current_head = json_str(
            json_member_object(
                ref_before_update,
                "object",
                required=True,
            ).get("sha")
        )
        if current_head != expected_head_sha:
            raise GitHubAgentError(
                "branch head changed during rewrite: "
                f"expected {expected_head_sha}, found {current_head}"
            )

        self._history_host()._repo_request(
            repository,
            "PATCH",
            f"/repos/{repository}/git/refs/heads/{branch_q}",
            payload={"sha": new_head, "force": True},
        )
        result["ref_updated"] = True
        return result
