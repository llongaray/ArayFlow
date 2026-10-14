"""CLI segura: validar -> preparar conteiner -> publicar, sempre em etapas distintas.

URLs publicas sao fornecidas por um manifesto local JSON (fora do Git).
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google_client import authenticate, services, read_calendar, BASE_DIR
from image_validator import validate_batch
from instagram_publisher import InstagramPublisher
from publication_store import PublicationStore

load_dotenv(BASE_DIR / ".env")

def post_files(post_id: str, day: str) -> list[Path]:
    folder = BASE_DIR / "downloads" / day / post_id
    files = sorted(folder.glob("*_slide-*.png")) + sorted(folder.glob("*_slide-*.jpg"))
    files = [p for p in files if not re.search(r"(alternativa|backup|alternative)",p.name,re.I)]
    return sorted(files, key=lambda p: int(re.search(r"slide-(\d+)", p.name).group(1)))

def load_post(post_id: str):
    creds = authenticate()
    sheets, _ = services(creds)
    rows = read_calendar(
        sheets,
        os.getenv("GOOGLE_SPREADSHEET_ID", "1dA5GFM2qS6RXzpgEiBXLHO4uYkwp4l46B17dCZCcZKM"),
        os.getenv("GOOGLE_SHEET_NAME","Calendário")
    )
    matches = [p for p in rows if p.get("ID","").strip() == post_id]
    if len(matches) != 1:
        raise ValueError(f"Esperado 1 post com ID={post_id}, encontrados {len(matches)}")
    return matches[0]

def main():
    parser = argparse.ArgumentParser(description="ArayFlow v0.2.0 — modo seguro por padrao")
    parser.add_argument("--post", required=True, help="Ex.: ARAY-20261014-001")
    parser.add_argument("--manifest", help="JSON local com {nome_arquivo: url_https_publica}")
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--prepare", action="store_true", help="Cria conteineres na Meta, mas NAO publica")
    commands.add_argument("--publish", action="store_true", help="Publica conteiner preparado; pede confirmacao")
    args = parser.parse_args()
    if not re.fullmatch(r"ARAY-\d{8}-\d{3,}", args.post):
        parser.error("ID invalido")
    date_value = datetime.strptime(args.post[5:13], "%Y%m%d").strftime("%Y-%m-%d")
    post = load_post(args.post)
    expected_date = datetime.strptime(post["Data"], "%d/%m/%Y").strftime("%Y-%m-%d")
    if date_value != expected_date:
        raise ValueError("Data da planilha difere da data no ID")
    images = post_files(args.post,date_value)
    expected = int(post["Qtd. imagens"])
    if len(images) != expected:
        raise ValueError(f"Esperadas {expected} imagens baixadas; encontradas {len(images)}. Execute main.py --download")
    reports = validate_batch(images)
    caption = post.get("Legenda pronta","").strip()
    if not caption:
        raise ValueError("Legenda vazia")
    status = post.get("Status","").strip()
    print(f"Post {args.post} | status: {status} | {len(images)} imagens")
    for r in reports:
        print(f"  [OK] {r.path.name}: {r.width}x{r.height} {r.format}")
    print(f"  Legenda: {len(caption)} caracteres")

    db_path = BASE_DIR / "data" / "arayflow.sqlite3"
    db = PublicationStore(db_path)
    try:
        previous = db.get(args.post)
        if previous:
            print(f"  Registro local: {previous[0]} | media={previous[1] or '-'} | container={previous[2] or '-'}")
        if not args.prepare and not args.publish:
            print("[DRY-RUN] Imagens e legenda validadas. Nenhuma chamada de escrita Meta.")
            return 0
        if status.casefold() not in {"aprovado","aprovado para publicação","aprovado para publicacao"}:
            raise ValueError("Post ainda nao aprovado na planilha. Altere o Status para 'Aprovado' apos revisao.")
        if previous and previous[0] in {"preparing","published","publishing","uncertain","failed"}:
            raise RuntimeError("Publicacao ja enviada ou em estado incerto. Verifique no Instagram antes de repetir.")
        publisher = InstagramPublisher(os.getenv("TOKEN","").strip(), os.getenv("CONTA_INSTA_ID","").strip())
        account = publisher.check_account()
        print(f"  Conta validada: @{account['username']}")
        if args.prepare:
            if previous and previous[0] == "prepared":
                raise RuntimeError("Conteiner ja preparado. Evitando preparo duplicado.")
            if not args.manifest:
                raise ValueError("Informe --manifest com URLs HTTPS publicas, uma por arquivo")
            manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8-sig"))
            if not isinstance(manifest, dict):
                raise ValueError("Manifesto deve ser objeto JSON")
            urls = []
            for path in images:
                if path.name not in manifest:
                    raise ValueError(f"URL ausente no manifesto: {path.name}")
                url = manifest[path.name]
                publisher.validate_url(url)
                urls.append(url)
            print("[ATENCAO] Criara conteineres na Meta. Isso NAO publica o post.")
            if input("Digite PREPARAR ARAY: ").strip() != "PREPARAR ARAY":
                print("Cancelado.")
                return 1
            if not db.claim(args.post):
                raise RuntimeError("Sessao ja existente; conferir SQLite antes de novo preparo.")
            cid = publisher.prepare(urls,caption)
            if not db.transition(args.post,"preparing","prepared",container_id=cid):
                raise RuntimeError("Falha ao registrar conteiner; conferir SQLite.")
            print(f"[OK] Conteiner pronto: {cid}. Nada publicado.")
            return 0

        if not previous or previous[0] != "prepared" or not previous[2]:
            raise RuntimeError("Nao ha conteiner preparado no SQLite. Use --prepare antes.")
        print("[ATENCAO] PUBLICACAO REAL E IMEDIATA NO INSTAGRAM.")
        print(f"  Post: {args.post} | Conteiner: {previous[2]}")
        if input("Digite exatamente PUBLICAR ARAY: ").strip() != "PUBLICAR ARAY":
            print("Cancelado.")
            return 1
        # Uma tentativa de publicacao nunca e repetida automaticamente.
        if not db.transition(args.post,"prepared","publishing"):
            raise RuntimeError("Sessao ja alterada por outro processo; publicacao bloqueada.")
        try:
            media_id = publisher.publish(previous[2])
        except Exception:
            db.transition(args.post,"publishing","uncertain")
            raise RuntimeError("Resposta incerta da Meta: conferir Instagram manualmente antes de nova tentativa.")
        db.transition(args.post,"publishing","published",media_id=media_id)
        print(f"[OK] Meta retornou Media ID={media_id}. Confira no Instagram.")
        print("[INFO] Planilha nao alterada nesta versao (escopos Google somente leitura).")
        return 0
    finally:
        db.close()

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"[ERRO] {exc}",file=sys.stderr)
        sys.exit(1)
