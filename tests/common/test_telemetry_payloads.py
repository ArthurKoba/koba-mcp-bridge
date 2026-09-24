from __future__ import annotations

import json

from common.telemetry_payloads import (
    MAX_PAYLOAD_CHARS,
    REDACTED,
    render_error,
    render_payload,
)


def test_render_payload_redacts_nested_sensitive_fields() -> None:
    rendered = render_payload(
        {
            "account_id": "github-work",
            "headers": {"Authorization": "Bearer secret", "X-Trace": "ok"},
            "nested": [{"access_token": "abc", "repository": "owner/repo"}],
            "client_secret": "secret",
            "message": "request used Bearer hidden-token",
        }
    )

    payload = json.loads(rendered)
    assert payload["account_id"] == "github-work"
    assert payload["headers"]["Authorization"] == REDACTED
    assert payload["headers"]["X-Trace"] == "ok"
    assert payload["nested"][0]["access_token"] == REDACTED
    assert payload["nested"][0]["repository"] == "owner/repo"
    assert payload["client_secret"] == REDACTED
    assert "hidden-token" not in payload["message"]


def test_render_payload_is_bounded() -> None:
    assert len(render_payload({"body": "x" * (MAX_PAYLOAD_CHARS * 2)})) == MAX_PAYLOAD_CHARS


def test_render_error_redacts_common_secret_forms() -> None:
    message = (
        "request failed Authorization: Bearer super-secret "
        "token=abc123 client_secret=qwerty "
        "-----BEGIN PRIVATE KEY-----\nsecret-key\n-----END PRIVATE KEY-----"
    )

    rendered = render_error(message)

    assert "super-secret" not in rendered
    assert "abc123" not in rendered
    assert "qwerty" not in rendered
    assert "secret-key" not in rendered
    assert rendered.count(REDACTED) >= 4
