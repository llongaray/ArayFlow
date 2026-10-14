"""Cloudflare R2 via API compativel com S3. Nao usa token administrativo."""
from __future__ import annotations
import os
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

from dotenv import load_dotenv
from google_client import BASE_DIR

load_dotenv(BASE_DIR / ".env")
_KEY_RE = re.compile(r"^arayflow/\d{4}-\d{2}-\d{2}/ARAY-\d{8}-\d{3,}/[A-Za-z0-9_.-]+\.(png|jpg|jpeg)$", re.I)

class R2Storage:
    def __init__(self, client=None):
        account = os.getenv("R2_ACCOUNT_ID", "").strip()
        access = os.getenv("R2_ACCESS_KEY_ID", "").strip()
        secret = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
        self.bucket = os.getenv("R2_BUCKET_NAME", "").strip()
        self.public_url = os.getenv("R2_PUBLIC_URL", "").strip().rstrip("/")
        parsed = urlsplit(self.public_url)
        if not (account and access and secret and self.bucket and
                parsed.scheme == "https" and parsed.hostname and
                not parsed.username and not parsed.password and
                not parsed.query and not parsed.fragment):
            raise ValueError("Configure R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME e R2_PUBLIC_URL no .env")
        if client is None:
            import boto3
            client = boto3.client("s3",
                endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
                aws_access_key_id=access, aws_secret_access_key=secret,
                region_name="auto")
        self.client = client

    @staticmethod
    def key_for(post_id: str, path: Path) -> str:
        path = Path(path)
        if not re.fullmatch(r"ARAY-\d{8}-\d{3,}", post_id):
            raise ValueError("ID de post invalido")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.(png|jpg|jpeg)", path.name, re.I):
            raise ValueError("Nome de imagem invalido")
        if not path.name.startswith(post_id + "_slide-"):
            raise ValueError("Imagem nao pertence ao post")
        day = f"{post_id[5:9]}-{post_id[9:11]}-{post_id[11:13]}"
        return f"arayflow/{day}/{post_id}/{path.name}"

    def url_for(self, key: str) -> str:
        if not _KEY_RE.fullmatch(key):
            raise ValueError("Chave de objeto R2 invalida")
        return f"{self.public_url}/{quote(key, safe='/')}"

    def check(self):
        return self.client.head_bucket(Bucket=self.bucket)

    def upload(self, post_id: str, path: Path) -> tuple[str, str]:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        key = self.key_for(post_id, path)
        content_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        # Nunca habilitar ACL 'public-read': acesso publico e configurado no bucket.
        self.client.upload_file(str(path), self.bucket, key,
                                ExtraArgs={"ContentType": content_type, "CacheControl":"public, max-age=300"})
        self.client.head_object(Bucket=self.bucket, Key=key)
        return key, self.url_for(key)

    def delete(self, key: str):
        if not _KEY_RE.fullmatch(key):
            raise ValueError("Recusada exclusao fora do prefixo gerenciado pelo ArayFlow")
        self.client.delete_object(Bucket=self.bucket, Key=key)
