#!/usr/bin/env python3
"""Teste seguro da Instagram API com Instagram Login.

Padrão: somente leitura, sem criação de mídia nem publicação.
Publicação real: --publish com confirmação interativa explícita.
"""
import argparse
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

BASE = "https://graph.instagram.com"


def request_api(method, url, token, *, params=None, data=None):
    try:
        response = requests.request(
            method, url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            data=data,
            timeout=35,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Falha na conexão: {exc}") from exc
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError(f"A API respondeu HTTP {response.status_code} sem JSON válido")
    if not response.ok or "error" in payload:
        error = payload.get("error", {})
        raise RuntimeError(
            f"API HTTP {response.status_code}: "
            f"{error.get('message', 'Erro desconhecido')} "
            f"(code={error.get('code', '?')}, subcode={error.get('error_subcode', '?')})"
        )
    return payload


def main():
    parser = argparse.ArgumentParser(description="Teste de publicação Instagram (modo seguro padrão)")
    parser.add_argument("--image-url", help="URL HTTPS pública, direta e acessível da imagem JPG/PNG")
    parser.add_argument("--caption", help="Legenda de teste (texto literal)")
    parser.add_argument("--caption-file", help="Arquivo UTF-8 com a legenda")
    parser.add_argument("--publish", action="store_true", help="CRIAR contêiner e PUBLICAR realmente (exige confirmação)")
    parser.add_argument("--create-container", action="store_true", help="CRIAR contêiner de teste, mas NÃO publicar")
    parser.add_argument("--check-container", help="Consultar status de contêiner existente, sem publicar")
    parser.add_argument("--version", default="v24.0", help="Versão da Graph API (padrão: v24.0)")
    args = parser.parse_args()
    load_dotenv(Path(__file__).with_name(".env"))
    token = os.getenv("TOKEN", "").strip()
    configured_id = os.getenv("CONTA_INSTA_ID", "").strip()
    if not token or not configured_id:
        parser.error("Preencha TOKEN e CONTA_INSTA_ID no .env da pasta do script")
    if args.publish and args.create_container:
        parser.error("Use --publish OU --create-container, não ambos")
    if args.caption and args.caption_file:
        parser.error("Use --caption OU --caption-file, não ambos")
    caption = args.caption or (Path(args.caption_file).read_text(encoding="utf-8") if args.caption_file else "")
    version = args.version.strip("/")
    api = f"{BASE}/{version}"

    print("[1] Verificando identidade da conta (somente leitura)...")
    me = request_api("GET", f"{api}/me", token, params={"fields": "id,username,account_type"})
    print(f"    @{me.get('username', '?')} | tipo={me.get('account_type', '?')} | ID={me.get('id', '?')}")
    if str(me.get("id")) != configured_id:
        print("[ERRO] CONTA_INSTA_ID diferente da conta autorizada. Abortado.", file=sys.stderr)
        return 2
    if me.get("username", "").lower() != "aray_solucoes":
        print("[ERRO] A conta autenticada não é @aray_solucoes. Abortado.", file=sys.stderr)
        return 2

    if args.check_container:
        print("[2] Consultando contêiner (somente leitura)...")
        status = request_api("GET", f"{api}/{args.check_container}", token,
                             params={"fields": "id,status_code,status"})
        print(f"    id={status.get('id')} status_code={status.get('status_code')} "
              f"detalhe={status.get('status', '')}")
        return 0

    if args.image_url:
        parsed = urlparse(args.image_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            parser.error("--image-url deve ser uma URL HTTPS direta e sem credenciais")
        print(f"[2] URL informada: {parsed.scheme}://{parsed.netloc}{parsed.path}")
        print("    Confira se é uma imagem pública direta; links de pasta ou visualização do Drive não servem.")
    else:
        print("[2] Nenhuma imagem informada.")

    if not (args.publish or args.create_container):
        print("\n[DRY-RUN] Nenhum contêiner criado. Nenhum post publicado.")
        print("Para publicar: py test_publish.py --image-url HTTPS_URL --caption-file legenda.txt --publish")
        print("ATENÇÃO: o sucesso da leitura NÃO confirma instagram_business_content_publish.")
        return 0

    if not args.image_url:
        parser.error("Informe --image-url para criar contêiner ou publicar")
    if args.publish:
        if not caption.strip():
            parser.error("Para --publish, informe --caption ou --caption-file")
        print("\nATENÇÃO: ESTE COMANDO PUBLICARÁ UM POST REAL NO INSTAGRAM.")
        print(f"Conta: @{me['username']} | legenda: {caption[:100]!r}")
        confirmation = input("Digite exatamente PUBLICAR ARAY para confirmar: ").strip()
        if confirmation != "PUBLICAR ARAY":
            print("Cancelado. Nenhuma publicação solicitada.")
            return 1
    else:
        print("\n[TESTE] Será criado apenas um contêiner temporário. Nenhuma publicação será feita.")

    print("[3] Criando contêiner de imagem...")
    container = request_api("POST", f"{api}/{configured_id}/media", token,
                            data={"image_url": args.image_url, "caption": caption})
    cid = str(container.get("id", ""))
    if not cid:
        raise RuntimeError("API não retornou ID de contêiner; publicação não iniciada")
    print(f"    Contêiner criado: {cid}")
    print("    Consulte com: py test_publish.py --check-container", cid)
    if args.create_container:
        print("[OK] Contêiner criado. NÃO foi chamado media_publish; nada foi publicado.")
        return 0

    print("[4] Aguardando processamento...")
    for attempt in range(12):
        status = request_api("GET", f"{api}/{cid}", token, params={"fields": "status_code,status"})
        code = status.get("status_code", "")
        print(f"    Tentativa {attempt + 1}/12: {code}")
        if code == "FINISHED":
            break
        if code in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Contêiner não publicável: {status.get('status', code)}")
        time.sleep(5)
    else:
        raise RuntimeError(f"Contêiner não ficou pronto. Não publicado. ID={cid}")

    print("[5] Publicando no Instagram...")
    published = request_api("POST", f"{api}/{configured_id}/media_publish", token,
                            data={"creation_id": cid})
    print(f"[OK] Publicação enviada. Media ID={published.get('id', '?')}")
    print("Confirme visualmente no perfil antes de registrar como Publicado na planilha.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, UnicodeError) as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        sys.exit(1)