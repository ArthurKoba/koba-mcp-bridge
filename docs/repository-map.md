# Repository map

```text
mcp-bridge/
├── .github/
├── docs/
├── src/
│   ├── bridge/            # public gateway only
│   ├── common/            # settings, runtime, secrets and shared primitives
│   └── modules/
│       ├── github/
│       ├── gitlab/
│       ├── files/
│       ├── curl/
│       └── analysis/
├── tests/
│   ├── bridge/
│   ├── common/
│   └── modules/
│       ├── github/
│       ├── gitlab/
│       ├── files/
│       ├── curl/
│       └── analysis/
├── Dockerfile
├── docker-compose.yaml
├── docker-entrypoint.sh
├── pyproject.toml
└── README.md
```

`bridge` owns only OAuth, public MCP surfaces and composition.

`common` contains provider-neutral primitives shared by modules, including the typed
settings boundary used by runtime composition roots.

Each directory under `modules/` owns one private runtime and its implementation.
Provider code does not belong in `bridge` or `common`.

The root `docker-compose.yaml` is the single production deployment definition.
