# koba-mcp-bridge

Extensible MCP bridge for AI agents, local tools, isolated compute workers, development automation, and reverse-engineering workflows.

## Purpose

`koba-mcp-bridge` provides AI agents with a controlled interface to tools and workloads running on user-owned infrastructure.

The project is designed around a few core ideas:

- expose local and self-hosted tools through MCP;
- keep long-running or compute-heavy work outside the chat process;
- persist task state, logs, artifacts, and errors so work can survive interrupted sessions;
- isolate workers and constrain CPU, memory, storage, network, and filesystem access;
- support interactive workflows where a task can pause when user input or intervention is required;
- make integrations modular so new development and analysis tools can be added over time.

## Initial direction

The first major integration is planned around reverse engineering with Ghidra. The bridge should eventually allow an agent to inspect program state, request decompilation and cross-references, run analysis scripts, manage longer analysis jobs, and persist useful findings without moving large project data into the chat context.

The architecture is not Ghidra-specific. Future integrations may include build systems, firmware tooling, Git workflows, device tooling, isolated command execution, and other local development services.

## Planned architecture

```text
AI client / MCP client
        |
        | MCP
        v
koba-mcp-bridge
        |
        +-- task/state management
        +-- logs and artifacts
        +-- policy / resource limits
        |
        +-- isolated workers
              |
              +-- Ghidra
              +-- executors
              +-- future integrations
```

The initial implementation uses Python and MCP. FastMCP is used for HTTP OAuth integration and can proxy GitHub OAuth into an MCP-compatible authorization flow.

## GitHub OAuth

OAuth is disabled by default so a deployment can be upgraded before credentials are configured. When `KOBA_OAUTH_ENABLED=true`, the bridge requires all of the following runtime environment variables:

- `KOBA_OAUTH_GITHUB_CLIENT_ID`
- `KOBA_OAUTH_GITHUB_CLIENT_SECRET`
- `KOBA_OAUTH_JWT_SIGNING_KEY`
- `KOBA_OAUTH_ALLOWED_GITHUB_USERS`

The public OAuth base URL defaults to `https://mcp-bridge.koba-nexus.ru` and can be changed with `KOBA_OAUTH_BASE_URL`.

The GitHub OAuth application callback URL is:

```text
https://mcp-bridge.koba-nexus.ru/auth/callback
```

OAuth client registrations and token state are stored below `FASTMCP_HOME`, which defaults to `/data/fastmcp` in the container. Production deployments should mount `/data/fastmcp` as persistent storage before enabling OAuth.

Secrets belong in runtime environment variables or the deployment secret store. They must not be committed to the repository or injected at image build time.

## Project status

Early design and bootstrap stage. APIs, storage layout, and worker interfaces are not stable yet.

## License

MIT
