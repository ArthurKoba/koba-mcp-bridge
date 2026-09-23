# Files hard cutover

The modular release is a hard cutover. New runtimes do not contain compatibility code
for the previous storage schema or previous connector credential sources.

## Required order

1. Finish or stop all workflows that can mutate persistent Files state.
2. Stop the current bridge.
3. Take a backup of the current persistent storage and FastMCP OAuth state.
4. Create the new `files-data` volume.
5. Perform the one-time offline data conversion into the new Files schema.
6. Verify the converted database and content-addressed object tree.
7. Save the new Coolify Compose configuration without starting it against the old image.
8. Merge the approved PR so CI/CD publishes the new image.
9. Deploy the modular Compose stack.
10. Run live acceptance before removing the backup.

The one-time conversion is an operator action, not runtime behavior. `FileStore` expects
only the final Files schema:

```text
FILE_ROOT=/files
database=/files/files.sqlite3
file_id=sha256:<digest>
```

## Target topology

```text
Internet / ChatGPT
        |
        v
gateway :8000
        |
        +-- github   :8000 (private)
        +-- gitlab   :8000 (private)
        +-- files    :8000 (private)
        +-- curl     :8000 (private)
        +-- analysis :8000 (private)
                              |
                              +-- ghidra-mcp :8081 (native/private)
```

Only the gateway is published.

## Public MCP URLs

```text
https://mcp.koba-nexus.ru/mcp
https://mcp.koba-nexus.ru/github/mcp
https://mcp.koba-nexus.ru/gitlab/mcp
https://mcp.koba-nexus.ru/files/mcp
https://mcp.koba-nexus.ru/http/mcp
https://mcp.koba-nexus.ru/analysis/mcp
```

## Acceptance

Verify after deployment:

- gateway build information and capabilities;
- GitHub development/reviewer operations;
- GitLab profile discovery and account validation;
- existing Files records and reads;
- resumable Files upload;
- HTTP download into Files;
- HTTP request body from `body_file_id`;
- analysis import/export through the native Ghidra backend;
- each dedicated public MCP URL independently.

## Failure recovery

The new code does not read the previous schema. Recovery is operational: stop the new
stack and restore the pre-cutover backup/previous deployment. Do not add compatibility
paths back into the new runtime.
