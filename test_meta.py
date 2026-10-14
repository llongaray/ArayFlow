"""Teste somente de leitura da Instagram API com Instagram Login.

Requer: pip install requests python-dotenv
Variáveis em .env (na mesma pasta deste arquivo):
    CONTA_INSTA_ID=
    APP_INSTA_ID=
    KEY_SECRET_INSTA=
    TOKEN=

Nunca imprime nem transmite APP_INSTA_ID/KEY_SECRET_INSTA. Não publica nada.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_URL = "https://graph.instagram.com"
TIMEOUT = 20


def main() -> int:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        print(f"[ERRO] Arquivo .env não encontrado em: {env_path.parent}")
        return 1

    load_dotenv(dotenv_path=env_path, override=False)
    token = os.getenv("TOKEN", "").strip().strip('"').strip("'")
    expected_id = os.getenv("CONTA_INSTA_ID", "").strip()
    app_id = os.getenv("APP_INSTA_ID", "").strip()
    app_secret = os.getenv("KEY_SECRET_INSTA", "").strip()

    if not token:
        print("[ERRO] Variável TOKEN está vazia no .env.")
        return 1
    if not expected_id:
        print("[AVISO] CONTA_INSTA_ID vazia: não será possível comparar IDs.")
    if not app_id or not app_secret:
        print("[INFO] APP_INSTA_ID/KEY_SECRET_INSTA não são necessários para este teste de leitura.")

    print("[1/2] Consultando o perfil autenticado (somente leitura)...")
    try:
        # Autenticação via header evita token na URL e em mensagens de erro HTTP.
        response = requests.get(
            f"{BASE_URL}/me",
            headers={"Authorization": f"Bearer {token}"},
            params={"fields": "id,username,account_type"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        # Não incluir o objeto completo da exceção para evitar exposição de credenciais.
        print(f"[ERRO] Falha de rede: {type(exc).__name__}.")
        return 2

    try:
        payload = response.json()
    except ValueError:
        print(f"[ERRO] Meta retornou resposta não JSON (HTTP {response.status_code}).")
        return 2

    if not response.ok or "error" in payload:
        error = payload.get("error") or {}
        # Mostrar somente campos de diagnóstico que não contêm credenciais.
        print(f"[ERRO] API retornou HTTP {response.status_code}.")
        print(f"       Código: {error.get('code', 'não informado')}; tipo: {error.get('type', 'não informado')}")
        if error.get("error_subcode") is not None:
            print(f"       Subcódigo: {error['error_subcode']}")
        print("       Verifique se o TOKEN é de Instagram Login, está válido e tem instagram_business_basic.")
        return 2

    returned_id = str(payload.get("id", ""))
    username = payload.get("username", "(não retornado)")
    account_type = payload.get("account_type", "(não retornado)")

    print("[OK] Autenticação e leitura do perfil funcionaram.")
    print(f"     Conta: @{username}")
    print(f"     Tipo: {account_type}")
    print(f"     ID retornado: {returned_id}")

    print("[2/2] Conferindo a conta configurada...")
    if expected_id and returned_id != expected_id:
        print("[ATENÇÃO] CONTA_INSTA_ID difere do ID retornado pela API.")
        print("          Confira qual identificador pertence à modalidade Instagram Login.")
        return 3
    if expected_id:
        print("[OK] O ID retornado corresponde a CONTA_INSTA_ID.")
    else:
        print("[INFO] Informe CONTA_INSTA_ID no .env para validar a correspondência.")

    print("\nTeste concluído. Nenhum post foi criado ou agendado.")
    print("OBS: este teste NÃO confirma que instagram_business_content_publish está autorizado no token.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
