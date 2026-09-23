from __future__ import annotations

import base64
import hashlib
import urllib.error
import urllib.parse
import urllib.request

from common.models import (
    JsonObject,
    json_bool,
    json_int,
    json_member_array,
    json_member_object,
    json_str,
)

from .github_agent import GitHubAgentError
from .github_collab import GitHubCollabClient, required_reviewer_logins_from_env
from .github_history import GitHubHistoryMixin
from .github_workflow import protected_branches_from_env

_GITHUB_API = "https://api.github.com"
_MAX_LOG_BYTES = 8 * 1024 * 1024
_MAX_WORKFLOW_FILE_BYTES = 8 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        del req, fp, code, msg, headers, newurl
        return None


class GitHubActionsClient(GitHubHistoryMixin, GitHubCollabClient):
    """Adds GitHub Actions diagnostics and controlled run mutations."""

    def assert_required_reviews(
        self,
        repository: str,
        number: int,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        required = required_reviewer_logins_from_env()
        if not required:
            return {
                "repository": repository,
                "number": number,
                "required_reviewers": [],
                "status": "not_configured",
            }

        _, pull = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}",
        )
        if not isinstance(pull, dict):
            raise GitHubAgentError("unexpected pull request response")
        head = json_member_object(pull, "head")
        head_sha = json_str(head.get("sha"))
        if not head_sha:
            raise GitHubAgentError("pull request head has no sha")

        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}/reviews?per_page=100",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected pull request review response")

        decisive_state: dict[str, tuple[str, str]] = {}
        for item in result:
            if not isinstance(item, dict):
                continue
            user = json_member_object(item, "user")
            login = json_str(user.get("login")).casefold()
            state = json_str(item.get("state")).upper()
            commit_id = json_str(item.get("commit_id"))
            if login and state in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
                decisive_state[login] = (state, commit_id)

        missing = []
        states: dict[str, str] = {}
        for login in required:
            state, review_sha = decisive_state.get(login, ("MISSING", ""))
            if state == "APPROVED" and review_sha == head_sha:
                states[login] = f"APPROVED@{review_sha}"
                continue
            if state == "APPROVED" and review_sha:
                states[login] = f"STALE_APPROVAL@{review_sha}"
            else:
                states[login] = state
            missing.append(login)

        if missing:
            raise GitHubAgentError(
                "required independent reviews not satisfied for current PR head; "
                f"head={head_sha}, missing={missing}, states={states}"
            )
        return {
            "repository": repository,
            "number": number,
            "head_sha": head_sha,
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
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        _, pull = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}",
        )
        if not isinstance(pull, dict):
            raise GitHubAgentError("unexpected pull request response")
        base = json_member_object(pull, "base")
        base_ref = json_str(base.get("ref"))
        if not base_ref:
            raise GitHubAgentError("pull request base has no ref")
        if base_ref.casefold() in protected_branches_from_env():
            raise GitHubAgentError(
                f"protected branch merge requires administrator: {base_ref}"
            )
        return super().merge_pull_request(
            repository,
            number,
            merge_method,
            commit_title,
            commit_message,
        )

    def _download_redirect_bytes(
        self,
        repository: str,
        endpoint: str,
        max_bytes: int,
    ) -> bytes:
        repository = self._assert_allowed(repository)
        max_bytes = max(1, min(max_bytes, 16 * 1024 * 1024))
        token = self._installation_token(repository)
        request = urllib.request.Request(
            f"{_GITHUB_API}{endpoint}",
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "mcp-bridge",
                "X-GitHub-Api-Version": "2026-03-10",
            },
        )
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            response = opener.open(request, timeout=30)
        except urllib.error.HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308}:
                detail = exc.read(4096).decode("utf-8", "replace")
                raise GitHubAgentError(
                    f"GitHub download endpoint returned HTTP {exc.code}: {detail}"
                ) from exc
            location = exc.headers.get("Location", "")
            if not location:
                raise GitHubAgentError("GitHub download redirect has no Location header") from exc
            parsed = urllib.parse.urlparse(location)
            if parsed.scheme != "https" or not parsed.netloc:
                raise GitHubAgentError("GitHub download redirect is not a valid HTTPS URL") from exc
            redirected = urllib.request.Request(
                location,
                method="GET",
                headers={"User-Agent": "mcp-bridge"},
            )
            try:
                response = urllib.request.urlopen(redirected, timeout=60)
            except urllib.error.URLError as redirect_exc:
                raise GitHubAgentError(
                    f"GitHub redirected download failed: {redirect_exc.reason}"
                ) from redirect_exc
        except urllib.error.URLError as exc:
            raise GitHubAgentError(f"GitHub download transport error: {exc.reason}") from exc

        with response:
            data = bytes(response.read(max_bytes + 1))
        if len(data) > max_bytes:
            raise GitHubAgentError(
                f"download exceeds MCP safety limit of {max_bytes} bytes"
            )
        return data

    def get_workflow_job_log(
        self,
        repository: str,
        job_id: int,
        max_chars: int = 100_000,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        max_chars = max(1, min(max_chars, 500_000))
        data = self._download_redirect_bytes(
            repository,
            f"/repos/{repository}/actions/jobs/{job_id}/logs",
            _MAX_LOG_BYTES,
        )
        text = data.decode("utf-8", "replace")
        truncated = len(text) > max_chars
        if truncated:
            text = text[-max_chars:]
        return {
            "repository": repository,
            "job_id": job_id,
            "log": text,
            "tail_chars": max_chars,
            "truncated": truncated,
            "downloaded_bytes": len(data),
        }

    def list_workflow_files(
        self,
        repository: str,
        run_id: int,
        per_page: int = 100,
        page: int = 1,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        query = urllib.parse.urlencode(
            {
                "per_page": max(1, min(per_page, 100)),
                "page": max(1, page),
            }
        )
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/actions/runs/{run_id}/artifacts?{query}",
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected workflow file response")
        raw = json_member_array(result, "artifacts")
        files = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            files.append(
                {
                    "id": json_int(item.get("id")),
                    "name": json_str(item.get("name")),
                    "size_in_bytes": json_int(item.get("size_in_bytes")),
                    "expired": json_bool(item.get("expired")),
                    "created_at": json_str(item.get("created_at")),
                    "expires_at": json_str(item.get("expires_at")),
                }
            )
        return {
            "repository": repository,
            "run_id": run_id,
            "total_count": json_int(result.get("total_count"), default=len(files)),
            "files": files,
            "page": page,
        }

    def download_workflow_file(
        self,
        repository: str,
        workflow_file_id: int,
        max_bytes: int = _MAX_WORKFLOW_FILE_BYTES,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        data = self._download_redirect_bytes(
            repository,
            f"/repos/{repository}/actions/artifacts/{workflow_file_id}/zip",
            max_bytes,
        )
        return {
            "repository": repository,
            "workflow_file_id": workflow_file_id,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "content_base64": base64.b64encode(data).decode("ascii"),
        }

    def enable_workflow(
        self,
        repository: str,
        workflow_id: str,
    ) -> JsonObject:
        """Enable one GitHub Actions workflow in an installed repository."""
        repository = self._assert_allowed(repository)
        workflow = workflow_id.strip()
        if not workflow:
            raise GitHubAgentError("workflow_id must not be empty")

        workflow_q = urllib.parse.quote(workflow, safe="")
        status, _ = self._repo_request(
            repository,
            "PUT",
            f"/repos/{repository}/actions/workflows/{workflow_q}/enable",
        )
        return {
            "repository": repository,
            "workflow_id": workflow,
            "status": status,
            "enabled": status in {200, 204},
        }

    def dispatch_workflow(
        self,
        repository: str,
        workflow_id: str,
        ref: str,
        inputs: JsonObject | None = None,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        workflow = workflow_id.strip()
        target_ref = ref.strip()
        if not workflow:
            raise GitHubAgentError("workflow_id must not be empty")
        if not target_ref:
            raise GitHubAgentError("ref must not be empty")

        workflow_q = urllib.parse.quote(workflow, safe="")
        payload: JsonObject = {"ref": target_ref}
        if inputs:
            payload["inputs"] = dict(inputs)

        status, _ = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/actions/workflows/{workflow_q}/dispatches",
            payload=payload,
        )
        return {
            "repository": repository,
            "workflow_id": workflow,
            "ref": target_ref,
            "inputs": dict(inputs or {}),
            "status": status,
            "dispatched": status in {201, 204},
        }

    def rerun_workflow_job(self, repository: str, job_id: int) -> JsonObject:
        repository = self._assert_allowed(repository)
        status, _ = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/actions/jobs/{job_id}/rerun",
        )
        return {"repository": repository, "job_id": job_id, "status": status}

    def rerun_failed_workflow_jobs(
        self,
        repository: str,
        run_id: int,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        status, _ = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/actions/runs/{run_id}/rerun-failed-jobs",
        )
        return {"repository": repository, "run_id": run_id, "status": status}

    def rerun_workflow_run(self, repository: str, run_id: int) -> JsonObject:
        repository = self._assert_allowed(repository)
        status, _ = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/actions/runs/{run_id}/rerun",
        )
        return {"repository": repository, "run_id": run_id, "status": status}

    def cancel_workflow_run(self, repository: str, run_id: int) -> JsonObject:
        repository = self._assert_allowed(repository)
        status, _ = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/actions/runs/{run_id}/cancel",
        )
        return {"repository": repository, "run_id": run_id, "status": status}
