from __future__ import annotations

import base64
import http.client
import json
import os
import queue
import re
import ssl
import threading
import urllib.parse
from dataclasses import dataclass
from typing import Any

from .secrets import SecretError, list_config_folders, resolve_config_secret

_PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ALLOWED_AUTH = {"private_token", "bearer", "job_token"}


class GitLabError(RuntimeError):
    pass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _protected_branches() -> set[str]:
    raw = os.getenv("GITLAB_PROTECTED_BRANCHES", "main,master")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _assert_mutable_branch(branch: str) -> str:
    value = branch.strip()
    if not value:
        raise GitLabError("branch must not be empty")
    if value in _protected_branches():
        raise GitLabError(
            f"direct mutation of protected branch {value!r} is blocked; use a merge request"
        )
    return value


@dataclass(frozen=True)
class GitLabProfile:
    profile_id: str
    base_url: str
    auth_type: str
    convention_path: str
    verify_tls: bool = True
    ca_file: str = ""
    label: str = ""

    @property
    def api_url(self) -> str:
        return self.base_url.rstrip("/") + "/api/v4"

    def token(self) -> str:
        try:
            return resolve_config_secret(self.convention_path, "TOKEN")
        except SecretError as exc:
            raise GitLabError(
                f"unable to resolve TOKEN for GitLab profile {self.profile_id!r}: {exc}"
            ) from exc

    def public(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "label": self.label,
            "base_url": self.base_url,
            "api_url": self.api_url,
            "auth_type": self.auth_type,
            "credential_source": {
                "type": "infisical_convention",
                "path": self.convention_path,
                "secret": "TOKEN",
            },
            "credential_configured": True,
            "verify_tls": self.verify_tls,
            "ca_file": self.ca_file or None,
        }


class GitLabProfileRegistry:
    def __init__(self, profiles: dict[str, GitLabProfile]) -> None:
        self._profiles = profiles

    @staticmethod
    def _optional_secret(path: str, name: str, default: str = "") -> str:
        try:
            return resolve_config_secret(path, name).strip()
        except SecretError:
            return default

    @classmethod
    def _from_infisical(cls) -> list[GitLabProfile]:
        try:
            folders = list_config_folders("gitlab/accounts")
        except SecretError as exc:
            raise GitLabError(
                f"unable to discover GitLab profiles from Infisical: {exc}"
            ) from exc

        profiles: list[GitLabProfile] = []
        for folder in folders:
            profile_id = str(folder.get("name", "")).strip()
            if not _PROFILE_ID_RE.fullmatch(profile_id):
                continue
            path = f"gitlab/accounts/{profile_id}"
            try:
                base_url = resolve_config_secret(path, "BASE_URL").strip().rstrip("/")
            except SecretError as exc:
                raise GitLabError(
                    f"GitLab profile {profile_id!r} is missing/unreadable BASE_URL: {exc}"
                ) from exc

            auth_type = cls._optional_secret(
                path,
                "AUTH_TYPE",
                "private_token",
            ).casefold()
            if auth_type not in _ALLOWED_AUTH:
                raise GitLabError(
                    f"profile {profile_id!r} AUTH_TYPE must be one of "
                    f"{sorted(_ALLOWED_AUTH)}"
                )
            parsed = urllib.parse.urlsplit(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise GitLabError(
                    f"profile {profile_id!r} has invalid BASE_URL"
                )

            verify_raw = cls._optional_secret(path, "VERIFY_TLS", "true")
            verify_tls = verify_raw.casefold() not in {"0", "false", "no", "off"}
            profiles.append(
                GitLabProfile(
                    profile_id=profile_id,
                    base_url=base_url,
                    auth_type=auth_type,
                    convention_path=path,
                    verify_tls=verify_tls,
                    ca_file=cls._optional_secret(path, "CA_FILE"),
                    label=cls._optional_secret(path, "LABEL", profile_id),
                )
            )
        return profiles

    @classmethod
    def from_infisical(cls) -> GitLabProfileRegistry:
        profiles = {
            profile.profile_id.casefold(): profile
            for profile in cls._from_infisical()
        }
        return cls(profiles)

    def list(self) -> dict[str, Any]:
        profiles = sorted(
            (profile.public() for profile in self._profiles.values()),
            key=lambda item: str(item["profile_id"]).casefold(),
        )
        return {"profiles": profiles, "count": len(profiles)}

    def get(self, profile_id: str) -> GitLabProfile:
        key = profile_id.strip().casefold()
        profile = self._profiles.get(key)
        if profile is None:
            raise GitLabError(f"unknown GitLab profile_id: {profile_id}")
        return profile


@dataclass
class GitLabResponse:
    status: int
    data: Any
    headers: dict[str, str]


class GitLabClient:
    def __init__(self, profile: GitLabProfile, *, max_connections: int = 4) -> None:
        self.profile = profile
        self.max_connections = max(1, int(max_connections))
        parsed = urllib.parse.urlsplit(profile.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise GitLabError(
                f"profile {profile.profile_id!r} has invalid base_url"
            )
        self._scheme = parsed.scheme
        self._hostname = parsed.hostname
        self._port = parsed.port
        self._connection_pool: queue.LifoQueue[
            http.client.HTTPConnection
        ] = queue.LifoQueue()
        self._connection_count = 0
        self._pool_lock = threading.Lock()

    def _ssl_context(self) -> ssl.SSLContext | None:
        if self._scheme != "https":
            return None
        if not self.profile.verify_tls:
            return ssl._create_unverified_context()
        if self.profile.ca_file:
            return ssl.create_default_context(cafile=self.profile.ca_file)
        return ssl.create_default_context()

    def _headers(self, has_body: bool = False) -> dict[str, str]:
        token = self.profile.token()
        headers = {
            "Accept": "application/json",
            "User-Agent": "mcp-bridge-gitlab",
        }
        if self.profile.auth_type == "private_token":
            headers["PRIVATE-TOKEN"] = token
        elif self.profile.auth_type == "bearer":
            headers["Authorization"] = f"Bearer {token}"
        else:
            headers["JOB-TOKEN"] = token
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _target(
        self,
        path: str,
        query: dict[str, Any] | None = None,
    ) -> str:
        if not path.startswith("/"):
            raise GitLabError("GitLab API path must start with /")
        pairs: list[tuple[str, str]] = []
        for key, raw in (query or {}).items():
            if raw is None:
                continue
            values = raw if isinstance(raw, list) else [raw]
            for value in values:
                if isinstance(value, bool):
                    pairs.append((key, "true" if value else "false"))
                else:
                    pairs.append((key, str(value)))
        encoded = urllib.parse.urlencode(pairs, doseq=True)
        return "/api/v4" + path + (f"?{encoded}" if encoded else "")

    def _url(
        self,
        path: str,
        query: dict[str, Any] | None = None,
    ) -> str:
        return self.profile.base_url.rstrip("/") + self._target(path, query)

    def _new_connection(self) -> http.client.HTTPConnection:
        if self._scheme == "https":
            return http.client.HTTPSConnection(
                self._hostname,
                self._port,
                timeout=45,
                context=self._ssl_context(),
            )
        return http.client.HTTPConnection(
            self._hostname,
            self._port,
            timeout=45,
        )

    def _acquire_connection(self) -> http.client.HTTPConnection:
        try:
            return self._connection_pool.get_nowait()
        except queue.Empty:
            pass

        create_new = False
        with self._pool_lock:
            if self._connection_count < self.max_connections:
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
            return self._connection_pool.get(timeout=45)
        except queue.Empty as exc:
            raise GitLabError(
                f"timed out waiting for a GitLab connection for profile "
                f"{self.profile.profile_id!r}"
            ) from exc

    def _release_connection(
        self,
        connection: http.client.HTTPConnection,
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

    def _perform(
        self,
        method: str,
        target: str,
        *,
        body: bytes | None,
        headers: dict[str, str],
    ) -> tuple[int, dict[str, str], bytes]:
        for attempt in range(2):
            connection = self._acquire_connection()
            try:
                connection.request(method, target, body=body, headers=headers)
                response = connection.getresponse()
                raw = response.read()
                status = response.status
                response_headers = {k: v for k, v in response.headers.items()}
                self._release_connection(
                    connection,
                    reusable=not response.will_close,
                )
                return status, response_headers, raw
            except (OSError, http.client.HTTPException) as exc:
                self._release_connection(connection, reusable=False)
                if attempt:
                    raise GitLabError(
                        f"GitLab API transport error after reconnect for profile "
                        f"{self.profile.profile_id!r}: {exc}"
                    ) from exc
        raise AssertionError("unreachable")

    def _error_message(self, status: int, target: str, data: Any) -> str:
        detail = json.dumps(data, ensure_ascii=False)[:4096]
        if status == 401:
            return (
                f"GitLab authentication failed for profile {self.profile.profile_id!r} "
                f"(HTTP 401); check its {self.profile.auth_type} credential"
            )
        if status == 403:
            return (
                f"GitLab denied the operation for profile {self.profile.profile_id!r} "
                f"(HTTP 403); check token scopes, project membership, and role: {detail}"
            )
        if status == 429:
            return (
                f"GitLab rate limit exceeded for profile {self.profile.profile_id!r} "
                f"(HTTP 429) on {target}"
            )
        return f"GitLab API HTTP {status}: {detail}"

    @staticmethod
    def _decode_response(raw: bytes, headers: dict[str, str]) -> Any:
        if not raw:
            return {}
        content_type = ""
        for key, value in headers.items():
            if key.casefold() == "content-type":
                content_type = value
                break
        if "json" in content_type.casefold():
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise GitLabError("GitLab returned invalid JSON") from exc
        return raw.decode("utf-8", "replace")

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> GitLabResponse:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        target = self._target(path, query)
        status, headers, raw = self._perform(
            method,
            target,
            body=body,
            headers=self._headers(has_body=body is not None),
        )
        data = self._decode_response(raw, headers)
        if status >= 400 and not (allowed_errors and status in allowed_errors):
            raise GitLabError(self._error_message(status, target, data))
        return GitLabResponse(status, data, headers)

    def request_text(self, method: str, path: str) -> GitLabResponse:
        target = self._target(path)
        status, headers, raw = self._perform(
            method,
            target,
            body=None,
            headers=self._headers(),
        )
        text = raw.decode("utf-8", "replace")
        if status >= 400:
            raise GitLabError(self._error_message(status, target, text))
        return GitLabResponse(status, text, headers)

    @staticmethod
    def project_selector(project: str | int) -> str:
        value = str(project).strip()
        if not value:
            raise GitLabError("project must be a numeric id or path_with_namespace")
        return urllib.parse.quote(value, safe="")

    def profile_status(self) -> dict[str, Any]:
        user = self.request("GET", "/user").data
        version = self.request("GET", "/version", allowed_errors={401, 403, 404}).data
        if not isinstance(user, dict):
            raise GitLabError("unexpected GitLab /user response")
        return {
            "profile": self.profile.public(),
            "authenticated_user": {
                "id": user.get("id"),
                "username": user.get("username"),
                "name": user.get("name"),
                "state": user.get("state"),
                "web_url": user.get("web_url"),
            },
            "gitlab_version": version if isinstance(version, dict) else {},
            "status": "ok",
        }

    def list_projects(
        self,
        search: str = "",
        membership: bool = True,
        owned: bool = False,
        min_access_level: int = 0,
        page: int = 1,
        per_page: int = 100,
    ) -> dict[str, Any]:
        if page <= 0 or per_page <= 0 or per_page > 100:
            raise GitLabError("page must be > 0 and per_page must be between 1 and 100")
        query: dict[str, Any] = {
            "membership": membership,
            "owned": owned,
            "simple": True,
            "page": page,
            "per_page": per_page,
            "order_by": "path",
            "sort": "asc",
        }
        if search.strip():
            query["search"] = search.strip()
        if min_access_level:
            query["min_access_level"] = min_access_level
        response = self.request("GET", "/projects", query=query)
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab project list response")
        return {
            "profile_id": self.profile.profile_id,
            "projects": response.data,
            "page": page,
            "per_page": per_page,
            "next_page": response.headers.get("X-Next-Page", ""),
            "total": _header_int(response.headers, "X-Total"),
            "total_pages": _header_int(response.headers, "X-Total-Pages"),
        }

    def project_status(self, project: str | int) -> dict[str, Any]:
        selector = self.project_selector(project)
        data = self.request("GET", f"/projects/{selector}").data
        if not isinstance(data, dict):
            raise GitLabError("unexpected GitLab project response")
        return {"profile_id": self.profile.profile_id, "project": data}

    def get_file(self, project: str | int, path: str, ref: str = "main") -> dict[str, Any]:
        selector = self.project_selector(project)
        file_path = urllib.parse.quote(path.strip("/"), safe="")
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/files/{file_path}",
            query={"ref": ref},
        )
        data = response.data
        if not isinstance(data, dict):
            raise GitLabError("unexpected GitLab repository file response")
        encoding = str(data.get("encoding", ""))
        content = str(data.get("content", ""))
        if encoding != "base64":
            raise GitLabError(f"unsupported GitLab repository file encoding: {encoding}")
        decoded = base64.b64decode(content).decode("utf-8", "replace")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "path": data.get("file_path", path),
            "ref": ref,
            "blob_id": data.get("blob_id"),
            "commit_id": data.get("commit_id"),
            "last_commit_id": data.get("last_commit_id"),
            "size": data.get("size"),
            "content": decoded,
        }

    def list_tree(
        self,
        project: str | int,
        path: str = "",
        ref: str = "main",
        recursive: bool = False,
        page: int = 1,
        per_page: int = 100,
    ) -> dict[str, Any]:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/tree",
            query={
                "path": path or None,
                "ref": ref,
                "recursive": recursive,
                "page": page,
                "per_page": per_page,
            },
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab repository tree response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "items": response.data,
            "page": page,
            "per_page": per_page,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def search_code(
        self,
        project: str | int,
        search: str,
        ref: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> dict[str, Any]:
        selector = self.project_selector(project)
        query: dict[str, Any] = {
            "scope": "blobs",
            "search": search,
            "page": page,
            "per_page": per_page,
        }
        if ref:
            query["ref"] = ref
        response = self.request("GET", f"/projects/{selector}/search", query=query)
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab code search response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "results": response.data,
            "page": page,
            "per_page": per_page,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def put_file(
        self,
        project: str | int,
        path: str,
        content: str,
        branch: str,
        commit_message: str,
        last_commit_id: str = "",
    ) -> dict[str, Any]:
        branch = _assert_mutable_branch(branch)
        selector = self.project_selector(project)
        file_path = urllib.parse.quote(path.strip("/"), safe="")
        existing = self.request(
            "GET",
            f"/projects/{selector}/repository/files/{file_path}",
            query={"ref": branch},
            allowed_errors={404},
        )
        method = "POST" if existing.status == 404 else "PUT"
        payload: dict[str, Any] = {
            "branch": branch,
            "content": content,
            "commit_message": commit_message,
        }
        if last_commit_id:
            payload["last_commit_id"] = last_commit_id
        response = self.request(
            method,
            f"/projects/{selector}/repository/files/{file_path}",
            payload=payload,
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "path": path,
            "branch": branch,
            "operation": "create" if method == "POST" else "update",
            "result": response.data,
        }

    def delete_file(
        self,
        project: str | int,
        path: str,
        branch: str,
        commit_message: str,
        last_commit_id: str = "",
    ) -> dict[str, Any]:
        branch = _assert_mutable_branch(branch)
        selector = self.project_selector(project)
        file_path = urllib.parse.quote(path.strip("/"), safe="")
        payload: dict[str, Any] = {
            "branch": branch,
            "commit_message": commit_message,
        }
        if last_commit_id:
            payload["last_commit_id"] = last_commit_id
        response = self.request(
            "DELETE",
            f"/projects/{selector}/repository/files/{file_path}",
            payload=payload,
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "path": path,
            "branch": branch,
            "result": response.data,
        }

    def commit_actions(
        self,
        project: str | int,
        branch: str,
        commit_message: str,
        actions: list[dict[str, Any]],
        start_branch: str = "",
    ) -> dict[str, Any]:
        branch = _assert_mutable_branch(branch)
        if not actions:
            raise GitLabError("actions must not be empty")
        allowed = {"create", "update", "delete", "move", "chmod"}
        clean_actions = []
        for action in actions:
            if not isinstance(action, dict):
                raise GitLabError("each commit action must be an object")
            kind = str(action.get("action", "")).strip()
            if kind not in allowed:
                raise GitLabError(f"unsupported commit action: {kind}")
            file_path = str(action.get("file_path", "")).strip("/")
            if not file_path:
                raise GitLabError("commit action file_path must not be empty")
            clean_actions.append(dict(action))
        selector = self.project_selector(project)
        payload: dict[str, Any] = {
            "branch": branch,
            "commit_message": commit_message,
            "actions": clean_actions,
        }
        if start_branch:
            payload["start_branch"] = start_branch
        response = self.request(
            "POST",
            f"/projects/{selector}/repository/commits",
            payload=payload,
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "branch": branch,
            "commit": response.data,
        }

    def list_branches(
        self,
        project: str | int,
        search: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> dict[str, Any]:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/branches",
            query={"search": search or None, "page": page, "per_page": per_page},
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab branch list response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "branches": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def create_branch(
        self,
        project: str | int,
        branch: str,
        ref: str,
    ) -> dict[str, Any]:
        branch = _assert_mutable_branch(branch)
        selector = self.project_selector(project)
        response = self.request(
            "POST",
            f"/projects/{selector}/repository/branches",
            query={"branch": branch, "ref": ref},
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "branch": response.data,
        }

    def delete_branch(self, project: str | int, branch: str) -> dict[str, Any]:
        branch = _assert_mutable_branch(branch)
        selector = self.project_selector(project)
        branch_q = urllib.parse.quote(branch, safe="")
        response = self.request(
            "DELETE",
            f"/projects/{selector}/repository/branches/{branch_q}",
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "branch": branch,
            "status": response.status,
            "deleted": True,
        }

    def compare(
        self,
        project: str | int,
        from_ref: str,
        to_ref: str,
        straight: bool = False,
    ) -> dict[str, Any]:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/compare",
            query={"from": from_ref, "to": to_ref, "straight": straight},
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "comparison": response.data,
        }

    def list_merge_requests(
        self,
        project: str | int,
        state: str = "opened",
        source_branch: str = "",
        target_branch: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> dict[str, Any]:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/merge_requests",
            query={
                "state": state or None,
                "source_branch": source_branch or None,
                "target_branch": target_branch or None,
                "page": page,
                "per_page": per_page,
            },
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab merge request list response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "merge_requests": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def get_merge_request(self, project: str | int, iid: int) -> dict[str, Any]:
        selector = self.project_selector(project)
        data = self.request(
            "GET",
            f"/projects/{selector}/merge_requests/{iid}",
            query={"include_diverged_commits_count": True, "include_rebase_in_progress": True},
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "merge_request": data,
        }

    def create_merge_request(
        self,
        project: str | int,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str = "",
        remove_source_branch: bool = False,
        squash: bool = False,
        draft: bool = False,
    ) -> dict[str, Any]:
        selector = self.project_selector(project)
        mr_title = title
        if draft and not title.lower().startswith(("draft:", "wip:")):
            mr_title = f"Draft: {title}"
        payload = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": mr_title,
            "description": description,
            "remove_source_branch": remove_source_branch,
            "squash": squash,
        }
        data = self.request(
            "POST",
            f"/projects/{selector}/merge_requests",
            payload=payload,
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "merge_request": data,
        }

    def update_merge_request(
        self,
        project: str | int,
        iid: int,
        title: str | None = None,
        description: str | None = None,
        state_event: str | None = None,
        target_branch: str | None = None,
        remove_source_branch: bool | None = None,
        squash: bool | None = None,
    ) -> dict[str, Any]:
        selector = self.project_selector(project)
        payload: dict[str, Any] = {}
        for key, value in {
            "title": title,
            "description": description,
            "state_event": state_event,
            "target_branch": target_branch,
            "remove_source_branch": remove_source_branch,
            "squash": squash,
        }.items():
            if value is not None:
                payload[key] = value
        if not payload:
            raise GitLabError("at least one merge request field must be supplied")
        data = self.request(
            "PUT",
            f"/projects/{selector}/merge_requests/{iid}",
            payload=payload,
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "merge_request": data,
        }

    def merge_merge_request(
        self,
        project: str | int,
        iid: int,
        sha: str = "",
        squash: bool | None = None,
        should_remove_source_branch: bool | None = None,
        merge_when_pipeline_succeeds: bool = False,
        merge_commit_message: str = "",
        squash_commit_message: str = "",
    ) -> dict[str, Any]:
        selector = self.project_selector(project)
        payload: dict[str, Any] = {
            "merge_when_pipeline_succeeds": merge_when_pipeline_succeeds,
        }
        if sha:
            payload["sha"] = sha
        if squash is not None:
            payload["squash"] = squash
        if should_remove_source_branch is not None:
            payload["should_remove_source_branch"] = should_remove_source_branch
        if merge_commit_message:
            payload["merge_commit_message"] = merge_commit_message
        if squash_commit_message:
            payload["squash_commit_message"] = squash_commit_message
        data = self.request(
            "PUT",
            f"/projects/{selector}/merge_requests/{iid}/merge",
            payload=payload,
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "merge_request": data,
        }

    def list_issues(
        self,
        project: str | int,
        state: str = "opened",
        search: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> dict[str, Any]:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/issues",
            query={
                "state": state or None,
                "search": search or None,
                "page": page,
                "per_page": per_page,
            },
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab issue list response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "issues": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def get_issue(self, project: str | int, iid: int) -> dict[str, Any]:
        selector = self.project_selector(project)
        data = self.request("GET", f"/projects/{selector}/issues/{iid}").data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "issue": data,
        }

    def create_issue(
        self,
        project: str | int,
        title: str,
        description: str = "",
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        selector = self.project_selector(project)
        payload: dict[str, Any] = {"title": title, "description": description}
        if labels:
            payload["labels"] = ",".join(labels)
        data = self.request(
            "POST",
            f"/projects/{selector}/issues",
            payload=payload,
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "issue": data,
        }

    def update_issue(
        self,
        project: str | int,
        iid: int,
        title: str | None = None,
        description: str | None = None,
        state_event: str | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        selector = self.project_selector(project)
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if description is not None:
            payload["description"] = description
        if state_event is not None:
            payload["state_event"] = state_event
        if labels is not None:
            payload["labels"] = ",".join(labels)
        if not payload:
            raise GitLabError("at least one issue field must be supplied")
        data = self.request(
            "PUT",
            f"/projects/{selector}/issues/{iid}",
            payload=payload,
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "issue": data,
        }

    def add_issue_note(
        self,
        project: str | int,
        iid: int,
        body: str,
    ) -> dict[str, Any]:
        selector = self.project_selector(project)
        data = self.request(
            "POST",
            f"/projects/{selector}/issues/{iid}/notes",
            payload={"body": body},
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "note": data,
        }

    def list_pipelines(
        self,
        project: str | int,
        ref: str = "",
        status: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> dict[str, Any]:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/pipelines",
            query={
                "ref": ref or None,
                "status": status or None,
                "page": page,
                "per_page": per_page,
                "order_by": "id",
                "sort": "desc",
            },
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab pipeline list response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "pipelines": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def list_pipeline_jobs(
        self,
        project: str | int,
        pipeline_id: int,
        page: int = 1,
        per_page: int = 100,
    ) -> dict[str, Any]:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/pipelines/{pipeline_id}/jobs",
            query={"page": page, "per_page": per_page},
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab pipeline jobs response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "pipeline_id": pipeline_id,
            "jobs": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def job_trace(
        self,
        project: str | int,
        job_id: int,
        max_chars: int = 100_000,
    ) -> dict[str, Any]:
        if max_chars <= 0 or max_chars > 2_000_000:
            raise GitLabError("max_chars must be between 1 and 2000000")
        selector = self.project_selector(project)
        response = self.request_text(
            "GET",
            f"/projects/{selector}/jobs/{job_id}/trace",
        )
        trace = str(response.data)
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "job_id": job_id,
            "truncated": len(trace) > max_chars,
            "trace_tail": trace[-max_chars:],
        }

    def retry_pipeline(self, project: str | int, pipeline_id: int) -> dict[str, Any]:
        selector = self.project_selector(project)
        data = self.request(
            "POST",
            f"/projects/{selector}/pipelines/{pipeline_id}/retry",
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "pipeline": data,
        }

    def cancel_pipeline(self, project: str | int, pipeline_id: int) -> dict[str, Any]:
        selector = self.project_selector(project)
        data = self.request(
            "POST",
            f"/projects/{selector}/pipelines/{pipeline_id}/cancel",
        ).data
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "pipeline": data,
        }


def _header_int(headers: dict[str, str], name: str) -> int | None:
    raw = headers.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
