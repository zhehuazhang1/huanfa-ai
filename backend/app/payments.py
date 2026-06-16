from __future__ import annotations

import os
import time
from typing import Protocol
from uuid import uuid4


class PaymentError(RuntimeError):
    pass


class PaymentProvider(Protocol):
    provider_name: str

    def create_mini_program_prepay(
        self,
        *,
        pay_order_no: str,
        openid: str,
        amount_yuan: float,
        description: str,
    ) -> dict:
        ...


class MockPaymentProvider:
    provider_name = "mock"

    def create_mini_program_prepay(
        self,
        *,
        pay_order_no: str,
        openid: str,
        amount_yuan: float,
        description: str,
    ) -> dict:
        nonce = uuid4().hex
        return {
            "provider": self.provider_name,
            "pay_order_no": pay_order_no,
            "pay_status": "pending",
            "wechat_pay_params": {
                "timeStamp": str(int(time.time())),
                "nonceStr": nonce,
                "package": f"prepay_id=mock_{pay_order_no}",
                "signType": "RSA",
                "paySign": "mock_pay_sign",
            },
            "mock": True,
            "description": description,
            "amount_yuan": amount_yuan,
            "openid": openid,
        }


class WeChatPayProvider:
    provider_name = "wechat_pay"

    def __init__(
        self,
        *,
        app_id: str,
        mch_id: str,
        api_v3_key: str,
        notify_url: str,
    ) -> None:
        self.app_id = app_id
        self.mch_id = mch_id
        self.api_v3_key = api_v3_key
        self.notify_url = notify_url

    def create_mini_program_prepay(
        self,
        *,
        pay_order_no: str,
        openid: str,
        amount_yuan: float,
        description: str,
    ) -> dict:
        raise PaymentError(
            "WeChat Pay v3 provider is configured but real request signing/certificate setup is not enabled yet"
        )


def build_payment_provider_from_env() -> PaymentProvider:
    provider = (os.getenv("PAYMENT_PROVIDER") or "mock").lower()
    if provider == "mock":
        return MockPaymentProvider()
    if provider in {"wechat", "wechat_pay"}:
        config = {
            "WECHAT_APP_ID": os.getenv("WECHAT_APP_ID", ""),
            "WECHAT_PAY_MCH_ID": os.getenv("WECHAT_PAY_MCH_ID", ""),
            "WECHAT_PAY_API_V3_KEY": os.getenv("WECHAT_PAY_API_V3_KEY", ""),
            "WECHAT_PAY_NOTIFY_URL": os.getenv("WECHAT_PAY_NOTIFY_URL", ""),
        }
        missing = [name for name, value in config.items() if not value]
        if missing:
            raise PaymentError("Missing WeChat Pay config: " + ", ".join(missing))
        return WeChatPayProvider(
            app_id=config["WECHAT_APP_ID"],
            mch_id=config["WECHAT_PAY_MCH_ID"],
            api_v3_key=config["WECHAT_PAY_API_V3_KEY"],
            notify_url=config["WECHAT_PAY_NOTIFY_URL"],
        )
    raise PaymentError(f"Unsupported PAYMENT_PROVIDER: {provider}")
