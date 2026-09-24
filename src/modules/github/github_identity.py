from __future__ import annotations

import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from common.account_contracts import ResolvedAccount
from common.models import (
    JsonContainer,
    JsonObject,
    json_int,
    json_member_object,
    json_object,
    json_str,
    json_value,
)
from common.settings import GitHubPolicySettings

from .github_actions import GitHubActionsClient
from .github_agent import GitHubAgentError

_GITHUB_API = "https://api.github.com"


class GitHubPrettyIdentityClient(GitHubActionsClient):
    @classmethod
    def from_account(
        cls,
        account: ResolvedAccount,
        policy: GitHubPolicySettings,
    ) -> GitHubPrettyIdentityClient:
        credential = account.credential.replace("\\n", "\n").strip()
        if not credential:
            raise GitHubAgentError("GitHub account has no credential")
        kwargs = {
            "account_id": account.id,
            "protected_branches": policy.protected_branches,
            "required_checks": policy.required_checks,
            "required_reviewers": policy.required_reviewers,
            "auth_type": account.auth_type,
        }
        if account.auth_type == "github_token":
            return cls(token=credential, **kwargs)
        app_id = (account.external_id or "").strip()
        if not app_id:
            raise GitHubAgentError("GitHub App account has no APP_ID")
        return cls(app_id=app_id, private_key=credential, **kwargs)

    """Use the GitHub App display name for Git-authored objects.

    GitHub still exposes the immutable App actor login (for example
    ``koba-ai-agent[bot]``). Direct Git objects created by the bridge use the
    human-friendly GitHub App name as ``author.name``/``committer.name`` while
    retaining the GitHub-generated bot noreply email for stable attribution.
    """

    def _app_identity(self) -> JsonObject:
        cached = getattr(self, "_app_identity_cache", None)
        if isinstance(cached, dict):
            return dict(cached)

        if self.token:
            _, app = self._request("GET", f"{_GITHUB_API}/user", token=self.token)
            if not isinstance(app, dict):
                raise GitHubAgentError("unexpected GitHub user response")
            login = json_str(app.get("login")).strip()
            if not login:
                raise GitHubAgentError("GitHub user response has no login")
            display_name = json_str(app.get("name")).strip() or login
            user_id = json_int(app.get("id"))
            email = json_str(app.get("email")).strip() or (
                f"{user_id}+{login}@users.noreply.github.com"
            )
            identity: JsonObject = {
                "source": "github_token",
                "display_name": display_name,
                "login": login,
                "id": user_id,
                "type": json_str(app.get("type"), default="User") or "User",
                "name": display_name,
                "email": email,
            }
            self._app_identity_cache = dict(identity)
            return identity

        _, app = self._request(
            "GET",
            f"{_GITHUB_API}/app",
            token=self._app_jwt(),
        )
        if not isinstance(app, dict):
            raise GitHubAgentError("unexpected GitHub App response")

        slug = json_str(app.get("slug")).strip()
        display_name = json_str(app.get("name")).strip()
        if not slug:
            raise GitHubAgentError("GitHub App response has no slug")
        if not display_name:
            display_name = slug

        login = f"{slug}[bot]"
        _, bot = self._request(
            "GET",
            f"{_GITHUB_API}/users/{urllib.parse.quote(login, safe='')}",
        )
        if not isinstance(bot, dict):
            raise GitHubAgentError("unable to resolve GitHub App bot identity")
        try:
            bot_id = json_int(bot.get("id"), field="bot.id")
        except ValueError as exc:
            raise GitHubAgentError("unable to resolve GitHub App bot identity") from exc
        if bot_id <= 0:
            raise GitHubAgentError("unable to resolve GitHub App bot identity")
        identity: JsonObject = {
            "source": "current_agent_app",
            "app_id": self.app_id,
            "slug": slug,
            "display_name": display_name,
            "login": login,
            "id": bot_id,
            "type": json_str(bot.get("type"), default="Bot") or "Bot",
            "name": display_name,
            "email": f"{bot_id}+{login}@users.noreply.github.com",
        }
        self._app_identity_cache = dict(identity)
        return identity

    def _agent_app_identity(self) -> JsonObject:
        """Compatibility hook used by history/admin policy code."""
        return self._app_identity()

    def _git_signature(self) -> dict[str, str]:
        identity = self._app_identity()
        return {
            "name": str(identity["name"]),
            "email": str(identity["email"]),
        }

    @staticmethod
    def _copy_payload(payload: object | None) -> JsonObject | None:
        if payload is None:
            return None
        try:
            return json_object(payload, context="GitHub request payload")
        except ValueError as exc:
            raise GitHubAgentError("GitHub request payload must be JSON-compatible") from exc

    def _repo_request(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, JsonContainer]:
        updated = self._copy_payload(payload)
        contents_prefix = f"/repos/{repository}/contents/"
        commit_path = f"/repos/{repository}/git/commits"
        tag_path = f"/repos/{repository}/git/tags"
        is_direct_commit = updated is not None and (
            (method in {"PUT", "DELETE"} and path.startswith(contents_prefix))
            or (method == "POST" and path == commit_path)
        )

        if updated is not None and is_direct_commit:
            signature = json_value(
                self._git_signature(),
                context="GitHub git signature",
            )
            updated.setdefault("author", signature)
            updated.setdefault("committer", signature)
        elif updated is not None and method == "POST" and path == tag_path:
            updated.setdefault(
                "tagger",
                json_value(
                    self._git_signature(),
                    context="GitHub tagger signature",
                ),
            )

        return super()._repo_request(
            repository,
            method,
            path,
            payload=updated if updated is not None else payload,
            allowed_errors=allowed_errors,
        )

    def account_capabilities(self) -> JsonObject:
        """Return provider-reported account permissions without requiring a repository."""
        if self.token:
            _, user = self._request("GET", f"{_GITHUB_API}/user", token=self.token)
            payload = json_object(user, context="GitHub user response")
            return {
                "account_id": self.account_id,
                "auth_type": self.auth_type,
                "identity": {
                    "login": json_str(payload.get("login")),
                    "name": json_str(payload.get("name")),
                    "type": json_str(payload.get("type")),
                },
                "provider_permissions": {},
                "provider_permissions_known": False,
                "note": (
                    "GitHub user tokens do not expose one reliable account-global permission map; "
                    "effective rights are repository/resource dependent."
                ),
            }

        _, app = self._request("GET", f"{_GITHUB_API}/app", token=self._app_jwt())
        payload = json_object(app, context="GitHub App response")
        permissions = json_member_object(payload, "permissions")
        return {
            "account_id": self.account_id,
            "auth_type": self.auth_type,
            "identity": {
                "app_id": self.app_id,
                "slug": json_str(payload.get("slug")),
                "name": json_str(payload.get("name")),
            },
            "provider_permissions": {
                key: json_str(value) for key, value in permissions.items()
            },
            "provider_permissions_known": True,
            "note": (
                "GitHub App permissions are the application ceiling; installation/repository "
                "selection can further reduce effective rights."
            ),
        }

    def list_repositories(self) -> JsonObject:
        base_list = super().list_repositories
        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="github-list",
        ) as pool:
            repositories_future = pool.submit(base_list)
            identity_future = pool.submit(self._app_identity)
            result = repositories_future.result()
            result["app_identity"] = identity_future.result()
            return result

    def status(self, repository: str) -> JsonObject:
        base_status = super().status
        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="github-status",
        ) as pool:
            status_future = pool.submit(base_status, repository)
            identity_future = pool.submit(self._app_identity)
            result = status_future.result()
            result["app_identity"] = identity_future.result()
            return result
