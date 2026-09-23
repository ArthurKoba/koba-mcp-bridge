from __future__ import annotations

import base64
import http.client
import json
import queue
import ssl
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from typing import Self
from typing import Self

import jwt

from common.models import (
    JsonContainer,
    json_bool,
    json_container,
    json_int,
    json_loads,
    json_member_array,
    json_member_object,
    json_object,
    json_str,
    json_value,
)
from common.secrets import SecretError, resolve_config_secret

_GITHUB_API = "https://api.github.com"
_GITHUB_API_VERSION = "2026-03-10"


class GitHubAgentError(RuntimeError):
    """Raised when the GitHub App backend cannot complete a request."""


def github_agent_configured() -> bool:
    try:
        return bool(
            resolve_config_secret("github/development", "APP_ID").strip()
            and resolve_config_secret(
                "github/development",
                "PRIVATE_KEY_PEM",
            ).strip()
        )
    except SecretError:
        return False


def _development_app_id() -> str:
    try:
        value = resolve_config_secret("github/development", "APP_ID").strip()
    except SecretError as exc:
        raise GitHubAgentError(
            f"unable to load GitHub development APP_ID from Infisical: {exc}"
        ) from exc
    if not value:
        raise GitHubAgentError("GitHub development APP_ID is empty")
    return value


def _development_private_key() -> str:
    try:
        value = resolve_config_secret(
            "github/development",
            "PRIVATE_KEY_PEM",
        ).replace("\\n", "\n").strip()
    except SecretError as exc:
        raise GitHubAgentError(
            "unable to load GitHub development PRIVATE_KEY_PEM from Infisical: "
            f"{exc}"
        ) from exc
    if not value:
        raise GitHubAgentError("GitHub development PRIVATE_KEY_PEM is empty")
    return value


@dataclass
class GitHubAppClient:
    app_id: str
    private_key: str
    _installation_ids: dict[str, int] = field(default_factory=dict)
    _tokens: dict[int, tuple[str, float]] = field(default_factory=dict)
    repository_cache_ttl_seconds: float = 30.0
    max_connections: int = 8
    _connection_pool: queue.LifoQueue[http.client.HTTPSConnection] = field(
        default_factory=queue.LifoQueue,
        init=False,
        repr=False,
    )
    _connection_count: int = field(default=0, init=False, repr=False)
    _pool_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )
    _cache_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )
    _credential_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )
    _repository_cache: dict[str, tuple[float, dict[str, object]]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    @classmethod
    def from_infisical(cls) -> Self:
        return cls(
            app_id=_development_app_id(),
            private_key=_development_private_key(),
        )

    def _assert_allowed(self, repository: str) -> str:
        """Validate a repository selector; GitHub installation scope is the access policy."""
        repository = repository.strip()
        owner, separator, name = repository.partition("/")
        if separator != "/" or not owner or not name or "/" in name:
            raise GitHubAgentError("repository must be owner/name")
        return repository

    def _app_jwt(self) -> str:
        app_id = self.app_id.strip()
        if not app_id.isdigit() or int(app_id) <= 0:
            raise GitHubAgentError(
                "GitHub APP_ID must be a positive numeric App ID; "
                f"got {app_id!r}"
            )

        now = int(time.time())
        try:
            token = jwt.encode(
                {
                    "iat": now - 60,
                    "exp": now + 9 * 60,
                    "iss": app_id,
                },
                self.private_key,
                algorithm="RS256",
            )
        except Exception as exc:
            raise GitHubAgentError(
                "GitHub App PRIVATE_KEY_PEM is not a usable RSA private key; "
                "check that the PEM belongs to the configured APP_ID and was not "
                "stored as base64 or truncated text"
            ) from exc
        return str(token)

    @staticmethod
    def _decode_json(data: bytes) -> JsonContainer:
        if not data:
            return {}
        try:
            return json_container(
                json_loads(data, context="GitHub response"),
                context="GitHub response",
            )
        except ValueError as exc:
            raise GitHubAgentError("GitHub returned invalid JSON") from exc

    @staticmethod
    def _request_target(url: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "api.github.com":
            raise GitHubAgentError("GitHub API request must target https://api.github.com")
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        return target

    def _new_connection(self) -> http.client.HTTPSConnection:
        return http.client.HTTPSConnection(
            "api.github.com",
            timeout=30,
            context=ssl.create_default_context(),
        )

    def _acquire_connection(self) -> http.client.HTTPSConnection:
        try:
            return self._connection_pool.get_nowait()
        except queue.Empty:
            pass

        create_new = False
        with self._pool_lock:
            if self._connection_count < max(1, self.max_connections):
                self._connection_count += 1
                create_new = True

        if create_new:
            try:
                return self._new_connection()
            except Exception:
                with self._pool_lock:
                    self._connection_count -= 1
                raise

        try:
            return self._connection_pool.get(timeout=30)
        except queue.Empty as exc:
            raise GitHubAgentError(
                "timed out waiting for an available GitHub API connection"
            ) from exc

    def _release_connection(
        self,
        connection: http.client.HTTPSConnection,
        *,
        reusable: bool,
    ) -> None:
        if reusable:
            self._connection_pool.put(connection)
            return
        try:
            connection.close()
        finally:
            with self._pool_lock:
                self._connection_count = max(0, self._connection_count - 1)

    @staticmethod
    def _github_error_message(status: int, url: str, data: bytes) -> str:
        detail = data[:4096].decode("utf-8", "replace")
        path = urllib.parse.urlsplit(url).path
        if status == 401:
            if path == "/app" or path.endswith("/installation") or (
                path.startswith("/app/installations/")
                and path.endswith("/access_tokens")
            ):
                return (
                    "GitHub App authentication failed (HTTP 401); check that APP_ID "
                    "matches PRIVATE_KEY_PEM and that the GitHub App private key is active"
                )
            return (
                "GitHub installation authentication failed (HTTP 401); the installation "
                "token may be expired/revoked or the App installation may have changed"
            )
        if status == 403:
            return (
                "GitHub API denied the operation (HTTP 403); check GitHub App repository "
                f"permissions/rate limits for {path}: {detail}"
            )
        return f"GitHub API HTTP {status}: {detail}"

    def _request(
        self,
        method: str,
        url: str,
        *,
        token: str | None = None,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, JsonContainer]:
        body = (
            None
            if payload is None
            else json.dumps(
                json_value(payload, context="GitHub request payload"),
                ensure_ascii=False,
            ).encode("utf-8")
        )
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "mcp-bridge",
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/json"

        target = self._request_target(url)
        data = b""
        status = 0
        for attempt in range(2):
            connection = self._acquire_connection()
            try:
                connection.request(method, target, body=body, headers=headers)
                response = connection.getresponse()
                data = response.read()
                status = response.status
                self._release_connection(
                    connection,
                    reusable=not response.will_close,
                )
                break
            except (OSError, http.client.HTTPException) as exc:
                self._release_connection(connection, reusable=False)
                if attempt:
                    raise GitHubAgentError(
                        f"GitHub API transport error after reconnect: {exc}"
                    ) from exc

        if status >= 400:
            if allowed_errors and status in allowed_errors:
                try:
                    parsed = self._decode_json(data)
                except Exception:
                    parsed = {"message": data.decode("utf-8", "replace")}
                return status, parsed
            raise GitHubAgentError(self._github_error_message(status, url, data))

        return status, self._decode_json(data)

    def _installation_id(self, repository: str) -> int:
        repository = self._assert_allowed(repository)
        key = repository.casefold()
        cached = self._installation_ids.get(key)
        if cached is not None:
            return cached

        with self._credential_lock:
            cached = self._installation_ids.get(key)
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
                    f"repository {repository!r} is not installed for GitHub App "
                    f"{self.app_id}; add it to the App installation or use the correct App"
                )
            try:
                payload = json_object(result, context="GitHub installation response")
                installation_id = json_int(payload.get("id"))
            except ValueError as exc:
                raise GitHubAgentError("GitHub did not return an installation id") from exc
            if installation_id <= 0:
                raise GitHubAgentError("GitHub did not return an installation id")
            self._installation_ids[key] = installation_id
            return installation_id

    def _installation_token_for_id(self, installation_id: int) -> str:
        cached = self._tokens.get(installation_id)
        if cached is not None and cached[1] > time.time() + 120:
            return cached[0]

        with self._credential_lock:
            cached = self._tokens.get(installation_id)
            if cached is not None and cached[1] > time.time() + 120:
                return cached[0]

            _, result = self._request(
                "POST",
                f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens",
                token=self._app_jwt(),
            )
            try:
                token_payload = json_object(
                    result,
                    context="GitHub installation token response",
                )
                token = json_str(token_payload.get("token"))
                expires_at = json_str(token_payload.get("expires_at"))
            except ValueError as exc:
                raise GitHubAgentError(
                    "GitHub did not return an installation token payload"
                ) from exc
            if not token or not expires_at:
                raise GitHubAgentError(
                    "GitHub installation token response is incomplete; check App "
                    "installation state and permissions"
                )
            try:
                expiry = datetime.fromisoformat(
                    expires_at.replace("Z", "+00:00")
                ).timestamp()
            except ValueError as exc:
                raise GitHubAgentError(
                    "GitHub installation token response has invalid expires_at"
                ) from exc
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
    ) -> tuple[int, JsonContainer]:
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
            for raw_item in result:
                try:
                    item = json_object(
                        raw_item,
                        context="GitHub App installation item",
                    )
                    installation_id = json_int(item.get("id"))
                except ValueError as exc:
                    raise GitHubAgentError(
                        "unexpected GitHub App installation item"
                    ) from exc
                if installation_id <= 0:
                    raise GitHubAgentError(
                        "unexpected GitHub App installation item"
                    )
                installation_ids.append(installation_id)
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
                try:
                    response = json_object(
                        result,
                        context="GitHub installation repository response",
                    )
                    items = json_member_array(
                        response,
                        "repositories",
                        required=True,
                    )
                except ValueError as exc:
                    raise GitHubAgentError(
                        "installation repository response has no repositories"
                    ) from exc

                for raw_item in items:
                    try:
                        item = json_object(
                            raw_item,
                            context="GitHub installation repository item",
                        )
                        full_name = json_str(item.get("full_name"))
                    except ValueError as exc:
                        raise GitHubAgentError(
                            "unexpected installation repository item"
                        ) from exc
                    if not full_name or full_name.casefold() in seen:
                        continue
                    seen.add(full_name.casefold())
                    cache_key = full_name.casefold()
                    self._installation_ids[cache_key] = installation_id

                    metadata: dict[str, object] = {
                        "repository": full_name,
                        "default_branch": json_str(item.get("default_branch")),
                        "private": json_bool(item.get("private")),
                        "archived": json_bool(item.get("archived")),
                        "fork": json_bool(item.get("fork")),
                    }
                    if self.repository_cache_ttl_seconds > 0:
                        with self._cache_lock:
                            self._repository_cache[cache_key] = (
                                time.monotonic() + self.repository_cache_ttl_seconds,
                                metadata,
                            )
                    permissions = json_member_object(item, "permissions")
                    repositories.append(
                        {
                            "full_name": full_name,
                            "private": json_bool(item.get("private")),
                            "default_branch": json_str(item.get("default_branch")),
                            "archived": json_bool(item.get("archived")),
                            "fork": json_bool(item.get("fork")),
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

    def _repository_metadata(
        self,
        repository: str,
        *,
        refresh: bool = False,
    ) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        key = repository.casefold()
        now = time.monotonic()
        if not refresh and self.repository_cache_ttl_seconds > 0:
            with self._cache_lock:
                cached = self._repository_cache.get(key)
                if cached is not None and cached[0] > now:
                    return dict(cached[1])

        _, result = self._repo_request(repository, "GET", f"/repos/{repository}")
        try:
            payload = json_object(result, context="GitHub repository response")
        except ValueError as exc:
            raise GitHubAgentError("unexpected repository response") from exc
        metadata: dict[str, object] = {
            "repository": json_str(payload.get("full_name"), default=repository),
            "default_branch": json_str(payload.get("default_branch")),
            "private": json_bool(payload.get("private")),
            "archived": json_bool(payload.get("archived")),
            "fork": json_bool(payload.get("fork")),
        }
        if self.repository_cache_ttl_seconds > 0:
            with self._cache_lock:
                self._repository_cache[key] = (
                    time.monotonic() + self.repository_cache_ttl_seconds,
                    dict(metadata),
                )
        return metadata

    def status(self, repository: str) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        result = self._repository_metadata(repository)
        return {
            "repository": str(result["repository"]),
            "default_branch": str(result["default_branch"]),
            "private": bool(result["private"]),
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
        try:
            payload = json_object(result, context="GitHub file response")
            if json_str(payload.get("type")) != "file":
                raise ValueError("not a file")
            encoding = json_str(payload.get("encoding"))
            content = json_str(payload.get("content"))
        except ValueError as exc:
            raise GitHubAgentError(
                "path is not a regular GitHub repository file"
            ) from exc
        if encoding != "base64":
            raise GitHubAgentError(f"unsupported GitHub content encoding: {encoding}")
        decoded = base64.b64decode(content).decode("utf-8", "replace")
        return {
            "repository": repository,
            "path": json_str(payload.get("path"), default=path),
            "sha": json_str(payload.get("sha")),
            "size": json_int(payload.get("size")),
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
        branches: list[dict[str, object]] = []
        for raw_item in result:
            try:
                item = json_object(raw_item, context="GitHub branch item")
                commit = json_member_object(item, "commit", required=True)
                branches.append(
                    {
                        "name": json_str(item.get("name")),
                        "sha": json_str(commit.get("sha")),
                        "protected": json_bool(item.get("protected")),
                    }
                )
            except ValueError as exc:
                raise GitHubAgentError("unexpected branch list response") from exc
        return {"repository": repository, "branches": branches}

    def create_branch(self, repository: str, branch: str, from_branch: str) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        source = urllib.parse.quote(from_branch, safe="")
        _, ref = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{source}",
        )
        try:
            ref_payload = json_object(ref, context="GitHub ref response")
            ref_object = json_member_object(ref_payload, "object", required=True)
            sha = json_str(ref_object.get("sha"))
        except ValueError as exc:
            raise GitHubAgentError("unable to resolve source branch") from exc
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
            try:
                current_payload = json_object(
                    current,
                    context="GitHub existing file response",
                )
                if json_str(current_payload.get("type")) != "file":
                    raise ValueError("not a file")
                payload["sha"] = json_str(current_payload.get("sha"))
            except ValueError as exc:
                raise GitHubAgentError(
                    "existing path is not a regular file"
                ) from exc
            operation = "update"

        response_status, result = self._repo_request(
            repository,
            "PUT",
            f"/repos/{repository}/contents/{quoted_path}",
            payload=payload,
        )
        try:
            write_payload = json_object(
                result,
                context="GitHub file write response",
            )
            commit = json_member_object(write_payload, "commit")
            saved = json_member_object(write_payload, "content")
        except ValueError as exc:
            raise GitHubAgentError("unexpected file write response") from exc
        return {
            "status": response_status,
            "operation": operation,
            "repository": repository,
            "branch": branch,
            "path": path,
            "commit_sha": json_str(commit.get("sha")),
            "content_sha": json_str(saved.get("sha")),
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
        try:
            current_payload = json_object(
                current,
                context="GitHub file delete source",
            )
            if json_str(current_payload.get("type")) != "file":
                raise ValueError("not a file")
            sha = json_str(current_payload.get("sha"))
        except ValueError as exc:
            raise GitHubAgentError("path is not a regular file") from exc
        _, result = self._repo_request(
            repository,
            "DELETE",
            f"/repos/{repository}/contents/{quoted_path}",
            payload={"message": message, "sha": sha, "branch": branch},
        )
        try:
            delete_payload = json_object(
                result,
                context="GitHub file delete response",
            )
            commit = json_member_object(delete_payload, "commit")
        except ValueError as exc:
            raise GitHubAgentError("unexpected file delete response") from exc
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
        try:
            compare_payload = json_object(
                result,
                context="GitHub compare response",
            )
            files = json_member_array(compare_payload, "files")
        except ValueError as exc:
            raise GitHubAgentError("unexpected compare response") from exc

        normalized_files: list[dict[str, object]] = []
        for raw_item in files:
            try:
                item = json_object(raw_item, context="GitHub compare file")
                normalized_files.append(
                    {
                        "filename": json_str(item.get("filename")),
                        "status": json_str(item.get("status")),
                        "additions": json_int(item.get("additions")),
                        "deletions": json_int(item.get("deletions")),
                    }
                )
            except ValueError as exc:
                raise GitHubAgentError("unexpected compare file response") from exc

        return {
            "repository": repository,
            "base": base,
            "head": head,
            "status": json_str(compare_payload.get("status")),
            "ahead_by": json_int(compare_payload.get("ahead_by")),
            "behind_by": json_int(compare_payload.get("behind_by")),
            "total_commits": json_int(compare_payload.get("total_commits")),
            "files": normalized_files,
        }

    def fast_forward(self, repository: str, branch: str, to_ref: str) -> dict[str, object]:
        repository = self._assert_allowed(repository)
        to_q = urllib.parse.quote(to_ref, safe="")
        _, commit = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/commits/{to_q}",
        )
        try:
            commit_payload = json_object(
                commit,
                context="GitHub target commit response",
            )
            sha = json_str(commit_payload.get("sha"))
        except ValueError as exc:
            raise GitHubAgentError("unable to resolve target ref") from exc
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
