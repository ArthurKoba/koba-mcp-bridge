from __future__ import annotations

import asyncio
import time

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult

from .account_contracts import InvocationEvent
from .management_client import ManagementClient
from .telemetry_payloads import render_error, render_payload


class ToolTelemetryMiddleware(Middleware):
    """Record bounded, secret-redacted MCP calls into the management service."""

    _MAX_PENDING_EVENTS = 128

    def __init__(self, module: str, management: ManagementClient) -> None:
        self.module = module
        self.management = management
        self._tasks: set[asyncio.Task[None]] = set()

    @staticmethod
    def _account_id(context: MiddlewareContext[mt.CallToolRequestParams]) -> str:
        arguments = context.message.arguments or {}
        value = arguments.get("account_id")
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def _request_id(context: MiddlewareContext[mt.CallToolRequestParams]) -> str:
        fastmcp_context = context.fastmcp_context
        if fastmcp_context is None or not fastmcp_context.request_context:
            return ""
        return str(fastmcp_context.request_id)

    async def _record(self, event: InvocationEvent) -> None:
        try:
            await asyncio.to_thread(self.management.record_invocation, event)
        except Exception:
            return

    def _submit(self, event: InvocationEvent) -> None:
        if len(self._tasks) >= self._MAX_PENDING_EVENTS:
            return
        task = asyncio.create_task(self._record(event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        started = time.monotonic()
        account_id = self._account_id(context)
        provider = self.module if self.module in {"github", "gitlab"} else ""
        request_id = self._request_id(context)
        arguments_json = render_payload(context.message.arguments or {})
        try:
            result = await call_next(context)
        except Exception as exc:
            self._submit(
                InvocationEvent(
                    request_id=request_id,
                    module=self.module,
                    tool=context.message.name,
                    account_id=account_id,
                    provider=provider,
                    status="error",
                    duration_ms=(time.monotonic() - started) * 1000,
                    error_type=type(exc).__name__,
                    arguments_json=arguments_json,
                    error_message=render_error(exc),
                )
            )
            raise
        self._submit(
            InvocationEvent(
                request_id=request_id,
                module=self.module,
                tool=context.message.name,
                account_id=account_id,
                provider=provider,
                status="success",
                duration_ms=(time.monotonic() - started) * 1000,
                arguments_json=arguments_json,
                result_json=render_payload(result),
            )
        )
        return result
