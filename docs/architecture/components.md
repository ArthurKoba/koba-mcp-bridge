# Component catalog

This catalog covers only the platform components currently being stabilized.

| Component | Current role | Direction |
| --- | --- | --- |
| Secrets | Internal secret-reference resolver | Self-hosted Infisical; machine identities; provider tokens leave Coolify |
| Gateway | OAuth boundary, local tools, mounted backends | Thin optional aggregate MCP entry point |
| GitHub | GitHub App development/reviewer workflows | Independent `github-mcp` runtime using shared policy/secrets libraries |
| GitLab | Multi-profile GitLab REST connector | Independent `gitlab-mcp` runtime; explicit `profile_id` |
| Files | Immutable content-addressed file storage and transfer | Independent `files-mcp`; `file_id = sha256:<digest>` |
| HTTP | Structured curl request/download/stream tools | Independent `http-mcp` runtime |
| Ghidra | Native project-scoped reverse-engineering backend | Keep raw `ghidra-mcp` unchanged and internal |
| Analysis/recovery layer | Transitional Ghidra adapter currently lives in gateway | Future domain MCP that hides Ghidra terminology and consumes Files |

## Secrets

Provider credentials should be referenced, not copied into connector configuration.

Supported reference forms:

```text
env://NAME
file:///absolute/path
infisical://prod/path/to/folder#SECRET_NAME
```

The first Infisical integration uses Universal Auth for runtime machine identities.
Only the machine identity bootstrap credential remains in the deployment system.

## Files

Files are the canonical MCP Bridge storage model.

The persistent identifier is:

```text
file_id = sha256:<digest>
```

Collections, references, uploads, HTTP downloads and Ghidra-facing adapters all use
file terminology. The migration from the former storage schema is performed in-place
for existing SQLite data.

## Ghidra boundary

The raw Ghidra service is not part of the Files renaming. Its native internal tools and
terminology remain unchanged. MCP Bridge adapters translate between the file-oriented MCP Bridge
surface and the native Ghidra API.

The future public-facing analysis/recovery MCP must not expose Ghidra-specific tool names
or require clients to understand Ghidra concepts unless a task explicitly needs them.
