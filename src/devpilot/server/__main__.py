import os
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from devpilot.server.app import create_app

# src/devpilot/server/__main__.py -> server -> devpilot -> src -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    # override=False (the default): real environment variables always win over .env
    load_dotenv(REPO_ROOT / ".env")

    token = os.environ.get("DEVPILOT_MCP_TOKEN")
    if not token:
        sys.exit("DEVPILOT_MCP_TOKEN must be set before starting the DevPilot MCP server")

    port = int(os.environ.get("DEVPILOT_MCP_PORT", "8080"))
    app = create_app(token, port=port)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
