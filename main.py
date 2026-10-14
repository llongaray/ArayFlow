"""Aray Social Publisher — P1 Google Sheets + Drive (sem publicação na Meta)."""
from __future__ import annotations
import argparse
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from google_client import authenticate, services, read_calendar, extract_folder_id, list_images, download_image, BASE_DIR, local_path

DATE_FORMAT = '%d/%m/%Y'


def parse_date(value: str) -> str:
    if value == 'tomorrow':
        from datetime import timezone
        try:
            from zoneinfo import ZoneInfo
            day = datetime.now(ZoneInfo('America/Sao_Paulo')).date() + timedelta(days=1)
        except Exception:
            # Windows sem tzdata: evitar escolher uma data no fuso errado.
            raise RuntimeError('Instale tzdata (`py -m pip install tzdata`) ou informe --date AAAA-MM-DD.')
    else:
        day = datetime.strptime(value, '%Y-%m-%d').date()
    return day.strftime(DATE_FORMAT)


def main() -> int:
    parser = argparse.ArgumentParser(description='Verifica posts no Google Sheets e baixa as imagens do Drive; não publica na Meta.')
    parser.add_argument('--date', default='tomorrow', help='AAAA-MM-DD ou tomorrow (padrão)')
    parser.add_argument('--dry-run', action='store_true', help='Somente leitura: não baixa arquivos')
    parser.add_argument('--download', action='store_true', help='Baixa imagens validadas para downloads/')
    parser.add_argument('--check', action='store_true', help='Apenas autentica e valida leitura da planilha')
    args = parser.parse_args()
    if args.dry_run and args.download:
        parser.error('Use apenas um dos modos: --dry-run ou --download.')

    spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID', '1dA5GFM2qS6RXzpgEiBXLHO4uYkwp4l46B17dCZCcZKM').strip()
    sheet_name = os.getenv('GOOGLE_SHEET_NAME', 'Calendário').strip()
    print('ARAY SOCIAL PUBLISHER — P1 (Google; SEM publicação Meta)')
    creds = authenticate()
    sheets, drive = services(creds)
    rows = read_calendar(sheets, spreadsheet_id, sheet_name)
    print(f'[OK] Planilha acessível | registros encontrados: {len(rows)}')
    if args.check:
        return 0

    selected_date = parse_date(args.date)
    selected = [p for p in rows if p.get('Data', '').strip() == selected_date]
    selected.sort(key=lambda p: p.get('Horário', ''))
    print(f'\nData: {selected_date} | posts encontrados: {len(selected)}')
    if not selected:
        print('[INFO] Nenhum post para essa data.')
        return 0
    issues = 0
    for post in selected:
        ident = post.get('ID', '?').strip()
        time = post.get('Horário', '?').strip()
        typ = post.get('Tipo', '').strip()
        link = post.get('Pasta das imagens', '')
        print(f'\n{time} | {ident} | {typ} | {post.get("Status", "")}')
        try:
            expected = int(post.get('Qtd. imagens', ''))
            if expected < 1:
                raise ValueError('Quantidade de imagens inválida')
            folder_id = extract_folder_id(link)
            files = list_images(drive, folder_id)
            print(f'    Imagens: esperadas={expected} encontradas={len(files)}')
            for f in files:
                print(f'      - {f["name"]}')
            if len(files) != expected:
                raise ValueError('Quantidade de imagens diferente da planilha.')
            if not post.get('Legenda pronta', '').strip():
                raise ValueError('Legenda vazia.')
            if args.download:
                dest_folder = local_path('DOWNLOAD_DIR', 'downloads') / datetime.strptime(selected_date, DATE_FORMAT).strftime('%Y-%m-%d') / re.sub(r'[^A-Za-z0-9_-]+', '_', ident)
                for f in files:
                    dest = dest_folder / Path(f['name']).name
                    download_image(drive, f, dest)
                    print(f'    [BAIXADO] {dest}')
            else:
                print('    [OK] Verificado; nenhuma imagem baixada (modo de leitura).')
        except Exception as e:
            issues += 1
            print(f'    [ERRO] {type(e).__name__}: {e}')
    print(f'\nResultado: {len(selected)-issues}/{len(selected)} publicações validadas. Nenhuma publicação Meta realizada.')
    return 1 if issues else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        print(f'[ERRO] {exc}', file=sys.stderr)
        sys.exit(1)
