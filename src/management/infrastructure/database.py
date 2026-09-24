from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, Float, Integer, MetaData, String, Text, create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry


class Base(DeclarativeBase):
    pass


class GitHubAccountRecord(Base):
    __tablename__ = "github_accounts"
    __allow_unmapped__ = True

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    alias: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    auth_type: Mapped[str] = mapped_column(String(32))
    app_id: Mapped[str] = mapped_column(String(512), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    encrypted_credential: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    _credential_input: str = ""

    @property
    def credential_input(self) -> str:
        return ""

    @credential_input.setter
    def credential_input(self, value: str) -> None:
        self._credential_input = value


class GitLabAccountRecord(Base):
    __tablename__ = "gitlab_accounts"
    __allow_unmapped__ = True

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    alias: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    auth_type: Mapped[str] = mapped_column(String(32))
    base_url: Mapped[str] = mapped_column(String(2048), default="https://gitlab.com")
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    ca_cert_pem: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    encrypted_credential: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    _credential_input: str = ""

    @property
    def credential_input(self) -> str:
        return ""

    @credential_input.setter
    def credential_input(self, value: str) -> None:
        self._credential_input = value


class InvocationRecord(Base):
    __tablename__ = "invocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    request_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    module: Mapped[str] = mapped_column(String(64), index=True)
    tool: Mapped[str] = mapped_column(String(256), index=True)
    account_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    provider: Mapped[str] = mapped_column(String(32), default="", index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    duration_ms: Mapped[float] = mapped_column(Float)
    error_type: Mapped[str] = mapped_column(String(256), default="")
    arguments_json: Mapped[str] = mapped_column(Text, default="")
    result_json: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[datetime] = mapped_column(index=True, default=lambda: datetime.now(UTC))


class ManagementConfigRecord(Base):
    __tablename__ = "management_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    logging_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    logging_capture_payloads: Mapped[bool] = mapped_column(Boolean, default=True)
    logging_retention_days: Mapped[int] = mapped_column(Integer, default=30)
    logging_max_records: Mapped[int] = mapped_column(Integer, default=10_000)
    file_auto_cleanup_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    file_retention_days: Mapped[int] = mapped_column(Integer, default=30)
    file_cleanup_limit: Mapped[int] = mapped_column(Integer, default=1_000)
    maintenance_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)


def create_database(database_url: str) -> tuple[Engine, sessionmaker[Session]]:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(
            dbapi_connection: sqlite3.Connection,
            _connection_record: ConnectionPoolEntry,
        ) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def ensure_zero_state_schema(engine: Engine) -> bool:
    """Create the current schema, resetting incompatible pre-production state."""
    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names())
    expected_tables = set(Base.metadata.tables)
    reset_required = actual_tables != expected_tables

    if not reset_required:
        for table_name, table in Base.metadata.tables.items():
            actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
            expected_columns = {column.name for column in table.columns}
            if actual_columns != expected_columns:
                reset_required = True
                break

    if reset_required and actual_tables:
        reflected = MetaData()
        reflected.reflect(bind=engine)
        reflected.drop_all(engine)

    Base.metadata.create_all(engine)
    return reset_required
