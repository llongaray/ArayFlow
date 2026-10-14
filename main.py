"""Aray Social Publisher — lê o Google Sheets e baixa as imagens do Drive.

Não publica na Meta.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from google_client import (
    authenticate,
    download_image,
    extract_folder_id,
    list_images,
    local_path,
    services,
)

from arayflow.editorial import load_sheet_rows
from arayflow.settings import ZONE

DATE_FORMAT = "%d/%m/%Y"


def parse_date(value: str) -> str:
    if value == "tomorrow":
        day = datetime.now(ZONE).date() + timedelta(days=1)
    else:
        day = datetime.strptime(value, "%Y-%m-%d").date()
    return day.strftime(DATE_FORMAT)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verifica posts no Google Sheets e baixa as imagens do Drive; não publica na Meta.",
    )
    parser.add_argument("--date", default="tomorrow", help="AAAA-MM-DD ou tomorrow (padrão)")
    parser.add_argument("--dry-run", action="store_true", help="Somente leitura: não baixa arquivos")
    parser.add_argument("--download", action="store_true", help="Baixa imagens validadas para downloads/")
    parser.add_argument("--check", action="store_true", help="Apenas autentica e valida leitura da planilha")
    args = parser.parse_args()
    if args.dry_run and args.download:
        parser.error("Use apenas um dos modos: --dry-run ou --download.")

    print("ARAY SOCIAL PUBLISHER — P1 (Google; SEM publicação Meta)")
    creds = authenticate()
    sheets, drive = services(creds)
    rows = load_sheet_rows(sheets)
    print(f"[OK] Planilha acessível | registros encontrados: {len(rows)}")
    if args.check:
        return 0

    selected_date = parse_date(args.date)
    selected = [post for post in rows if post.get("Data", "").strip() == selected_date]
    selected.sort(key=lambda post: post.get("Horário", ""))
    print(f"\nData: {selected_date} | posts encontrados: {len(selected)}")
    if not selected:
        print("[INFO] Nenhum post para essa data.")
        return 0

    issues = 0
    day_folder = datetime.strptime(selected_date, DATE_FORMAT).strftime("%Y-%m-%d")
    for post in selected:
        ident = post.get("ID", "?").strip()
        print(f"\n{post.get('Horário', '?').strip()} | {ident} | {post.get('Tipo', '').strip()} | {post.get('Status', '')}")
        try:
            expected = int(post.get("Qtd. imagens", ""))
            if expected < 1:
                raise ValueError("Quantidade de imagens inválida")
            files = list_images(drive, extract_folder_id(post.get("Pasta das imagens", "")))
            print(f"    Imagens: esperadas={expected} encontradas={len(files)}")
            for item in files:
                print(f"      - {item['name']}")
            if len(files) != expected:
                raise ValueError("Quantidade de imagens diferente da planilha.")
            if not post.get("Legenda pronta", "").strip():
                raise ValueError("Legenda vazia.")
            if args.download:
                safe_id = re.sub(r"[^A-Za-z0-9_-]+", "_", ident)
                dest_folder = local_path("DOWNLOAD_DIR", "downloads") / day_folder / safe_id
                for item in files:
                    dest = dest_folder / Path(item["name"]).name
                    download_image(drive, item, dest)
                    print(f"    [BAIXADO] {dest}")
            else:
                print("    [OK] Verificado; nenhuma imagem baixada (modo de leitura).")
        except Exception as exc:
            issues += 1
            print(f"    [ERRO] {type(exc).__name__}: {exc}")
    print(f"\nResultado: {len(selected) - issues}/{len(selected)} publicações validadas. Nenhuma publicação Meta realizada.")
    return 1 if issues else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        sys.exit(1)
