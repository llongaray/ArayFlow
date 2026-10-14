"""Google OAuth + Google Sheets/Drive para o calendário editorial Aray."""
from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid',
]


def local_path(name: str, default: str) -> Path:
    value = os.getenv(name, default)
    p = Path(value)
    return p if p.is_absolute() else BASE_DIR / p


def authenticate():
    credentials_file = local_path('GOOGLE_OAUTH_CLIENT_FILE', 'config/google_credentials.json')
    token_file = local_path('GOOGLE_TOKEN_FILE', 'config/google_token.json')
    creds = None
    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        except (ValueError, OSError) as exc:
            raise RuntimeError(f'Token OAuth local inválido: {exc}. Exclua apenas o token local e autentique novamente.') from exc
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:
            raise RuntimeError(f'Não foi possível renovar a sessão Google: {exc}. Reautorize a conta.') from exc
    if not creds or not creds.valid:
        if not credentials_file.exists():
            raise FileNotFoundError(
                f'Credencial OAuth não encontrada: {credentials_file}\n'
                'Crie um cliente OAuth do tipo Aplicativo para computador no Google Cloud, '
                'habilite Sheets API e Drive API e salve o JSON nesse caminho.'
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding='utf-8')
    # Validação efetiva de conta para evitar gravação de token do Google pessoal.
    import requests
    resp = requests.get('https://www.googleapis.com/oauth2/v3/userinfo',
                        headers={'Authorization': f'Bearer {creds.token}'}, timeout=20)
    resp.raise_for_status()
    email = resp.json().get('email', '')
    expected = os.getenv('GOOGLE_ACCOUNT_EMAIL', 'aray.solucoes@gmail.com').strip().lower()
    if email.lower() != expected:
        token_file.unlink(missing_ok=True)
        raise RuntimeError(f'Conta Google incorreta: {email!r}. Esperada: {expected!r}. Token local descartado.')
    print(f'[OK] Conta Google validada: {email}')
    return creds


def services(creds):
    return build('sheets', 'v4', credentials=creds, cache_discovery=False), build('drive', 'v3', credentials=creds, cache_discovery=False)


def read_calendar(sheets: Any, spreadsheet_id: str, sheet_name: str) -> list[dict[str, str]]:
    safe_name = sheet_name.replace("'", "''")
    result = sheets.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=f"'{safe_name}'!A1:T1000"
    ).execute()
    values = result.get('values', [])
    if not values:
        raise RuntimeError('A planilha está vazia, sem cabeçalho.')
    headers = [str(h).strip() for h in values[0]]
    required = ['ID', 'Data', 'Horário', 'Tipo', 'Qtd. imagens', 'Pasta das imagens', 'Legenda pronta', 'Status']
    missing = [x for x in required if x not in headers]
    if missing:
        raise RuntimeError(f'Faltam colunas obrigatórias: {missing}. Encontradas: {headers}')
    return [dict(zip(headers, [str(v) for v in row] + [''] * (len(headers) - len(row)))) for row in values[1:] if any(str(v).strip() for v in row)]


def extract_folder_id(value: str) -> str:
    value = value.strip()
    m = re.search(r'/folders/([A-Za-z0-9_-]+)', value)
    if m:
        return m.group(1)
    qs = parse_qs(urlparse(value).query)
    if 'id' in qs:
        return qs['id'][0]
    if re.fullmatch(r'[A-Za-z0-9_-]{20,}', value):
        return value
    raise ValueError(f'Link de pasta do Google Drive inválido: {value!r}')


def list_images(drive: Any, folder_id: str) -> list[dict[str, Any]]:
    files = []
    page_token = None
    while True:
        result = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields='nextPageToken,files(id,name,mimeType,size)',
            pageSize=1000,
            pageToken=page_token,
        ).execute()
        files.extend(f for f in result.get('files', []) if f.get('mimeType') in ('image/jpeg', 'image/png'))
        page_token = result.get('nextPageToken')
        if not page_token:
            break
    # Alternativas não contam como slides oficiais.
    files = [f for f in files if not re.search(r'(alternativa|alternative|backup)', f['name'], re.I)]
    return sorted(files, key=lambda f: (int(re.search(r'slide[-_ ]*(\d+)', f['name'], re.I).group(1)) if re.search(r'slide[-_ ]*(\d+)', f['name'], re.I) else 999, f['name'].lower()))


def download_image(drive: Any, file: dict[str, Any], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = drive.files().get_media(fileId=file['id'])
    with destination.open('wb') as handle:
        downloader = MediaIoBaseDownload(handle, request, chunksize=1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()
