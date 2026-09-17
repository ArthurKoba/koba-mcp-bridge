from __future__ import annotations

import urllib.parse

from .github_agent import GitHubAgentError
from .github_workflow import protected_branches_from_env

_GITHUB_API = "https://api.github.com"


def _actor(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        return {"login": None, "id": None, "type": None}
    return {
        "login": str(item.get("login", "")) or None,
        "id": item.get("id"),
        "type": str(item.get("type", "")) or None,
    }


def _git_identity(item: object, actor: object) -> dict[str, object]:
    data = item if isinstance(item, dict) else {}
    result = {
        "name": str(data.get("name", "")),
        "email": str(data.get("email", "")),
        "date": str(data.get("date", "")),
    }
    result.update(_actor(actor))
    return result


def _verification(item: object, *, include_material: bool) -> dict[str, object]:
    data = item if isinstance(item, dict) else {}
    result: dict[str, object] = {
        "verified": bool(data.get("verified", False)),
        "reason": str(data.get("reason", "")),
        "verified_at": data.get("verified_at"),
        "signature_present": bool(data.get("signature")),
        "payload_present": bool(data.get("payload")),
    }
    if include_material:
        result["signature"] = data.get("signature")
        result["payload"] = data.get("payload")
    return result


class GitHubHistoryMixin:
    """Identity-aware history and branch-policy operations for GitHub App clients."""

    app_id: str

    def _branch_policy(self, repository: str, branch: str) -> dict[str, object]:
        repository = self._assert_allowed(repository)  # type: ignore[attr-defined]
        branch = branch.strip()
        if not branch:
            raise GitHubAgentError("branch must not be empty")
        status, result = self._repo_request(  # type: ignore[attr-defined]
            repository,
            "GET",
            f"/repos/{repository}/branches/{urllib.parse.quote(branch, safe='')}",
            allowed_errors={404},
        )
        github_protected = False
        exists = status != 404
        if exists:
            if not isinstance(result, dict):
                raise GitHubAgentError("unexpected branch response")
            github_protected = bool(result.get("protected", False))
        bridge_reserved = branch.casefold() in protected_branches_from_env()
        denial_reason: str | None = None
        if bridge_reserved:
            denial_reason = "branch is reserved by bridge mutation policy"
        elif github_protected:
            denial_reason = "branch is protected by GitHub"
        return {
            "repository": repository,
            "branch": branch,
            "exists": exists,
            "github_protected": github_protected,
            "bridge_reserved": bridge_reserved,
            "mutation_allowed": denial_reason is None,
            "mutation_denial_reason": denial_reason,
        }

    def _assert_branch_mutation_allowed(self, repository: str, branch: str) -> str:
        policy = self._branch_policy(repository, branch)
        reason = policy["mutation_denial_reason"]
        if reason:
            raise GitHubAgentError(f"{reason}: {branch}")
        return branch.strip()

    def list_branches(self, repository: str) -> dict[str, object]:
        repository = self._assert_allowed(repository)  # type: ignore[attr-defined]
        _, result = self._repo_request(  # type: ignore[attr-defined]
            repository,
            "GET",
            f"/repos/{repository}/branches?per_page=100",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected branch list response")
        reserved = protected_branches_from_env()
        branches = []
        for item in result:
            if not isinstance(item, dict):
                continue
            commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
            name = str(item.get("name", ""))
            github_protected = bool(item.get("protected", False))
            bridge_reserved = name.casefold() in reserved
            reason = None
            if bridge_reserved:
                reason = "branch is reserved by bridge mutation policy"
            elif github_protected:
                reason = "branch is protected by GitHub"
            branches.append(
                {
                    "name": name,
                    "sha": str(commit.get("sha", "")),
                    "protected": github_protected,
                    "github_protected": github_protected,
                    "bridge_reserved": bridge_reserved,
                    "mutation_allowed": reason is None,
                    "mutation_denial_reason": reason,
                }
            )
        return {"repository": repository, "branches": branches}

    def list_commits(
        self,
        repository: str,
        ref: str | None = None,
        path: str | None = None,
        per_page: int = 50,
        page: int = 1,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)  # type: ignore[attr-defined]
        params: dict[str, str | int] = {
            "per_page": max(1, min(per_page, 100)),
            "page": max(1, page),
        }
        if ref:
            params["sha"] = ref
        if path:
            params["path"] = path
        query = urllib.parse.urlencode(params)
        _, result = self._repo_request(  # type: ignore[attr-defined]
            repository,
            "GET",
            f"/repos/{repository}/commits?{query}",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected commit list response")
        commits = []
        for item in result:
            if not isinstance(item, dict):
                continue
            details = item.get("commit") if isinstance(item.get("commit"), dict) else {}
            commits.append(
                {
                    "sha": str(item.get("sha", "")),
                    "message": str(details.get("message", "")),
                    "author": _git_identity(details.get("author"), item.get("author")),
                    "committer": _git_identity(details.get("committer"), item.get("committer")),
                    "verification": _verification(details.get("verification"), include_material=False),
                    "parents": [
                        str(parent.get("sha", ""))
                        for parent in item.get("parents", [])
                        if isinstance(parent, dict)
                    ],
                }
            )
        return {"repository": repository, "commits": commits, "page": page}

    def get_commit(self, repository: str, ref: str) -> dict[str, object]:
        repository = self._assert_allowed(repository)  # type: ignore[attr-defined]
        _, result = self._repo_request(  # type: ignore[attr-defined]
            repository,
            "GET",
            f"/repos/{repository}/commits/{urllib.parse.quote(ref, safe='')}",
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected commit response")
        details = result.get("commit") if isinstance(result.get("commit"), dict) else {}
        tree = details.get("tree") if isinstance(details.get("tree"), dict) else {}
        files = result.get("files") if isinstance(result.get("files"), list) else []
        return {
            "repository": repository,
            "sha": str(result.get("sha", "")),
            "message": str(details.get("message", "")),
            "tree_sha": str(tree.get("sha", "")),
            "author": _git_identity(details.get("author"), result.get("author")),
            "committer": _git_identity(details.get("committer"), result.get("committer")),
            "verification": _verification(details.get("verification"), include_material=True),
            "parents": [
                str(item.get("sha", ""))
                for item in result.get("parents", [])
                if isinstance(item, dict)
            ],
            "files": [
                {
                    "filename": str(item.get("filename", "")),
                    "status": str(item.get("status", "")),
                    "additions": int(item.get("additions", 0)),
                    "deletions": int(item.get("deletions", 0)),
                    "patch": item.get("patch"),
                }
                for item in files
                if isinstance(item, dict)
            ],
        }

    def delete_branch(self, repository: str, branch: str) -> dict[str, object]:
        repository = self._assert_allowed(repository)  # type: ignore[attr-defined]
        branch = self._assert_branch_mutation_allowed(repository, branch)
        self._repo_request(  # type: ignore[attr-defined]
            repository,
            "DELETE",
            f"/repos/{repository}/git/refs/heads/{urllib.parse.quote(branch, safe='')}",
        )
        return {"repository": repository, "branch": branch, "deleted": True}

    def _agent_app_identity(self) -> dict[str, object]:
        _, app = self._request(  # type: ignore[attr-defined]
            "GET",
            f"{_GITHUB_API}/app",
            token=self._app_jwt(),  # type: ignore[attr-defined]
        )
        if not isinstance(app, dict):
            raise GitHubAgentError("unexpected GitHub App response")
        slug = str(app.get("slug", ""))
        if not slug:
            raise GitHubAgentError("GitHub App response has no slug")
        login = f"{slug}[bot]"
        _, bot = self._request(  # type: ignore[attr-defined]
            "GET",
            f"{_GITHUB_API}/users/{urllib.parse.quote(login, safe='')}",
            token=self._app_jwt(),  # type: ignore[attr-defined]
        )
        if not isinstance(bot, dict) or not isinstance(bot.get("id"), int):
            raise GitHubAgentError("unable to resolve GitHub App bot identity")
        bot_id = int(bot["id"])
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
        installation_id = self._installation_id(repository)  # type: ignore[attr-defined]
        _, token_payload = self._request(  # type: ignore[attr-defined]
            "POST",
            f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens",
            token=self._app_jwt(),  # type: ignore[attr-defined]
        )
        if not isinstance(token_payload, dict):
            raise GitHubAgentError("unexpected installation token response")
        permissions = token_payload.get("permissions")
        if not isinstance(permissions, dict):
            return {}
        return {str(key): str(value) for key, value in permissions.items()}

    def capabilities(
        self,
        repository: str,
        *,
        reviewer_available: bool = False,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)  # type: ignore[attr-defined]
        _, repo = self._repo_request(  # type: ignore[attr-defined]
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
            "installation_id": self._installation_id(repository),  # type: ignore[attr-defined]
            "agent_identity": self._agent_app_identity(),
            "repository_metadata": {
                "default_branch": str(repo.get("default_branch", "")),
                "fork": bool(repo.get("fork", False)),
                "archived": bool(repo.get("archived", False)),
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
                "reserved_branches": sorted(protected_branches_from_env()),
                "reserved_branch_mutation_allowed": False,
            },
            "reviewer_available": reviewer_available,
        }

    def _git_commit_object(self, repository: str, sha: str) -> dict[str, object]:
        _, result = self._repo_request(  # type: ignore[attr-defined]
            repository,
            "GET",
            f"/repos/{repository}/git/commits/{urllib.parse.quote(sha, safe='')}",
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected git commit response")
        return result

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
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)  # type: ignore[attr-defined]
        branch = self._assert_branch_mutation_allowed(repository, branch)
        if identity_source != "current_agent_app":
            raise GitHubAgentError("identity_source must be current_agent_app")
        if not expected_head_sha.strip():
            raise GitHubAgentError("expected_head_sha is required")
        if not preserve_messages or not preserve_trees:
            raise GitHubAgentError(
                "identity rewrite is identity-only; preserve_messages and preserve_trees must be true"
            )
        max_commits = max(1, min(max_commits, 500))
        branch_q = urllib.parse.quote(branch, safe="")
        _, ref = self._repo_request(  # type: ignore[attr-defined]
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_q}",
        )
        if not isinstance(ref, dict) or not isinstance(ref.get("object"), dict):
            raise GitHubAgentError("unable to resolve branch head")
        old_head = str(ref["object"].get("sha", ""))
        if old_head != expected_head_sha:
            raise GitHubAgentError(
                f"branch head changed: expected {expected_head_sha}, found {old_head}"
            )

        chain_newest_first: list[dict[str, object]] = []
        current = old_head
        reached_base = base_sha is None
        for _ in range(max_commits):
            if base_sha is not None and current == base_sha:
                reached_base = True
                break
            commit = self._git_commit_object(repository, current)
            parents = commit.get("parents") if isinstance(commit.get("parents"), list) else []
            if len(parents) > 1:
                raise GitHubAgentError(
                    f"history rewrite supports linear history only; merge commit found: {current}"
                )
            chain_newest_first.append(commit)
            if not parents:
                reached_base = base_sha is None
                break
            parent = parents[0] if isinstance(parents[0], dict) else {}
            current = str(parent.get("sha", ""))
            if not current:
                raise GitHubAgentError("git commit parent has no sha")
        else:
            raise GitHubAgentError(
                f"rewrite range exceeds max_commits={max_commits}; provide base_sha or raise the limit"
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
        planned: list[dict[str, object]] = []

        for original in chain:
            old_sha = str(original.get("sha", ""))
            tree = original.get("tree") if isinstance(original.get("tree"), dict) else {}
            tree_sha = str(tree.get("sha", ""))
            message = str(original.get("message", ""))
            author = original.get("author") if isinstance(original.get("author"), dict) else {}
            planned.append(
                {
                    "old_sha": old_sha,
                    "tree_sha": tree_sha,
                    "message": message,
                    "old_author_date": str(author.get("date", "")),
                    "new_parent_sha": parent_sha,
                }
            )
            if dry_run:
                parent_sha = f"<rewritten:{old_sha}>"
                continue

            author_payload: dict[str, object] = {"name": git_name, "email": git_email}
            committer_payload: dict[str, object] = {"name": git_name, "email": git_email}
            if preserve_author_dates and author.get("date"):
                author_payload["date"] = str(author["date"])
            payload: dict[str, object] = {
                "message": message,
                "tree": tree_sha,
                "parents": [parent_sha] if parent_sha else [],
                "author": author_payload,
                "committer": committer_payload,
            }
            _, created = self._repo_request(  # type: ignore[attr-defined]
                repository,
                "POST",
                f"/repos/{repository}/git/commits",
                payload=payload,
            )
            if not isinstance(created, dict) or not created.get("sha"):
                raise GitHubAgentError("GitHub did not return rewritten commit sha")
            created_tree = created.get("tree") if isinstance(created.get("tree"), dict) else {}
            if str(created_tree.get("sha", "")) != tree_sha:
                raise GitHubAgentError(
                    f"rewritten commit tree mismatch for {old_sha}: "
                    f"expected {tree_sha}, found {created_tree.get('sha', '')}"
                )
            new_sha = str(created["sha"])
            mapping[old_sha] = new_sha
            parent_sha = new_sha

        result: dict[str, object] = {
            "repository": repository,
            "branch": branch,
            "dry_run": dry_run,
            "identity_source": identity_source,
            "identity": identity,
            "old_head_sha": old_head,
            "base_sha": base_sha,
            "commit_count": len(chain),
            "preserve_messages": preserve_messages,
            "preserve_trees": preserve_trees,
            "preserve_author_dates": preserve_author_dates,
            "plan": planned,
            "mapping": mapping,
        }
        if dry_run:
            result["new_head_sha"] = None
            result["ref_updated"] = False
            return result

        if len(mapping) != len(chain):
            raise GitHubAgentError("rewritten commit count does not match source commit count")
        new_head = parent_sha or ""
        old_head_tree_obj = (
            chain_newest_first[0].get("tree")
            if isinstance(chain_newest_first[0].get("tree"), dict)
            else {}
        )
        old_head_tree = str(old_head_tree_obj.get("sha", ""))
        new_head_commit = self._git_commit_object(repository, new_head)
        new_head_tree_obj = (
            new_head_commit.get("tree") if isinstance(new_head_commit.get("tree"), dict) else {}
        )
        new_head_tree = str(new_head_tree_obj.get("sha", ""))
        if not old_head_tree or new_head_tree != old_head_tree:
            raise GitHubAgentError(
                f"final tree mismatch: expected {old_head_tree}, found {new_head_tree}"
            )

        _, ref_before_update = self._repo_request(  # type: ignore[attr-defined]
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_q}",
        )
        if not isinstance(ref_before_update, dict) or not isinstance(
            ref_before_update.get("object"), dict
        ):
            raise GitHubAgentError("unable to re-check branch head before rewrite")
        current_head = str(ref_before_update["object"].get("sha", ""))
        if current_head != expected_head_sha:
            raise GitHubAgentError(
                f"branch head changed during rewrite: expected {expected_head_sha}, found {current_head}"
            )

        self._repo_request(  # type: ignore[attr-defined]
            repository,
            "PATCH",
            f"/repos/{repository}/git/refs/heads/{branch_q}",
            payload={"sha": new_head, "force": True},
        )
        result["new_head_sha"] = new_head
        result["final_tree_sha"] = new_head_tree
        result["ref_updated"] = True
        return result
