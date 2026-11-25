"""Lo que comparten los scripts de auditoría: la raíz del repo, las carpetas de proveedores y la carga de fichas."""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_cache: dict = {}   # libros de Excel y PDF ya abiertos (no usar desde varios hilos a la vez)


def _proveedores() -> dict:
    return {p.name[:3]: p for p in (RAIZ / "data" / "proveedores").iterdir() if p.is_dir()}


def _sin_tildes(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()


def cargar(carpeta: str = "final") -> list[dict]:
    """Todas las fichas de resultados/<carpeta>/ (sin trazas ni extracciones)."""
    fichas = []
    for f in sorted((RAIZ / "resultados" / carpeta).glob("P*.json")):
        if f.stem.endswith(("_traza", "_extraccion")):
            continue
        datos = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(datos, list):
            fichas.extend(datos)
    return fichas
