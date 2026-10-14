"""Sincroniza um dia editorial com o R2; simulacao por padrao.

Fluxo: le Sheets -> valida todos os arquivos -> inventaria R2 -> planeja limpeza
-> confirma -> remove somente objetos seguros -> envia/reutiliza imagens do dia.
Nunca chama a API Meta.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import sys
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from google_client import BASE_DIR, authenticate, read_calendar, services
from image_validator import validate_batch
from r2_storage import R2Storage
from r2_upload import images_for
from sync_store import SyncStore
import os

IGNORED_STATUSES = {"cancelado", "cancelada", "rejeitado", "rejeitada", "publicado", "publicada"}

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

@contextmanager
def single_sync():
    """Impede duas sincronizacoes simultaneas na mesma maquina (sem lock obsoleto apos queda)."""
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        try:
            lock.bind(("127.0.0.1", 49567))
            lock.listen(1)
        except OSError as exc:
            raise RuntimeError("Ja existe uma sincronizacao local ou a porta 49567 esta ocupada") from exc
        yield
    finally:
        lock.close()

def get_posts(day: str):
    creds = authenticate()
    sheets, _ = services(creds)
    rows = read_calendar(sheets,
        os.getenv("GOOGLE_SPREADSHEET_ID", "1dA5GFM2qS6RXzpgEiBXLHO4uYkwp4l46B17dCZCcZKM"),
        os.getenv("GOOGLE_SHEET_NAME", "Calendário"))
    selected = []
    for post in rows:
        if not post.get("Data", "").strip():
            continue
        try:
            row_day = datetime.strptime(post["Data"].strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            continue
        if row_day != day or post.get("Status", "").strip().casefold() in IGNORED_STATUSES:
            continue
        selected.append(post)
    return selected

def make_assets(day: str, posts: list[dict], storage: R2Storage) -> list[dict]:
    if not posts:
        raise ValueError("Nenhuma publicacao pendente encontrada nessa data; limpeza cancelada")
    planned = []
    used_ids = set()
    for post in posts:
        post_id = post.get("ID", "").strip()
        if post_id in used_ids or not re.fullmatch(r"ARAY-\d{8}-\d{3,}", post_id):
            raise ValueError(f"ID duplicado ou invalido: {post_id!r}")
        used_ids.add(post_id)
        if datetime.strptime(post_id[5:13], "%Y%m%d").strftime("%Y-%m-%d") != day:
            raise ValueError(f"ID {post_id} nao pertence ao dia {day}")
        expected = int(post.get("Qtd. imagens", "0"))
        if expected < 1 or expected > 10:
            raise ValueError(f"Quantidade de imagens invalida para {post_id}")
        paths = images_for(post_id)
        if len(paths) != expected:
            raise ValueError(f"{post_id}: esperadas {expected} imagens locais; encontradas {len(paths)}. Execute main.py --download")
        validate_batch(paths)
        if not post.get("Legenda pronta", "").strip():
            raise ValueError(f"{post_id}: legenda vazia")
        for path in paths:
            key = storage.key_for(post_id, path)
            planned.append({
                "post_id": post_id, "path": path, "key": key,
                "sha256": sha256_file(path), "url": storage.url_for(key)
            })
    keys = [item["key"] for item in planned]
    if len(set(keys)) != len(keys):
        raise ValueError("Chaves R2 duplicadas")
    return planned

def classify(remote: list[str], desired_keys: set[str],
             protected_posts: set[str], protected_days: set[str]) -> tuple[list[str], list[str]]:
    """Retorna (excluiveis, protegidos); assume inventario ja filtrado por R2Storage."""
    old = []
    protected = []
    for key in remote:
        if key in desired_keys:
            continue
        _, day, post_id, _ = key.split("/")
        if day in protected_days or post_id in protected_posts:
            protected.append(key)
        else:
            old.append(key)
    return sorted(old), sorted(protected)

def make_plan(storage: R2Storage, store: SyncStore, day: str, assets: list[dict]):
    remote = storage.list_managed()
    remote_set = set(remote)
    desired_keys = {a["key"] for a in assets}
    delete, protected = classify(remote, desired_keys, store.protected_posts(),
                                  store.protected_days(day))
    uploads, reuse = [], []
    for a in assets:
        if a["key"] in remote_set and storage.remote_sha256(a["key"]) == a["sha256"]:
            reuse.append(a)
        else:
            uploads.append(a)
    return {"remote": remote, "delete": delete, "protected": protected,
            "upload": uploads, "reuse": reuse}

def show_plan(day: str, posts: int, assets: list[dict], plan: dict):
    print(f"\nARAYFLOW v0.4.0 — SINCRONIZACAO {day}")
    print(f"Publicacoes: {posts} | imagens locais validadas: {len(assets)}")
    print(f"Objetos gerenciados no R2: {len(plan['remote'])}")
    print(f"Remover antigos: {len(plan['delete'])} | protegidos: {len(plan['protected'])}")
    print(f"Enviar/substituir: {len(plan['upload'])} | reutilizar: {len(plan['reuse'])}")
    for key in plan["delete"]:
        print(f"  [REMOVER] {key}")
    for key in plan["protected"]:
        print(f"  [PROTEGER] {key}")
    for item in plan["upload"]:
        print(f"  [ENVIAR] {item['key']}")
    for item in plan["reuse"]:
        print(f"  [REUTILIZAR] {item['key']}")

def write_manifests(assets: list[dict]) -> None:
    grouped = defaultdict(dict)
    for asset in assets:
        grouped[asset["post_id"]][asset["path"].name] = asset["url"]
    target_dir = BASE_DIR / "data"
    target_dir.mkdir(parents=True, exist_ok=True)
    for post_id, manifest in grouped.items():
        target = target_dir / f"{post_id}-r2-urls.json"
        # arquivo temporario + substituicao atomica para evitar JSON parcial
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
        print(f"  [MANIFESTO] {target}")

def execute_plan(day: str, assets: list[dict], plan: dict,
                 storage: R2Storage, store: SyncStore):
    store.begin(day)
    try:
        # Inventario da revisao final; nao faz uma listagem remota por imagem.
        available = set(plan["remote"])
        # Apaga arquivos antigos ANTES dos uploads, apos pre-validar os arquivos locais.
        for key in plan["delete"]:
            storage.delete(key)
            available.discard(key)
            store.forget_asset(day, key)
            print(f"  [EXCLUIDO] {key}")
        for item in assets:
            key, digest = item["key"], item["sha256"]
            # Interrompe se o arquivo local mudou depois da validacao.
            if sha256_file(item["path"]) != digest:
                raise RuntimeError(f"Arquivo local mudou durante a sincronizacao: {item['path']}")
            # Metadados SHA-256 persistentes permitem retomar uploads interrompidos.
            if key in available and storage.remote_sha256(key) == digest:
                print(f"  [REUTILIZADO] {key}")
            else:
                storage.upload(item["post_id"], item["path"], sha256=digest)
                if storage.remote_sha256(key) != digest:
                    raise RuntimeError(f"SHA256 nao confirmado no R2: {key}")
                available.add(key)
                print(f"  [ENVIADO] {key}")
            store.record_asset(day, item["post_id"], key, digest)
        write_manifests(assets)
        store.finish(day, "complete")
    except Exception as exc:
        store.finish(day, "failed", str(exc))
        raise

def main() -> int:
    parser = argparse.ArgumentParser(description="Sincroniza R2 por dia; DRY-RUN por padrao; nunca publica na Meta")
    parser.add_argument("--date", help="Dia editorial AAAA-MM-DD")
    parser.add_argument("--apply", action="store_true", help="Exclui objetos antigos elegiveis e envia as imagens do dia")
    parser.add_argument("--sessions", action="store_true", help="Consulta historico SQLite sem acessar Google/R2")
    args = parser.parse_args()
    db = BASE_DIR / "data" / "arayflow.sqlite3"
    store = SyncStore(db)
    try:
        if args.sessions:
            if args.apply or args.date:
                parser.error("--sessions nao aceita --date nem --apply")
            rows = store.get_sessions()
            if not rows:
                print("Nenhuma sessao de sincronizacao registrada.")
            for day, status, updated, error in rows:
                print(f"{day} | {status} | {updated} | {error or '-'}")
            return 0
        if not args.date:
            parser.error("Informe --date AAAA-MM-DD ou --sessions")
        try:
            day = datetime.strptime(args.date, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            parser.error("Data invalida: use AAAA-MM-DD")
        if day != args.date:
            parser.error("Data deve estar no formato AAAA-MM-DD")
        with single_sync():
            posts = get_posts(day)
            storage = R2Storage()
            assets = make_assets(day, posts, storage)
            plan = make_plan(storage, store, day, assets)
            show_plan(day, len(posts), assets, plan)
            if not args.apply:
                print("\n[DRY-RUN] Nada excluido, nenhum upload, nenhuma publicacao Meta.")
                return 0
            expected = f"SINCRONIZAR {day}"
            if input(f"Operacao real! Digite exatamente {expected}: ").strip() != expected:
                print("Cancelado; nenhum arquivo alterado.")
                return 1
            # Revalida inventario e protecoes para evitar exclusoes sobre um plano desatualizado.
            fresh = make_plan(storage, store, day, assets)
            if fresh["remote"] != plan["remote"] or fresh["delete"] != plan["delete"] or fresh["protected"] != plan["protected"]:
                raise RuntimeError("Inventario/protecoes mudaram durante confirmacao; execute novamente")
            execute_plan(day, assets, fresh, storage, store)
            print(f"\n[OK] Sessao {day} salva no SQLite; R2 sincronizado.")
            print("[OK] Manifestos locais gerados. Nenhuma publicacao Instagram realizada.")
            return 0
    finally:
        store.close()

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        sys.exit(1)
