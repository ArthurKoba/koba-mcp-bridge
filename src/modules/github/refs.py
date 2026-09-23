from __future__ import annotations

import urllib.parse

from common.models import (
    JsonObject,
    json_array,
    json_bool,
    json_int,
    json_member_array,
    json_member_object,
    json_object,
    json_str,
)

from .base import GitHubRepositoryClientBase
from .github_agent import GitHubAgentError
from .policy import protected_branches_from_env


class GitHubRefsClient(GitHubRepositoryClientBase):
    def list_branches(self, repository: str) -> JsonObject:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/branches?per_page=100",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected branch list response")
        branches: list[JsonObject] = []
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
        return {
            "repository": repository,
            "branches": json_array(branches, context="GitHub branches"),
        }

    def create_branch(self, repository: str, branch: str, from_branch: str) -> JsonObject:
        repository = self._assert_allowed(repository)
        source = self._quote(from_branch)
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

    def compare(self, repository: str, base: str, head: str) -> JsonObject:
        repository = self._assert_allowed(repository)
        base_q = self._quote(base)
        head_q = self._quote(head)
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

        normalized_files: list[JsonObject] = []
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
            "files": json_array(normalized_files, context="GitHub compare files"),
        }

    def list_commits(
        self,
        repository: str,
        ref: str | None = None,
        path: str | None = None,
        per_page: int = 50,
        page: int = 1,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        params: dict[str, str | int] = {
            "per_page": max(1, min(per_page, 100)),
            "page": max(1, page),
        }
        if ref:
            params["sha"] = ref
        if path:
            params["path"] = path
        query = urllib.parse.urlencode(params)
        _, result = self._repo_request(
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
            details = json_member_object(item, "commit")
            author = json_member_object(details, "author")
            commits.append(
                {
                    "sha": json_str(item.get("sha")),
                    "message": json_str(details.get("message")),
                    "author": json_str(author.get("name")),
                    "date": json_str(author.get("date")),
                }
            )
        return {
            "repository": repository,
            "commits": json_array(commits, context="GitHub commits"),
            "page": page,
        }

    def get_commit(self, repository: str, ref: str) -> JsonObject:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self._quote(ref)}",
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected commit response")
        details = json_member_object(result, "commit")
        files = json_member_array(result, "files")
        return {
            "repository": repository,
            "sha": json_str(result.get("sha")),
            "message": json_str(details.get("message")),
            "parents": [
                json_str(item.get("sha"))
                for item in json_member_array(result, "parents")
                if isinstance(item, dict)
            ],
            "files": [
                {
                    "filename": json_str(item.get("filename")),
                    "status": json_str(item.get("status")),
                    "additions": json_int(item.get("additions")),
                    "deletions": json_int(item.get("deletions")),
                    "patch": item.get("patch"),
                }
                for item in files
                if isinstance(item, dict)
            ],
        }

    def delete_branch(self, repository: str, branch: str) -> JsonObject:
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        self._repo_request(
            repository,
            "DELETE",
            f"/repos/{repository}/git/refs/heads/{self._quote(branch)}",
        )
        return {"repository": repository, "branch": branch, "deleted": True}

    def rename_branch(
        self,
        repository: str,
        branch: str,
        new_name: str,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        new_name = self._assert_mutable_branch(new_name)
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/branches/{self._quote(branch)}/rename",
            payload={"new_name": new_name},
        )
        return {
            "repository": repository,
            "old_branch": branch,
            "new_branch": new_name,
            "result": result,
        }

    def fast_forward(self, repository: str, branch: str, to_ref: str) -> JsonObject:
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        to_q = self._quote(to_ref)
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
        branch_q = self._quote(branch)
        _, result = self._repo_request(
            repository,
            "PATCH",
            f"/repos/{repository}/git/refs/heads/{branch_q}",
            payload={"sha": sha, "force": False},
        )
        return {"repository": repository, "branch": branch, "sha": sha, "result": result}

    def reset_branch(
        self,
        repository: str,
        branch: str,
        target_ref: str,
        expected_head_sha: str,
        allow_protected_branch: bool = False,
        dry_run: bool = True,
    ) -> JsonObject:
        """Force-reset a branch to an existing ancestor commit with CAS safeguards."""
        repository = self._assert_allowed(repository)
        branch = branch.strip()
        target_ref = target_ref.strip()
        expected_head_sha = expected_head_sha.strip()
        if not branch:
            raise GitHubAgentError("branch must not be empty")
        if not target_ref:
            raise GitHubAgentError("target_ref must not be empty")
        if not expected_head_sha:
            raise GitHubAgentError("expected_head_sha must not be empty")
        if (
            branch.casefold() in protected_branches_from_env()
            and not allow_protected_branch
        ):
            raise GitHubAgentError(
                f"reset of protected branch requires allow_protected_branch=true: {branch}"
            )

        branch_q = self._quote(branch)
        _, ref = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_q}",
        )
        if not isinstance(ref, dict):
            raise GitHubAgentError("unable to resolve branch head")
        head_sha = json_str(
            json_member_object(ref, "object", required=True).get("sha")
        )
        if not head_sha:
            raise GitHubAgentError("branch head has no sha")
        if head_sha != expected_head_sha:
            raise GitHubAgentError(
                f"branch head changed: expected {expected_head_sha}, found {head_sha}"
            )

        _, target = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self._quote(target_ref)}",
        )
        if not isinstance(target, dict):
            raise GitHubAgentError("unable to resolve target_ref")
        target_sha = json_str(target.get("sha"))
        if not target_sha:
            raise GitHubAgentError("unable to resolve target_ref")

        if target_sha != head_sha:
            _, comparison = self._repo_request(
                repository,
                "GET",
                (
                    f"/repos/{repository}/compare/"
                    f"{self._quote(target_sha)}...{self._quote(head_sha)}"
                ),
            )
            if not isinstance(comparison, dict):
                raise GitHubAgentError("unexpected compare response")
            if (
                json_str(comparison.get("status")) != "ahead"
                or json_int(comparison.get("behind_by")) != 0
            ):
                raise GitHubAgentError(
                    "target_ref must resolve to an ancestor of the current branch head"
                )

        result: JsonObject = {
            "repository": repository,
            "branch": branch,
            "previous_head_sha": head_sha,
            "target_ref": target_ref,
            "target_sha": target_sha,
            "protected_branch_override": allow_protected_branch,
            "dry_run": dry_run,
        }
        if dry_run or target_sha == head_sha:
            return result

        _, current_ref = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_q}",
        )
        current_object = (
            json_member_object(current_ref, "object")
            if isinstance(current_ref, dict)
            else {}
        )
        current_head_sha = json_str(current_object.get("sha"))
        if current_head_sha != head_sha:
            raise GitHubAgentError(
                f"branch head changed before reset: expected {head_sha}, "
                f"found {current_head_sha}"
            )

        _, updated = self._repo_request(
            repository,
            "PATCH",
            f"/repos/{repository}/git/refs/heads/{branch_q}",
            payload={"sha": target_sha, "force": True},
        )
        return {**result, "dry_run": False, "result": updated}

    def list_tags(
        self,
        repository: str,
        per_page: int = 100,
        page: int = 1,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        params = urllib.parse.urlencode(
            {"per_page": max(1, min(per_page, 100)), "page": max(1, page)}
        )
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/tags?{params}",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected tag list response")
        tags = []
        for item in result:
            if isinstance(item, dict):
                commit = json_member_object(item, "commit")
                tags.append(
                    {
                        "name": json_str(item.get("name")),
                        "sha": json_str(commit.get("sha")),
                    }
                )
        return {
            "repository": repository,
            "tags": json_array(tags, context="GitHub tags"),
            "page": page,
        }

    def create_tag(
        self,
        repository: str,
        tag: str,
        target_ref: str,
        message: str | None = None,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        _, target = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self._quote(target_ref)}",
        )
        if not isinstance(target, dict):
            raise GitHubAgentError("unable to resolve tag target")
        target_sha = json_str(target.get("sha"))
        if not target_sha:
            raise GitHubAgentError("unable to resolve tag target")
        ref_sha = target_sha
        annotated = bool(message)
        if message:
            _, tag_obj = self._repo_request(
                repository,
                "POST",
                f"/repos/{repository}/git/tags",
                payload={
                    "tag": tag,
                    "message": message,
                    "object": target_sha,
                    "type": "commit",
                },
            )
            if not isinstance(tag_obj, dict):
                raise GitHubAgentError("GitHub did not return an annotated tag sha")
            ref_sha = json_str(tag_obj.get("sha"))
            if not ref_sha:
                raise GitHubAgentError("GitHub did not return an annotated tag sha")
        self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/git/refs",
            payload={"ref": f"refs/tags/{tag}", "sha": ref_sha},
        )
        return {
            "repository": repository,
            "tag": tag,
            "target_sha": target_sha,
            "annotated": annotated,
        }

    def delete_tag(self, repository: str, tag: str) -> JsonObject:
        repository = self._assert_allowed(repository)
        self._repo_request(
            repository,
            "DELETE",
            f"/repos/{repository}/git/refs/tags/{self._quote(tag)}",
        )
        return {"repository": repository, "tag": tag, "deleted": True}
