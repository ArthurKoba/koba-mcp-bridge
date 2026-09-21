import pytest

import koba_mcp_bridge.github_workflow as github_workflow
from koba_mcp_bridge.github_agent import GitHubAgentError
from koba_mcp_bridge.github_workflow import (
    GitHubDevClient,
    protected_branches_from_env,
    required_checks_from_env,
)


def client() -> GitHubDevClient:
    return GitHubDevClient(
        app_id="123",
        private_key="key-material",
    )


def test_default_protected_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_AGENT_PROTECTED_BRANCHES", raising=False)
    assert protected_branches_from_env() == {"main", "master"}


def test_custom_protected_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", "main,release")
    assert protected_branches_from_env() == {"main", "release"}


def test_protected_branches_prefer_infisical_convention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_PROTECTED_BRANCHES", "legacy")
    monkeypatch.setattr(
        github_workflow,
        "resolve_config_secret",
        lambda path, name: "main,production"
        if (path, name)
        == ("github/development", "PROTECTED_BRANCHES")
        else "",
    )

    assert protected_branches_from_env() == {"main", "production"}


def test_default_required_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_AGENT_REQUIRED_CHECKS", raising=False)
    assert required_checks_from_env() == ["test", "docker"]


def test_direct_write_to_main_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_AGENT_PROTECTED_BRANCHES", raising=False)
    with pytest.raises(GitHubAgentError, match="protected branch"):
        client().put_file(
            "ArthurKoba/koba-mcp-bridge",
            "README.md",
            "content",
            "message",
            "main",
        )


def test_fast_forward_main_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_AGENT_PROTECTED_BRANCHES", raising=False)
    with pytest.raises(GitHubAgentError, match="protected branch"):
        client().fast_forward("ArthurKoba/koba-mcp-bridge", "main", "feature")


def test_cross_repository_pull_request_is_blocked() -> None:
    with pytest.raises(GitHubAgentError, match="cross-repository"):
        client().create_pull_request(
            "ArthurKoba/koba-mcp-bridge",
            "title",
            "someone:branch",
            "main",
        )


def test_same_head_and_base_is_blocked() -> None:
    with pytest.raises(GitHubAgentError, match="head and base"):
        client().create_pull_request(
            "ArthurKoba/koba-mcp-bridge",
            "title",
            "main",
            "main",
        )


def test_empty_atomic_commit_is_blocked() -> None:
    with pytest.raises(GitHubAgentError, match="changes must not be empty"):
        client().commit_files(
            "ArthurKoba/koba-mcp-bridge",
            "feature/test",
            "message",
            [],
        )


def test_invalid_binary_content_is_blocked() -> None:
    with pytest.raises(GitHubAgentError, match="valid base64"):
        client().put_binary_file(
            "ArthurKoba/koba-mcp-bridge",
            "payload.bin",
            "not base64!",
            "message",
            "feature/test",
        )


def test_invalid_review_event_is_blocked() -> None:
    with pytest.raises(GitHubAgentError, match="event must be"):
        client().create_review(
            "ArthurKoba/koba-mcp-bridge",
            1,
            "SHIP_IT",
            "body",
        )


def test_invalid_merge_method_is_blocked() -> None:
    with pytest.raises(GitHubAgentError, match="merge_method"):
        client().merge_pull_request(
            "ArthurKoba/koba-mcp-bridge",
            1,
            "octopus",
        )



def test_required_checks_delegate_when_names_do_not_belong_to_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_REQUIRED_CHECKS", "test,docker")
    dev = client()

    def fake_check_runs(repository: str, ref: str) -> dict[str, object]:
        return {
            "repository": repository,
            "ref": ref,
            "check_runs": [
                {
                    "name": "Build Status",
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        }

    def fake_repo_request(
        repository: str,
        method: str,
        endpoint: str,
        **kwargs: object,
    ) -> tuple[int, object]:
        assert method == "GET"
        assert endpoint == f"/repos/{repository}"
        return 200, {"default_branch": "main"}

    monkeypatch.setattr(dev, "check_runs", fake_check_runs)
    monkeypatch.setattr(dev, "_repo_request", fake_repo_request)

    result = dev.assert_required_checks("ArthurKoba/ghidra-mcp", "head-sha")

    assert result["status"] == "delegated_to_github"


def test_required_checks_stay_strict_when_repository_uses_configured_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_AGENT_REQUIRED_CHECKS", "test,docker")
    dev = client()

    def fake_check_runs(repository: str, ref: str) -> dict[str, object]:
        if ref == "head-sha":
            checks = [
                {"name": "test", "status": "completed", "conclusion": "success"},
            ]
        else:
            checks = [
                {"name": "test", "status": "completed", "conclusion": "success"},
                {"name": "docker", "status": "completed", "conclusion": "success"},
            ]
        return {"repository": repository, "ref": ref, "check_runs": checks}

    def fake_repo_request(
        repository: str,
        method: str,
        endpoint: str,
        **kwargs: object,
    ) -> tuple[int, object]:
        return 200, {"default_branch": "main"}

    monkeypatch.setattr(dev, "check_runs", fake_check_runs)
    monkeypatch.setattr(dev, "_repo_request", fake_repo_request)

    with pytest.raises(GitHubAgentError, match="missing=\\['docker'\\]"):
        dev.assert_required_checks("ArthurKoba/koba-mcp-bridge", "head-sha")


class BlobCopyClient(GitHubDevClient):
    def __init__(
        self,
        *,
        destination_exists: bool = False,
        second_head: str = "head-old",
    ) -> None:
        super().__init__(app_id="123", private_key="unused")
        self.destination_exists = destination_exists
        self.second_head = second_head
        self.calls: list[tuple[str, str, object | None]] = []
        self.ref_reads = 0

    def _repo_request(
        self,
        repository: str,
        method: str,
        endpoint: str,
        *,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, object]:
        del repository, allowed_errors
        self.calls.append((method, endpoint, payload))

        if method == "GET" and endpoint.endswith("/git/ref/heads/feature%2Flarge-file"):
            self.ref_reads += 1
            sha = "head-old" if self.ref_reads == 1 else self.second_head
            return 200, {"object": {"sha": sha}}
        if method == "GET" and endpoint.endswith("/git/commits/head-old"):
            return 200, {"tree": {"sha": "tree-root"}}
        if method == "GET" and endpoint.endswith("/git/trees/tree-root"):
            return 200, {
                "tree": [
                    {"path": "assets", "type": "tree", "sha": "tree-assets", "mode": "040000"},
                    {"path": "archive", "type": "tree", "sha": "tree-archive", "mode": "040000"},
                ]
            }
        if method == "GET" and endpoint.endswith("/git/trees/tree-assets"):
            return 200, {
                "tree": [
                    {
                        "path": "large.bin",
                        "type": "blob",
                        "sha": "blob-large",
                        "mode": "100755",
                    }
                ]
            }
        if method == "GET" and endpoint.endswith("/git/trees/tree-archive"):
            entries = []
            if self.destination_exists:
                entries.append(
                    {
                        "path": "large.bin",
                        "type": "blob",
                        "sha": "blob-existing",
                        "mode": "100644",
                    }
                )
            return 200, {"tree": entries}
        if method == "POST" and endpoint.endswith("/git/trees"):
            return 201, {"sha": "tree-new"}
        if method == "POST" and endpoint.endswith("/git/commits"):
            return 201, {"sha": "commit-new"}
        if method == "PATCH" and endpoint.endswith("/git/refs/heads/feature%2Flarge-file"):
            return 200, {"object": {"sha": "commit-new"}}
        raise AssertionError(f"unexpected request: {method} {endpoint} payload={payload!r}")


def test_copy_blob_reuses_existing_sha_without_blob_upload() -> None:
    dev = BlobCopyClient()

    result = dev.copy_blob(
        "ArthurKoba/koba-mcp-bridge",
        "assets/large.bin",
        "archive/large.bin",
        "copy large binary",
        "feature/large-file",
        expected_head_sha="head-old",
    )

    assert result["operation"] == "copy"
    assert result["reused_blob_sha"] == "blob-large"
    assert result["mode"] == "100755"
    tree_call = next(
        call
        for call in dev.calls
        if call[0] == "POST" and call[1].endswith("/git/trees")
    )
    assert tree_call[2] == {
        "base_tree": "tree-root",
        "tree": [
            {
                "path": "archive/large.bin",
                "mode": "100755",
                "type": "blob",
                "sha": "blob-large",
            }
        ],
    }
    assert not any(
        method == "POST" and endpoint.endswith("/git/blobs")
        for method, endpoint, _ in dev.calls
    )


def test_move_blob_is_atomic_copy_plus_source_delete() -> None:
    dev = BlobCopyClient()

    result = dev.copy_blob(
        "ArthurKoba/koba-mcp-bridge",
        "assets/large.bin",
        "archive/large.bin",
        "rename large binary",
        "feature/large-file",
        operation="move",
    )

    assert result["operation"] == "move"
    tree_call = next(
        call
        for call in dev.calls
        if call[0] == "POST" and call[1].endswith("/git/trees")
    )
    assert tree_call[2] == {
        "base_tree": "tree-root",
        "tree": [
            {
                "path": "archive/large.bin",
                "mode": "100755",
                "type": "blob",
                "sha": "blob-large",
            },
            {
                "path": "assets/large.bin",
                "mode": "100755",
                "type": "blob",
                "sha": None,
            },
        ],
    }


def test_copy_blob_refuses_existing_destination_without_overwrite() -> None:
    dev = BlobCopyClient(destination_exists=True)

    with pytest.raises(GitHubAgentError, match="destination_path already exists"):
        dev.copy_blob(
            "ArthurKoba/koba-mcp-bridge",
            "assets/large.bin",
            "archive/large.bin",
            "copy",
            "feature/large-file",
        )

    assert not any(method == "POST" for method, _, _ in dev.calls)


def test_copy_blob_rechecks_branch_head_before_update() -> None:
    dev = BlobCopyClient(second_head="head-raced")

    with pytest.raises(GitHubAgentError, match="branch head changed before update"):
        dev.copy_blob(
            "ArthurKoba/koba-mcp-bridge",
            "assets/large.bin",
            "archive/large.bin",
            "copy",
            "feature/large-file",
        )

    assert not any(method == "PATCH" for method, _, _ in dev.calls)


def test_copy_blob_respects_protected_branch_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_AGENT_PROTECTED_BRANCHES", raising=False)
    with pytest.raises(GitHubAgentError, match="protected branch"):
        client().copy_blob(
            "ArthurKoba/koba-mcp-bridge",
            "a.bin",
            "b.bin",
            "move",
            "main",
            operation="move",
        )
