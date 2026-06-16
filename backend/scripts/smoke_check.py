from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def get_json(path: str) -> dict | list:
    with urllib.request.urlopen(BASE_URL + path, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    checks = [
        ("/health", lambda data: data["status"] == "ok"),
        ("/hairstyles?tenant_id=1&direction=female", lambda data: isinstance(data, list) and len(data) >= 1),
        ("/hair-colors?tenant_id=1&direction=female", lambda data: isinstance(data, list) and len(data) >= 1),
        ("/platform/usage?tenant_id=1", lambda data: "balance" in data),
    ]
    for path, validate in checks:
        try:
            data = get_json(path)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"FAIL {path}: {exc}")
            return 1
        if not validate(data):
            print(f"FAIL {path}: unexpected response {data}")
            return 1
        print(f"OK {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
