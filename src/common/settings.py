from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_DEFAULT_PRIVATE_HOSTS = (
    "localhost:*",
    "127.0.0.1:*",
    "[::1]:*",
    "github:*",
    "gitlab:*",
    "files:*",
    "curl:*",
    "analysis:*",
    "ghidra:*",
)
_DEFAULT_PRIVATE_ORIGINS = (
    "http://localhost:*",
    "http://127.0.0.1:*",
    "http://[::1]:*",
)
_DEFAULT_PUBLIC_HOSTS = ("localhost:*", "127.0.0.1:*", "[::1]:*")
_DEFAULT_PUBLIC_ORIGINS = (
    "http://localhost:*",
    "http://127.0.0.1:*",
    "http://[::1]:*",
)


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _tuple_value(value: object) -> object:
    return _csv(value) if isinstance(value, str) else value


def _frozenset_value(value: object) -> object:
    if isinstance(value, str):
        return frozenset(item.casefold() for item in _csv(value))
    if isinstance(value, (set, frozenset, tuple, list)):
        return frozenset(str(item).casefold() for item in value)
    return value


class FrozenSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HttpSurfaceSettings(FrozenSettings):
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]


class ProcessSettings(BaseSettings):
    """Immutable environment-backed configuration created only by composition roots."""

    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=True,
        env_file=None,
        validate_default=True,
        populate_by_name=True,
        frozen=True,
    )


class AsgiServerSettings(ProcessSettings):
    app: str = Field("bridge.server:app", validation_alias="ASGI_APP")
    host: str = Field("0.0.0.0", validation_alias="ASGI_HOST")
    port: int = Field(8000, ge=1, le=65535, validation_alias="ASGI_PORT")
    forwarded_allow_ips: str = Field(
        "127.0.0.1",
        validation_alias="ASGI_FORWARDED_ALLOW_IPS",
    )

    @field_validator("app", "host", "forwarded_allow_ips", mode="before")
    @classmethod
    def _strip_values(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PrivateRuntimeSettings(ProcessSettings):
    allowed_hosts: Annotated[tuple[str, ...], NoDecode] = Field(
        _DEFAULT_PRIVATE_HOSTS,
        validation_alias="PRIVATE_MCP_ALLOWED_HOSTS",
    )
    allowed_origins: Annotated[tuple[str, ...], NoDecode] = Field(
        _DEFAULT_PRIVATE_ORIGINS,
        validation_alias="PRIVATE_MCP_ALLOWED_ORIGINS",
    )

    @field_validator("allowed_hosts", "allowed_origins", mode="before")
    @classmethod
    def _parse_csv(cls, value: object) -> object:
        return _tuple_value(value)

    @property
    def http(self) -> HttpSurfaceSettings:
        return HttpSurfaceSettings(
            allowed_hosts=self.allowed_hosts,
            allowed_origins=self.allowed_origins,
        )


class BridgeSettings(ProcessSettings):
    oauth_enabled: bool = Field(False, validation_alias="OAUTH_ENABLED")
    oauth_base_url: str = Field(
        "https://mcp.koba-nexus.ru",
        validation_alias="OAUTH_BASE_URL",
    )
    oauth_client_id: str = Field("", validation_alias="GITHUB_OAUTH_CLIENT_ID")
    oauth_client_secret: str = Field("", validation_alias="GITHUB_OAUTH_CLIENT_SECRET")
    oauth_jwt_signing_key: str = Field("", validation_alias="GITHUB_OAUTH_JWT_SIGNING_KEY")
    oauth_allowed_users: Annotated[tuple[str, ...], NoDecode] = Field(
        (),
        validation_alias="GITHUB_OAUTH_ALLOWED_USERS",
    )
    github_url: str = Field("http://github:8000/mcp", validation_alias="GITHUB_URL")
    gitlab_url: str = Field("http://gitlab:8000/mcp", validation_alias="GITLAB_URL")
    files_url: str = Field("http://files:8000/mcp", validation_alias="FILES_URL")
    curl_url: str = Field("http://curl:8000/mcp", validation_alias="CURL_URL")
    analysis_url: str = Field(
        "http://analysis:8000/mcp",
        validation_alias="ANALYSIS_URL",
    )
    ghidra_url: str = Field(
        "http://ghidra:8000/mcp",
        validation_alias="GHIDRA_URL",
    )
    build_sha: str = Field(
        "unknown",
        validation_alias=AliasChoices("BUILD_SHA", "SOURCE_COMMIT"),
    )
    build_time: str = Field("unknown", validation_alias="BUILD_TIME")
    allowed_hosts: Annotated[tuple[str, ...], NoDecode] = Field(
        _DEFAULT_PUBLIC_HOSTS,
        validation_alias="MCP_ALLOWED_HOSTS",
    )
    allowed_origins: Annotated[tuple[str, ...], NoDecode] = Field(
        _DEFAULT_PUBLIC_ORIGINS,
        validation_alias="MCP_ALLOWED_ORIGINS",
    )

    @field_validator(
        "oauth_base_url",
        "oauth_client_id",
        "oauth_client_secret",
        "oauth_jwt_signing_key",
        "github_url",
        "gitlab_url",
        "files_url",
        "curl_url",
        "analysis_url",
        "ghidra_url",
        "build_sha",
        "build_time",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("oauth_allowed_users", mode="before")
    @classmethod
    def _parse_oauth_users(cls, value: object) -> object:
        parsed = _tuple_value(value)
        if isinstance(parsed, tuple):
            return tuple(item.casefold() for item in parsed)
        return parsed

    @field_validator("allowed_hosts", "allowed_origins", mode="before")
    @classmethod
    def _parse_csv(cls, value: object) -> object:
        return _tuple_value(value)

    @property
    def backends(self) -> dict[str, str]:
        return {
            "github": self.github_url or "http://github:8000/mcp",
            "gitlab": self.gitlab_url or "http://gitlab:8000/mcp",
            "files": self.files_url or "http://files:8000/mcp",
            "web": self.curl_url or "http://curl:8000/mcp",
            "analysis": self.analysis_url or "http://analysis:8000/mcp",
            "ghidra": self.ghidra_url or "http://ghidra:8000/mcp",
        }

    @property
    def http(self) -> HttpSurfaceSettings:
        return HttpSurfaceSettings(
            allowed_hosts=self.allowed_hosts,
            allowed_origins=self.allowed_origins,
        )


class ManagementClientSettings(ProcessSettings):
    url: str = Field("http://management:8000", validation_alias="MANAGEMENT_URL")
    service_token: str = Field("", validation_alias="MANAGEMENT_SERVICE_TOKEN")
    timeout_seconds: float = Field(
        10,
        gt=0,
        le=60,
        validation_alias="MANAGEMENT_TIMEOUT_SECONDS",
    )

    @field_validator("url", "service_token", mode="before")
    @classmethod
    def _strip_values(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ManagementSettings(ProcessSettings):
    database_path: Path = Field(
        Path("/control-plane/control-plane.sqlite3"),
        validation_alias="MANAGEMENT_DATABASE_PATH",
    )
    encryption_key: str = Field("", validation_alias="MANAGEMENT_ENCRYPTION_KEY")
    service_token: str = Field("", validation_alias="MANAGEMENT_SERVICE_TOKEN")
    admin_username: str = Field("admin", validation_alias="MANAGEMENT_ADMIN_USERNAME")
    admin_password: str = Field("", validation_alias="MANAGEMENT_ADMIN_PASSWORD")
    session_secret: str = Field("", validation_alias="MANAGEMENT_SESSION_SECRET")
    session_https_only: bool = Field(
        True,
        validation_alias="MANAGEMENT_SESSION_HTTPS_ONLY",
    )

    @field_validator(
        "encryption_key",
        "service_token",
        "admin_username",
        "admin_password",
        "session_secret",
        mode="before",
    )
    @classmethod
    def _strip_secrets(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("database_path")
    @classmethod
    def _absolute_database_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("MANAGEMENT_DATABASE_PATH must be absolute")
        return value.resolve(strict=False)

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    def validate_bootstrap(self) -> None:
        missing = [
            name
            for name, value in (
                ("MANAGEMENT_ENCRYPTION_KEY", self.encryption_key),
                ("MANAGEMENT_SERVICE_TOKEN", self.service_token),
                ("MANAGEMENT_ADMIN_PASSWORD", self.admin_password),
                ("MANAGEMENT_SESSION_SECRET", self.session_secret),
            )
            if not value
        ]
        if missing:
            raise ValueError("missing management bootstrap settings: " + ", ".join(missing))


class AnalysisSettings(ProcessSettings):
    backend_url: str = Field(
        "http://ghidra:8000/mcp",
        validation_alias="GHIDRA_URL",
    )
    schema_cache_ttl_seconds: float = Field(
        30,
        ge=0,
        le=3600,
        validation_alias="ANALYSIS_SCHEMA_CACHE_TTL_SECONDS",
    )

    @field_validator("backend_url", mode="before")
    @classmethod
    def _strip_backend_url(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class GhidraSettings(ProcessSettings):
    backend_url: str = Field(
        "http://bridge:8081/mcp",
        validation_alias="GHIDRA_MCP_URL",
    )

    @field_validator("backend_url", mode="before")
    @classmethod
    def _strip_backend_url(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class GitHubPolicySettings(ProcessSettings):
    protected_branches: Annotated[frozenset[str], NoDecode] = Field(
        frozenset({"main", "master"}),
        validation_alias="GITHUB_AGENT_PROTECTED_BRANCHES",
    )
    required_checks: Annotated[tuple[str, ...], NoDecode] = Field(
        ("test", "docker"),
        validation_alias="GITHUB_AGENT_REQUIRED_CHECKS",
    )
    required_reviewers: Annotated[tuple[str, ...], NoDecode] = Field(
        (),
        validation_alias="GITHUB_AGENT_REQUIRED_REVIEWERS",
    )

    @field_validator("protected_branches", mode="before")
    @classmethod
    def _parse_branches(cls, value: object) -> object:
        return _frozenset_value(value)

    @field_validator("required_checks", mode="before")
    @classmethod
    def _parse_checks(cls, value: object) -> object:
        return _tuple_value(value)

    @field_validator("required_reviewers", mode="before")
    @classmethod
    def _parse_reviewers(cls, value: object) -> object:
        parsed = _tuple_value(value)
        if isinstance(parsed, tuple):
            return tuple(item.casefold() for item in parsed)
        return parsed


class GitLabSettings(ProcessSettings):
    protected_branches: Annotated[frozenset[str], NoDecode] = Field(
        frozenset({"main", "master"}),
        validation_alias="GITLAB_PROTECTED_BRANCHES",
    )
    registry_cache_ttl_seconds: float = Field(
        60,
        ge=0,
        le=3600,
        validation_alias="GITLAB_REGISTRY_CACHE_TTL_SECONDS",
    )

    @field_validator("protected_branches", mode="before")
    @classmethod
    def _parse_branches(cls, value: object) -> object:
        return _frozenset_value(value)


class FileSettings(ProcessSettings):
    root: Path = Field(Path("/files"), validation_alias="FILE_ROOT")
    upload_max_bytes: int = Field(
        8 * 1024 * 1024 * 1024,
        ge=1024 * 1024,
        le=64 * 1024 * 1024 * 1024,
        validation_alias="FILE_UPLOAD_MAX_BYTES",
    )
    max_extract_files: int = Field(
        20_000,
        ge=1,
        le=100_000,
        validation_alias="FILE_MAX_EXTRACT_FILES",
    )
    max_extract_bytes: int = Field(
        16 * 1024 * 1024 * 1024,
        ge=1024 * 1024,
        le=128 * 1024 * 1024 * 1024,
        validation_alias="FILE_MAX_EXTRACT_BYTES",
    )
    upload_chunk_bytes: int = Field(
        1024 * 1024,
        ge=64 * 1024,
        le=8 * 1024 * 1024,
        validation_alias="FILE_UPLOAD_CHUNK_BYTES",
    )

    @field_validator("root")
    @classmethod
    def _absolute_root(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("FILE_ROOT must be absolute")
        return value.resolve(strict=False)


class CurlSettings(ProcessSettings):
    binary: Path | None = Field(None, validation_alias="CURL_BINARY")

    @field_validator("binary", mode="before")
    @classmethod
    def _binary_file(cls, value: object) -> object:
        if value in {None, ""}:
            return None
        path = Path(str(value)).expanduser()
        if not path.is_file():
            raise ValueError("configured curl binary does not point to a file")
        return path
