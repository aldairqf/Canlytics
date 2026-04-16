from __future__ import annotations

import base64
import json
import pickle
import sys

from services.dbc_manager import DbcManager


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if len(args) != 1:
        print(json.dumps({"ok": False, "error": "Expected DBC path argument"}), flush=True)
        return 2

    path = args[0]
    try:
        db = DbcManager()._load_database(path)
        payload = {
            "ok": True,
            "path": path,
            "db_b64": base64.b64encode(pickle.dumps(db, protocol=pickle.HIGHEST_PROTOCOL)).decode("ascii"),
        }
    except Exception as exc:
        payload = {
            "ok": False,
            "path": path,
            "error": str(exc),
        }

    print(json.dumps(payload), flush=True)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
