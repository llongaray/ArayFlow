"""ArayFlow v0.7: assistente VISIVEL de agendamento no Meta Business Suite.

O Playwright ajuda no upload e legenda, mas a data/hora, conta Instagram e
botao final AGENDAR devem ser conferidos e acionados pelo operador.
Nunca tenta contornar login, MFA, CAPTCHA ou restricoes da plataforma.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from business_suite_store import BusinessSuiteStore
from publication_store import PublicationStore
from google_client import BASE_DIR, authenticate, read_calendar, services
from scheduled_publish import APPROVED, ensure_local, scheduled_time
from sync_day import single_sync

load_dotenv(BASE_DIR / ".env")
ZONE = ZoneInfo("America/Sao_Paulo")
POST_RE = re.compile(r"ARAY-\d{8}-\d{3,}$")
DB_FILE = BASE_DIR / "data" / "arayflow.sqlite3"
PROFILE_DIR = BASE_DIR / "data" / "playwright_meta_profile"
CAPTION_LABELS = re.compile(
    r"legenda|escreva uma legenda|caption|write a caption|descri[cç][aã]o do post",
    re.I
)


def approved_rows(day: str, post_id: str | None = None) -> tuple[list[dict], object]:
    creds = authenticate()
    sheets, drive = services(creds)
    rows = read_calendar(
        sheets,
        os.getenv("GOOGLE_SPREADSHEET_ID", "1dA5GFM2qS6RXzpgEiBXLHO4uYkwp4l46B17dCZCcZKM"),
        os.getenv("GOOGLE_SHEET_NAME", "Calendário"),
    )
    result = []
    for row in rows:
        if row.get("Data", "").strip() != datetime.strptime(day, "%Y-%m-%d").strftime("%d/%m/%Y"):
            continue
        ident = row.get("ID", "").strip()
        if post_id and ident != post_id:
            continue
        if row.get("Status", "").strip().casefold() not in APPROVED:
            continue
        if not POST_RE.fullmatch(ident):
            raise ValueError(f"ID invalido na planilha: {ident}")
        due = scheduled_time(row)
        if due.date().isoformat() != day:
            raise ValueError(f"ID e data inconsistentes: {ident}")
        result.append(row)
    ids = [r["ID"].strip() for r in result]
    if len(ids) != len(set(ids)):
        raise ValueError("IDs duplicados no Google Sheets; agendamento interrompido")
    return sorted(result, key=scheduled_time), drive


def candidate_caption_field(page):
    """Escolhe somente um campo com identificacao semantica inequivoca."""
    candidates = [
        page.get_by_role("textbox", name=CAPTION_LABELS),
        page.get_by_placeholder(CAPTION_LABELS),
        page.locator('[aria-label*="legenda" i][contenteditable="true"]'),
        page.locator('[aria-label*="caption" i][contenteditable="true"]'),
    ]
    for locator in candidates:
        try:
            visible = []
            for n in range(min(locator.count(), 8)):
                element = locator.nth(n)
                if element.is_visible():
                    visible.append(element)
            if len(visible) == 1:
                return visible[0]
            if len(visible) > 1:
                return None
        except Exception:
            continue
    return None


def try_prefill(page, files: list[Path], caption: str) -> dict[str, bool]:
    """Preenche apenas controles nao ambiguos; nunca clica em Publicar/Agendar."""
    result = {"images": False, "caption": False}
    try:
        inputs = page.locator('input[type="file"]')
        # Em geral o seletor de upload existe apos abrir o compositor.
        candidates = []
        for i in range(min(inputs.count(), 8)):
            el = inputs.nth(i)
            accept = (el.get_attribute("accept") or "").lower()
            if (not accept or "image" in accept or ".png" in accept or ".jpg" in accept):
                candidates.append(el)
        if len(candidates) == 1:
            candidates[0].set_input_files([str(path.resolve()) for path in files], timeout=30_000)
            result["images"] = True
    except Exception as exc:
        print(f"[AVISO] Upload automatico indisponivel: {type(exc).__name__}; adicione imagens manualmente.")
    try:
        field = candidate_caption_field(page)
        if field is not None:
            field.fill(caption, timeout=8_000)
            result["caption"] = True
    except Exception as exc:
        print(f"[AVISO] Campo de legenda nao identificado: {type(exc).__name__}; preencha manualmente.")
    return result


def manual_schedule(page, row: dict, images: list[Path], ledger: BusinessSuiteStore) -> bool:
    ident = row["ID"].strip()
    due = scheduled_time(row)
    if due <= datetime.now(ZONE):
        print(f"[IGNORADO] {ident}: horario {due:%d/%m/%Y %H:%M} ja passou.")
        return True
    current = ledger.get(ident)
    if current:
        print(f"[PROTEGIDO] {ident}: sessao existente '{current['status']}'. Nao duplicar.")
        return True

    print(f"\n{'='*65}\n{ident} | {due:%d/%m/%Y %H:%M} (America/Sao_Paulo)")
    print(f"Artes: {len(images)} | legenda: {len(row.get('Legenda pronta','').strip())} caracteres")
    print("1) No navegador visivel, acesse o compositor do Business Suite.")
    print("2) Confira a PAGINA e selecione a conta Instagram @aray_solucoes.")
    print("3) Clique em 'Criar publicacao' (ou equivalente).")
    if input("Quando o compositor estiver aberto, digite PRONTO (ou PULAR): ").strip() != "PRONTO":
        print("[PARADO] Operador interrompeu. Nenhuma reserva criada.")
        return False

    # Reservar ANTES de qualquer interacao de envio para impedir concorrencia com API.
    if not ledger.reserve(ident, due.isoformat()):
        print("[PROTEGIDO] Registro existente pela API ou Business Suite; verificar SQLite.")
        return False
    try:
        result = try_prefill(page, images, row["Legenda pronta"].strip())
        print(f"Preenchimento: imagens={'OK' if result['images'] else 'MANUAL'}; legenda={'OK' if result['caption'] else 'MANUAL'}")
        print("Confira no Business Suite: slides na ordem, legenda, destino Instagram,")
        print(f"data {due:%d/%m/%Y}, hora {due:%H:%M}, fuso da conta e OPCAO AGENDAR (nao Publicar agora).")
        print("Complete os campos que nao foram preenchidos automaticamente.")
        print("CLIQUE EM AGENDAR no proprio Business Suite e confirme o post no Planejador.")
        expected = f"AGENDADO {ident}"
        answer = input(f"Somente depois de ver 'Agendado' na Meta, digite '{expected}': ").strip()
        if answer == expected:
            if not ledger.update(ident, "awaiting_confirmation", "scheduled",
                                 "Confirmacao manual pelo operador no Meta Business Suite"):
                raise RuntimeError("Falha ao registrar confirmacao; conferir SQLite")
            print(f"[CONFIRMADO PELO OPERADOR] {ident} | {due:%d/%m/%Y %H:%M}")
            return True
        ledger.update(ident, "awaiting_confirmation", "needs_review",
                      "Sem confirmacao do operador; verificar Meta antes de tentar novamente")
        print(f"[ATENCAO] {ident} marcado como needs_review; NAO tentaremos criar outro post.")
        return False
    except Exception:
        # Falha de navegador pode ocorrer depois do envio: nunca repetir automaticamente.
        ledger.update(ident, "awaiting_confirmation", "needs_review",
                      "Interrupcao ou falha durante preenchimento; conferir Meta manualmente")
        raise


def start_browser(rows: list[dict], drive, ledger: BusinessSuiteStore):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright nao instalado. Execute python -m pip install -r requirements.txt "
            "e python -m playwright install chromium no .venv."
        ) from exc

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), headless=False,
            viewport={"width": 1440, "height": 900},
            accept_downloads=False,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto("https://business.facebook.com/", wait_until="domcontentloaded", timeout=45_000)
            except Exception:
                print("[AVISO] Nao foi possivel carregar a pagina inicial. Verifique a conexao.")
            print("Navegador visivel iniciado; faca login e MFA manualmente, se necessario.")
            print("Sessao isolada em data/playwright_meta_profile (ignorada no Git).")
            api = PublicationStore(DB_FILE)
            try:
                for row in rows:
                    ident = row["ID"].strip()
                    if api.get(ident):
                        print(f"[PROTEGIDO] {ident}: ja possui conteiner/sessao Meta API; ignorado no Suite.")
                        continue
                    if ledger.reserved(ident):
                        print(f"[PROTEGIDO] {ident}: ja possui registro no assistente.")
                        continue
                    due = scheduled_time(row)
                    if due <= datetime.now(ZONE):
                        print(f"[IGNORADO] {ident}: horario ja passou.")
                        continue
                    images = ensure_local(row, drive)
                    if not manual_schedule(page, row, images, ledger):
                        print("[PARADO] Lote interrompido para conferencia. Demais posts nao foram alterados.")
                        break
            finally:
                api.close()
        finally:
            context.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Meta Business Suite: lote assistido com navegador visivel")
    parser.add_argument("--date", help="AAAA-MM-DD")
    parser.add_argument("--post", help="Filtra ID de uma publicacao")
    parser.add_argument("--start", action="store_true", help="Abre navegador e auxilia agendamento")
    parser.add_argument("--status", action="store_true", help="Mostra registros SQLite sem acessar Meta")
    parser.add_argument("--confirm", metavar="ID", help="Confirma agendamento pendente apos verificar manualmente no Meta")
    args = parser.parse_args()
    ledger = BusinessSuiteStore(DB_FILE)
    try:
        if args.status:
            for r in ledger.all():
                print(f"{r['post_id']} | {r['target_at']} | {r['status']} | {r['note'] or '-'}")
            return 0
        if args.confirm:
            if not POST_RE.fullmatch(args.confirm):
                parser.error("ID invalido")
            record = ledger.get(args.confirm)
            if not record or record["status"] not in {"needs_review", "awaiting_confirmation"}:
                raise ValueError("Somente agendamentos pendentes podem ser confirmados apos revisao")
            expected = f"AGENDADO {args.confirm}"
            print("Confirme visualmente que existe um agendamento no Planejador do Business Suite.")
            if input(f"Digite exatamente {expected}: ").strip() != expected:
                print("Cancelado.")
                return 1
            ledger.update(args.confirm, record["status"], "scheduled",
                          "Confirmacao manual posterior no Business Suite")
            print("[OK] Confirmacao manual salva no SQLite.")
            return 0
        if not args.date:
            parser.error("Informe --date AAAA-MM-DD, --status ou --confirm ID")
        try:
            day = datetime.strptime(args.date, "%Y-%m-%d").date().isoformat()
        except ValueError as exc:
            raise ValueError("Data invalida; use AAAA-MM-DD") from exc
        if day != args.date:
            raise ValueError("Data deve seguir AAAA-MM-DD")
        if args.post and not POST_RE.fullmatch(args.post):
            parser.error("ID invalido")
        if args.start and os.getenv("ARAYFLOW_AUTOPUBLISH_ENABLED", "").strip().lower() == "true":
            raise RuntimeError(
                "DESATIVE primeiro ARAYFLOW_AUTOPUBLISH_ENABLED no .env e a tarefa ArayFlow Publisher "
                "para evitar postagens duplicadas entre a API e o Business Suite."
            )
        with single_sync():
            rows, drive = approved_rows(day, args.post)
            if not rows:
                print("[INFO] Nenhuma publicacao aprovada encontrada para a data.")
                return 0
            print(f"Meta Business Suite | data {day} | {len(rows)} publicacoes aprovadas")
            for row in rows:
                ident = row["ID"].strip()
                record = ledger.get(ident)
                print(f"  {row['Horário']} {ident} | {record['status'] if record else 'sem registro'}")
            if not args.start:
                print("[DRY-RUN] Nada foi agendado. Use --start para abrir o navegador.")
                return 0
            start_browser(rows, drive, ledger)
            return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        sys.exit(1)
