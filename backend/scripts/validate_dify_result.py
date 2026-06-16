from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.dify_client import DifyWorkflowClient
from app.models import JobStatus


def load_json(path: str | None) -> dict:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return json.loads(sys.stdin.read())


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL invalid JSON input: {exc}")
        return 1

    client = DifyWorkflowClient(base_url="https://validator.local", api_key="validator")
    result = client._parse_generation_result("AI_VALIDATION", payload)
    if result.status != JobStatus.SUCCESS:
        print(f"FAIL {result.error_code}: {result.error_message}")
        if result.internal_api_cost:
            print(f"internal_api_cost={result.internal_api_cost}")
        return 1

    print("PASS Dify result contract")
    print(f"images={len(result.images)}")
    print(f"slots={','.join(image.slot for image in result.images)}")
    print(f"internal_api_cost={result.internal_api_cost}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
