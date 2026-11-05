"""Punto de entrada: sin argumentos abre la ventana; con argumentos funciona por consola.

    resuapp-cli revisar --uafi CARPETA_UAFI CLI.xlsx OPR.xlsx TRA.xlsx
        Lee las plantillas y muestra los errores con las reglas del UAFI y del manual.
    resuapp-cli rehacer --uafi CARPETA_UAFI --salida CARPETA CLI.xlsx OPR.xlsx TRA.xlsx
        Lee las plantillas y las vuelve a escribir limpias en otra carpeta.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _consola(argv: list[str]) -> int:
    from . import excel, reglas
    from .estructura import cargar_de_uafi

    p = argparse.ArgumentParser(prog="resuapp-cli")
    sub = p.add_subparsers(dest="orden", required=True)
    for nombre in ("revisar", "rehacer"):
        s = sub.add_parser(nombre)
        s.add_argument("--uafi", required=True, type=Path, help="carpeta del aplicativo UAFI de la empresa")
        s.add_argument("plantillas", nargs="+", type=Path)
        if nombre == "rehacer":
            s.add_argument("--salida", required=True, type=Path)
    a = p.parse_args(argv)
    est, cat = cargar_de_uafi(a.uafi)
    rep, avisos = excel.importar(a.plantillas, est, cat)
    for aviso in avisos:
        print("AVISO:", aviso)
    mensajes = reglas.validar(rep, est, cat)
    for m in mensajes:
        donde = " > ".join(str(i + 1) for i in m.ruta) or "reporte"
        print(f"{m.severidad.value}: [{m.nivel or 'REPORTE'} {donde}] {m.campo} {m.texto}")
    errores = sum(m.es_error for m in mensajes)
    print(f"{errores} error(es), {len(mensajes) - errores} advertencia(s).")
    if a.orden == "rehacer":
        for ruta in excel.exportar(rep, est, a.salida):
            print("Generado:", ruta)
    return 1 if errores else 0


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] in ("revisar", "rehacer", "-h", "--help"):
        return _consola(argv)
    from .ui.aplicacion import ejecutar

    return ejecutar(argv)


if __name__ == "__main__":
    sys.exit(main())
