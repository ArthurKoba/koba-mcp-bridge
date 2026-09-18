from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime

import jwt

from .secrets import resolve_secret

_GITHUB_API = "https://api.github.com"
_GITHUB_API_VERSION = "2026-03-10"


class GitHubAgentError(RuntimeError):
    """Raised when the GitHub App backend cannot complete a request."""


def github_agent_configured() -> bool:
    return bool(
        os.getenv("GITHUB_AGENT_APP_ID", "").strip()
        and (
            os.getenv("GITHUB_AGENT_PRIVATE_KEY_REF", "").strip()
            or os.getenv("GITHUB_AGENT_PRIVATE_KEY", "").strip()
            or os.getenv("GITHUB_AGENT_PRIVATE_KEY_B64", "").strip()
        )
    )


def _private_key_from_env() -> str:
    secret_ref = os.getenv("GITHUB_AGENT_PRIVATE_KEY_REF", "").strip()
    if secret_ref:
        return resolve_secret(secret_ref).replace("\\n", "\n")

    raw = os.getenv("GITHUB_AGENT_PRIVATE_KEY", "").strip()
    if raw:
        return raw.replace("\\n", "\n")

    encoded = os.getenv("GITHUB_AGENT_PRIVATE_KEY_B64", "").strip()
    if encoded:
        try:
            return base64.b64decode(encoded).decode("utf-8")
        except Exception as exc:  # pragma: no cover - defensive configuration error path
            raise GitHubAgentError(
                "GITHUB_AGENT_PRIVATE_KEY_B64 is not valid base64 UTF-8"
            ) from exc

    raise GitHubAgentError("GitHub agent private key is not configured")


@dataclass
class GitHubAppClient:
    app_id: str
    private_key: str
    _installation_ids: dict[str, int] = field(default_factory=dict)
    _tokens: dict[int, tuple[str, float]] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> GitHubAppClient:
        app_id = os.getenv("GITHUB_AGENT_APP_ID", "").strip()
        if not app_id:
            raise GitHubAgentError("GITHUB_AGENT_APP_ID is not configured")
        return cls(
            app_id=app_id,
            private_key=_private_key_from_env(),
        )

    def _assert_allowed(self, repository: str) -> str:
        """Validate a repository selector; GitHub installation scope is the access policy."""
        repository = repository.strip()
        owner, separator, name = repository.partition("/")
        if separator != "/" or not owner or not name or "/" in name:
            raise GitHubAgentError("repository must be owner/name")
        return repository

    def _app_jwt(self) -> str:
        now = int(time.time())
        token = jwt.encode(
            {
                "iat": now - 60,
                "exp": now + 9 * 60,
                "iss": self.app_id,
            },
            self.private_key,
            algorithm="RS256",
        )
        return str(token)

    @staticmethod
    def _decode_json(data: bytes) -> object:
        if not data:
            return {}
        return json.loads(data.decode("utf-8"))

    def _request(
        self,
        method: str,
        url: str,
        *,
        token: str | None = None,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, object]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "koba-mcp-bridge",
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, self._decode_json(response.read())
        except urllib.error.HTTPError as exc:
            data = exc.read()
            if allowed_errors and exc.code in allowed_errors:
                try:
                    parsed = self._decode_json(data)
                except Exception:
                    parsed = {"message": data.decode("utf-8", "replace")}
                return exc.code, parsed
            detail = data[:4096].decode("utf-8", "replace")
            raise GitHubAgentError(f"GitHub API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise GitHubAgentError(f"GitHub API transport error: {exc.reason}") from exc

    def _installation_id(self, repository: str) -> int:
        repository = self._assert_allowed(repository)
        cached = self._installation_ids.get(repository.casefold())
        if cached is not None:
            return cached

        status, result = self._request(
            "GET",
            f"{_GITHUB_API}/repos/{repository}/installation",
            token=self._app_jwt(),
            allowed_errors={404},
        )
        if status == 404:
            raise GitHubAgentError(
                f"repository is not installed for GitHub App {self.app_id}: {repository}"
            )
        if not isinstance(result, dict) or not isinstance(result.get("id"), int):
            raise GitHubAgentError("GitHub did not return an installation id")
        installation_id = int(result["id"])
        self._installation_ids[repository.casefold()] = installation_id
        return installation_id

    def _installation_token_for_id(self, installation_id: int) -> str:
        cached = self._tokens.get(installation_id)
        if cached is not None and cached[1] > time.time() + 120:
            return cached[0]

        _, result = self._request(
            "POST",
            f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens",
            token=self._app_jwt(),
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("GitHub did not return an installation token payload")
        token = str(result.get("token", ""))
        expires_at = str(result.get("expires_at", ""))
        if not token or not expires_at:
            raise GitHubAgentError("GitHub installation token response is incomplete")
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()
        self._tokens[installation_id] = (token, expiry)
        return token

    def _installation_token(self, repository: str) -> str:
        return self._installation_token_for_id(self._installation_id(repository))

    def _repo_request(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, object]:
        repository = self._assert_allowed(repository)
        token = self._installation_token(repository)
        return self._request(
            method,
            f"{_GITHUB_API}{path}",
            token=token,
            payload=payload,
            allowed_errors=allowed_errors,
        )

    def _installation_ids_from_github(self) -> list[int]:
        installation_ids: list[int] = []
        page = 1
        while True:
            _, result = self._request(
                "GET",
                f"{_GITHUB_API}/app/installations?per_page=100&page={page}",
                token=self._app_jwt(),
            )
            if not isinstance(result, list):
                raise GitHubAgentError("unexpected GitHub App installation list response")
            for item in result:
                if isinstance(item, dict) and isinstance(item.get("id"), int):
                    installation_ids.append(int(item["id"]))
            if len(result) < 100:
                break
            page += 1
        return installation_ids

    def list_repositories(self) -> dict[str, object]:
        """List every repository currently granted to this GitHub App installation."""
        repositories: list[dict[str, object]] = []
        seen: set[str] = set()
        for installation_id in self._installation_ids_from_github():
            token = self._installation_token_for_id(installation_id)
            page = 1
            while True:
                _, result = self._request(
                    "GET",
                    f"{_GITHUB_API}/installation/repositories?per_page=100&page={page}",
                    token=token,
                )
                if not isinstance(result, dict):
                    raise GitHubAgentError("unexpected installation repository response")
                items = result.get("repositories")
                if not isinstance(items, list):
                    raise GitHubAgentError("installation repository response has no repositories")
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    full_name = str(item.get("full_name", ""))
                    if not full_name or full_name.casefold() in seen:
                        continue
                    seen.add(full_name.casefold())
                    self._installation_ids[full_name.casefold()] = installation_id
                    permissions = (
                        item.get("permissions")
                        if isinstance(item.get("permissions"), dict)
                        else {}
                    )
                    repositories.append(
                        {
                            "full_name": full_name,
                            "private": bool(item.get("private", False)),
                            "default_branch": str(item.get("default_branch", "")),
                            "archived": bool(item.get("archived", False)),
                            "fork": bool(item.get("fork", False)),
                            "permissions": permissions,
                            "installation_id": installation_id,
                        }
                    )
                if len(items) < 100:
                    break
                page += 1
        repositories.sort(key=lambda item: str(item["full_name"]).casefold())
        return {
            "app_id": self.app_id,
            "count": len(repositories),
            "repositories": repositories,
        }

    def status(self, repository: str) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(repository, "GET", f"/repos/{repository}")
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected repository response")
        return {
            "repository": str(result.get("full_name", repository)),
            "default_branch": str(result.get("default_branch", "")),
            "private": bool(result.get("private", False)),
            "app_id": self.app_id,
            "installation_id": self._installation_id(repository),
            "status": "ok",
        }

    def get_file(self, repository: str, path: str, ref: str | None = None) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        quoted_path = urllib.parse.quote(path.strip("/"), safe="/")
        query = ""
        if ref:
            query = "?ref=" + urllib.parse.quote(ref, safe="")
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/contents/{quoted_path}{query}",
        )
        if not isinstance(result, dict) or result.get("type") != "file":
            raise GitHubAgentError("path is not a regular GitHub repository file")
        encoding = str(result.get("encoding", ""))
        content = str(result.get("content", ""))
        if encoding != "base64":
            raise GitHubAgentError(f"unsupported GitHub content encoding: {encoding}")
        decoded = base64.b64decode(content).decode("utf-8", "replace")
        return {
            "repository": repository,
            "path": str(result.get("path", path)),
            "sha": str(result.get("sha", "")),
            "size": int(result.get("size", 0)),
            "content": decoded,
        }

    def list_branches(self, repository: str) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/branches?per_page=100",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected branch list response")
        branches = []
        for item in result:
            if isinstance(item, dict):
                commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
                branches.append(
                    {
                        "name": str(item.get("name", "")),
                        "sha": str(commit.get("sha", "")),
                        "protected": bool(item.get("protected", False)),
                    }
                )
        return {"repository": repository, "branches": branches}

    def create_branch(self, repository: str, branch: str, from_branch: str) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        source = urllib.parse.quote(from_branch, safe="")
        _, ref = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{source}",
        )
        if not isinstance(ref, dict) or not isinstance(ref.get("object"), dict):
            raise GitHubAgentError("unable to resolve source branch")
        sha = str(ref["object"].get("sha", ""))
        if not sha:
            raise GitHubAgentError("source branch has no commit sha")
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/git/refs",
            payload={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        return {"repository": repository, "branch": branch, "sha": sha, "result": result}

    def put_file(
        self,
        repository: str,
        path: str,
        content: str,
        message: str,
        branch: str,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        quoted_path = urllib.parse.quote(path.strip("/"), safe="/")
        ref = urllib.parse.quote(branch, safe="")
        status, current = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/contents/{quoted_path}?ref={ref}",
            allowed_errors={404},
        )
        payload: dict[str, object] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        operation = "create"
        if status != 404:
            if not isinstance(current, dict) or current.get("type") != "file":
                raise GitHubAgentError("existing path is not a regular file")
            payload["sha"] = str(current.get("sha", ""))
            operation = "update"

        response_status, result = self._repo_request(
            repository,
            "PUT",
            f"/repos/{repository}/contents/{quoted_path}",
            payload=payload,
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected file write response")
        commit = result.get("commit") if isinstance(result.get("commit"), dict) else {}
        saved = result.get("content") if isinstance(result.get("content"), dict) else {}
        return {
            "status": response_status,
            "operation": operation,
            "repository": repository,
            "branch": branch,
            "path": path,
            "commit_sha": str(commit.get("sha", "")),
            "content_sha": str(saved.get("sha", "")),
        }

    def delete_file(
        self,
        repository: str,
        path: str,
        message: str,
        branch: str,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        quoted_path = urllib.parse.quote(path.strip("/"), safe="/")
        ref = urllib.parse.quote(branch, safe="")
        _, current = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/contents/{quoted_path}?ref={ref}",
        )
        if not isinstance(current, dict) or current.get("type") != "file":
            raise GitHubAgentError("path is not a regular file")
        sha = str(current.get("sha", ""))
        _, result = self._repo_request(
            repository,
            "DELETE",
            f"/repos/{repository}/contents/{quoted_path}",
            payload={"message": message, "sha": sha, "branch": branch},
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected file delete response")
        commit = result.get("commit") if isinstance(result.get("commit"), dict) else {}
        return {
            "repository": repository,
            "branch": branch,
            "path": path,
            "commit_sha": str(commit.get("sha", "")),
        }

    def compare(self, repository: str, base: str, head: str) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        base_q = urllib.parse.quote(base, safe="")
        head_q = urllib.parse.quote(head, safe="")
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/compare/{base_q}...{head_q}",
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected compare response")
        files = result.get("files") if isinstance(result.get("files"), list) else []
        return {
            "repository": repository,
            "base": base,
            "head": head,
            "status": str(result.get("status", "")),
            "ahead_by": int(result.get("ahead_by", 0)),
            "behind_by": int(result.get("behind_by", 0)),
            "total_commits": int(result.get("total_commits", 0)),
            "files": [
                {
                    "filename": str(item.get("filename", "")),
                    "status": str(item.get("status", "")),
                    "additions": int(item.get("additions", 0)),
                    "deletions": int(item.get("deletions", 0)),
                }
                for item in files
                if isinstance(item, dict)
            ],
        }

    def fast_forward(self, repository: str, branch: str, to_ref: str) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        to_q = urllib.parse.quote(to_ref, safe="")
        _, commit = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/commits/{to_q}",
        )
        if not isinstance(commit, dict):
            raise GitHubAgentError("unable to resolve target ref")
        sha = str(commit.get("sha", ""))
        if not sha:
            raise GitHubAgentError("target ref has no commit sha")
        branch_q = urllib.parse.quote(branch, safe="")
        _, result = self._repo_request(
            repository,
            "PATCH",
            f"/repos/{repository}/git/refs/heads/{branch_q}",
            payload={"sha": sha, "force": False},
        )
        return {"repository": repository, "branch": branch, "sha": sha, "result": result}
