# Files and service cutover

The modular release uses a hard operational cutover. Runtime code does not contain
compatibility branches for the previous service topology or previous provider-secret
registry.

The persistent Files store keeps the canonical `FileStore` schema and content-addressed
objects. Management starts from an empty management database and creates its current
schema directly at startup.

## Required order

1. Stop workflows that can mutate Files state during the cutover window.
2. Keep the old service and old volumes intact as rollback authority.
3. Copy the existing `files-data` and FastMCP OAuth state into the volumes used by the
   new stack, preserving ownership, permissions and bytes.
4. Verify file counts, sizes and checksums before starting the new consumers.
5. Create the empty `management-data` volume for the new management database.
6. Let Coolify build the exact Git commit from source through `build: .`; production does
   not depend on a floating GHCR image.
7. Start the modular stack and verify the management health endpoint internally.
8. Verify the public gateway/admin/MCP surfaces and account-scoped provider calls.
9. Rename the new Coolify resource only after live acceptance.
10. Remove the old service and obsolete volumes only after rollback is no longer needed.

## Persistent storage

```text
management-data -> /management
  database=/management/management.sqlite3

files-data -> /files
  database=/files/files.sqlite3
  file_id=sha256:<digest>

fastmcp-data -> /data/fastmcp
```

The management database is intentionally zero-state during this development cutover.
No Alembic or legacy control-plane migration is performed.

## Target topology

```text
Internet / ChatGPT
        |
        v
gateway :8000
        |
        +-- management :8000 (private)
        +-- github     :8000 (private)
        +-- gitlab     :8000 (private)
        +-- files      :8000 (private)
        +-- curl       :8000 (private, public surface = /web/mcp)
        +-- analysis   :8000 (private)
        +-- ghidra     :8000 (private facade to native ghidra-mcp)
```

Only the gateway publishes a host port.

## Public URLs

```text
https://mcp.koba-nexus.ru/mcp
https://mcp.koba-nexus.ru/github/mcp
https://mcp.koba-nexus.ru/gitlab/mcp
https://mcp.koba-nexus.ru/files/mcp
https://mcp.koba-nexus.ru/web/mcp
https://mcp.koba-nexus.ru/analysis/mcp
https://mcp.koba-nexus.ru/ghidra/mcp
https://mcp.koba-nexus.ru/admin/
```

## Acceptance

Verify after deployment:

- Coolify deployed the intended `SOURCE_COMMIT` and built it from source;
- management health is `200` from the gateway/private network;
- `/admin/` authenticates and stays on the public origin;
- every provider tool remains present even before accounts are configured;
- GitHub/GitLab discovery tools list configured accounts and capability/permission data;
- an unavailable, disabled or under-privileged account fails at tool invocation rather
  than removing tools from the catalog;
- existing Files records, object bytes and downloads are intact;
- Files upload, guarded deletion and manual/automatic cleanup work through Admin;
- MCP invocation logging can be enabled/disabled, payload capture toggled, retained and
  cleared;
- `/analysis/mcp` and `/ghidra/mcp` both reach the native Ghidra backend as intended;
- every dedicated public MCP URL independently returns the expected OAuth challenge or
  authenticated response.

## Failure recovery

Until final acceptance, recovery is operational: stop the new stack, restore the old
service/upstream and keep the original volumes untouched. Do not add compatibility paths
back into the runtime merely to support rollback.
