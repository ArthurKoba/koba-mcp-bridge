import pytest

from koba_mcp_bridge.github_agent import GitHubAgentError
from koba_mcp_bridge.github_workflow import GitHubDevClient


class CopyMoveClient(GitHubDevClient):
    def __init__(
        self,
        *,
        source_sha: str = "head-sha",
        second_head: str = "head-sha",
        destination_exists: bool = False,
    ) -> None:
        super().__init__(app_id="123", private_key="unused")
        self.source_sha = source_sha
        self.second_head = second_head
        self.destination_exists = destination_exists
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

        if method == "GET" and "/commits/" in endpoint and "/git/commits/" not in endpoint:
            return 200, {"sha": self.source_sha}
        if method == "GET" and endpoint.endswith("/git/ref/heads/feature%2Ftest"):
            self.ref_reads += 1
            sha = "head-sha" if self.ref_reads == 1 else self.second_head
            return 200, {"object": {"sha": sha}}
        if method == "GET" and endpoint.endswith("/git/commits/head-sha"):
            return 200, {"tree": {"sha": "tree-head"}}
        if method == "GET" and endpoint.endswith("/git/commits/source-sha"):
            return 200, {"tree": {"sha": "tree-source"}}
        if method == "GET" and endpoint.endswith("/git/trees/tree-head"):
            entries = [
                {"path": "old", "type": "tree", "sha": "tree-old", "mode": "040000"},
                {"path": "new", "type": "tree", "sha": "tree-new-dir", "mode": "040000"},
            ]
            return 200, {"tree": entries}
        if method == "GET" and endpoint.endswith("/git/trees/tree-source"):
            return 200, {
                "tree": [
                    {"path": "old", "type": "tree", "sha": "tree-old", "mode": "040000"}
                ]
            }
        if method == "GET" and endpoint.endswith("/git/trees/tree-old"):
            return 200, {
                "tree": [
                    {
                        "path": "large.bin",
                        "type": "blob",
                        "sha": "blob-large",
                        "mode": "100755",
                        "size": 73400320,
                    }
                ]
            }
        if method == "GET" and endpoint.endswith("/git/trees/tree-new-dir"):
            if self.destination_exists:
                return 200, {
                    "tree": [
                        {
                            "path": "large.bin",
                            "type": "blob",
                            "sha": "blob-existing",
                            "mode": "100644",
                            "size": 1,
                        }
                    ]
                }
            return 200, {"tree": []}
        if method == "POST" and endpoint.endswith("/git/trees"):
            return 201, {"sha": "tree-result"}
        if method == "POST" and endpoint.endswith("/git/commits"):
            return 201, {"sha": "commit-result"}
        if method == "PATCH" and endpoint.endswith("/git/refs/heads/feature%2Ftest"):
            return 200, {"object": {"sha": "commit-result"}}
        raise AssertionError(f"unexpected request: {method} {endpoint} payload={payload!r}")


def test_copy_files_uses_tree_metadata_without_reading_blob_contents() -> None:
    dev = CopyMoveClient(source_sha="source-sha")

    result = dev.copy_files(
        "ArthurKoba/koba-mcp-bridge",
        "source-tag",
        "feature/test",
        "copy large file",
        [{"source_path": "old/large.bin", "destination_path": "new/large.bin"}],
        operation="copy",
    )

    assert result["copied"] == [
        {
            "source_path": "old/large.bin",
            "destination_path": "new/large.bin",
            "sha": "blob-large",
            "mode": "100755",
            "size": 73400320,
        }
    ]
    assert result["moved"] == []
    assert not any("/contents/" in endpoint for _, endpoint, _ in dev.calls)
    assert not any(endpoint.endswith("/git/blobs") for _, endpoint, _ in dev.calls)


def test_move_files_reuses_blob_and_deletes_source_in_same_tree() -> None:
    dev = CopyMoveClient()

    result = dev.copy_files(
        "ArthurKoba/koba-mcp-bridge",
        "feature/test",
        "feature/test",
        "rename large file",
        [{"source_path": "old/large.bin", "destination_path": "new/large.bin"}],
        expected_head_sha="head-sha",
        operation="move",
    )

    assert result["copied"] == []
    assert result["moved"][0]["sha"] == "blob-large"
    tree_call = next(
        call
        for call in dev.calls
        if call[0] == "POST" and call[1].endswith("/git/trees")
    )
    assert tree_call[2] == {
        "base_tree": "tree-head",
        "tree": [
            {
                "path": "new/large.bin",
                "mode": "100755",
                "type": "blob",
                "sha": "blob-large",
            },
            {
                "path": "old/large.bin",
                "mode": "100755",
                "type": "blob",
                "sha": None,
            },
        ],
    }


def test_move_requires_source_ref_at_destination_head() -> None:
    dev = CopyMoveClient(source_sha="source-sha")

    with pytest.raises(GitHubAgentError, match="move requires source_ref"):
        dev.copy_files(
            "ArthurKoba/koba-mcp-bridge",
            "source-tag",
            "feature/test",
            "move",
            [{"source_path": "old/large.bin", "destination_path": "new/large.bin"}],
            operation="move",
        )

    assert not any(method == "POST" for method, _, _ in dev.calls)


def test_copy_files_refuses_existing_destination_by_default() -> None:
    dev = CopyMoveClient(destination_exists=True)

    with pytest.raises(GitHubAgentError, match="destination_path already exists"):
        dev.copy_files(
            "ArthurKoba/koba-mcp-bridge",
            "feature/test",
            "feature/test",
            "copy",
            [{"source_path": "old/large.bin", "destination_path": "new/large.bin"}],
        )


def test_copy_files_detects_branch_race_before_ref_update() -> None:
    dev = CopyMoveClient(second_head="raced-head")

    with pytest.raises(GitHubAgentError, match="branch head changed before update"):
        dev.copy_files(
            "ArthurKoba/koba-mcp-bridge",
            "feature/test",
            "feature/test",
            "copy",
            [{"source_path": "old/large.bin", "destination_path": "new/large.bin"}],
        )

    assert not any(method == "PATCH" for method, _, _ in dev.calls)
