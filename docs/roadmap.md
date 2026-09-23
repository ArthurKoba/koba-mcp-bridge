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

Infisical is the selected implementation for this phase.

## Phase 2 — GitHub runtime boundary

- reuse existing GitHub modules;
- move GitHub into an independently deployable runtime;
- preserve development/reviewer identities and PR policy;
- keep aggregate gateway compatibility.

## Phase 3 — GitLab runtime boundary

- preserve explicit `profile_id` routing;
- move GitLab to an independent runtime;
- keep gateway compatibility.

## Phase 4 — Files runtime and data migration

- replace the old storage terminology completely with Files;
- migrate persisted SQLite schema to `files/file_id/file_refs/source_file_id`;
- move Files into an independently deployable runtime;
- preserve content-addressed bytes and collection/reference semantics.

## Phase 5 — HTTP runtime boundary

- move the existing structured curl engine to an independent runtime;
- preserve request/download/stream behavior and Files integration.

## Phase 6 — Ghidra masking boundary

- keep raw `ghidra-mcp` unchanged;
- remove direct Ghidra terminology from the future client-facing surface;
- design a domain analysis/recovery MCP that consumes Files and calls native Ghidra internally;
- preserve project-scoped worker routing behind that boundary.

## Migration rule

No flag-day deployment. Storage/API breaking changes must have an explicit data migration,
acceptance test and rollback procedure before production rollout.
