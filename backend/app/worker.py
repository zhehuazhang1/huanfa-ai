from __future__ import annotations

import os
import time

from .db import build_store_from_env
from .dify_client import build_dify_client_from_env
from .feishu import build_feishu_sync_provider_from_env
from .payments import build_payment_provider_from_env
from .queue import build_queue_from_env
from .services import HairAiService
from .storage import build_temp_storage_from_env


def build_service() -> HairAiService:
    store = build_store_from_env()
    store.seed_demo()
    return HairAiService(
        store,
        dify_client=build_dify_client_from_env(),
        queue=build_queue_from_env(),
        storage_provider=build_temp_storage_from_env(),
        payment_provider=build_payment_provider_from_env(),
        feishu_provider=build_feishu_sync_provider_from_env(),
    )


def run_forever(poll_seconds: float = 1.0) -> None:
    service = build_service()
    while True:
        processed = service.process_next_generation_job()
        if processed is None:
            time.sleep(poll_seconds)
            continue
        print(f"processed ai job: {processed['job_no']} status={processed['status']}", flush=True)


if __name__ == "__main__":
    run_forever()
