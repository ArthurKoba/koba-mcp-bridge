# Component catalog

This catalog is intentionally high-level. It describes ownership boundaries we want to preserve while the implementation is still being reorganized.

| Component | Current role | Direction |
| --- | --- | --- |
| Gateway | OAuth boundary, local tools, mounted backends | Thin optional aggregate MCP entry point |
| GitHub | GitHub App development/reviewer workflows | Independent `github-mcp` runtime using shared policy/auth libraries |
| GitLab | Multi-profile GitLab REST connector | Independent `gitlab-mcp` runtime; explicit `profile_id` |
| Files | Immutable content-addressed file/artifact storage and transfer | User-facing `files-mcp`; internal artifact IDs may remain |
| HTTP | Structured curl request/download/stream tools | Independent `http-mcp` runtime |
| Ghidra | Project-scoped reverse-engineering backend | Existing independent backend plus high-level adapters |
| Agents | Future long-running task/worker operations | Independent `agents-mcp` / execution plane |
| Control plane | Not implemented | Profiles, connector metadata, policy, health, administrative workflows |
| Secret manager | Not implemented | Central secret lifecycle and machine access |
| Identity/SSO | GitHub OAuth currently protects public MCP | Potential future shared IdP such as Keycloak |
| Camera Manager | Not implemented | One manager service owns camera inventory, state and operations; clients do not talk directly to each camera |

## Files versus artifacts

The current implementation uses immutable `artifact_id = sha256:...` identifiers, collections and references. That model is useful internally and should not be discarded casually.

The public MCP/component name may move from "artifact" toward "files" because agents think in terms of files, archives and transfers rather than storage implementation details. The naming/API migration needs its own design issue.

## Camera Manager direction

Cameras should not become one MCP endpoint per device. A future Camera Manager should provide:

- camera inventory and stable camera IDs;
- metadata/capabilities;
- health and reachability;
- configuration/state operations;
- controlled access to camera-specific protocols or backend adapters;
- audit/policy boundaries.

The exact implementation is intentionally left open.
