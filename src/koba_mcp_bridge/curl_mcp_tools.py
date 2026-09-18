from __future__ import annotations

from typing import Any

from fastmcp import FastMCP


def register_curl_tools(
    mcp: FastMCP,
    read_annotations: Any,
    write_annotations: Any,
) -> None:
    from .curl_tools import (
        curl_download_impl,
        curl_presets_impl,
        curl_request_impl,
        curl_stream_capture_impl,
    )

    @mcp.tool(title="Curl presets", annotations=read_annotations)
    def curl_presets() -> dict[str, Any]:
        """List built-in HTTP header presets for the structured curl tools."""
        return curl_presets_impl()

    @mcp.tool(title="Curl request", annotations=write_annotations)
    def curl_request(
        url: str,
        method: str = "GET",
        query: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        body_text: str | None = None,
        body_json: dict[str, Any] | list[Any] | None = None,
        body_form: dict[str, Any] | None = None,
        body_base64: str | None = None,
        body_artifact_id: str | None = None,
        body_content_type: str = "",
        preset: str = "curl",
        follow_redirects: bool = True,
        max_redirects: int = 10,
        timeout_seconds: float = 60,
        connect_timeout_seconds: float = 15,
        verify_tls: bool = True,
        proxy_url: str = "",
        max_response_bytes: int = 2 * 1024 * 1024,
        preview_bytes: int = 4096,
    ) -> dict[str, Any]:
        """Run a structured curl request with arbitrary HTTP method, headers, cookies and body.

        For large or binary responses prefer curl_download. body_artifact_id sends
        immutable artifact bytes directly from server-side storage without model-visible
        base64. Browser presets reproduce HTTP headers only; they are not browser engines.
        """
        return curl_request_impl(
            url=url,
            method=method,
            query=query,
            headers=headers,
            cookies=cookies,
            body_text=body_text,
            body_json=body_json,
            body_form=body_form,
            body_base64=body_base64,
            body_artifact_id=body_artifact_id,
            body_content_type=body_content_type,
            preset=preset,
            follow_redirects=follow_redirects,
            max_redirects=max_redirects,
            timeout_seconds=timeout_seconds,
            connect_timeout_seconds=connect_timeout_seconds,
            verify_tls=verify_tls,
            proxy_url=proxy_url,
            max_response_bytes=max_response_bytes,
            preview_bytes=preview_bytes,
        )

    @mcp.tool(title="Curl download", annotations=write_annotations)
    def curl_download(
        url: str,
        method: str = "GET",
        query: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        body_text: str | None = None,
        body_json: dict[str, Any] | list[Any] | None = None,
        body_form: dict[str, Any] | None = None,
        body_base64: str | None = None,
        body_artifact_id: str | None = None,
        body_content_type: str = "",
        artifact_name: str = "",
        preset: str = "curl",
        follow_redirects: bool = True,
        max_redirects: int = 10,
        timeout_seconds: float = 300,
        connect_timeout_seconds: float = 15,
        verify_tls: bool = True,
        proxy_url: str = "",
        max_bytes: int = 1024 * 1024 * 1024,
        store_http_errors: bool = False,
        preview_bytes: int = 4096,
    ) -> dict[str, Any]:
        """Stream an HTTP response into the immutable artifact store.

        Supports arbitrary HTTP methods and the same request controls as curl_request.
        The response is never serialized through model context; the result contains
        artifact_id plus HTTP metadata and a small text/hex preview.
        """
        return curl_download_impl(
            url=url,
            method=method,
            query=query,
            headers=headers,
            cookies=cookies,
            body_text=body_text,
            body_json=body_json,
            body_form=body_form,
            body_base64=body_base64,
            body_artifact_id=body_artifact_id,
            body_content_type=body_content_type,
            artifact_name=artifact_name,
            preset=preset,
            follow_redirects=follow_redirects,
            max_redirects=max_redirects,
            timeout_seconds=timeout_seconds,
            connect_timeout_seconds=connect_timeout_seconds,
            verify_tls=verify_tls,
            proxy_url=proxy_url,
            max_bytes=max_bytes,
            store_http_errors=store_http_errors,
            preview_bytes=preview_bytes,
        )

    @mcp.tool(title="Curl stream capture", annotations=write_annotations)
    def curl_stream_capture(
        url: str,
        method: str = "GET",
        query: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        body_text: str | None = None,
        body_json: dict[str, Any] | list[Any] | None = None,
        body_form: dict[str, Any] | None = None,
        body_base64: str | None = None,
        body_artifact_id: str | None = None,
        body_content_type: str = "",
        artifact_name: str = "",
        preset: str = "curl",
        follow_redirects: bool = True,
        max_redirects: int = 10,
        duration_seconds: float = 15,
        connect_timeout_seconds: float = 15,
        verify_tls: bool = True,
        proxy_url: str = "",
        max_bytes: int = 16 * 1024 * 1024,
        preview_bytes: int = 4096,
    ) -> dict[str, Any]:
        """Observe/capture a response byte stream for a bounded duration or byte count.

        Useful for SSE, MJPEG, chunked telemetry and other long-lived byte streams.
        Captured bytes are committed to the immutable artifact store.
        """
        return curl_stream_capture_impl(
            url=url,
            method=method,
            query=query,
            headers=headers,
            cookies=cookies,
            body_text=body_text,
            body_json=body_json,
            body_form=body_form,
            body_base64=body_base64,
            body_artifact_id=body_artifact_id,
            body_content_type=body_content_type,
            artifact_name=artifact_name,
            preset=preset,
            follow_redirects=follow_redirects,
            max_redirects=max_redirects,
            duration_seconds=duration_seconds,
            connect_timeout_seconds=connect_timeout_seconds,
            verify_tls=verify_tls,
            proxy_url=proxy_url,
            max_bytes=max_bytes,
            preview_bytes=preview_bytes,
        )
