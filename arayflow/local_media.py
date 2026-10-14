"""Artes já baixadas em downloads/ e o download que completa o que falta."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

from google_client import download_image, extract_folder_id, list_images, local_path
from image_validator import validate_batch

from arayflow.editorial import scheduled_time

_SLIDE_FILE = re.compile(r"_slide-(\d+)\.(?:png|jpg|jpeg)$", re.I)

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slide_number(name: str) -> int:
    match = _SLIDE_FILE.search(name)
    if not match:
        raise ValueError(f"Nome de imagem nao esperado: {name}")
    return int(match.group(1))


def require_slide_sequence(paths: list[Path], expected: int, post_id: str) -> None:
    """Exige os slides 1..N, sem lacuna, repetição ou número fora da série."""
    numbers = [slide_number(path.name) for path in paths]
    wanted = list(range(1, expected + 1))
    if numbers != wanted:
        raise ValueError(
            f"{post_id}: slides devem ser continuos de 1 a {expected}; encontrados {numbers}"
        )


def _filename_pattern(post_id: str) -> re.Pattern[str]:
    return re.compile(re.escape(post_id) + r"_slide-(\d+)\.(?:png|jpg|jpeg)", re.I)


def _downloads_folder(post_id: str, root: Path | None) -> Path:
    day = datetime.strptime(post_id[5:13], "%Y%m%d").strftime("%Y-%m-%d")
    if root is None:
        return local_path("DOWNLOAD_DIR", "downloads") / day / post_id
    return Path(root) / "downloads" / day / post_id


def images_for(post: str, root: Path | None = None) -> list[Path]:
    """Lista slides oficiais de um post, em ordem, dentro de downloads/."""
    folder = _downloads_folder(post, root)
    if not folder.is_dir():
        return []
    pattern = _filename_pattern(post)
    numbered = []
    for path in folder.iterdir():
        match = pattern.fullmatch(path.name) if path.is_file() else None
        if match:
            numbered.append((int(match.group(1)), path))
    return [path for _, path in sorted(numbered)]


def expected_image_count(row: dict) -> int:
    post_id = row["ID"].strip()
    expected = int(row.get("Qtd. imagens", "0") or 0)
    if not 1 <= expected <= 10:
        raise ValueError(f"Quantidade invalida em {post_id}")
    return expected


def checked_remote(row: dict, drive) -> list[dict]:
    """Confere nomes, quantidade e sequência no Drive, sem baixar arquivos."""
    post_id = row["ID"].strip()
    expected = expected_image_count(row)
    if not row.get("Legenda pronta", "").strip():
        raise ValueError(f"{post_id}: legenda vazia")
    remote = list_images(drive, extract_folder_id(row.get("Pasta das imagens", "")))
    if len(remote) != expected:
        raise RuntimeError(
            f"{post_id}: Google Drive possui {len(remote)} imagens, esperado {expected}"
        )
    pattern = _filename_pattern(post_id)
    numbers = []
    for item in remote:
        match = pattern.fullmatch(item["name"])
        if not match:
            raise ValueError(f"Nome de imagem nao esperado: {item['name']}")
        numbers.append(int(match.group(1)))
    if numbers != list(range(1, expected + 1)):
        raise ValueError(
            f"{post_id}: slides do Drive devem ser continuos de 1 a {expected}; encontrados {numbers}"
        )
    return remote


def ensure_local(row: dict, drive, root: Path | None = None) -> list[Path]:
    """Baixa imagens ausentes sem sobrescrever artes que já existem."""
    post_id = row["ID"].strip()
    day = scheduled_time(row).strftime("%Y-%m-%d")
    expected = expected_image_count(row)
    paths = images_for(post_id, root)
    if len(paths) != expected:
        remote = checked_remote(row, drive)
        target = _downloads_folder(post_id, root)
        if target.parent.name != day:
            raise ValueError(f"ID {post_id} nao pertence ao dia {day}")
        target.mkdir(parents=True, exist_ok=True)
        for remote_file in remote:
            destination = target / remote_file["name"]
            if destination.is_file():
                continue
            temp = target / (remote_file["name"] + ".partial")
            try:
                download_image(drive, remote_file, temp)
                temp.replace(destination)
            finally:
                temp.unlink(missing_ok=True)
        paths = images_for(post_id, root)
    if len(paths) != expected:
        raise RuntimeError(
            f"{post_id}: encontradas {len(paths)} imagens locais, esperado {expected}"
        )
    require_slide_sequence(paths, expected, post_id)
    validate_batch(paths)
    if not row.get("Legenda pronta", "").strip():
        raise ValueError(f"{post_id}: legenda vazia")
    return paths
