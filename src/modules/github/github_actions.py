from __future__ import annotations

from common.models import JsonObject, json_member_object, json_str

from .actions_diagnostics import GitHubActionsDiagnosticsClient
from .actions_mutations import GitHubActionsMutationClient
from .contents import GitHubContentsClient
from .github_agent import GitHubAgentError
from .github_collab import GitHubCollabClient
from .github_history import GitHubHistoryMixin
from .issues import GitHubIssueClient
from .policy import protected_branches_from_env
from .refs import GitHubRefsClient
from .runs import GitHubRunClient


class GitHubActionsClient(
    GitHubHistoryMixin,
    GitHubCollabClient,
    GitHubContentsClient,
    GitHubRefsClient,
    GitHubIssueClient,
    GitHubRunClient,
    GitHubActionsDiagnosticsClient,
    GitHubActionsMutationClient,
):
    """Full GitHub client composed from repository, review, history, and Actions capabilities."""

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
