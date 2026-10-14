"""Validacao offline das imagens antes da publicacao no Instagram."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from PIL import Image, UnidentifiedImageError

@dataclass(frozen=True)
class ImageReport:
    path: Path
    width: int
    height: int
    mode: str
    format: str

def inspect_image(path: Path) -> ImageReport:
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Arquivo inexistente: {path}")
    if path.stat().st_size == 0:
        raise ValueError(f"Arquivo vazio: {path}")
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            width, height = img.size
            fmt = img.format or ""
            mode = img.mode
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError(f"Imagem corrompida ou nao reconhecida: {path}") from exc
    if fmt not in {"JPEG", "PNG"}:
        raise ValueError(f"Formato nao suportado: {path.name} ({fmt})")
    if width < 320 or height < 320:
        raise ValueError(f"Imagem pequena demais: {path.name} ({width}x{height})")
    ratio = width / height
    # Instagram feed: entre retrato 4:5 e paisagem 1.91:1.
    if not 0.8 <= ratio <= 1.91:
        raise ValueError(f"Proporcao nao suportada: {path.name} ({width}:{height})")
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError(f"Arquivo acima de 8 MiB: {path.name}")
    return ImageReport(path, width, height, mode, fmt)

def validate_batch(paths: list[Path]) -> list[ImageReport]:
    if not paths:
        raise ValueError("Nenhuma imagem recebida")
    if len(paths) > 10:
        raise ValueError("Carrossel excede 10 imagens")
    reports = [inspect_image(p) for p in paths]
    if len(paths) > 1:
        ratios = [round(r.width / r.height, 3) for r in reports]
        if max(ratios) - min(ratios) > 0.015:
            raise ValueError("Slides do carrossel possuem proporcoes divergentes")
    return reports
