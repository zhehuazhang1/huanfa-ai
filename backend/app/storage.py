from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from datetime import datetime
from datetime import timedelta
from typing import Protocol
import urllib.error
import urllib.request
from urllib.parse import quote
from uuid import uuid4


ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


class StorageError(RuntimeError):
    pass


class TempStorageProvider(Protocol):
    provider_name: str

    def create_temp_upload_url(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        file_ext: str,
        ttl_minutes: int = 30,
    ) -> dict:
        ...

    def delete_temp_asset(self, photo_temp_url: str) -> None:
        ...

    def create_catalog_upload_url(
        self,
        *,
        tenant_id: int,
        store_id: int,
        asset_type: str,
        file_ext: str,
    ) -> dict:
        ...

    def upload_temp_bytes(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        file_ext: str,
        content: bytes,
        content_type: str,
        ttl_minutes: int = 30,
    ) -> str:
        ...


def normalize_image_extension(file_ext: str) -> str:
    clean_ext = file_ext.lower().lstrip(".")
    if clean_ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise StorageError("Unsupported image file extension")
    return clean_ext


class MockTempStorageProvider:
    provider_name = "mock"

    def __init__(self) -> None:
        self.temp_assets: dict[str, dict] = {}

    def create_temp_upload_url(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        file_ext: str,
        ttl_minutes: int = 30,
    ) -> dict:
        clean_ext = normalize_image_extension(file_ext)
        object_key = build_object_key(tenant_id, store_id, user_id, clean_ext)
        token = uuid4().hex
        expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)
        upload_url = f"https://temp-upload.local/{object_key}?token={token}"
        temp_url = f"https://temp-object.local/{object_key}?token={token}"
        self.temp_assets[temp_url] = {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "user_id": user_id,
            "object_key": object_key,
            "expires_at": expires_at,
        }
        return build_upload_response(
            upload_url=upload_url,
            photo_temp_url=temp_url,
            object_key=object_key,
            expires_at=expires_at,
            ttl_minutes=ttl_minutes,
            provider_name=self.provider_name,
            persistent_storage=False,
        )

    def delete_temp_asset(self, photo_temp_url: str) -> None:
        self.temp_assets.pop(photo_temp_url, None)

    def create_catalog_upload_url(
        self,
        *,
        tenant_id: int,
        store_id: int,
        asset_type: str,
        file_ext: str,
    ) -> dict:
        clean_ext = normalize_image_extension(file_ext)
        object_key = build_catalog_object_key(tenant_id, store_id, asset_type, clean_ext)
        token = uuid4().hex
        asset_url = f"https://catalog-object.local/{object_key}?token={token}"
        return {
            "upload_url": f"https://catalog-upload.local/{object_key}?token={token}",
            "asset_url": asset_url,
            "object_key": object_key,
            "provider": self.provider_name,
            "persistent_storage": True,
        }

    def upload_temp_bytes(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        file_ext: str,
        content: bytes,
        content_type: str,
        ttl_minutes: int = 30,
    ) -> str:
        upload = self.create_temp_upload_url(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            file_ext=file_ext,
            ttl_minutes=ttl_minutes,
        )
        self.temp_assets[upload["photo_temp_url"]]["content"] = content
        return upload["photo_temp_url"]


class AliyunOssTempStorageProvider:
    """Minimal OSS presign adapter.

    Production should prefer STS credentials with least privilege. This adapter
    keeps the backend contract stable for POC/MVP and avoids leaking permanent
    credentials to the mini program.
    """

    provider_name = "aliyun_oss"

    def __init__(
        self,
        *,
        bucket: str,
        endpoint: str,
        access_key_id: str,
        access_key_secret: str,
    ) -> None:
        self.bucket = bucket
        self.endpoint = endpoint.rstrip("/")
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret

    def create_temp_upload_url(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        file_ext: str,
        ttl_minutes: int = 30,
    ) -> dict:
        clean_ext = normalize_image_extension(file_ext)
        object_key = build_object_key(tenant_id, store_id, user_id, clean_ext)
        expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)
        expires_ts = int(expires_at.timestamp())
        upload_url = self._signed_url(
            "PUT",
            object_key,
            expires_ts,
            content_type="application/octet-stream",
        )
        temp_url = self._signed_url("GET", object_key, expires_ts)
        return build_upload_response(
            upload_url=upload_url,
            photo_temp_url=temp_url,
            object_key=object_key,
            expires_at=expires_at,
            ttl_minutes=ttl_minutes,
            provider_name=self.provider_name,
            persistent_storage=False,
        )

    def delete_temp_asset(self, photo_temp_url: str) -> None:
        object_key = self._object_key_from_url(photo_temp_url)
        expires_ts = int((datetime.utcnow() + timedelta(minutes=5)).timestamp())
        request = urllib.request.Request(
            self._signed_url("DELETE", object_key, expires_ts),
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(request, timeout=10):
                return
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return
            raise StorageError(f"OSS temporary asset cleanup failed: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise StorageError(f"OSS temporary asset cleanup failed: {exc.reason}") from exc

    def create_catalog_upload_url(
        self,
        *,
        tenant_id: int,
        store_id: int,
        asset_type: str,
        file_ext: str,
    ) -> dict:
        clean_ext = normalize_image_extension(file_ext)
        object_key = build_catalog_object_key(tenant_id, store_id, asset_type, clean_ext)
        upload_expires = int((datetime.utcnow() + timedelta(minutes=30)).timestamp())
        read_expires = int((datetime.utcnow() + timedelta(days=365)).timestamp())
        return {
            "upload_url": self._signed_url(
                "PUT",
                object_key,
                upload_expires,
                content_type="application/octet-stream",
            ),
            "asset_url": self._signed_url("GET", object_key, read_expires),
            "object_key": object_key,
            "provider": self.provider_name,
            "persistent_storage": True,
        }

    def upload_temp_bytes(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        file_ext: str,
        content: bytes,
        content_type: str,
        ttl_minutes: int = 30,
    ) -> str:
        upload = self.create_temp_upload_url(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            file_ext=file_ext,
            ttl_minutes=ttl_minutes,
        )
        for attempt in range(3):
            request = urllib.request.Request(
                upload["upload_url"],
                data=content,
                method="PUT",
                headers={"Content-Type": "application/octet-stream"},
            )
            try:
                with urllib.request.urlopen(request, timeout=30):
                    return upload["photo_temp_url"]
            except urllib.error.HTTPError as exc:
                if exc.code < 500 or attempt == 2:
                    raise StorageError(f"OSS temporary upload failed: HTTP {exc.code}") from exc
            except urllib.error.URLError as exc:
                if attempt == 2:
                    raise StorageError(f"OSS temporary upload failed: {exc.reason}") from exc
            time.sleep(attempt + 1)
        raise StorageError("OSS temporary upload failed")

    def _object_key_from_url(self, photo_temp_url: str) -> str:
        prefix = self.endpoint + "/"
        if not photo_temp_url.startswith(prefix):
            raise StorageError("Temporary asset URL does not belong to configured OSS endpoint")
        return photo_temp_url[len(prefix):].split("?", 1)[0]

    def _signed_url(
        self,
        method: str,
        object_key: str,
        expires_ts: int,
        *,
        content_type: str = "",
    ) -> str:
        encoded_key = quote(object_key)
        canonical = f"{method}\n\n{content_type}\n{expires_ts}\n/{self.bucket}/{object_key}"
        digest = hmac.new(
            self.access_key_secret.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        signature = quote(base64.b64encode(digest).decode("utf-8"))
        return (
            f"{self.endpoint}/{encoded_key}"
            f"?OSSAccessKeyId={quote(self.access_key_id)}"
            f"&Expires={expires_ts}"
            f"&Signature={signature}"
        )


def build_object_key(tenant_id: int, store_id: int, user_id: int, clean_ext: str) -> str:
    return f"temp/{tenant_id}/{store_id}/{user_id}/{uuid4().hex}.{clean_ext}"


def build_catalog_object_key(tenant_id: int, store_id: int, asset_type: str, clean_ext: str) -> str:
    if asset_type not in {"hairstyle", "hair_color"}:
        raise StorageError("Unsupported catalog asset type")
    return f"catalog/{tenant_id}/{store_id}/{asset_type}/{uuid4().hex}.{clean_ext}"


def build_upload_response(
    *,
    upload_url: str,
    photo_temp_url: str,
    object_key: str,
    expires_at: datetime,
    ttl_minutes: int,
    provider_name: str,
    persistent_storage: bool,
) -> dict:
    return {
        "upload_url": upload_url,
        "photo_temp_url": photo_temp_url,
        "object_key": object_key,
        "expires_at": expires_at.isoformat() + "Z",
        "ttl_seconds": ttl_minutes * 60,
        "provider": provider_name,
        "persistent_storage": persistent_storage,
    }


def build_temp_storage_from_env() -> TempStorageProvider:
    provider = (os.getenv("TEMP_STORAGE_PROVIDER") or "mock").lower()
    if provider in {"mock", "local"}:
        return MockTempStorageProvider()
    if provider in {"aliyun_oss", "oss", "aliyun"}:
        bucket = os.getenv("OSS_BUCKET", "")
        endpoint = os.getenv("OSS_ENDPOINT", "")
        region = os.getenv("OSS_REGION", "")
        access_key_id = os.getenv("OSS_ACCESS_KEY_ID", "")
        access_key_secret = os.getenv("OSS_ACCESS_KEY_SECRET", "")
        if not endpoint and bucket and region:
            endpoint = f"https://{bucket}.oss-{region}.aliyuncs.com"
        missing = [
            name
            for name, value in {
                "OSS_BUCKET": bucket,
                "OSS_ENDPOINT or OSS_REGION": endpoint,
                "OSS_ACCESS_KEY_ID": access_key_id,
                "OSS_ACCESS_KEY_SECRET": access_key_secret,
            }.items()
            if not value
        ]
        if missing:
            raise StorageError("Missing OSS storage config: " + ", ".join(missing))
        return AliyunOssTempStorageProvider(
            bucket=bucket,
            endpoint=endpoint,
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
        )
    raise StorageError(f"Unsupported TEMP_STORAGE_PROVIDER: {provider}")
