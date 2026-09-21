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


def test_atomic_commit_copy_reuses_existing_blob_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dev = client()
    calls: list[tuple[str, str, object | None]] = []

    def fake_repo_request(
        repository: str,
        method: str,
        endpoint: str,
        *,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, object]:
        calls.append((method, endpoint, payload))
        if endpoint.endswith("/git/ref/heads/feature%2Ftest"):
            return 200, {"object": {"sha": "head-sha"}}
        if endpoint.endswith("/git/commits/head-sha"):
            return 200, {"tree": {"sha": "base-tree"}}
        if endpoint.endswith("/commits/files"):
            return 200, {"sha": "source-commit-sha"}
        if "/contents/source.bin?ref=source-commit-sha" in endpoint:
            return 200, {
                "type": "file",
                "sha": "existing-blob-sha",
                "size": 1048576,
            }
        if endpoint.endswith("/git/trees"):
            assert payload == {
                "base_tree": "base-tree",
                "tree": [
                    {
                        "path": "firmware/stock/dump.bin",
                        "mode": "100644",
                        "type": "blob",
                        "sha": "existing-blob-sha",
                    }
                ],
            }
            return 201, {"sha": "tree-sha"}
        if endpoint.endswith("/git/commits"):
            return 201, {"sha": "commit-sha"}
        if endpoint.endswith("/git/refs/heads/feature%2Ftest"):
            assert payload == {"sha": "commit-sha", "force": False}
            return 200, {}
        raise AssertionError(f"unexpected request: {method} {endpoint}")

    monkeypatch.setattr(dev, "_repo_request", fake_repo_request)

    result = dev.commit_files(
        "ArthurKoba/koba-mcp-bridge",
        "feature/test",
        "copy evidence",
        [
            {
                "operation": "copy",
                "path": "firmware/stock/dump.bin",
                "source_ref": "files",
                "source_path": "source.bin",
            }
        ],
        expected_head_sha="head-sha",
    )

    assert result["commit_sha"] == "commit-sha"
    assert not any(endpoint.endswith("/git/blobs") for _, endpoint, _ in calls)


def test_atomic_commit_copy_pins_source_ref_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dev = client()
    source_resolutions = 0

    def fake_repo_request(
        repository: str,
        method: str,
        endpoint: str,
        *,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, object]:
        nonlocal source_resolutions
        if endpoint.endswith("/git/ref/heads/feature%2Ftest"):
            return 200, {"object": {"sha": "head-sha"}}
        if endpoint.endswith("/git/commits/head-sha"):
            return 200, {"tree": {"sha": "base-tree"}}
        if endpoint.endswith("/commits/files"):
            source_resolutions += 1
            return 200, {"sha": "source-commit-sha"}
        if "?ref=source-commit-sha" in endpoint:
            name = endpoint.split("/contents/", 1)[1].split("?", 1)[0]
            return 200, {"type": "file", "sha": f"blob-{name}", "size": 1}
        if endpoint.endswith("/git/trees"):
            return 201, {"sha": "tree-sha"}
        if endpoint.endswith("/git/commits"):
            return 201, {"sha": "commit-sha"}
        if endpoint.endswith("/git/refs/heads/feature%2Ftest"):
            return 200, {}
        raise AssertionError(f"unexpected request: {method} {endpoint}")

    monkeypatch.setattr(dev, "_repo_request", fake_repo_request)

    dev.commit_files(
        "ArthurKoba/koba-mcp-bridge",
        "feature/test",
        "copy evidence",
        [
            {
                "operation": "copy",
                "path": "a.bin",
                "source_ref": "files",
                "source_path": "a.bin",
            },
            {
                "operation": "copy",
                "path": "b.bin",
                "source_ref": "files",
                "source_path": "b.bin",
            },
        ],
    )

    assert source_resolutions == 1


def test_invalid_binary_content_is_blocked() -> None:
    with pytest.raises(GitHubAgentError, match="valid base64"):
        client().put_binary_file(
            "ArthurKoba/koba-mcp-bridge",
            "payload.bin",
            "not base64!",
            "message",
            "feature/test",
        )



def test_copy_files_requires_entries() -> None:
    with pytest.raises(GitHubAgentError, match="copies must not be empty"):
        client().copy_files(
            "ArthurKoba/koba-mcp-bridge",
            "files",
            "feature/test",
            "copy",
            [],
        )


def test_copy_files_reuses_existing_blob_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dev = client()
    calls: list[tuple[str, str, object | None]] = []

    def fake_repo_request(
        repository: str,
        method: str,
        endpoint: str,
        *,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, object]:
        calls.append((method, endpoint, payload))
        if endpoint.endswith("/commits/files"):
            return 200, {"sha": "source-commit-sha"}
        if method == "GET" and endpoint.endswith("/git/ref/heads/feature%2Ftest"):
            return 200, {"object": {"sha": "head-sha"}}
        if endpoint.endswith("/git/commits/head-sha"):
            return 200, {"tree": {"sha": "base-tree"}}
        if endpoint.endswith("/git/commits/source-commit-sha"):
            return 200, {"tree": {"sha": "source-tree"}}
        if endpoint.endswith("/git/trees/source-tree"):
            return 200, {
                "tree": [
                    {
                        "path": "source.bin",
                        "type": "blob",
                        "sha": "existing-blob-sha",
                        "mode": "100644",
                        "size": 1048576,
                    }
                ]
            }
        if endpoint.endswith("/git/trees/base-tree"):
            return 200, {
                "tree": [
                    {
                        "path": "nested",
                        "type": "tree",
                        "sha": "nested-tree",
                        "mode": "040000",
                    }
                ]
            }
        if endpoint.endswith("/git/trees/nested-tree"):
            return 200, {"tree": []}
        if endpoint.endswith("/git/trees"):
            assert payload == {
                "base_tree": "base-tree",
                "tree": [
                    {
                        "path": "nested/destination.bin",
                        "mode": "100644",
                        "type": "blob",
                        "sha": "existing-blob-sha",
                    }
                ],
            }
            return 201, {"sha": "new-tree"}
        if endpoint.endswith("/git/commits"):
            return 201, {"sha": "new-commit"}
        if method == "PATCH" and endpoint.endswith("/git/refs/heads/feature%2Ftest"):
            assert payload == {"sha": "new-commit", "force": False}
            return 200, {}
        raise AssertionError(f"unexpected request: {method} {endpoint}")

    monkeypatch.setattr(dev, "_repo_request", fake_repo_request)

    result = dev.copy_files(
        "ArthurKoba/koba-mcp-bridge",
        "files",
        "feature/test",
        "copy evidence",
        [
            {
                "source_path": "source.bin",
                "destination_path": "nested/destination.bin",
            }
        ],
        expected_head_sha="head-sha",
    )

    assert result["commit_sha"] == "new-commit"
    assert result["source_sha"] == "source-commit-sha"
    assert result["copied"] == [
        {
            "source_path": "source.bin",
            "destination_path": "nested/destination.bin",
            "sha": "existing-blob-sha",
            "mode": "100644",
            "size": 1048576,
        }
    ]
    assert result["moved"] == []
    assert not any("/contents/" in endpoint for _, endpoint, _ in calls)
    assert not any(endpoint.endswith("/git/blobs") for _, endpoint, _ in calls)


def test_copy_files_detects_branch_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dev = client()
    ref_reads = 0

    def fake_repo_request(
        repository: str,
        method: str,
        endpoint: str,
        *,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, object]:
        nonlocal ref_reads
        if endpoint.endswith("/commits/files"):
            return 200, {"sha": "source-commit-sha"}
        if method == "GET" and endpoint.endswith("/git/ref/heads/feature%2Ftest"):
            ref_reads += 1
            sha = "head-sha" if ref_reads == 1 else "changed-head"
            return 200, {"object": {"sha": sha}}
        if endpoint.endswith("/git/commits/head-sha"):
            return 200, {"tree": {"sha": "base-tree"}}
        if endpoint.endswith("/git/commits/source-commit-sha"):
            return 200, {"tree": {"sha": "source-tree"}}
        if endpoint.endswith("/git/trees/source-tree"):
            return 200, {
                "tree": [
                    {
                        "path": "source.bin",
                        "type": "blob",
                        "sha": "blob-sha",
                        "mode": "100644",
                        "size": 7,
                    }
                ]
            }
        if endpoint.endswith("/git/trees/base-tree"):
            return 200, {"tree": []}
        if endpoint.endswith("/git/trees"):
            return 201, {"sha": "new-tree"}
        if endpoint.endswith("/git/commits"):
            return 201, {"sha": "new-commit"}
        raise AssertionError(f"unexpected request: {method} {endpoint}")

    monkeypatch.setattr(dev, "_repo_request", fake_repo_request)

    with pytest.raises(GitHubAgentError, match="branch head changed before update"):
        dev.copy_files(
            "ArthurKoba/koba-mcp-bridge",
            "files",
            "feature/test",
            "copy evidence",
            [
                {
                    "source_path": "source.bin",
                    "destination_path": "destination.bin",
                }
            ],
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
