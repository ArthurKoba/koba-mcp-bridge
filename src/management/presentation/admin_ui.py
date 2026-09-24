from __future__ import annotations

from starlette.requests import Request
from starlette_admin.helpers import static_url
from starlette_admin.plugins import BasePlugin


class ManagementUiPlugin(BasePlugin):
    """Global management-console presentation policy."""

    name = "management-ui"
    package = "management.presentation.admin_ui_plugin"

    def css_links(self, request: Request) -> list[str]:
        return [static_url(request, "plugins/management-ui/admin.css", v=2)]
