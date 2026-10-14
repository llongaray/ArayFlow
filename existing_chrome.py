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
from urllib.parse import urlsplit

from publication_store import PublicationStore

from arayflow.editorial import scheduled_time
from arayflow.local_media import ensure_local
from arayflow.settings import ZONE
from business_suite_forms import (
    discover_fields, field_report, plan_form_values, validate_media_files,
)

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


_BROWSER_PATH = re.compile(r"/devtools/browser/[A-Za-z0-9_-]+")


def chrome_user_data_dir() -> Path:
    override = os.getenv("ARAYFLOW_CHROME_USER_DATA", "").strip()
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        raise RuntimeError("LOCALAPPDATA ausente; defina ARAYFLOW_CHROME_USER_DATA")
    return Path(local) / "Google" / "Chrome" / "User Data"


def read_devtools_endpoint() -> str:
    """Chrome 144+ publica a porta e o caminho secreto em DevToolsActivePort.

    O HTTP em /json/version responde 404 de proposito. A conexao valida e o
    WebSocket indicado nesse arquivo, em 127.0.0.1.
    """
    port_file = chrome_user_data_dir() / "DevToolsActivePort"
    if not port_file.is_file():
        raise RuntimeError(
            "Chrome nao publicou DevToolsActivePort. Abra "
            "chrome://inspect/#remote-debugging e marque "
            "'Allow remote debugging for this browser instance'."
        )
    lines = [line.strip() for line in port_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) < 2 or not lines[0].isdecimal():
        raise RuntimeError("DevToolsActivePort incompleto; religue a depuracao remota no Chrome")
    port = int(lines[0])
    path = lines[1]
    if not 1 <= port <= 65535 or not _BROWSER_PATH.fullmatch(path):
        raise RuntimeError("DevToolsActivePort nao aponta para um navegador local esperado")
    return f"ws://127.0.0.1:{port}{path}"


def chrome_connection_args() -> list[str]:
    """Padrao: WebSocket do DevToolsActivePort. auto e browserUrl continuam opcionais."""
    raw = os.getenv("ARAYFLOW_CHROME_BROWSER_URL", "active-port").strip()
    if raw.casefold() in {"", "active-port", "ws", "websocket"}:
        return ["--wsEndpoint", read_devtools_endpoint()]
    if raw.casefold() in {"auto", "autoconnect"}:
        return ["--autoConnect"]
    parsed = urlsplit(raw)
    host = (parsed.hostname or "").casefold()
    if (parsed.scheme != "http" or host not in {"127.0.0.1", "localhost"}
            or parsed.port is None or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise ValueError(
            "ARAYFLOW_CHROME_BROWSER_URL aceita active-port, auto, "
            "http://127.0.0.1:9222 ou http://localhost:9222"
        )
    return ["--browserUrl", f"http://{host}:{parsed.port}"]


def connection_label(args: list[str]) -> str:
    """Descricao segura: nao revela o caminho secreto do WebSocket."""
    if args == ["--autoConnect"]:
        return "autoConnect"
    if len(args) == 2 and args[0] == "--browserUrl":
        return args[1]
    if len(args) == 2 and args[0] == "--wsEndpoint":
        parsed = urlsplit(args[1])
        return f"ws://{parsed.hostname}:{parsed.port}"
    return "desconhecida"


def _mcp_invocation() -> list[str]:
    return [
        "npx", "--yes", "chrome-devtools-mcp@latest",
        *chrome_connection_args(),
        "--no-usage-statistics", "--no-performance-crux",
    ]


def server_command() -> tuple[str, list[str]]:
    """Chrome DevTools MCP precisa de Node.js/npx local, nao de Chromium."""
    if not shutil.which("node"):
        raise RuntimeError(
            "Node.js nao encontrado. Instale Node.js 22+ (inclui npx), "
            "abra novo PowerShell e confira 'node -v' e 'npx -v'."
        )
    invocation = _mcp_invocation()
    if os.name == "nt":
        if not (shutil.which("npx.cmd") or shutil.which("npx")):
            raise RuntimeError("npx nao encontrado. Reinstale Node.js 22+.")
        return os.environ.get("COMSPEC", "cmd.exe"), [
            "/d", "/s", "/c", " ".join(invocation),
        ]
    npx = shutil.which("npx")
    if not npx:
        raise RuntimeError("npx nao encontrado. Instale Node.js 22+.")
    return npx, invocation[1:]


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

    async def prefill(self, page_id: int, paths: list[Path], caption: str,
                      when: datetime | None = None) -> dict[str, bool]:
        """Preenche campos identificados; nunca envia o formulario final da Meta.

        O operador abre previamente o compositor E as opcoes de agendamento.
        Se data e hora nao forem ambas identificadas, nenhuma delas e alterada.
        Os indicadores mostram aceite do MCP, nao comprovacao do agendamento.
        """
        outcome = {"images": False, "caption": False}
        if when is not None:
            outcome.update(date=False, time=False)
            if when <= datetime.now(ZONE):
                raise ValueError("Data/hora de agendamento ja passou")
        # Verifica a aba ANTES de interagir, caso o operador a tenha mudado.
        await self.assert_meta_page(page_id)
        snapshot = await self.call("take_snapshot", pageId=page_id)
        fields = discover_fields(snapshot)
        if fields.ambiguous:
            print("[AVISO] Campos ambiguos, exigem preenchimento manual: "
                  + ", ".join(fields.ambiguous))
        if fields.upload_uid:
            try:
                files = validate_media_files(paths)
                await self.call("upload_file", pageId=page_id, uid=fields.upload_uid,
                                filePaths=files, includeSnapshot=False)
                outcome["images"] = True
            except Exception:
                print("[AVISO] Upload nao confirmado; confira anexos e insira manualmente se necessario.")
        else:
            print("[MANUAL] Botao de imagens nao identificado no compositor.")
        # O upload pode alterar o DOM; UIDs do snapshot anterior expirariam.
        await self.assert_meta_page(page_id)
        snapshot = await self.call("take_snapshot", pageId=page_id)
        fields = discover_fields(snapshot)
        if fields.ambiguous:
            print("[AVISO] Campos ambiguos na revisao: " + ", ".join(fields.ambiguous))
        if when is None:
            plan = plan_form_values(fields, caption, datetime.now(ZONE))
            plan = [item for item in plan if item["uid"] == fields.caption_uid]
        else:
            plan = plan_form_values(fields, caption, when)
        if not fields.caption_uid:
            print("[MANUAL] Legenda sem campo inequivoco; cole diretamente no Business Suite.")
        if when is not None and not (fields.date_uid and fields.time_uid):
            print("[MANUAL] Data e horario nao identificados como par de campos. "
                  "Abra as opcoes de Programar na Meta e preencha manualmente.")
        if plan:
            try:
                await self.call("fill_form", pageId=page_id, elements=plan,
                                includeSnapshot=False)
                outcome["caption"] = fields.caption_uid is not None
                if when is not None and fields.date_uid and fields.time_uid:
                    outcome["date"] = outcome["time"] = True
            except Exception:
                print("[AVISO] O formulario pode ter sido parcialmente alterado. "
                      "Confira TODOS os campos manualmente antes de agendar.")
        print("[REVISAO] MCP nao clicou em Publicar ou Agendar. "
              "Data, horario, conta, imagens e legenda exigem verificacao visual.")
        return outcome

    async def assert_meta_page(self, page_id: int) -> None:
        """Recusa preencher se a aba foi navegada para outro dominio."""
        listing = await self.call("list_pages")
        if page_id not in parse_business_pages(listing):
            raise RuntimeError(
                "A aba selecionada nao esta mais no dominio business.facebook.com. "
                "Nenhum campo sera preenchido."
            )


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
        message = re.sub(r"(?:https?|wss?)://\S+", "[URL]", message)
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
    endpoint = chrome_connection_args()
    print("[DIAGNOSTICO] Chrome 144 ou mais recente deve estar aberto.")
    print("[DIAGNOSTICO] Em chrome://inspect/#remote-debugging, a opcao")
    print("    'Allow remote debugging for this browser instance' precisa estar marcada.")
    print("    A pagina mostra 'Server running at: 127.0.0.1:9222' quando esta pronta.")
    print(f"[DIAGNOSTICO] Conexao: {connection_label(endpoint)}")
    print("[DIAGNOSTICO] O Chrome pedira sua autorizacao de conexao. Clique em Permitir.")
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


async def inspect_existing_composer() -> None:
    """Diagnostico SOMENTE LEITURA: imprime presenca de campos, jamais conteudo."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        raise RuntimeError("SDK MCP ausente: execute pip install -r requirements.txt") from exc
    command, args = server_command()
    print("[INSPECAO] No Chrome pessoal, abra o compositor Business Suite,")
    print("selecione a conta Instagram e exiba as opcoes Data e Horario.")
    print("[INSPECAO] Apenas identifica UIDs. Nao envia imagens, preenche campos,")
    print("nem cria reserva SQLite ou agenda publicacao.")
    if input("Digite INSPECIONAR CAMPOS: ").strip() != "INSPECIONAR CAMPOS":
        print("[CANCELADO] Inspecao nao iniciada.")
        return
    params = StdioServerParameters(command=command, args=args)
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                bridge = ChromeMCP(session)
                page_id = await bridge.meta_page()
                await bridge.assert_meta_page(page_id)
                fields = discover_fields(await bridge.call("take_snapshot", pageId=page_id))
                for name, found in field_report(fields).items():
                    print(f"[CAMPO] {name}: {'IDENTIFICADO' if found else 'MANUAL'}")
                if fields.ambiguous:
                    print("[AMBIGUO] " + ", ".join(fields.ambiguous))
                print("[OK] Inspecao sem alterar formulario, planilha ou SQLite.")
    except Exception as exc:
        raise RuntimeError(
            "Falha ao inspecionar campos: " + connection_failure_details(exc)
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
        "Com a opcao ligada, o Chrome grava DevToolsActivePort e escuta em "
        "127.0.0.1:9222. O ArayFlow usa esse WebSocket. "
        "ARAYFLOW_CHROME_BROWSER_URL=auto volta para a descoberta do MCP."
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
                        print("Na aba do Chrome, selecione @aray_solucoes, abra o compositor")
                        print("e EXIBA as opcoes de PROGRAMAR com campos Data e Horario.")
                        print("Nao clique no botao final Agendar ainda.")
                        if input("Quando o compositor estiver aberto, digite PRONTO (ou PULAR): ").strip() != "PRONTO":
                            print("[PARADO] Lote interrompido sem reservar o post.")
                            break
                        # A reserva e feita antes de preencher: se algo falhar,
                        # verificacao manual sera obrigatoria para evitar duplicata.
                        if not ledger.reserve(ident, due.isoformat()):
                            print(f"[PROTEGIDO] {ident}: sessao ja existente; nao repetir.")
                            break
                        try:
                            filled = await bridge.prefill(
                                page_id, images, row["Legenda pronta"].strip(), due
                            )
                            print(
                                "Preenchimento MCP (revisar visualmente): "
                                + ", ".join(
                                    f"{label}={'ENVIADO' if filled.get(key) else 'MANUAL'}"
                                    for key, label in (
                                        ("images", "imagens"), ("caption", "legenda"),
                                        ("date", "data"), ("time", "horario")
                                    )
                                )
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
