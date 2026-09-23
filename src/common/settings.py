from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from .secret_config import InfisicalConfig

_DEFAULT_PRIVATE_HOSTS = (
    "localhost:*",
    "127.0.0.1:*",
    "[::1]:*",
    "github:*",
    "gitlab:*",
    "files:*",
    "curl:*",
    "analysis:*",
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
    github_url: str = Field("http://github:8000/mcp", validation_alias="GITHUB_URL")
    gitlab_url: str = Field("http://gitlab:8000/mcp", validation_alias="GITLAB_URL")
    files_url: str = Field("http://files:8000/mcp", validation_alias="FILES_URL")
    curl_url: str = Field("http://curl:8000/mcp", validation_alias="CURL_URL")
    analysis_url: str = Field(
        "http://analysis:8000/mcp",
        validation_alias="ANALYSIS_URL",
    )
    build_sha: str = Field("unknown", validation_alias="BUILD_SHA")
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
        "github_url",
        "gitlab_url",
        "files_url",
        "curl_url",
        "analysis_url",
        "build_sha",
        "build_time",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

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
            "http": self.curl_url or "http://curl:8000/mcp",
            "analysis": self.analysis_url or "http://analysis:8000/mcp",
        }

    @property
    def http(self) -> HttpSurfaceSettings:
        return HttpSurfaceSettings(
            allowed_hosts=self.allowed_hosts,
            allowed_origins=self.allowed_origins,
        )


class InfisicalSettings(ProcessSettings):
    host: str = Field("", validation_alias="INFISICAL_HOST")
    project_id: str = Field("", validation_alias="INFISICAL_PROJECT_ID")
    environment: str = Field("prod", validation_alias="INFISICAL_ENVIRONMENT")
    base_path: str = Field("/", validation_alias="INFISICAL_BASE_PATH")
    client_id: str = Field("", validation_alias="INFISICAL_CLIENT_ID")
    client_id_file: str = Field("", validation_alias="INFISICAL_CLIENT_ID_FILE")
    client_secret: str = Field("", validation_alias="INFISICAL_CLIENT_SECRET")
    client_secret_file: str = Field(
        "",
        validation_alias="INFISICAL_CLIENT_SECRET_FILE",
    )
    verify_tls: bool = Field(True, validation_alias="INFISICAL_VERIFY_TLS")
    ca_file: str = Field("", validation_alias="INFISICAL_CA_FILE")
    cache_ttl_seconds: float = Field(
        60,
        ge=0,
        le=3600,
        validation_alias="INFISICAL_CACHE_TTL_SECONDS",
    )

    @field_validator(
        "host",
        "project_id",
        "environment",
        "base_path",
        "client_id",
        "client_id_file",
        "client_secret",
        "client_secret_file",
        "ca_file",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @staticmethod
    def _bootstrap_value(
        value: str,
        file_value: str,
        env_name: str,
        file_env_name: str,
    ) -> tuple[str, str]:
        if value and file_value:
            raise ValueError(f"configure only one of {env_name} or {file_env_name}")
        if value:
            return value, f"env:{env_name}"
        if not file_value:
            return "", ""
        path = Path(file_value)
        if not path.is_absolute():
            raise ValueError(f"{file_env_name} must point to an absolute path")
        try:
            resolved = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"unable to read {file_env_name}") from exc
        if not resolved:
            raise ValueError(f"{file_env_name} points to an empty file")
        return resolved, f"file:{file_value}"

    def config(self) -> InfisicalConfig:
        client_id, client_id_source = self._bootstrap_value(
            self.client_id,
            self.client_id_file,
            "INFISICAL_CLIENT_ID",
            "INFISICAL_CLIENT_ID_FILE",
        )
        client_secret, client_secret_source = self._bootstrap_value(
            self.client_secret,
            self.client_secret_file,
            "INFISICAL_CLIENT_SECRET",
            "INFISICAL_CLIENT_SECRET_FILE",
        )
        base_path = self.base_path or "/"
        if not base_path.startswith("/"):
            base_path = "/" + base_path
        base_path = "/" + base_path.strip("/") if base_path.strip("/") else "/"
        if self.ca_file and not Path(self.ca_file).is_absolute():
            raise ValueError("INFISICAL_CA_FILE must be an absolute path")
        return InfisicalConfig(
            host=self.host.rstrip("/"),
            project_id=self.project_id,
            client_id=client_id,
            client_secret=client_secret,
            environment=self.environment or "prod",
            base_path=base_path,
            verify_tls=self.verify_tls,
            ca_file=self.ca_file,
            client_id_source=client_id_source,
            client_secret_source=client_secret_source,
        )


class AnalysisSettings(ProcessSettings):
    backend_url: str = Field("", validation_alias="GHIDRA_MCP_URL")
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
