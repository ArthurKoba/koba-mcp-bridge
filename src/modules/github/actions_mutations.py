from __future__ import annotations

import urllib.parse

from common.models import JsonObject

from .base import GitHubRepositoryClientBase
from .github_agent import GitHubAgentError


class GitHubActionsMutationClient(GitHubRepositoryClientBase):
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
