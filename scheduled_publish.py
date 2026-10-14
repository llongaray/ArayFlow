"""ArayFlow v0.5 — agendador local, protegido por opt-in explicito.

Execute a cada 5 minutos no Windows Task Scheduler.
Sem --live: somente simulacao; nenhuma gravacao na Meta/R2.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from google_client import (BASE_DIR, authenticate, services, read_calendar,
                           list_images, extract_folder_id, download_image)
from image_validator import validate_batch
from instagram_publisher import InstagramPublisher
from publication_store import PublicationStore
from r2_storage import R2Storage
from r2_upload import images_for
from sync_day import single_sync, sha256_file
from sync_store import SyncStore

load_dotenv(BASE_DIR / ".env")
ZONE = ZoneInfo("America/Sao_Paulo")
PREPARE_MINUTES = 10
MAX_DELAY_MINUTES = 15
APPROVED = {"aprovado", "aprovado para publicação", "aprovado para publicacao"}
ID_RE = re.compile(r"ARAY-\d{8}-\d{3,}$")
LOG = logging.getLogger("arayflow.scheduler")


def configure_log() -> None:
    from logging.handlers import RotatingFileHandler
    folder = BASE_DIR / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    LOG.setLevel(logging.INFO)
    if not LOG.handlers:
        h = RotatingFileHandler(folder / "scheduled_publish.log", maxBytes=2_000_000,
                                backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOG.addHandler(h)


def scheduled_time(row: dict) -> datetime:
    post_id = row.get("ID", "").strip()
    if not ID_RE.fullmatch(post_id):
        raise ValueError("ID editorial invalido")
    day = datetime.strptime(row.get("Data", "").strip(), "%d/%m/%Y").date()
    if post_id[5:13] != day.strftime("%Y%m%d"):
        raise ValueError(f"ID/data divergentes em {post_id}")
    hour = row.get("Horário", "").strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::00)?", hour)
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        raise ValueError(f"Horario invalido em {post_id}: {hour}")
    return datetime(day.year, day.month, day.day,
                    int(match[1]), int(match[2]), tzinfo=ZONE)


def decision(row: dict, now: datetime) -> str:
    """SKIP, WAIT, PREPARE ou DUE; nunca recuperar posts muito atrasados."""
    if row.get("Status", "").strip().casefold() not in APPROVED:
        return "SKIP"
    due = scheduled_time(row)
    delta = (due - now.astimezone(ZONE)).total_seconds()
    if delta > PREPARE_MINUTES * 60:
        return "WAIT"
    if delta < -MAX_DELAY_MINUTES * 60:
        return "EXPIRED"
    return "DUE" if delta <= 0 else "PREPARE"


def rows_today(sheets, now: datetime) -> list[dict]:
    rows = read_calendar(sheets,
        os.getenv("GOOGLE_SPREADSHEET_ID", "1dA5GFM2qS6RXzpgEiBXLHO4uYkwp4l46B17dCZCcZKM"),
        os.getenv("GOOGLE_SHEET_NAME", "Calendário"))
    date = now.astimezone(ZONE).strftime("%d/%m/%Y")
    result = [row for row in rows if row.get("Data", "").strip() == date]
    ids = [row.get("ID", "").strip() for row in result]
    if len(ids) != len(set(ids)):
        raise ValueError("IDs duplicados no calendario do dia; operacao cancelada")
    return result


def ensure_local(row: dict, drive) -> list[Path]:
    """Baixa automaticamente imagens ausentes, sem sobrescrever artes existentes."""
    post_id = row["ID"].strip()
    day = scheduled_time(row).strftime("%Y-%m-%d")
    expected = int(row.get("Qtd. imagens", "0"))
    if not 1 <= expected <= 10:
        raise ValueError(f"Quantidade invalida em {post_id}")
    paths = images_for(post_id)
    if len(paths) != expected:
        folder_id = extract_folder_id(row.get("Pasta das imagens", ""))
        remote = list_images(drive, folder_id)
        if len(remote) != expected:
            raise RuntimeError(f"{post_id}: Google Drive possui {len(remote)} imagens, esperado {expected}")
        target = BASE_DIR / "downloads" / day / post_id
        target.mkdir(parents=True, exist_ok=True)
        for f in remote:
            name = f["name"]
            if not re.fullmatch(re.escape(post_id) + r"_slide-\d+\.(?:png|jpg|jpeg)", name, re.I):
                raise ValueError(f"Nome de imagem nao esperado: {name}")
            destination = target / name
            if destination.is_file():
                continue
            temp = target / (name + ".partial")
            try:
                download_image(drive, f, temp)
                temp.replace(destination)
            finally:
                temp.unlink(missing_ok=True)
        paths = images_for(post_id)
    if len(paths) != expected:
        raise RuntimeError(f"{post_id}: faltam imagens locais")
    validate_batch(paths)
    if not row.get("Legenda pronta", "").strip():
        raise ValueError(f"{post_id}: legenda vazia")
    return paths


def safe_cleanup(storage: R2Storage, sessions: SyncStore, now_day: str) -> int:
    """Limpa somente dias anteriores; preserva uploads que podem estar em uso na Meta."""
    protected_posts = sessions.protected_posts()
    protected_days = sessions.protected_days(now_day)
    keys = storage.list_managed()
    removed = 0
    for key in keys:
        _, key_day, post_id, _ = key.split("/")
        if key_day >= now_day or key_day in protected_days or post_id in protected_posts:
            continue
        storage.delete(key)
        sessions.forget_asset(now_day, key)
        removed += 1
    return removed


def ensure_r2(post_id: str, paths: list[Path], storage: R2Storage,
              sessions: SyncStore, day: str) -> list[str]:
    """Reutiliza imagens com hash conhecido e publica URLs do bucket informado."""
    present = set(storage.list_managed())
    urls = []
    manifest = {}
    for path in paths:
        key = storage.key_for(post_id, path)
        digest = sha256_file(path)
        if key not in present or storage.remote_sha256(key) != digest:
            storage.upload(post_id, path, sha256=digest)
            if storage.remote_sha256(key) != digest:
                raise RuntimeError(f"Hash no R2 nao confirmado: {key}")
        sessions.record_asset(day, post_id, key, digest)
        url = storage.url_for(key)
        urls.append(url)
        manifest[path.name] = url
    folder = BASE_DIR / "data"
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{post_id}-r2-urls.json"
    tmp = destination.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(destination)
    return urls


def prepare_post(row: dict, store: PublicationStore, publisher: InstagramPublisher,
                 drive, storage: R2Storage, sessions: SyncStore, day: str,
                 now: datetime) -> bool:
    post_id = row["ID"].strip()
    paths = ensure_local(row, drive)
    if decision(row, datetime.now(ZONE)) == "EXPIRED":
        LOG.warning("%s perdeu janela de publicacao antes de preparar", post_id)
        return False
    # Apaga apenas arquivos de dias ANTERIORES, nunca arquivos do dia atual.
    removed = safe_cleanup(storage, sessions, day)
    if removed:
        LOG.info("Limpeza R2: %d objetos antigos removidos", removed)
    urls = ensure_r2(post_id, paths, storage, sessions, day)
    if not store.claim(post_id):
        LOG.info("%s ja possui sessao; nenhuma nova preparacao", post_id)
        return False
    # Se uma chamada Meta falhar, o estado 'preparing' fica bloqueado.
    # Nao repetimos automaticamente requisicoes possivelmente aceitas.
    try:
        publisher.check_account()
        cid = publisher.prepare(urls, row["Legenda pronta"].strip())
    except Exception as exc:
        LOG.exception("%s: resultado incerto na preparacao; conferir manualmente", post_id)
        raise RuntimeError(f"{post_id}: preparacao incerta; sessao 'preparing' bloqueada para revisao") from exc
    if not store.transition(post_id, "preparing", "prepared", container_id=cid):
        raise RuntimeError(f"{post_id}: estado alterado durante preparacao")
    LOG.info("%s: conteiner preparado %s", post_id, cid)
    return True


def publish_due(row: dict, store: PublicationStore, publisher: InstagramPublisher) -> None:
    post_id = row["ID"].strip()
    current = store.get(post_id)
    if not current or current[0] != "prepared" or not current[2]:
        return
    if decision(row, datetime.now(ZONE)) != "DUE":
        return
    publisher.check_account()
    # Em caso de erro, a sessao sera bloqueada para prevencao de duplicatas.
    try:
        publisher.wait(current[2], attempts=1, interval=0)
    except Exception:
        LOG.exception("%s: conteiner nao pronto; verificar antes de tentar novamente", post_id)
        return
    if not store.transition(post_id, "prepared", "publishing"):
        return
    try:
        media_id = publisher.publish(current[2])
    except Exception as exc:
        store.transition(post_id, "publishing", "uncertain")
        LOG.exception("%s: retorno incerto de media_publish; NAO repetir automaticamente", post_id)
        raise RuntimeError(f"{post_id}: resposta incerta da Meta; verificar Instagram manualmente") from exc
    store.transition(post_id, "publishing", "published", media_id=media_id)
    LOG.info("%s: PUBLICADO. Media ID=%s", post_id, media_id)


def run_once(live: bool, now: datetime | None = None, *, sheets=None, drive=None,
             store=None, sessions=None, storage=None, publisher=None) -> int:
    now = now or datetime.now(ZONE)
    owns_google = sheets is None
    if owns_google:
        credentials = authenticate()
        sheets, drive = services(credentials)
    rows = rows_today(sheets, now)
    print(f"ArayFlow scheduler | {now.strftime('%Y-%m-%d %H:%M %Z')} | posts: {len(rows)}")
    actionable = []
    for row in rows:
        try:
            stage = decision(row, now)
            post_id = row.get("ID", "?")
            print(f"  {row.get('Horário','?')} {post_id} [{row.get('Status','')}] => {stage}")
            if stage in {"PREPARE", "DUE"}:
                actionable.append((row, stage))
        except (ValueError, KeyError) as exc:
            LOG.error("Linha editorial ignorada: %s", exc)
    if not live:
        print("[DRY-RUN] Nenhuma operacao Meta/R2 realizada.")
        return 0
    if os.getenv("ARAYFLOW_AUTOPUBLISH_ENABLED", "").strip().lower() != "true":
        raise RuntimeError("Auto-publicacao desativada. Configure ARAYFLOW_AUTOPUBLISH_ENABLED=true no .env apos validar o dry-run.")
    owns_store = store is None
    if owns_store:
        store = PublicationStore(BASE_DIR / "data" / "arayflow.sqlite3")
    owns_sessions = sessions is None
    if owns_sessions:
        sessions = SyncStore(BASE_DIR / "data" / "arayflow.sqlite3")
    try:
        if not actionable:
            return 0
        if publisher is None:
            publisher = InstagramPublisher(os.getenv("TOKEN", ""), os.getenv("CONTA_INSTA_ID", ""))
        if storage is None:
            storage = R2Storage()
        day = now.astimezone(ZONE).strftime("%Y-%m-%d")
        failures = 0
        for row, stage in actionable:
            post_id = row["ID"].strip()
            try:
                # Agendamentos Business Suite (inclusive pendentes) bloqueiam media_publish pela API.
                if isinstance(store, PublicationStore) and store.business_suite_reserved(post_id):
                    LOG.info("%s: reservado pelo Business Suite; API ignorada", post_id)
                    continue
                current = store.get(post_id)
                if not current:
                    prepare_post(row, store, publisher, drive, storage, sessions, day, now)
                elif current[0] in {"preparing", "publishing", "uncertain", "failed", "published"}:
                    LOG.info("%s: sessao bloqueada/concluida: %s", post_id, current[0])
                    continue
                # Uma preparacao concluida apos o horario tambem pode publicar
                # se ainda estiver dentro da janela de tolerancia.
                if decision(row, datetime.now(ZONE)) == "DUE":
                    publish_due(row, store, publisher)
            except Exception:
                failures += 1
                LOG.exception("%s: falha ao processar agendamento; necessita revisao", post_id)
        return 1 if failures else 0
    finally:
        if owns_store:
            store.close()
        if owns_sessions:
            sessions.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Agendador ArayFlow; --live autoriza execucao automatica")
    parser.add_argument("--once", action="store_true", help="Executa um ciclo e encerra")
    parser.add_argument("--live", action="store_true", help="Habilita escrita no R2/Meta (exige .env)")
    args = parser.parse_args()
    configure_log()
    try:
        with single_sync():
            return run_once(args.live)
    except Exception as exc:
        LOG.exception("Falha no ciclo de agendamento")
        print(f"[ERRO] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
