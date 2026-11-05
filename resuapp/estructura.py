"""Estructura de archivos y catálogos que trae el aplicativo UAFI de cada empresa.

El UAFI que se descarga del SISLAFT incluye dos XML legibles:
  * DatosSujeto.xml: datos cifrados del sujeto obligado (no se usan aquí) y, en claro, la
    <estructura> del sector: archivos (CLIENTE > OPERACION > TRANSACCION…) y sus campos.
  * Catalogos.xml: tablas de códigos (cantones, actividades, países…).
Se leen tal cual para que el programa se adapte al sector de cada empresa.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

RUTA_RECURSOS = Path("ec/gob/uaf/sislaft/uafi/util/xml")

# Código de catálogo usado en la estructura -> etiqueta en Catalogos.xml
CATALOGO_XML = {
    "TI": "tipoIdentificacion",
    "N": "nacionalidad",
    "C": "canton",
    "AE": "actividadEconomica",
    "TM": "tipoMoneda",
    "TP": "tipoProducto",
    "TT": "tipoTransaccion",
    "P": "pais",
    "TB": "tipoBien",
    "DD": "destinoDonacion",
    "RI": "papelesInterviniente",
    "PT": "tipoPago",
    "TV": "tipoVehiculo",
    "TO": "tipoOperacion",
    "MP": "medidaPeso",
    "TD": "tipoDocumento",
    "TC": "tipoContraparte",
    "DR": "destinoRecurso",
    "MT": "motivoTraslado",
    "TR": "trayecto",
}

# Prefijo de la plantilla Excel según el archivo (el UAFI exige que el nombre empiece así).
PREFIJOS = {"CLIENTE": "CLI", "OPERACION": "OPR", "TRANSACCION": "TRA", "PRODUCTO": "PRD",
            "CONTRAPARTE": "TRC"}


@dataclass
class Campo:
    nombre: str
    tipo: str            # string | long | date
    minimo: int
    maximo: int
    llave: str           # PK | FK | NK
    catalogo: str        # código de catálogo o "NO"
    etiqueta: str

    @property
    def es_numero(self) -> bool:
        return self.tipo == "long"

    @property
    def es_fecha(self) -> bool:
        return self.tipo == "date"

    @property
    def tiene_catalogo(self) -> bool:
        return self.catalogo in CATALOGO_XML


@dataclass
class Archivo:
    nombre: str
    campos: list[Campo]
    hijo: "Archivo | None" = None

    @property
    def prefijo(self) -> str:
        return PREFIJOS.get(self.nombre, self.nombre[:3])

    @property
    def propios(self) -> list[Campo]:
        """Campos que se llenan en este nivel (las FK se heredan del padre)."""
        return [c for c in self.campos if c.llave != "FK"]

    @property
    def llaves(self) -> list[Campo]:
        return [c for c in self.campos if c.llave == "PK"]

    def campo(self, nombre: str) -> Campo | None:
        return next((c for c in self.campos if c.nombre == nombre), None)


@dataclass
class Estructura:
    sector: str
    niveles: list[Archivo]

    @property
    def es_inmobiliaria(self) -> bool:
        return "INMOBILIARIA" in self.sector.upper() or "CONSTRUCTORA" in self.sector.upper()


@dataclass
class Catalogos:
    tablas: dict[str, dict[str, str]] = field(default_factory=dict)

    def tabla(self, codigo_catalogo: str) -> dict[str, str]:
        return self.tablas.get(CATALOGO_XML.get(codigo_catalogo, ""), {})

    def contiene(self, codigo_catalogo: str, valor: str) -> bool:
        return valor in self.tabla(codigo_catalogo)

    def nombre(self, codigo_catalogo: str, valor: str) -> str:
        return self.tabla(codigo_catalogo).get(valor, "")


def _entero(texto: str | None, defecto: int = 0) -> int:
    try:
        return int((texto or "").strip())
    except ValueError:
        return defecto


def _leer_archivo(nodo: ET.Element) -> Archivo:
    campos = []
    for c in nodo.findall("campo"):
        campos.append(Campo(
            nombre=(c.findtext("nombre") or "").strip(),
            tipo=(c.findtext("tipo") or "string").strip(),
            minimo=_entero(c.findtext("minimo")),
            maximo=_entero(c.findtext("maximo"), 9999),
            llave=(c.findtext("llavePrimaria") or "NK").strip(),
            catalogo=(c.findtext("catalogo") or "NO").strip(),
            etiqueta=(c.findtext("label") or "").strip(),
        ))
    archivo = Archivo((nodo.findtext("nombre") or "").strip(), campos)
    hijo = nodo.find("archivos")
    if hijo is not None:
        archivo.hijo = _leer_archivo(hijo)
    return archivo


def leer_estructura(datos_sujeto: Path | bytes) -> Estructura:
    raiz = ET.fromstring(datos_sujeto) if isinstance(datos_sujeto, bytes) else ET.parse(datos_sujeto).getroot()
    est = raiz.find("estructura")
    if est is None:
        raise ValueError("El archivo DatosSujeto.xml no contiene la estructura del reporte.")
    primero = est.find("archivo")
    if primero is None:
        raise ValueError("La estructura no define archivos.")
    niveles = []
    actual: Archivo | None = _leer_archivo(primero)
    while actual is not None:
        niveles.append(actual)
        actual = actual.hijo
    return Estructura(sector=(est.findtext("sector") or "").strip(), niveles=niveles)


def leer_catalogos(ruta: Path | bytes) -> Catalogos:
    raiz = ET.fromstring(ruta) if isinstance(ruta, bytes) else ET.parse(ruta).getroot()
    tablas: dict[str, dict[str, str]] = {}
    for nodo in raiz:
        codigo = (nodo.findtext("codigo") or "").strip()
        if codigo:
            tablas.setdefault(nodo.tag, {})[codigo] = (nodo.findtext("nombre") or "").strip()
    return Catalogos(tablas)


def carpeta_recursos(carpeta_uafi: Path) -> Path:
    """Carpeta con DatosSujeto.xml y Catalogos.xml que realmente usa el UAFI.

    El UAFI arranca con classpath «bin;lib/*», así que manda la copia que está dentro de bin/.
    """
    for base in (carpeta_uafi / "bin", carpeta_uafi):
        ruta = base / RUTA_RECURSOS
        if (ruta / "DatosSujeto.xml").is_file() and (ruta / "Catalogos.xml").is_file():
            return ruta
    raise FileNotFoundError(f"No se encontró DatosSujeto.xml en {carpeta_uafi}")


def cargar_de_uafi(carpeta_uafi: Path) -> tuple[Estructura, Catalogos]:
    recursos = carpeta_recursos(carpeta_uafi)
    return leer_estructura(recursos / "DatosSujeto.xml"), leer_catalogos(recursos / "Catalogos.xml")
