from __future__ import annotations

from common.models import JsonObject

from .models import CurlPreset, CurlPresetDefinition, CurlPresetsResponse

DEFAULT_CURL_PRESET = "chrome-desktop"

_RAW_PRESETS: dict[str, JsonObject] = {
    "curl": {
        "description": "Native curl defaults plus automatic compressed-response decoding.",
        "headers": {"Accept": "*/*"},
    },
    "chrome-desktop": {
        "description": (
            "Browser-like desktop Chrome HTTP headers. This is not a JavaScript engine "
            "and does not reproduce Chrome TLS/HTTP2 fingerprints."
        ),
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/153.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-CH-UA": (
                '"Chromium";v="153", "Not_A Brand";v="99", '
                '"Google Chrome";v="153"'
            ),
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
            "Upgrade-Insecure-Requests": "1",
        },
    },
    "chrome-mobile": {
        "description": (
            "Browser-like Android Chrome HTTP headers. This is not a JavaScript engine "
            "and does not reproduce Chrome TLS/HTTP2 fingerprints."
        ),
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 15; Pixel 9) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/153.0.0.0 Mobile Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-CH-UA": (
                '"Chromium";v="153", "Not_A Brand";v="99", '
                '"Google Chrome";v="153"'
            ),
            "Sec-CH-UA-Mobile": "?1",
            "Sec-CH-UA-Platform": '"Android"',
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
            "Upgrade-Insecure-Requests": "1",
        },
    },
    "json-api": {
        "description": "JSON API defaults.",
        "headers": {
            "User-Agent": "MCP-Bridge-Curl/1.0",
            "Accept": "application/json",
        },
    },
    "none": {
        "description": "No preset headers; only caller-provided headers are sent.",
        "headers": {},
    },
}
_PRESETS = {
    name: CurlPresetDefinition.model_validate(payload)
    for name, payload in _RAW_PRESETS.items()
}

def curl_presets_impl() -> JsonObject:
    return CurlPresetsResponse(
        default_preset=DEFAULT_CURL_PRESET,
        presets=[
            CurlPreset(
                name=name,
                description=data.description,
                headers=dict(data.headers),
            )
            for name, data in _PRESETS.items()
        ],
    ).to_json()
