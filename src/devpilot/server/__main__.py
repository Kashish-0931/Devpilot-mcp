import os
import sys

import uvicorn

from devpilot.server.app import create_app


def main() -> None:
    token = os.environ.get("DEVPILOT_MCP_TOKEN")
    if not token:
        sys.exit("DEVPILOT_MCP_TOKEN must be set before starting the DevPilot MCP server")

    port = int(os.environ.get("DEVPILOT_MCP_PORT", "8080"))
    app = create_app(token, port=port)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
