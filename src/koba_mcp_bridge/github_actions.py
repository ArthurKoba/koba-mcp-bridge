from __future__ import annotations

import base64
import hashlib
import urllib.error
import urllib.parse
import urllib.request

from .github_agent import GitHubAgentError
from .github_collab import GitHubCollabClient

_GITHUB_API = "https://api.github.com"
_MAX_LOG_BYTES = 8 * 1024 * 1024
_MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


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


class GitHubActionsClient(GitHubCollabClient):
    """Adds GitHub Actions diagnostics and controlled run mutations."""

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
                "User-Agent": "koba-mcp-bridge",
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
                headers={"User-Agent": "koba-mcp-bridge"},
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
            data = response.read(max_bytes + 1)
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
    ) -> dict[str, object]:
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

    def list_workflow_artifacts(
        self,
        repository: str,
        run_id: int,
        per_page: int = 100,
        page: int = 1,
    ) -> dict[str, object]:
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
            raise GitHubAgentError("unexpected workflow artifact response")
        raw = result.get("artifacts") if isinstance(result.get("artifacts"), list) else []
        artifacts = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            artifacts.append(
                {
                    "id": int(item.get("id", 0)),
                    "name": str(item.get("name", "")),
                    "size_in_bytes": int(item.get("size_in_bytes", 0)),
                    "expired": bool(item.get("expired", False)),
                    "created_at": str(item.get("created_at", "")),
                    "expires_at": str(item.get("expires_at", "")),
                }
            )
        return {
            "repository": repository,
            "run_id": run_id,
            "total_count": int(result.get("total_count", len(artifacts))),
            "artifacts": artifacts,
            "page": page,
        }

    def download_workflow_artifact(
        self,
        repository: str,
        artifact_id: int,
        max_bytes: int = _MAX_ARTIFACT_BYTES,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        data = self._download_redirect_bytes(
            repository,
            f"/repos/{repository}/actions/artifacts/{artifact_id}/zip",
            max_bytes,
        )
        return {
            "repository": repository,
            "artifact_id": artifact_id,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "content_base64": base64.b64encode(data).decode("ascii"),
        }

    def rerun_workflow_job(self, repository: str, job_id: int) -> dict[str, object]:
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
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        status, _ = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/actions/runs/{run_id}/rerun-failed-jobs",
        )
        return {"repository": repository, "run_id": run_id, "status": status}

    def rerun_workflow_run(self, repository: str, run_id: int) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        status, _ = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/actions/runs/{run_id}/rerun",
        )
        return {"repository": repository, "run_id": run_id, "status": status}

    def cancel_workflow_run(self, repository: str, run_id: int) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        status, _ = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/actions/runs/{run_id}/cancel",
        )
        return {"repository": repository, "run_id": run_id, "status": status}
