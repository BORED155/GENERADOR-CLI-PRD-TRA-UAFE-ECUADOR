"""Abre el aplicativo UAFI oficial de cada empresa (Linux, Windows y Mac) y crea accesos directos."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .empresas import Empresa

CLASE_PRINCIPAL = "ec.gob.uaf.sislaft.uafi.ide.FormularioInicial"


def buscar_java() -> str | None:
    """Ejecutable de Java: JAVA_HOME, el PATH o las rutas habituales."""
    nombre = "javaw.exe" if sys.platform.startswith("win") else "java"
    home = os.environ.get("JAVA_HOME")
    if home and (Path(home) / "bin" / nombre).is_file():
        return str(Path(home) / "bin" / nombre)
    encontrado = shutil.which(nombre) or shutil.which("java")
    if encontrado:
        return encontrado
    if sys.platform.startswith("win"):
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            for java in sorted(Path(base).glob("*/*/bin/javaw.exe"), reverse=True):
                return str(java)
    return None


def comando(empresa: Empresa) -> list[str]:
    """Mismo arranque que uafi.bat: idioma español, UTF-8 y classpath «bin + lib/*»."""
    carpeta = empresa.carpeta_uafi
    java = buscar_java()
    if java is None:
        exe = carpeta / "uafi.exe"
        if sys.platform.startswith("win") and exe.is_file():
            return [str(exe)]
        raise FileNotFoundError(
            "No se encontró Java, que es necesario para el aplicativo UAFI.\n"
            "Linux: instale el paquete «default-jre» (sudo apt install default-jre).\n"
            "Windows y Mac: instale Java desde https://adoptium.net")
    sep = ";" if sys.platform.startswith("win") else ":"
    return [java, "-Duser.language=es", "-Dfile.encoding=UTF-8", "-classpath",
            f"bin{sep}lib{os.sep}*", CLASE_PRINCIPAL]


def abrir(empresa: Empresa) -> subprocess.Popen:
    if not empresa.tiene_uafi:
        raise FileNotFoundError(f"La empresa {empresa.nombre} no tiene instalado su aplicativo UAFI.")
    opciones = {}
    if sys.platform.startswith("win"):
        opciones["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        opciones["start_new_session"] = True
    return subprocess.Popen(comando(empresa), cwd=empresa.carpeta_uafi, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, **opciones)


# ----------------------------------------------------------------------
def carpeta_escritorio() -> Path:
    if sys.platform.startswith("linux"):
        try:
            salida = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5)
            if salida.returncode == 0 and salida.stdout.strip():
                return Path(salida.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    for nombre in ("Escritorio", "Desktop"):
        if (Path.home() / nombre).is_dir():
            return Path.home() / nombre
    return Path.home()


def _icono(empresa: Empresa) -> str:
    for nombre in ("iconoApp.png", "icono1.png"):
        for ruta in empresa.carpeta_uafi.rglob(nombre):
            return str(ruta)
    return "applications-office"


def crear_acceso_directo(empresa: Empresa) -> Path:
    """Acceso directo «UAFE - <empresa>» en el escritorio que abre su UAFI."""
    escritorio = carpeta_escritorio()
    titulo = f"UAFE - {empresa.nombre}"
    if sys.platform.startswith("win"):
        ruta = escritorio / f"{titulo}.bat"
        cmd = comando(empresa)
        linea = " ".join(f'"{p}"' if " " in p else p for p in cmd)
        ruta.write_text(f'@echo off\r\ncd /d "{empresa.carpeta_uafi}"\r\nstart "" {linea}\r\n', "utf-8")
        return ruta
    if sys.platform == "darwin":
        ruta = escritorio / f"{titulo}.command"
        cmd = " ".join(f"'{p}'" for p in comando(empresa))
        ruta.write_text(f"#!/bin/sh\ncd '{empresa.carpeta_uafi}' && exec {cmd}\n", "utf-8")
        ruta.chmod(0o755)
        return ruta
    ruta = escritorio / f"uafe-{empresa.id}.desktop"
    reservados = set(' \t"\'\\><~|&;$*?#()`')
    cmd = " ".join('"' + p.replace("\\", "\\\\").replace('"', '\\"') + '"' if reservados & set(p) else p
                   for p in comando(empresa))
    ruta.write_text(
        "[Desktop Entry]\nType=Application\nVersion=1.0\n"
        f"Name={titulo}\nComment=Aplicativo UAFI oficial (reporte RESU) de {empresa.nombre}\n"
        f"Exec={cmd}\nPath={empresa.carpeta_uafi}\nIcon={_icono(empresa)}\nTerminal=false\n"
        "Categories=Office;Finance;\n", "utf-8")
    ruta.chmod(0o755)
    try:  # GNOME/Zorin: marcar como confiable para que se pueda abrir con doble clic
        subprocess.run(["gio", "set", str(ruta), "metadata::trusted", "true"], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass
    return ruta
