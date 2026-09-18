# Component catalog

This catalog covers only the platform components currently being stabilized.

| Component | Current role | Direction |
| --- | --- | --- |
| Secrets | New internal secret-reference resolver | Self-hosted Infisical; machine identities; provider tokens leave Coolify |
| Gateway | OAuth boundary, local tools, mounted backends | Thin optional aggregate MCP entry point |
| GitHub | GitHub App development/reviewer workflows | Independent `github-mcp` runtime using shared policy/secrets libraries |
| GitLab | Multi-profile GitLab REST connector | Independent `gitlab-mcp` runtime; explicit `profile_id` |
| Ghidra | Project-scoped reverse-engineering backend | Keep independent backend; isolate adapters from gateway failure |
| Files | Immutable content-addressed file/artifact storage and transfer | User-facing `files-mcp`; internal artifact IDs remain compatible |
| HTTP | Structured curl request/download/stream tools | Independent `http-mcp` runtime |

## Secrets

Provider credentials should be referenced, not copied into connector configuration.

Supported reference forms:

```text
env://NAME
file:///absolute/path
infisical://prod/path/to/folder#SECRET_NAME
```

The first Infisical integration uses Universal Auth for runtime machine identities. Only the machine identity bootstrap credential remains in the deployment system.

## Files versus artifacts

The existing `artifact_id = sha256:...` model, collections and references remain useful. The planned change is primarily the public component/API naming toward Files, not a rewrite of content-addressed storage.
