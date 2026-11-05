"""Empresas (sujetos obligados) y sus aplicativos UAFI instalados.

Cada empresa tiene su propia carpeta dentro de la carpeta de datos:
    empresas/<id>/empresa.json      datos que escribe el usuario (nombre, código de registro…)
    empresas/<id>/uafi/             copia del UAFI oficial descargado del SISLAFT
    empresas/<id>/reportes/         reportes RESU guardados por período
    empresas/<id>/clientes.json     directorio de clientes para reutilizar sus datos
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unicodedata
import zipfile
from dataclasses import asdict, dataclass, field
from functools import cached_property
from pathlib import Path

from .estructura import Catalogos, Estructura, carpeta_recursos, cargar_de_uafi
from .rutas import carpeta_empresas


@dataclass
class Empresa:
    id: str
    nombre: str
    codigo: str                 # código de registro UAFE (CDR), 4 o 5 dígitos
    ruc: str = ""
    usuario: str = ""           # usuario del oficial de cumplimiento en el SISLAFT
    agencia: str = ""           # código de agencia (CAT) que se propone por defecto
    extra: dict = field(default_factory=dict)

    # --- carpetas ---
    @property
    def carpeta(self) -> Path:
        return carpeta_empresas() / self.id

    @property
    def carpeta_uafi(self) -> Path:
        return self.carpeta / "uafi"

    @property
    def carpeta_reportes(self) -> Path:
        ruta = self.carpeta / "reportes"
        ruta.mkdir(parents=True, exist_ok=True)
        return ruta

    @property
    def tiene_uafi(self) -> bool:
        try:
            carpeta_recursos(self.carpeta_uafi)
            return True
        except FileNotFoundError:
            return False

    @cached_property
    def _estructura_catalogos(self) -> tuple[Estructura, Catalogos]:
        return cargar_de_uafi(self.carpeta_uafi)

    @property
    def estructura(self) -> Estructura:
        return self._estructura_catalogos[0]

    @property
    def catalogos(self) -> Catalogos:
        return self._estructura_catalogos[1]

    def agencia_defecto(self) -> str:
        return self.agencia or (f"{self.codigo}1000" if self.codigo else "")

    def guardar(self) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        datos = {k: v for k, v in asdict(self).items() if k != "id"}
        (self.carpeta / "empresa.json").write_text(json.dumps(datos, ensure_ascii=False, indent=2), "utf-8")

    # --- memoria de valores por empresa ---
    def _json(self, nombre: str) -> dict:
        ruta = self.carpeta / nombre
        try:
            return json.loads(ruta.read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def _guardar_json(self, nombre: str, datos: dict) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        (self.carpeta / nombre).write_text(json.dumps(datos, ensure_ascii=False, indent=1), "utf-8")

    def directorio_clientes(self) -> dict[str, dict[str, str]]:
        return self._json("clientes.json")

    def recordar_clientes(self, clientes: list[dict[str, str]]) -> None:
        directorio = self.directorio_clientes()
        for valores in clientes:
            ide = valores.get("IDE", "").strip()
            if ide:
                directorio[ide] = {k: v for k, v in valores.items() if k not in ("CDR", "FCT")}
        self._guardar_json("clientes.json", directorio)

    def valores_recordados(self) -> dict[str, dict[str, str]]:
        return self._json("valores.json")

    def recordar_valores(self, nivel: str, valores: dict[str, str]) -> None:
        todos = self.valores_recordados()
        todos[nivel] = valores
        self._guardar_json("valores.json", todos)


def _identificador(nombre: str) -> str:
    sin_tildes = "".join(c for c in unicodedata.normalize("NFKD", nombre) if not unicodedata.combining(c))
    base = re.sub(r"[^a-z0-9]+", "-", sin_tildes.lower()).strip("-") or "empresa"
    ident, n = base, 2
    while (carpeta_empresas() / ident).exists():
        ident, n = f"{base}-{n}", n + 1
    return ident


def listar() -> list[Empresa]:
    empresas = []
    for carpeta in sorted(carpeta_empresas().iterdir()):
        ruta = carpeta / "empresa.json"
        if not ruta.is_file():
            continue
        try:
            datos = json.loads(ruta.read_text("utf-8"))
        except ValueError:
            continue
        campos = {k: datos.get(k, "") for k in ("nombre", "codigo", "ruc", "usuario", "agencia")}
        empresas.append(Empresa(id=carpeta.name, extra=datos.get("extra", {}), **campos))
    return sorted(empresas, key=lambda e: e.nombre.upper())


def _raiz_uafi(carpeta: Path) -> Path:
    """Carpeta que contiene bin/ y lib/ del UAFI (puede venir anidada dentro del zip)."""
    for candidato in [carpeta, *sorted(p for p in carpeta.rglob("*") if p.is_dir())]:
        if (candidato / "lib").is_dir() and (candidato / "bin").is_dir():
            return candidato
    carpeta_recursos(carpeta)  # lanza FileNotFoundError con un mensaje claro
    return carpeta


def instalar_uafi(origen: Path, empresa: Empresa) -> None:
    """Copia el UAFI (uafi.zip o carpeta ya descomprimida) dentro de la carpeta de la empresa."""
    origen = Path(origen)
    with tempfile.TemporaryDirectory() as tmp:
        if origen.is_file():
            if not zipfile.is_zipfile(origen):
                raise ValueError("El archivo elegido no es un .zip del aplicativo UAFI.")
            with zipfile.ZipFile(origen) as z:
                for nombre in z.namelist():
                    destino = (Path(tmp) / nombre).resolve()
                    if not str(destino).startswith(str(Path(tmp).resolve())):
                        raise ValueError(f"Ruta no permitida dentro del zip: {nombre}")
                z.extractall(tmp)
            raiz = _raiz_uafi(Path(tmp))
        else:
            raiz = _raiz_uafi(origen)
        cargar_de_uafi(raiz)  # valida que se pueda leer antes de reemplazar nada
        if empresa.carpeta_uafi.exists():
            shutil.rmtree(empresa.carpeta_uafi)
        empresa.carpeta.mkdir(parents=True, exist_ok=True)
        shutil.copytree(raiz, empresa.carpeta_uafi)
    empresa.__dict__.pop("_estructura_catalogos", None)


def crear(nombre: str, codigo: str, origen_uafi: Path, ruc: str = "", usuario: str = "", agencia: str = "") -> Empresa:
    empresa = Empresa(id=_identificador(nombre), nombre=nombre.strip(), codigo=codigo.strip(), ruc=ruc.strip(),
                      usuario=usuario.strip(), agencia=agencia.strip())
    try:
        instalar_uafi(origen_uafi, empresa)
        empresa.guardar()
    except Exception:
        shutil.rmtree(empresa.carpeta, ignore_errors=True)
        raise
    return empresa


def eliminar(empresa: Empresa) -> None:
    shutil.rmtree(empresa.carpeta, ignore_errors=True)
