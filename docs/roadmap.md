# Repository and platform roadmap

This roadmap contains only the active stabilization scope.

## Phase 0 — documentation and inventory

- maintain the architecture/repository map;
- inventory public endpoints and runtime ownership;
- document deployment, rollback and recovery.

## Phase 1 — Secrets foundation

- deploy a self-hosted Infisical baseline;
- define secret paths and machine identity conventions;
- add a shared internal secret resolver;
- migrate GitHub/GitLab credentials from direct Coolify provider-secret variables;
- verify backup/recovery and rotation procedures.

Infisical is now the selected implementation for this phase.

## Phase 2 — GitHub runtime boundary

- reuse existing GitHub modules;
- move GitHub into an independently deployable runtime;
- preserve development/reviewer identities and PR policy;
- keep aggregate gateway compatibility.

## Phase 3 — GitLab runtime boundary

- preserve explicit `profile_id` routing;
- move GitLab to an independent runtime;
- keep gateway compatibility.

## Phase 4 — Ghidra integration boundary

- keep the Ghidra backend independent;
- reduce gateway coupling in high-level Ghidra adapters;
- preserve project-scoped worker routing.

## Phase 5 — Files surface

- establish Files as the user-facing component name;
- preserve immutable file IDs and collection/reference semantics;
- make Files independently deployable.

## Phase 6 — HTTP runtime boundary

- move the existing structured curl engine to an independent runtime;
- preserve request/download/stream behavior and Files integration.

## Migration rule

No flag-day rewrite. Existing MCP paths and legacy credential env variables remain available until replacement paths have tests, live acceptance and rollback documentation.
