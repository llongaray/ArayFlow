"""Publicacao pela Instagram API; URLs das imagens devem ser HTTPS publicas."""
from __future__ import annotations
import time
from urllib.parse import urlparse
import requests

class InstagramPublisher:
    def __init__(self, token: str, account_id: str, version="v24.0"):
        if not token or not account_id:
            raise ValueError("TOKEN e CONTA_INSTA_ID obrigatorios")
        self.token = token
        self.account_id = account_id
        self.base = f"https://graph.instagram.com/{version}"

    def _api(self, method, path, *, data=None, params=None):
        response = requests.request(
            method, self.base + path, data=data, params=params,
            headers={"Authorization": f"Bearer {self.token}"}, timeout=40
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Meta HTTP {response.status_code}: resposta nao JSON") from exc
        if not response.ok or "error" in payload:
            error = payload.get("error", {})
            raise RuntimeError(
                f"Meta HTTP {response.status_code}: {error.get('message', payload)}"
            )
        return payload

    def check_account(self, expected_username="aray_solucoes"):
        user = self._api("GET", "/me", params={"fields":"id,username,account_type"})
        if str(user.get("id")) != str(self.account_id):
            raise RuntimeError("ID da conta Instagram nao corresponde ao token")
        if user.get("username","").lower() != expected_username.lower():
            raise RuntimeError("Username inesperado: publicacao bloqueada")
        if user.get("account_type") != "BUSINESS":
            raise RuntimeError("Conta Instagram nao e BUSINESS")
        return user

    @staticmethod
    def validate_url(url: str):
        p = urlparse(url)
        if p.scheme != "https" or not p.netloc or p.username or p.password or p.fragment:
            raise ValueError("Imagem exige URL HTTPS publica, sem credenciais ou fragmento")
        if p.hostname in {"localhost", "127.0.0.1"}:
            raise ValueError("A Meta nao pode acessar localhost")
        return url

    def make_container(self, *, url: str, caption: str="", carousel_item=False):
        self.validate_url(url)
        payload = {"image_url":url}
        if carousel_item:
            payload["is_carousel_item"] = "true"
        elif caption:
            payload["caption"] = caption
        result = self._api("POST", f"/{self.account_id}/media", data=payload)
        if not result.get("id"):
            raise RuntimeError("Meta nao retornou ID de conteiner")
        return str(result["id"])

    def wait(self, container_id: str, attempts=15, interval=5):
        for _ in range(attempts):
            status = self._api("GET", f"/{container_id}",
                               params={"fields":"status_code,status"})
            code = status.get("status_code")
            if code == "FINISHED":
                return
            if code in {"ERROR","EXPIRED"}:
                raise RuntimeError(f"Conteiner {container_id}: {status}")
            time.sleep(interval)
        raise RuntimeError(f"Timeout no conteiner {container_id}; consulte antes de tentar novamente")

    def prepare(self, image_urls: list[str], caption: str):
        if not image_urls or len(image_urls) > 10:
            raise ValueError("Quantidade de imagens invalida (1 a 10)")
        if len(image_urls) == 1:
            cid = self.make_container(url=image_urls[0], caption=caption)
            self.wait(cid)
            return cid
        children = []
        for url in image_urls:
            cid = self.make_container(url=url, carousel_item=True)
            self.wait(cid)
            children.append(cid)
        parent = self._api("POST", f"/{self.account_id}/media", data={
            "media_type":"CAROUSEL", "children":",".join(children), "caption":caption
        })
        cid = str(parent["id"])
        self.wait(cid)
        return cid

    def publish(self, container_id: str):
        result = self._api("POST", f"/{self.account_id}/media_publish",
                           data={"creation_id":container_id})
        media_id = str(result.get("id", ""))
        if not media_id:
            raise RuntimeError("Meta nao retornou Media ID; conferir conta antes de tentar novamente")
        return media_id
