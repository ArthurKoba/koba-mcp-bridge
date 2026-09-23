# Files production migration

This migration keeps the old Docker volume untouched until acceptance is complete.

## Preconditions

- PR checks are green.
- A production image exists for the approved commit.
- No file uploads or file-mutating workflows are running during the copy.
- The current bridge container is stopped or in a maintenance window before the final copy.

## 1. Identify current storage

On the Docker host:

```bash
CID="$(docker ps -q --filter ancestor=ghcr.io/arthurkoba/koba-mcp-bridge:latest | head -n1)"

docker inspect "$CID"   --format '{{range .Mounts}}{{println .Name .Destination}}{{end}}'
```

Record the volume mounted at the old storage destination. Do not delete or modify it.

## 2. Create the Files volume

```bash
docker volume create koba-files
```

## 3. Copy persistent data

Replace `OLD_VOLUME` with the discovered volume:

```bash
OLD_VOLUME="<current-volume-name>"

docker run --rm   -v "$OLD_VOLUME":/from:ro   -v koba-files:/to   alpine:3.22   sh -c 'cd /from && cp -a . /to/'
```

The source volume stays read-only and unchanged.

## 4. Verify the raw copy

```bash
docker run --rm -v "$OLD_VOLUME":/from:ro alpine:3.22   sh -c 'find /from/objects/sha256 -type f | wc -l; du -sb /from'

docker run --rm -v koba-files:/to:ro alpine:3.22   sh -c 'find /to/objects/sha256 -type f | wc -l; du -sb /to'
```

Object counts must match.

## 5. Start new Files code only against the new volume

The new runtime uses:

```text
FILE_ROOT=/files
volume: koba-files:/files
database: /files/files.sqlite3
```

On first `FileStore.ensure()`, the application:

1. renames an existing `index.sqlite3` to `files.sqlite3`;
2. migrates old storage table/column names in-place;
3. migrates resumable upload state to `file_id`;
4. leaves content-addressed bytes unchanged.

## 6. Verify the migrated SQLite schema

```bash
python - <<'PY'
import sqlite3

db = sqlite3.connect("/files/files.sqlite3")
tables = {
    row[0]
    for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
}
schema = "\n".join(
    row[0] or ""
    for row in db.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"
    )
)
print("tables:", sorted(tables))
assert {"files", "aliases", "collections", "collection_items", "file_refs"} <= tables
for old_name in (
    "artifacts",
    "artifact_id",
    "source_artifact_id",
    "artifact_refs",
):
    assert old_name not in schema, old_name
print("Files schema: OK")
PY
```

For resumable uploads:

```bash
python - <<'PY'
import os
import sqlite3

path = "/files/uploads.sqlite3"
if os.path.exists(path):
    db = sqlite3.connect(path)
    cols = {
        row[1]
        for row in db.execute("PRAGMA table_info(upload_sessions)")
    }
    assert "file_id" in cols
    assert "artifact_id" not in cols
print("Upload schema: OK")
PY
```

## 7. Modular cutover

Target:

```text
public gateway
  -> github-mcp   (private)
  -> gitlab-mcp   (private)
  -> files-mcp    (private)
  -> http-mcp     (private)
  -> raw ghidra-mcp (native backend)
```

Only the gateway is public.

```text
KOBA_GATEWAY_MODE=proxy
GITHUB_MCP_URL=http://github-mcp:8000/mcp
GITLAB_MCP_URL=http://gitlab-mcp:8000/mcp
FILES_MCP_URL=http://files-mcp:8000/mcp
HTTP_MCP_URL=http://http-mcp:8000/mcp
```

The transitional Ghidra adapter remains in the gateway and translates Koba `file_id`
operations into the unchanged native Ghidra staging contract.

## 8. Acceptance

Verify:

- `file_status`;
- known existing `file_info(file_id)`;
- `file_read`;
- resumable upload;
- HTTP download -> Files;
- HTTP `body_file_id`;
- Ghidra import through the Koba adapter;
- GitHub and GitLab calls through the aggregate gateway;
- dedicated `/gitlab/mcp`.

## Rollback

If acceptance fails:

1. stop the new modular containers;
2. do not copy migrated data back into the old volume;
3. restore the previous production image/configuration;
4. mount the untouched original volume at its previous destination;
5. return to the previous embedded deployment.

The old volume is removed only after production acceptance and backup.
