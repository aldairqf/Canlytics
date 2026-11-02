from __future__ import annotations

import argparse

from mcp_server.server import build_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Canlytics headless MCP server")
    parser.add_argument(
        "--allow-can-send",
        action="store_true",
        help="Register the send_frame tool and permit bus transmission",
    )
    args = parser.parse_args()
    build_server(allow_can_send=args.allow_can_send).run()


if __name__ == "__main__":
    main()
