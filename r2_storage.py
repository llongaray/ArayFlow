"""Cloudflare R2 via API compativel com S3. Nao usa token administrativo."""
from __future__ import annotations
import os
import re
from pathlib import Path
from datetime import datetime
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
        if not self.is_managed_key(key):
            raise ValueError("Chave de objeto R2 invalida")
        return f"{self.public_url}/{quote(key, safe='/')}"

    @staticmethod
    def is_managed_key(key: str) -> bool:
        """Exclui somente objetos da estrutura gerenciada pelo ArayFlow."""
        if not _KEY_RE.fullmatch(key):
            return False
        parts = key.split("/")
        _, day, post_id, filename = parts
        try:
            parsed_day = datetime.strptime(post_id[5:13], "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            return False
        return day == parsed_day and bool(re.fullmatch(
            re.escape(post_id) + r"_slide-\d+\.(png|jpg|jpeg)", filename, re.I
        ))

    def list_managed(self) -> list[str]:
        """Lista todos os objetos do prefixo gerenciado, inclusive pagina 2+."""
        keys = []
        token = None
        seen = set()
        while True:
            kwargs = {"Bucket": self.bucket, "Prefix": "arayflow/", "MaxKeys": 1000}
            if token:
                kwargs["ContinuationToken"] = token
            page = self.client.list_objects_v2(**kwargs)
            for obj in page.get("Contents", []):
                key = obj.get("Key", "")
                if self.is_managed_key(key):
                    keys.append(key)
            if not page.get("IsTruncated", False):
                break
            token = page.get("NextContinuationToken")
            if not token or token in seen:
                raise RuntimeError("Paginacao R2 inconsistente; limpeza cancelada")
            seen.add(token)
        return sorted(set(keys))

    def remote_sha256(self, key: str) -> str | None:
        if not self.is_managed_key(key):
            raise ValueError("Chave R2 fora do padrao gerenciado")
        info = self.client.head_object(Bucket=self.bucket, Key=key)
        return (info.get("Metadata") or {}).get("sha256")

    def check(self):
        return self.client.head_bucket(Bucket=self.bucket)

    def upload(self, post_id: str, path: Path, sha256: str | None = None) -> tuple[str, str]:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        key = self.key_for(post_id, path)
        content_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        # Nunca habilitar ACL 'public-read': acesso publico e configurado no bucket.
        extra = {"ContentType": content_type, "CacheControl": "public, max-age=300"}
        if sha256:
            if not re.fullmatch(r"[a-f0-9]{64}", sha256):
                raise ValueError("SHA256 invalido")
            extra["Metadata"] = {"sha256": sha256}
        self.client.upload_file(str(path), self.bucket, key, ExtraArgs=extra)
        self.client.head_object(Bucket=self.bucket, Key=key)
        return key, self.url_for(key)

    def delete(self, key: str):
        if not self.is_managed_key(key):
            raise ValueError("Recusada exclusao fora do prefixo gerenciado pelo ArayFlow")
        self.client.delete_object(Bucket=self.bucket, Key=key)
