"""Carpetas de datos del usuario según el sistema operativo."""

from __future__ import annotations

import os
import sys
from pathlib import Path

NOMBRE_APP = "resuapp"


def carpeta_datos() -> Path:
    """Carpeta de empresas, reportes y programas UAFI instalados. Se puede forzar con RESUAPP_DATOS."""
    forzada = os.environ.get("RESUAPP_DATOS")
    if forzada:
        base = Path(forzada)
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / NOMBRE_APP
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / NOMBRE_APP
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / NOMBRE_APP
    base.mkdir(parents=True, exist_ok=True)
    return base


def carpeta_empresas() -> Path:
    ruta = carpeta_datos() / "empresas"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def carpeta_documentos() -> Path:
    """Carpeta sugerida para exportar las plantillas Excel."""
    for nombre in ("Documentos", "Documents"):
        ruta = Path.home() / nombre
        if ruta.is_dir():
            return ruta / "UAFE"
    return Path.home() / "UAFE"
