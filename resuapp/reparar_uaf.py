"""Corrige los .uaf que el UAFI guarda con nombre de Windows al usarse en Linux o Mac.

El UAFI une la carpeta elegida y el nombre con «\\» (separador de Windows). En Linux ese
carácter no separa carpetas, así que al elegir «…/prueb/mi carpeta» el archivo queda en
«…/prueb» con el nombre «mi carpeta\\RESU9999920260831.uaf». Aquí se mueve a
«…/prueb/mi carpeta/RESU9999920260831.uaf», que es lo que se quiso guardar.
"""

from __future__ import annotations

import os
from pathlib import Path

PROFUNDIDAD = 4
SALTAR = {".venv", "venv", "node_modules", "__pycache__", ".git", ".cache", "site-packages", "snap"}


def candidatos(carpetas: list[Path], desde: float = 0.0, profundidad: int = PROFUNDIDAD) -> list[Path]:
    """Archivos «…\\…uaf» modificados después de `desde` (marca de tiempo) dentro de esas carpetas."""
    vistos: set[Path] = set()
    salida: list[Path] = []

    def recorrer(carpeta: Path, nivel: int) -> None:
        try:
            entradas = list(os.scandir(carpeta))
        except OSError:
            return
        for e in entradas:
            try:
                if e.is_file(follow_symlinks=False):
                    if "\\" in e.name and e.name.lower().endswith(".uaf") and e.stat().st_mtime >= desde:
                        ruta = Path(e.path)
                        if ruta not in vistos:
                            vistos.add(ruta)
                            salida.append(ruta)
                elif e.is_dir(follow_symlinks=False) and nivel < profundidad and \
                        not e.name.startswith(".") and e.name not in SALTAR:
                    recorrer(Path(e.path), nivel + 1)
            except OSError:
                continue

    for c in carpetas:
        if c and Path(c).is_dir():
            recorrer(Path(c), 0)
    return salida


def destino_correcto(ruta: Path) -> Path:
    """«…/prueb/mi carpeta\\RESU….uaf» -> «…/prueb/mi carpeta/RESU….uaf»."""
    partes = [p for p in ruta.name.replace("\\", "/").split("/") if p]
    return ruta.parent.joinpath(*partes)


def reparar(ruta: Path) -> Path:
    """Mueve el archivo a donde se quiso guardar. Devuelve la ruta final."""
    final = destino_correcto(ruta)
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        if final.read_bytes() == ruta.read_bytes():
            ruta.unlink()           # ya estaba guardado igual
            return final
        n = 2
        while (alt := final.with_name(f"{final.stem} ({n}){final.suffix}")).exists():
            n += 1
        final = alt
    ruta.replace(final)
    return final


def reparar_todo(carpetas: list[Path], desde: float = 0.0) -> list[tuple[Path, Path]]:
    cambios = []
    for r in candidatos(carpetas, desde):
        try:
            cambios.append((r, reparar(r)))
        except OSError:
            continue
    return cambios
