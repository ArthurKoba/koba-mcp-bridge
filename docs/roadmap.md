# Repository and platform roadmap

This roadmap records direction, not delivery dates.

## Phase 0 — documentation and inventory

- establish the documentation index and architecture map;
- inventory modules, endpoints, credentials and policy sources;
- document deployment and recovery paths;
- identify hidden cross-component coupling;
- create focused issues for missing documentation.

## Phase 1 — secret management foundation

- evaluate and select the first secret-manager deployment;
- define secret naming/ownership conventions;
- define machine identities for connector runtimes;
- migrate connector credentials away from direct Coolify environment management;
- document backup, recovery and rotation procedures.

The current leading implementation candidate is Infisical, but the decision should be recorded explicitly rather than implied by code.

## Phase 2 — runtime boundaries

Incrementally split runtime entry points while reusing common libraries:

- GitHub;
- GitLab;
- Files;
- HTTP;
- Agents;
- Ghidra integration/gateway adapters.

The aggregate `/mcp` endpoint can remain for compatibility while dedicated endpoints become first-class.

## Phase 3 — control plane

Introduce a Koba control plane/dashboard for connector profiles and policy metadata. It should reference secrets from the secret manager rather than storing provider tokens itself.

Candidate responsibilities:

- provider account/profile inventory;
- enable/disable state;
- connector-to-profile assignment;
- policy bindings;
- health/status;
- audit references;
- administrative workflows.

## Phase 4 — common identity

Evaluate a shared IdP/SSO layer for human-facing Koba applications and administrative endpoints. Keycloak is one candidate. This is separate from provider API-token storage.

## Phase 5 — domain managers

Add higher-level managers where direct device/tool exposure would create a poor abstraction. Camera Manager is the first identified example.

## Migration rule

Do not require a flag-day rewrite. Every phase should keep the currently working MCP paths available until the replacement runtime has acceptance coverage and deployment recovery documentation.
