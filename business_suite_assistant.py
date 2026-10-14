"""ArayFlow v0.7.3: assistente visivel em Chrome pessoal ou isolado.

No modo existente, Chrome DevTools MCP tenta anexar artes e preencher
legenda, data e horario quando encontra controles sem ambiguidade.
Conta Instagram, fuso e botao final AGENDAR exigem verificacao humana.
Nunca tenta contornar login, MFA, CAPTCHA ou restricoes da plataforma.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from business_suite_store import BusinessSuiteStore
from publication_store import PublicationStore
from google_client import authenticate, services
from sync_day import single_sync

from arayflow.editorial import APPROVED, load_sheet_rows, scheduled_time
from arayflow.local_media import ensure_local
from arayflow.settings import (
    CHROME_PROFILE_DIR,
    DB_PATH,
    POST_ID_RE,
    ZONE,
    autopublish_enabled,
)

PROFILE_DIR = CHROME_PROFILE_DIR
DB_FILE = DB_PATH
CAPTION_LABELS = re.compile(
    r"legenda|escreva uma legenda|caption|write a caption|descri[cç][aã]o do post",
    re.I
)


def approved_rows(day: str, post_id: str | None = None) -> tuple[list[dict], object]:
    creds = authenticate()
    sheets, drive = services(creds)
    rows = load_sheet_rows(sheets)
    result = []
    for row in rows:
        if row.get("Data", "").strip() != datetime.strptime(day, "%Y-%m-%d").strftime("%d/%m/%Y"):
            continue
        ident = row.get("ID", "").strip()
        if post_id and ident != post_id:
            continue
        if row.get("Status", "").strip().casefold() not in APPROVED:
            continue
        if not POST_ID_RE.fullmatch(ident):
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


def launch_chrome_context(playwright, profile_dir: Path = PROFILE_DIR):
    """Usa Google Chrome instalado e um perfil SEPARADO do Chrome pessoal.

    A pasta permanece entre execucoes (login/cookies locais, quando validos).
    Nunca anexa a janela pessoal aberta ou ao perfil Default do usuario.
    """
    profile_dir = Path(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    try:
        return playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=False,
            viewport={"width": 1440, "height": 900},
            accept_downloads=False,
        )
    except Exception as exc:
        details = str(exc).lower()
        if ("executable doesn't exist" in details
                or "executable does not exist" in details
                or ("chrome" in details and ("not found" in details or "not installed" in details))):
            raise RuntimeError(
                "Google Chrome nao encontrado. Instale o Google Chrome oficial no Windows "
                "e tente novamente. O Chromium do Playwright nao e necessario."
            ) from exc
        if any(fragment in details for fragment in (
                "processsingleton", "profile appears to be in use", "user data directory is already in use")):
            raise RuntimeError(
                "O perfil exclusivo do ArayFlow ja esta aberto. Feche a janela "
                "do Chrome iniciada anteriormente pelo ArayFlow e tente novamente."
            ) from exc
        raise


def start_browser(rows: list[dict], drive, ledger: BusinessSuiteStore):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright nao instalado. No .venv, execute: "
            "python -m pip install -r requirements.txt. "
            "Nao precisa instalar o Chromium do Playwright."
        ) from exc

    with sync_playwright() as playwright:
        context = launch_chrome_context(playwright)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto("https://business.facebook.com/", wait_until="domcontentloaded", timeout=45_000)
            except Exception:
                print("[AVISO] Nao foi possivel carregar a pagina inicial. Verifique a conexao.")
            print("Google Chrome instalado iniciado; faca login e MFA manualmente, se necessario.")
            print("Sessao persistente: data/playwright_chrome_profile (ignorada no Git).")
            print("O Chrome pessoal aberto nao e controlado nem tem seus cookies copiados.")
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
    parser = argparse.ArgumentParser(description="Meta Business Suite: agendamento assistido em Chrome isolado ou ja aberto")
    parser.add_argument("--date", help="AAAA-MM-DD")
    parser.add_argument("--post", help="Filtra ID de uma publicacao")
    parser.add_argument("--start", action="store_true", help="Inicia agendamento assistido")
    parser.add_argument(
        "--browser", choices=["isolated", "existing"], default="isolated",
        help="isolated = Chrome com perfil exclusivo; existing = conectar ao Chrome ja aberto (MCP)",
    )
    parser.add_argument("--diagnose-chrome", action="store_true", help="Diagnostica conexao ao Chrome existente sem publicar ou ler Sheets")
    parser.add_argument("--inspect-composer", action="store_true", help="Detecta campos do compositor no Chrome existente sem alterar posts")
    parser.add_argument("--test-schedule-fields", action="store_true", help="Testa apenas data e hora no compositor real, sem Google ou SQLite")
    parser.add_argument("--at", metavar="AAAA-MM-DDTHH:MM", help="Data e hora local desejadas no teste")
    parser.add_argument("--status", action="store_true", help="Mostra registros SQLite sem acessar Meta")
    parser.add_argument("--confirm", metavar="ID", help="Confirma agendamento pendente apos verificar manualmente no Meta")
    args = parser.parse_args()
    if sum([bool(args.diagnose_chrome), bool(args.inspect_composer), bool(args.test_schedule_fields)]) > 1:
        parser.error("Escolha somente um modo de diagnostico")
    if args.at and not args.test_schedule_fields:
        parser.error("--at exige --test-schedule-fields")
    if args.diagnose_chrome:
        import asyncio
        from existing_chrome import diagnose_chrome_connection
        asyncio.run(diagnose_chrome_connection())
        return 0
    if args.inspect_composer:
        import asyncio
        from existing_chrome import inspect_existing_composer
        asyncio.run(inspect_existing_composer())
        return 0
    if args.test_schedule_fields:
        if not args.at:
            parser.error("Informe --at AAAA-MM-DDTHH:MM")
        try:
            requested = datetime.strptime(args.at, "%Y-%m-%dT%H:%M")
            if requested.strftime("%Y-%m-%dT%H:%M") != args.at:
                raise ValueError("Formato incorreto")
            due = requested.replace(tzinfo=ZONE)
        except ValueError as exc:
            raise ValueError("Data/hora de teste invalida; use AAAA-MM-DDTHH:MM") from exc
        if due <= datetime.now(ZONE):
            raise ValueError("Data/hora do teste precisa estar no futuro")
        import asyncio
        from existing_chrome import test_schedule_fields_in_existing_chrome
        asyncio.run(test_schedule_fields_in_existing_chrome(due))
        return 0
    ledger = BusinessSuiteStore(DB_FILE)
    try:
        if args.status:
            for r in ledger.all():
                print(f"{r['post_id']} | {r['target_at']} | {r['status']} | {r['note'] or '-'}")
            return 0
        if args.confirm:
            if not POST_ID_RE.fullmatch(args.confirm):
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
        if args.post and not POST_ID_RE.fullmatch(args.post):
            parser.error("ID invalido")
        if args.start and autopublish_enabled():
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
            if args.browser == "existing":
                import asyncio
                from existing_chrome import schedule_existing_chrome
                asyncio.run(schedule_existing_chrome(rows, drive, ledger, DB_FILE))
            else:
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
