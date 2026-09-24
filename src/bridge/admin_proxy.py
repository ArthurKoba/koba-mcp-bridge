from __future__ import annotations

from collections.abc import Mapping

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
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.casefold() not in _HOP_BY_HOP | {"host", "content-length"}
        }
        headers["x-forwarded-host"] = request.headers.get(
            "x-forwarded-host",
            request.headers.get("host", ""),
        )
        headers["x-forwarded-proto"] = request.headers.get(
            "x-forwarded-proto",
            request.url.scheme,
        )
        return headers

    def _response_headers(self, headers: Mapping[str, str]) -> dict[str, str]:
        forwarded = {
            key: value
            for key, value in headers.items()
            if key.casefold() not in _HOP_BY_HOP | {"content-length"}
        }
        location = forwarded.get("location")
        if location is not None and location.startswith(self.base_url):
            forwarded["location"] = location[len(self.base_url) :] or "/"
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
