from __future__ import annotations

import uvicorn

from common.settings import AsgiServerSettings


def main() -> None:
    settings = AsgiServerSettings()
    uvicorn.run(settings.app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
