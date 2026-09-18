# Documentation index

This directory is the documentation entry point for Koba MCP Bridge and the wider Koba integration layer.

The repository is currently evolving from a single authenticated MCP gateway into a modular platform with reusable connector runtimes, shared services, and an optional aggregate gateway. The documents below intentionally distinguish the current implementation from the target architecture.

## Start here

- [Architecture overview](architecture/overview.md) — current and target system shape.
- [Component catalog](architecture/components.md) — what each connector/service is responsible for.
- [Repository map](repository-map.md) — where the current implementation lives in this repository.
- [Roadmap](roadmap.md) — staged cleanup and modularization plan.
- [Architecture decisions](decisions/README.md) — placeholder for future ADRs.

## Existing technical notes

- [Artifact service architecture](artifact-service.md)
- [GitHub Actions diagnostics](github-actions.md)
- [GitHub history and policy surface](github-history-surface.md)
- [ChatGPT OAuth flow](oauth-chatgpt.md)

## Documentation status

This is an initial map, not a complete reference manual. Missing detail should be added through focused issues and pull requests rather than expanding a single monolithic README.

When a component is split into its own runtime, its documentation should move toward a consistent structure:

1. purpose and ownership;
2. public MCP endpoints/tools;
3. runtime dependencies;
4. authentication and secret requirements;
5. policy boundaries;
6. deployment/health checks;
7. failure isolation and recovery;
8. tests and acceptance procedures.
