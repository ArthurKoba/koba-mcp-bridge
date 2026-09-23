from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from common.account_contracts import AccountList, InvocationEvent
from common.models import JsonObject
from control_plane.application.services import AccountService, TelemetryService
from control_plane.domain.accounts import AccountRole, Provider
from control_plane.domain.telemetry import Invocation


class ApiServices:
    def __init__(
        self,
        accounts: AccountService,
        telemetry: TelemetryService,
        service_token: str,
    ) -> None:
        self.accounts = accounts
        self.telemetry = telemetry
        self.service_token = service_token


def build_internal_router(services: ApiServices) -> APIRouter:
    router = APIRouter(prefix="/internal", tags=["internal"])

    def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {services.service_token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")

    @router.get("/accounts")
    def list_accounts(
        provider: Annotated[Provider | None, Query()] = None,
        role: Annotated[AccountRole | None, Query()] = None,
        _authorized: None = Depends(authorize),
    ) -> JsonObject:
        accounts = services.accounts.list(provider=provider, role=role)
        return AccountList(accounts=accounts, count=len(accounts)).to_json()

    @router.get("/accounts/{selector}/resolve")
    def resolve_account(
        selector: str,
        provider: Provider,
        role: Annotated[AccountRole | None, Query()] = None,
        _authorized: None = Depends(authorize),
    ) -> JsonObject:
        try:
            return services.accounts.resolve(
                selector,
                provider=provider,
                role=role,
            ).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/events", status_code=204)
    def record_event(
        event: InvocationEvent,
        _authorized: None = Depends(authorize),
    ) -> None:
        services.telemetry.record(Invocation.model_validate(event.model_dump()))

    @router.get("/events/recent")
    def recent_events(
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        _authorized: None = Depends(authorize),
    ) -> JsonObject:
        events = services.telemetry.recent(limit=limit)
        return {
            "events": [event.model_dump(mode="json") for event in events],
            "count": len(events),
        }

    return router
