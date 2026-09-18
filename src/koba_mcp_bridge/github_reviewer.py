from __future__ import annotations

import base64
import os
from functools import lru_cache

from .github_agent import GitHubAgentError
from .github_identity import GitHubPrettyIdentityClient
from .github_workflow import protected_branches_from_env


def github_reviewer_configured() -> bool:
    return bool(
        os.getenv("GITHUB_REVIEWER_APP_ID", "").strip()
        and (
            os.getenv("GITHUB_REVIEWER_PRIVATE_KEY", "").strip()
            or os.getenv("GITHUB_REVIEWER_PRIVATE_KEY_B64", "").strip()
        )
    )


def _reviewer_private_key_from_env() -> str:
    raw = os.getenv("GITHUB_REVIEWER_PRIVATE_KEY", "").strip()
    if raw:
        return raw.replace("\\n", "\n")

    encoded = os.getenv("GITHUB_REVIEWER_PRIVATE_KEY_B64", "").strip()
    if encoded:
        try:
            return base64.b64decode(encoded).decode("utf-8")
        except Exception as exc:  # pragma: no cover - defensive configuration path
            raise GitHubAgentError(
                "GITHUB_REVIEWER_PRIVATE_KEY_B64 is not valid base64 UTF-8"
            ) from exc

    raise GitHubAgentError("GitHub reviewer private key is not configured")


class GitHubReviewerClient(GitHubPrettyIdentityClient):
    """Independent reviewer identity with one narrowly-scoped protected mutation."""

    def _assert_self_approval_current_head(
        self,
        repository: str,
        number: int,
        head_sha: str,
    ) -> dict[str, object]:
        login = str(self._app_identity()["login"]).casefold()
        _, raw = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}/reviews?per_page=100",
        )
        if not isinstance(raw, list):
            raise GitHubAgentError("unexpected pull request review response")

        state = "MISSING"
        review_sha = ""
        for item in raw:
            if not isinstance(item, dict):
                continue
            user = item.get("user") if isinstance(item.get("user"), dict) else {}
            if str(user.get("login", "")).casefold() != login:
                continue
            candidate = str(item.get("state", "")).upper()
            if candidate not in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
                continue
            state = candidate
            review_sha = str(item.get("commit_id", ""))

        if state != "APPROVED":
            raise GitHubAgentError(
                f"reviewer must APPROVE before protected merge; reviewer={login}, state={state}"
            )
        if review_sha != head_sha:
            raise GitHubAgentError(
                "reviewer approval is stale; "
                f"reviewed={review_sha or 'unknown'}, current_head={head_sha}"
            )
        return {
            "reviewer": login,
            "state": state,
            "reviewed_head_sha": review_sha,
        }

    def _assert_no_unresolved_threads(
        self,
        repository: str,
        number: int,
    ) -> dict[str, object]:
        result = self.list_review_threads(repository, number)
        raw = result.get("threads")
        threads = raw if isinstance(raw, list) else []
        unresolved = [
            thread
            for thread in threads
            if isinstance(thread, dict)
            and not bool(thread.get("resolved", False))
            and not bool(thread.get("outdated", False))
        ]
        if unresolved:
            ids = [str(thread.get("id", "")) for thread in unresolved[:20]]
            raise GitHubAgentError(
                f"unresolved review threads block protected merge: {ids}"
            )
        return {"unresolved_threads": 0}

    def merge_protected_pull_request(
        self,
        repository: str,
        number: int,
        merge_method: str = "squash",
        commit_title: str | None = None,
        commit_message: str | None = None,
    ) -> dict[str, object]:
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
        if str(pull.get("state", "")).casefold() != "open":
            raise GitHubAgentError("protected merge requires an open pull request")
        if bool(pull.get("draft", False)):
            raise GitHubAgentError("draft pull request cannot be merged")

        head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
        base = pull.get("base") if isinstance(pull.get("base"), dict) else {}
        head_repo = head.get("repo") if isinstance(head.get("repo"), dict) else {}
        base_repo = base.get("repo") if isinstance(base.get("repo"), dict) else {}
        if str(head_repo.get("full_name", "")).casefold() != repository.casefold():
            raise GitHubAgentError("cross-repository protected merge is disabled")
        if str(base_repo.get("full_name", "")).casefold() != repository.casefold():
            raise GitHubAgentError("cross-repository protected merge is disabled")

        base_ref = str(base.get("ref", ""))
        if base_ref.casefold() not in protected_branches_from_env():
            raise GitHubAgentError(
                f"reviewer merge is reserved for protected branches: {base_ref}"
            )
        head_sha = str(head.get("sha", ""))
        if not head_sha:
            raise GitHubAgentError("pull request head has no sha")

        checks = self.assert_required_checks(repository, head_sha)
        approval = self._assert_self_approval_current_head(repository, number, head_sha)
        threads = self._assert_no_unresolved_threads(repository, number)

        payload: dict[str, object] = {
            "merge_method": merge_method,
            "sha": head_sha,
        }
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
        if not bool(result.get("merged", False)):
            raise GitHubAgentError(
                f"GitHub refused protected merge: {result.get('message', 'unknown reason')}"
            )
        return {
            "repository": repository,
            "number": number,
            "base": base_ref,
            "head_sha": head_sha,
            "merged": True,
            "sha": str(result.get("sha", "")),
            "message": str(result.get("message", "")),
            "merge_method": merge_method,
            "checks": checks,
            "approval": approval,
            "review_threads": threads,
        }


@lru_cache(maxsize=1)
def github_reviewer_client_from_env() -> GitHubReviewerClient:
    app_id = os.getenv("GITHUB_REVIEWER_APP_ID", "").strip()
    if not app_id:
        raise GitHubAgentError("GITHUB_REVIEWER_APP_ID is not configured")
    return GitHubReviewerClient(
        app_id=app_id,
        private_key=_reviewer_private_key_from_env(),
    )
