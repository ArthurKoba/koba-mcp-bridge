from __future__ import annotations

import urllib.parse
from pathlib import Path

from pydantic import ConfigDict

from .models import JsonObject, StrictModel
from .secret_errors import SecretError


class SecretReference(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )
    raw: str
    scheme: str
    environment: str = ""
    secret_path: str = "/"
    secret_name: str = ""
    project_id: str = ""
    env_name: str = ""
    file_path: str = ""

    @classmethod
    def parse(cls, value: str) -> SecretReference:
        raw = value.strip()
        if not raw:
            raise SecretError("secret reference must not be empty")
        parsed = urllib.parse.urlsplit(raw)
        scheme = parsed.scheme.casefold()
        if scheme == "env":
            name = (parsed.netloc + parsed.path).strip("/")
            if not name:
                raise SecretError("env secret reference must name an environment variable")
            return cls(raw=raw, scheme=scheme, env_name=name)

        if scheme == "file":
            path = urllib.parse.unquote(parsed.path)
            if parsed.netloc and parsed.netloc not in {"", "localhost"}:
                path = f"//{parsed.netloc}{path}"
            candidate = Path(path)
            if not candidate.is_absolute():
                raise SecretError("file secret reference must use an absolute path")
            return cls(raw=raw, scheme=scheme, file_path=str(candidate))

        if scheme == "infisical":
            environment = urllib.parse.unquote(parsed.netloc).strip()
            if not environment:
                raise SecretError("Infisical reference must include environment")
            secret_name = urllib.parse.unquote(parsed.fragment).strip()
            if not secret_name:
                raise SecretError("Infisical reference must include #SECRET_NAME")
            path = urllib.parse.unquote(parsed.path) or "/"
            if not path.startswith("/"):
                path = "/" + path
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
            project_id = ""
            for key in ("projectId", "project_id"):
                values = query.get(key)
                if values:
                    project_id = values[-1].strip()
                    break
            return cls(
                raw=raw,
                scheme=scheme,
                environment=environment,
                secret_path=path,
                secret_name=secret_name,
                project_id=project_id,
            )

        raise SecretError(
            "secret reference scheme must be env://, file://, or infisical://"
        )

    def public(self) -> JsonObject:
        if self.scheme == "env":
            return {"scheme": "env", "env_name": self.env_name}
        if self.scheme == "file":
            return {"scheme": "file", "file_path": self.file_path}
        return {
            "scheme": "infisical",
            "environment": self.environment,
            "secret_path": self.secret_path,
            "secret_name": self.secret_name,
            "project_id": self.project_id or None,
        }
