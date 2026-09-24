from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


class AdminProxy:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def _request_headers(request: Request) -> dict[str, str]:
        stripped = {
            "host",
            "content-length",
            "x-forwarded-host",
            "x-forwarded-proto",
        }
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.casefold() not in _HOP_BY_HOP | stripped
        }
        public_host = request.headers.get("host", "")
        headers["host"] = public_host
        headers["x-forwarded-host"] = public_host
        headers["x-forwarded-proto"] = request.headers.get(
            "x-forwarded-proto",
            request.url.scheme,
        )
        return headers

    def _without_backend_origin(self, value: str) -> str:
        backend = urlsplit(self.base_url)
        candidate = urlsplit(value)
        if (candidate.scheme, candidate.netloc) != (backend.scheme, backend.netloc):
            return value

        base_path = backend.path.rstrip("/")
        if base_path and not candidate.path.startswith(base_path + "/"):
            return value
        path = candidate.path[len(base_path) :] if base_path else candidate.path
        return urlunsplit(("", "", path or "/", candidate.query, candidate.fragment))

    def _rewrite_location(self, location: str) -> str:
        rewritten = self._without_backend_origin(location)
        parsed = urlsplit(rewritten)
        if not parsed.query:
            return rewritten

        query = parse_qsl(parsed.query, keep_blank_values=True)
        normalized = [(key, self._without_backend_origin(value)) for key, value in query]
        if normalized == query:
            return rewritten
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(normalized), parsed.fragment)
        )

    def _response_headers(self, headers: Mapping[str, str]) -> dict[str, str]:
        forwarded = {
            key: value
            for key, value in headers.items()
            if key.casefold() not in _HOP_BY_HOP | {"content-length"}
        }
        location = forwarded.get("location")
        if location is not None:
            forwarded["location"] = self._rewrite_location(location)
        return forwarded

    async def handle(self, request: Request) -> Response:
        target = self.base_url + request.url.path
        if request.url.query:
            target += "?" + request.url.query
        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=30) as client:
                response = await client.request(
                    request.method,
                    target,
                    content=await request.body(),
                    headers=self._request_headers(request),
                )
        except httpx.RequestError:
            return PlainTextResponse("admin backend unavailable", status_code=502)

        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=self._response_headers(response.headers),
            media_type=None,
        )
