# Repository map

```text
mcp-bridge/
├── .github/
├── docs/
├── migrations/                 # Alembic management schema
├── src/
│   ├── bridge/                 # public gateway only
│   ├── common/                 # shared contracts/settings/runtime primitives
│   ├── management/
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/
│   │   └── presentation/
│   └── modules/
│       ├── github/
│       ├── gitlab/
│       ├── files/
│       ├── curl/
│       └── analysis/
├── tests/
│   ├── bridge/
│   ├── common/
│   ├── management/
│   └── modules/
├── alembic.ini
├── Dockerfile
├── docker-compose.yaml
├── docker-entrypoint.sh
├── pyproject.toml
└── README.md
```

`bridge` owns only OAuth, public MCP surfaces and composition. `management` owns dynamic
provider account persistence and encrypted credentials. Each provider module owns its API
semantics and consumes account data only through the common account port/client.

The root `docker-compose.yaml` is the production topology definition.
