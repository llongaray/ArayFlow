"""Artes já baixadas em downloads/ e o download que completa o que falta."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

from google_client import BASE_DIR, download_image, extract_folder_id, list_images
from image_validator import validate_batch

from arayflow.editorial import scheduled_time

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def images_for(post: str, root: Path | None = None) -> list[Path]:
    """Lista slides oficiais de um post, em ordem, dentro de downloads/."""
    day = datetime.strptime(post[5:13], "%Y%m%d").strftime("%Y-%m-%d")
    folder = Path(root or BASE_DIR) / "downloads" / day / post
    if not folder.is_dir():
        return []
    pattern = re.compile(re.escape(post) + r"_slide-(\d+)\.(png|jpg|jpeg)", re.I)
    numbered = []
    for path in folder.iterdir():
        match = pattern.fullmatch(path.name) if path.is_file() else None
        if match:
            numbered.append((int(match.group(1)), path))
    return [path for _, path in sorted(numbered)]


def ensure_local(row: dict, drive, root: Path | None = None) -> list[Path]:
    """Baixa imagens ausentes sem sobrescrever artes que já existem."""
    post_id = row["ID"].strip()
    day = scheduled_time(row).strftime("%Y-%m-%d")
    expected = int(row.get("Qtd. imagens", "0"))
    if not 1 <= expected <= 10:
        raise ValueError(f"Quantidade invalida em {post_id}")
    base = Path(root or BASE_DIR)
    paths = images_for(post_id, base)
    if len(paths) != expected:
        folder_id = extract_folder_id(row.get("Pasta das imagens", ""))
        remote = list_images(drive, folder_id)
        if len(remote) != expected:
            raise RuntimeError(
                f"{post_id}: Google Drive possui {len(remote)} imagens, esperado {expected}"
            )
        target = base / "downloads" / day / post_id
        target.mkdir(parents=True, exist_ok=True)
        name_re = re.compile(
            re.escape(post_id) + r"_slide-\d+\.(?:png|jpg|jpeg)", re.I,
        )
        for remote_file in remote:
            name = remote_file["name"]
            if not name_re.fullmatch(name):
                raise ValueError(f"Nome de imagem nao esperado: {name}")
            destination = target / name
            if destination.is_file():
                continue
            temp = target / (name + ".partial")
            try:
                download_image(drive, remote_file, temp)
                temp.replace(destination)
            finally:
                temp.unlink(missing_ok=True)
        paths = images_for(post_id, base)
    if len(paths) != expected:
        raise RuntimeError(f"{post_id}: faltam imagens locais")
    validate_batch(paths)
    if not row.get("Legenda pronta", "").strip():
        raise ValueError(f"{post_id}: legenda vazia")
    return paths
