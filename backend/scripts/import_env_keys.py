"""
把服务器现有环境变量里的 API 密钥导入 api_key_configs 数据库。
在容器内运行：python /app/scripts/import_env_keys.py
"""
import os, sys, base64, hashlib, sqlite3
from pathlib import Path

DB_PATH = os.getenv("HAIR_AI_DB_PATH", "/data/hair_ai.sqlite3")
ENC_KEY  = os.getenv("PLATFORM_SECRET_ENCRYPTION_KEY", "local-dev-key")

def encrypt(plaintext: str) -> str:
    key_stream = hashlib.sha256(ENC_KEY.encode()).digest()
    raw = plaintext.encode("utf-8")
    return base64.urlsafe_b64encode(
        bytes(b ^ key_stream[i % len(key_stream)] for i, b in enumerate(raw))
    ).decode()

def mask(s: str) -> str:
    if len(s) <= 8: return "*" * len(s)
    return f"{s[:4]}***{s[-4:]}"

# provider / key_name / 环境变量名
KEY_MAP = [
    ("dify",       "api_key",          "DIFY_API_KEY"),
    ("dashscope",  "api_key",          "ALIYUN_DASHSCOPE_API_KEY"),
    ("oss",        "access_key_id",    "OSS_ACCESS_KEY_ID"),
    ("oss",        "access_key_secret","OSS_ACCESS_KEY_SECRET"),
]

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
imported = 0
skipped  = 0

for provider, key_name, env_var in KEY_MAP:
    value = os.getenv(env_var, "").strip()
    if not value:
        print(f"  SKIP  {provider}/{key_name}  ({env_var} 未设置)")
        skipped += 1
        continue

    ciphertext  = encrypt(value)
    fingerprint = hashlib.sha256(value.encode()).hexdigest()[:16]
    masked      = mask(value)

    existing = conn.execute(
        "SELECT id FROM api_key_configs WHERE provider=? AND key_name=? AND tenant_id IS NULL",
        (provider, key_name)
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE api_key_configs
               SET secret_ciphertext=?, secret_fingerprint=?, masked_secret=?,
                   status='active', updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (ciphertext, fingerprint, masked, existing["id"])
        )
        print(f"  UPDATE {provider}/{key_name}  → {masked}")
    else:
        conn.execute(
            """INSERT INTO api_key_configs
               (tenant_id, provider, key_name, secret_ciphertext, secret_fingerprint, masked_secret)
               VALUES (NULL, ?, ?, ?, ?, ?)""",
            (provider, key_name, ciphertext, fingerprint, masked)
        )
        print(f"  INSERT {provider}/{key_name}  → {masked}")
    imported += 1

conn.commit()
conn.close()
print(f"\n完成：导入 {imported} 条，跳过 {skipped} 条（未设置的环境变量）")
