"""Conexao assistida ao Chrome pessoal JA ABERTO via Chrome DevTools MCP.

Chrome >=144: usuario habilita chrome://inspect/#remote-debugging, autoriza
a conexao e mantem sessao/login no proprio perfil. Nenhum cookie e copiado.
O programa NAO cria Chrome novo ou controla abas nao relacionadas a Meta.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from publication_store import PublicationStore

from arayflow.editorial import scheduled_time
from arayflow.local_media import ensure_local
from arayflow.settings import ZONE

META_URL = "https://business.facebook.com/"
PAGE_PATTERN = re.compile(r"(?m)^\s*(?:[-*]\s*)?(\d+):\s+(https?://\S+)")
UID_PATTERN = re.compile(r"\b(?:uid=)?(\d+_\d+)\b")
CAPTION_TERMS = re.compile(
    r"legenda|caption|escreva uma legenda|write a caption|descri[cç][aã]o", re.I
)
UPLOAD_TERMS = re.compile(
    r"adicionar (?:fotos?|m[ií]dia|imagens?)|carregar (?:fotos?|m[ií]dia|imagens?)"
    r"|upload (?:photos?|images?|media)|add (?:photos?|images?|media)", re.I
)


def server_command() -> tuple[str, list[str]]:
    """Chrome DevTools MCP precisa de Node.js/npx local, nao de Chromium."""
    if not shutil.which("node"):
        raise RuntimeError(
            "Node.js nao encontrado. Instale Node.js 22+ (inclui npx), "
            "abra novo PowerShell e confira 'node -v' e 'npx -v'."
        )
    if os.name == "nt":
        if not (shutil.which("npx.cmd") or shutil.which("npx")):
            raise RuntimeError("npx nao encontrado. Reinstale Node.js 22+.")
        return os.environ.get("COMSPEC", "cmd.exe"), [
            "/d", "/s", "/c",
            "npx --yes chrome-devtools-mcp@latest --autoConnect "
            "--no-usage-statistics --no-performance-crux",
        ]
    npx = shutil.which("npx")
    if not npx:
        raise RuntimeError("npx nao encontrado. Instale Node.js 22+.")
    return npx, ["--yes", "chrome-devtools-mcp@latest", "--autoConnect",
                 "--no-usage-statistics", "--no-performance-crux"]


def extract_text(result) -> str:
    """Le somente blocos textuais de uma resposta MCP (nao armazena cookies)."""
    return "\n".join(
        str(part.text)
        for part in getattr(result, "content", [])
        if getattr(part, "type", None) == "text"
    )


def parse_business_pages(output: str) -> list[int]:
    """Somente abas do Meta Business Suite, sem navegar/ler outras paginas."""
    return [
        int(match[1])
        for match in PAGE_PATTERN.finditer(output)
        if re.match(r"https://business\.facebook\.com(?:/|$)", match[2], re.I)
    ]


def unique_uid(snapshot: str, label: re.Pattern[str], allowed: re.Pattern[str]) -> str | None:
    """Retorna uid apenas se houver UM controle nao ambiguo no snapshot atual."""
    matches = []
    for line in snapshot.splitlines():
        if not (label.search(line) and allowed.search(line)):
            continue
        match = UID_PATTERN.search(line)
        if match:
            matches.append(match[1])
    return matches[0] if len(set(matches)) == 1 and matches else None

def describe_mcp_tool_error(result) -> str:
    """Classifica erro MCP sem exibir texto bruto de paginas ou credenciais."""
    raw = extract_text(result)
    cases = [
        ("DevToolsActivePort", "Chrome nao criou/encontrou DevToolsActivePort; confira depuracao do perfil correto"),
        ("Network.enable timed out", "Timeout de Network.enable; possivel aba congelada ou conflito de conexao"),
        ("Runtime.runIfWaitingForDebugger timed out", "Timeout de inicializacao de abas Chrome"),
        ("socket connection was closed", "Conexao CDP/WebSocket encerrada"),
        ("Target closed", "Aba ou Chrome fechado durante conexao"),
        ("Permission denied", "Permissao de depuracao recusada"),
        ("not allowed", "Operacao nao autorizada pelo Chrome"),
        ("not found", "Recurso do navegador nao encontrado"),
        ("timed out", "Tempo limite excedido ao consultar o Chrome"),
        ("could not connect", "Nao foi possivel estabelecer conexao de depuracao"),
    ]
    for fragment, description in cases:
        if fragment.casefold() in raw.casefold():
            return description
    # O retorno de erro pode conter cookies, titulos de abas, querystrings
    # e IDs de sessao. Nunca o registramos integralmente no terminal.
    return "Falha nao classificada de list_pages; verifique depuracao, perfis e logs locais do MCP"


class ChromeMCP:
    def __init__(self, session):
        self.session = session

    async def call(self, name: str, **arguments) -> str:
        result = await self.session.call_tool(name, arguments=arguments)
        if getattr(result, "isError", False):
            raise RuntimeError(
                f"Chrome DevTools MCP {name}: {describe_mcp_tool_error(result)}"
            )
        return extract_text(result)

    async def meta_page(self) -> int:
        listing = await self.call("list_pages")
        options = parse_business_pages(listing)
        if len(options) > 1:
            print(f"[CHROME] Encontradas {len(options)} abas do Meta Business Suite.")
            print("IDs disponiveis: " + ", ".join(str(option) for option in options))
            selection = input("Digite o ID da aba correta (Enter para primeira): ").strip()
            if selection:
                if not selection.isascii() or not selection.isdecimal() or int(selection) not in options:
                    raise ValueError("ID de aba invalido; nenhuma aba sera modificada")
                options = [int(selection)]
        if not options:
            print("[INFO] Abrindo uma aba do Business Suite no Chrome pessoal ja aberto.")
            await self.call("new_page", url=META_URL, background=False)
            options = parse_business_pages(await self.call("list_pages"))
        if not options:
            raise RuntimeError(
                "Chrome conectado, mas nenhuma aba Business Suite foi encontrada. "
                "Abra https://business.facebook.com/ manualmente e tente novamente."
            )
        page_id = options[0]
        await self.call("select_page", pageId=page_id, bringToFront=True)
        return page_id

    async def prefill(self, page_id: int, paths: list[Path], caption: str) -> dict[str, bool]:
        """Preenche controles identificados com seguranca; NUNCA clica em Agendar."""
        outcome = {"images": False, "caption": False}
        # O snapshot pode conter conteudo de terceiros. Usamos apenas UIDs
        # e rotulos limitados: nao executamos instrucoes de texto da pagina.
        try:
            snap = await self.call("take_snapshot", pageId=page_id)
            uid = unique_uid(
                snap, UPLOAD_TERMS, re.compile(r"button|input|file|upload", re.I)
            )
            if uid:
                await self.call("upload_file", pageId=page_id, uid=uid,
                                filePaths=[str(p.resolve()) for p in paths],
                                includeSnapshot=False)
                outcome["images"] = True
        except Exception:
            print("[AVISO] Upload nao identificado/aceito com seguranca; anexe os arquivos manualmente.")
        try:
            snap = await self.call("take_snapshot", pageId=page_id)
            uid = unique_uid(
                snap, CAPTION_TERMS, re.compile(r"textbox|textarea|editable", re.I)
            )
            if uid:
                await self.call("fill", pageId=page_id, uid=uid, value=caption,
                                includeSnapshot=False)
                outcome["caption"] = True
        except Exception:
            print("[AVISO] Legenda nao preenchida automaticamente; cole no campo manualmente.")
        return outcome


def connection_failure_details(error: BaseException) -> str:
    """Diagnostico curto, com redacao; evita ocultar a causa em ExceptionGroup.

    Jamais imprime cookies, headers Authorization ou URLs de abas visitadas.
    """
    found, visited = [], set()

    def walk(exc, depth=0):
        if id(exc) in visited or depth > 8 or len(found) >= 6:
            return
        visited.add(id(exc))
        kind = type(exc).__name__
        message = str(exc).splitlines()[0][:500] if str(exc).strip() else "sem descricao"
        message = re.sub(r"https?://\S+", "[URL]", message)
        message = re.sub(
            r"(?i)\b(token|cookie|password|secret|authorization|api[_-]?key)\b"
            r"\s*[:=]\s*[^\s,;]+",
            r"\1=[OCULTO]",
            message,
        )
        # Descarta conteudo nao necessario de mensagens de processos externos.
        found.append(f"{kind}: {message[:240]}")
        for inner in getattr(exc, "exceptions", ()):
            walk(inner, depth + 1)
        cause = getattr(exc, "__cause__", None)
        if cause is not None:
            walk(cause, depth + 1)
        context = getattr(exc, "__context__", None)
        if context is not None and context is not cause:
            walk(context, depth + 1)

    walk(error)
    return " | ".join(found)[:1000] or type(error).__name__


async def diagnose_chrome_connection() -> None:
    """Somente handshake MCP e contagem de abas Business Suite; NAO modifica abas."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        raise RuntimeError("SDK MCP ausente: execute pip install -r requirements.txt") from exc

    command, args = server_command()
    print("[DIAGNOSTICO] Chrome 144 ou mais recente deve estar aberto.")
    print("[DIAGNOSTICO] Em chrome://inspect/#remote-debugging, a opcao")
    print("    'Allow remote debugging for this browser instance' precisa estar marcada.")
    print("    A pagina mostra 'Server running at: 127.0.0.1:9222' quando esta pronta.")
    print("[DIAGNOSTICO] O Chrome pedira sua autorizacao de conexao.")
    if input("Digite DIAGNOSTICAR CHROME para conectar sem agendar: ").strip() != "DIAGNOSTICAR CHROME":
        print("[CANCELADO] Nenhuma conexao iniciada.")
        return
    try:
        params = StdioServerParameters(command=command, args=args)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("list_pages", arguments={})
                if getattr(result, "isError", False):
                    raise RuntimeError(
                        "Chrome DevTools MCP list_pages: "
                        + describe_mcp_tool_error(result)
                    )
                count = len(parse_business_pages(extract_text(result)))
                print(f"[OK] MCP conectado ao Chrome existente; abas Meta Business Suite: {count}.")
                print("[OK] Nenhum post foi preparado, enviado ou agendado.")
    except Exception as exc:
        details = connection_failure_details(exc)
        raise RuntimeError(
            "Falha no diagnostico do Chrome DevTools MCP. "
            f"Causa identificada: {details}. "
            "Verifique Chrome 144+, chrome://inspect/#remote-debugging, "
            "autorizacao no Chrome, e conexoes MCP concorrentes."
        ) from exc


async def schedule_existing_chrome(rows: list[dict], drive, ledger, db_file: Path) -> None:
    """Vincula somente apos consentimento explicito; nao acessa credenciais."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        raise RuntimeError(
            "SDK MCP nao instalado. Execute python -m pip install -r requirements.txt."
        ) from exc

    command, args = server_command()
    print(
        "\n[CHROME PESSOAL] No Chrome onde a Meta JA esta logada, abra "
        "chrome://inspect/#remote-debugging e marque "
        "'Allow remote debugging for this browser instance'. "
        "Com a opcao ligada, a pagina mostra Server running at: 127.0.0.1:9222."
    )
    print(
        "[SEGURANCA] Autorize a conexao solicitada PELO Chrome somente "
        "se reconhecer o ArayFlow. A depuracao pode dar acesso a outras abas "
        "deste perfil; desative-a depois do uso."
    )
    if input("Digite CONECTAR CHROME para solicitar acesso ao seu perfil aberto: ").strip() != "CONECTAR CHROME":
        print("[CANCELADO] Nao foi solicitada conexao ao Chrome.")
        return

    params = StdioServerParameters(command=command, args=args)
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                bridge = ChromeMCP(session)
                page_id = await bridge.meta_page()
                print("[OK] Conectado a aba Meta Business Suite do Chrome ja aberto.")
                print("Nao foi criado perfil separado; nao copie nem compartilhe cookies.")
                api = PublicationStore(db_file)
                try:
                    for row in rows:
                        ident = row["ID"].strip()
                        if api.get(ident):
                            print(f"[PROTEGIDO] {ident}: ja possui sessao Meta API; ignorado.")
                            continue
                        if ledger.reserved(ident):
                            print(f"[PROTEGIDO] {ident}: possui sessao Suite; ignorado.")
                            continue
                        due = scheduled_time(row)
                        if due <= datetime.now(ZONE):
                            print(f"[IGNORADO] {ident}: horario ja passou.")
                            continue
                        images = ensure_local(row, drive)
                        print(f"\n{'='*64}\n{ident} | {due:%d/%m/%Y %H:%M} (America/Sao_Paulo)")
                        print(f"Artes: {len(images)} | Legenda: {len(row.get('Legenda pronta','').strip())} caracteres")
                        print("Na ABA do Chrome existente, selecione @aray_solucoes e abra o compositor.")
                        if input("Quando o compositor estiver aberto, digite PRONTO (ou PULAR): ").strip() != "PRONTO":
                            print("[PARADO] Lote interrompido sem reservar o post.")
                            break
                        # A reserva e feita antes de preencher: se algo falhar,
                        # verificacao manual sera obrigatoria para evitar duplicata.
                        if not ledger.reserve(ident, due.isoformat()):
                            print(f"[PROTEGIDO] {ident}: sessao ja existente; nao repetir.")
                            break
                        try:
                            filled = await bridge.prefill(page_id, images, row["Legenda pronta"].strip())
                            print(
                                f"Preenchimento: imagens={'OK' if filled['images'] else 'MANUAL'}, "
                                f"legenda={'OK' if filled['caption'] else 'MANUAL'}."
                            )
                            print("Confira conta @aray_solucoes, ordem dos slides, legenda,")
                            print(f"data {due:%d/%m/%Y}, horario {due:%H:%M} e fuso na tela.")
                            print("Escolha a opcao AGENDAR e clique voce mesmo no Business Suite.")
                            print("Verifique no Planejador se o post ficou agendado.")
                            expected = f"AGENDADO {ident}"
                            if input(f"Depois da confirmacao na Meta, digite {expected}: ").strip() == expected:
                                if not ledger.update(
                                    ident, "awaiting_confirmation", "scheduled",
                                    "Confirmacao manual no Planejador do Business Suite"
                                ):
                                    raise RuntimeError("Falha ao salvar confirmacao no SQLite")
                                print(f"[CONFIRMADO] {ident}: sessao registrada.")
                                continue
                            ledger.update(ident, "awaiting_confirmation", "needs_review",
                                          "Nao confirmado; verificar agendamento antes de repetir")
                            print(f"[ATENCAO] {ident}: needs_review. Nao repetir sem verificacao.")
                            break
                        except Exception:
                            ledger.update(ident, "awaiting_confirmation", "needs_review",
                                          "Falha durante preenchimento; verificar Meta")
                            raise
                finally:
                    api.close()
    except Exception as exc:
        # O SDK MCP pode encapsular erros de inicializacao em ExceptionGroup.
        # Preserve o diagnostico sem incluir URLs, credenciais ou cookies.
        details = connection_failure_details(exc)
        raise RuntimeError(
            f"Falha no Chrome DevTools MCP: {details}. "
            "Confirme depuracao em chrome://inspect/#remote-debugging, "
            "autorize o pedido do navegador e verifique se outro MCP ja esta conectado. "
            "O ArayFlow nunca clica em Publicar ou Agendar automaticamente."
        ) from exc
