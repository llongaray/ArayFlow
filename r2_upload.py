"""CLI Cloudflare R2: conexao, upload explicito e manifesto local.

Nao faz chamadas a API Meta e nunca publica no Instagram.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from google_client import BASE_DIR
from image_validator import validate_batch
from r2_storage import R2Storage

load_dotenv(BASE_DIR / ".env")

def images_for(post: str) -> list[Path]:
    day = datetime.strptime(post[5:13], "%Y%m%d").strftime("%Y-%m-%d")
    folder = BASE_DIR / "downloads" / day / post
    paths = [
        p for p in folder.iterdir()
        if p.is_file() and re.fullmatch(
            re.escape(post) + r"_slide-\d+\.(png|jpg|jpeg)", p.name, re.I
        )
    ] if folder.exists() else []
    return sorted(paths, key=lambda p: int(re.search(r"_slide-(\d+)", p.name).group(1)))

def main() -> int:
    parser = argparse.ArgumentParser(description="ArayFlow R2 — nenhum comando publica no Instagram")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Verifica autenticacao com o bucket R2")
    group.add_argument("--post", help="Valida um post local e lista URLs planejadas, sem upload por padrao")
    parser.add_argument("--upload", action="store_true", help="Faz upload real das imagens ao R2; pede confirmacao")
    args = parser.parse_args()
    storage = R2Storage()
    if args.check:
        if args.upload:
            parser.error("--upload exige --post")
        storage.check()
        print(f"[OK] R2 acessivel: {storage.bucket}")
        print("[OK] Nenhuma imagem enviada.")
        return 0
    if not re.fullmatch(r"ARAY-\d{8}-\d{3,}", args.post):
        parser.error("ID de post invalido")
    paths = images_for(args.post)
    validate_batch(paths)
    print(f"Post: {args.post} | imagens: {len(paths)}")
    for path in paths:
        key = storage.key_for(args.post, path)
        print(f"  {path.name} -> {storage.url_for(key)}")
    if not args.upload:
        print("[DRY-RUN] Nenhum upload R2 e nenhuma publicacao Meta.")
        return 0
    if input("Arquivos ficarao publicos. Digite ENVIAR R2: ").strip() != "ENVIAR R2":
        print("Cancelado.")
        return 1
    manifest = {}
    for path in paths:
        key, url = storage.upload(args.post, path)
        manifest[path.name] = url
        print(f"  [ENVIADO] {key}")
    target = BASE_DIR / "data" / f"{args.post}-r2-urls.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] {len(manifest)} imagens enviadas. Manifesto local: {target}")
    print("[INFO] URLs publicas; revise antes de executar publish_post.py --prepare.")
    print("[INFO] Nenhum conteiner Meta criado; nada publicado.")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        sys.exit(1)
