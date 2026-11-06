"""Lectura de las facturas de venta de la empresa para armar el reporte RESU.

Se aceptan:
  * XML de comprobantes electrónicos del SRI (con o sin el sobre <autorizacion>), sueltos o en ZIP;
  * PDF (RIDE) de las facturas, porque el portal del SRI no deja descargar el XML de las ventas;
  * el reporte TXT de «comprobantes electrónicos emitidos» que se descarga del portal del SRI
    (FECHA_EMISION, COMPROBANTE, NUMERO_COMPROBANTE, IDENTIFICACION_RECEPTOR, RAZON_SOCIAL,
    CLAVE_ACCESO, VALOR_TOTAL).
"""

from __future__ import annotations

import datetime as dt
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

LIMITE_BYTES = 20 * 1024 * 1024
TIPOS = {"factura": ("01", "Factura"), "notaCredito": ("04", "Nota de crédito"),
         "notaDebito": ("05", "Nota de débito"), "liquidacionCompra": ("03", "Liquidación de compra"),
         "comprobanteRetencion": ("07", "Retención"), "guiaRemision": ("06", "Guía de remisión")}
NOMBRE_TIPO = {c: n for c, n in TIPOS.values()}


class ErrorFactura(Exception):
    pass


@dataclass
class Factura:
    archivo: str
    tipo: str = "01"                    # 01 factura, 04 nota de crédito…
    origen: str = "xml"                 # xml | pdf | txt
    ruc_emisor: str = ""
    tipo_id_cliente: str = ""           # código SRI: 04 RUC, 05 cédula, 06 pasaporte, 07 consumidor final, 08 exterior
    id_cliente: str = ""
    nombre_cliente: str = ""
    direccion_cliente: str = ""
    estab: str = ""
    pto_emi: str = ""
    secuencial: str = ""
    fecha: dt.date | None = None
    clave_acceso: str = ""
    total: Decimal = Decimal(0)
    pagos: list[tuple[str, Decimal]] = field(default_factory=list)   # (forma de pago SRI, valor)
    # Datos del RESU elegidos por el usuario para esta factura (ttr, inst, ttb, adb, cco); vacío = automático
    resu: dict[str, str] = field(default_factory=dict)

    @property
    def numero(self) -> str:
        return f"{self.estab}-{self.pto_emi}-{self.secuencial}"

    @property
    def tipo_nombre(self) -> str:
        return NOMBRE_TIPO.get(self.tipo, self.tipo)


@dataclass
class NoLeido:
    archivo: str
    motivo: str


# ----------------------------------------------------------------------
def clave_acceso_valida(clave: str) -> bool:
    """Dígito verificador (módulo 11) de la clave de acceso de 49 dígitos."""
    if len(clave) != 49 or not clave.isdigit():
        return False
    suma, factor = 0, 2
    for d in reversed(clave[:48]):
        suma += int(d) * factor
        factor = 2 if factor == 7 else factor + 1
    dv = 11 - suma % 11
    dv = {11: 0, 10: 1}.get(dv, dv)
    return dv == int(clave[48])


def _desde_clave(f: Factura, clave: str) -> None:
    f.clave_acceso = clave
    f.fecha = _fecha(f"{clave[0:2]}/{clave[2:4]}/{clave[4:8]}")
    f.tipo = clave[8:10]
    f.ruc_emisor = clave[10:23]
    f.estab, f.pto_emi, f.secuencial = clave[24:27], clave[27:30], clave[30:39]


def _dec(texto: str) -> Decimal:
    try:
        return Decimal(texto.replace(",", "")) if texto else Decimal(0)
    except InvalidOperation:
        return Decimal(0)


def _fecha(texto: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(texto.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def tipo_id_por_numero(ident: str) -> str:
    if ident == "9999999999999":
        return "07"
    if ident.isdigit() and len(ident) == 13:
        return "04"
    if ident.isdigit() and len(ident) == 10:
        return "05"
    return "06" if ident else ""


# ----------------------------------------------------------------------
def leer_rutas(rutas: list[str | Path]) -> list[Factura | NoLeido]:
    """Lee archivos XML, PDF, TXT, ZIP o carpetas completas."""
    salida: list[Factura | NoLeido] = []
    for ruta in map(Path, rutas):
        if ruta.is_dir():
            salida += leer_rutas(sorted(p for p in ruta.rglob("*")
                                        if p.suffix.lower() in (".xml", ".pdf", ".zip", ".txt")))
            continue
        try:
            if ruta.stat().st_size > LIMITE_BYTES:
                raise ErrorFactura("El archivo es demasiado grande")
            sufijo = ruta.suffix.lower()
            if sufijo == ".zip":
                salida += _leer_zip(ruta)
            elif sufijo == ".pdf":
                salida.append(leer_pdf(ruta.read_bytes(), ruta.name))
            elif sufijo == ".txt":
                salida += leer_txt(ruta.read_bytes(), ruta.name)
            else:
                salida.append(leer_xml(ruta.read_bytes(), ruta.name))
        except (ErrorFactura, OSError, zipfile.BadZipFile) as e:
            salida.append(NoLeido(ruta.name, str(e)))
    return salida


def _leer_zip(ruta: Path) -> list[Factura | NoLeido]:
    salida: list[Factura | NoLeido] = []
    with zipfile.ZipFile(ruta) as z:
        for info in z.infolist():
            nombre = f"{ruta.name}/{info.filename}"
            if info.is_dir() or not info.filename.lower().endswith((".xml", ".pdf")):
                continue
            if info.file_size > LIMITE_BYTES:
                salida.append(NoLeido(nombre, "El archivo es demasiado grande"))
                continue
            try:
                datos = z.read(info)
                salida.append(leer_pdf(datos, nombre) if nombre.lower().endswith(".pdf") else leer_xml(datos, nombre))
            except ErrorFactura as e:
                salida.append(NoLeido(nombre, str(e)))
    return salida


# --- XML ---------------------------------------------------------------
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _hijo(e, nombre: str):
    return next((h for h in e if _local(h.tag) == nombre), None) if e is not None else None


def _texto(e, nombre: str) -> str:
    h = _hijo(e, nombre)
    return (h.text or "").strip() if h is not None else ""


def _parsear(datos: bytes):
    if b"<!DOCTYPE" in datos[:2000] or b"<!ENTITY" in datos[:4000]:
        raise ErrorFactura("XML con declaraciones no permitidas")
    try:
        return ET.fromstring(datos)
    except ET.ParseError as e:
        raise ErrorFactura(f"No es un XML válido: {e}") from None


def leer_xml(datos: bytes, nombre: str = "") -> Factura:
    raiz = _parsear(datos)
    if _local(raiz.tag) in ("autorizacion", "RespuestaAutorizacionComprobante", "respuestaComprobante"):
        aut = raiz if _local(raiz.tag) == "autorizacion" else next(
            (e for e in raiz.iter() if _local(e.tag) == "autorizacion"), None)
        nodo = _hijo(aut, "comprobante") if aut is not None else None
        if nodo is None:
            raise ErrorFactura("El archivo de autorización no contiene el comprobante")
        estado = _texto(aut, "estado").upper()
        if estado and estado != "AUTORIZADO":
            raise ErrorFactura(f"Comprobante {estado.lower()}")
        internos = list(nodo)
        raiz = internos[0] if internos else _parsear((nodo.text or "").strip().encode("utf-8"))
    elemento = _local(raiz.tag)
    if elemento == "iva":
        raise ErrorFactura("Es un anexo ATS, no una factura")
    if elemento not in TIPOS:
        raise ErrorFactura(f"No es un comprobante electrónico del SRI (<{elemento}>)")
    f = Factura(archivo=nombre, tipo=TIPOS[elemento][0])
    it = _hijo(raiz, "infoTributaria")
    if it is None:
        raise ErrorFactura("Falta la sección infoTributaria")
    f.ruc_emisor = _texto(it, "ruc")
    f.clave_acceso = _texto(it, "claveAcceso")
    f.estab, f.pto_emi, f.secuencial = _texto(it, "estab"), _texto(it, "ptoEmi"), _texto(it, "secuencial")
    info = _hijo(raiz, {"factura": "infoFactura", "notaCredito": "infoNotaCredito",
                        "notaDebito": "infoNotaDebito"}.get(elemento, ""))
    if info is None:
        return f  # otros tipos: se informan como no importables
    f.fecha = _fecha(_texto(info, "fechaEmision"))
    f.tipo_id_cliente = _texto(info, "tipoIdentificacionComprador")
    f.id_cliente = _texto(info, "identificacionComprador")
    f.nombre_cliente = _texto(info, "razonSocialComprador")
    f.direccion_cliente = _texto(info, "direccionComprador")
    f.total = _dec(_texto(info, "importeTotal") or _texto(info, "valorModificacion") or _texto(info, "valorTotal"))
    pagos = _hijo(info, "pagos")
    for p in (pagos if pagos is not None else []):
        if _local(p.tag) == "pago" and _texto(p, "formaPago"):
            f.pagos.append((_texto(p, "formaPago"), _dec(_texto(p, "total"))))
    if not f.direccion_cliente:  # algunos emisores la ponen en la información adicional
        adicional = _hijo(raiz, "infoAdicional")
        for campo in (adicional if adicional is not None else []):
            if "DIREC" in (campo.get("nombre") or "").upper() and (campo.text or "").strip():
                f.direccion_cliente = campo.text.strip()
                break
    return f


# --- PDF (RIDE) --------------------------------------------------------
_NUM = r"([\d,]*\d\.\d{2})"


def leer_pdf(datos: bytes, nombre: str = "") -> Factura:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:  # pragma: no cover
        raise ErrorFactura("Falta la librería pypdf para leer PDF") from None
    try:
        lector = PdfReader(io.BytesIO(datos))
        if lector.is_encrypted:
            raise ErrorFactura("El PDF está protegido con contraseña")
        texto = "\n".join(p.extract_text(extraction_mode="layout") or "" for p in lector.pages[:10])
    except (PdfReadError, ValueError, KeyError, OSError) as e:
        raise ErrorFactura(f"No se pudo leer el PDF: {e}") from None
    return factura_desde_texto_ride(texto, nombre)


def factura_desde_texto_ride(texto: str, nombre: str = "") -> Factura:
    claves = [c for c in re.findall(r"(?<!\d)\d{49}(?!\d)", texto) if clave_acceso_valida(c)]
    if not claves:
        raise ErrorFactura("El PDF no tiene una clave de acceso válida (¿es un RIDE del SRI?)")
    f = Factura(archivo=nombre, origen="pdf")
    _desde_clave(f, claves[0])

    def buscar(patron: str) -> str:
        m = re.search(patron, texto, re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else ""

    f.nombre_cliente = buscar(r"Raz[oó]n\s+Social\s*/\s*Nombres\s+y\s+Apellidos:?[ \t]+(.+?)(?:\s{3,}|$)")
    f.id_cliente = buscar(r"Identificaci[oó]n:?[ \t]+([0-9A-Za-z-]{3,20})")
    f.tipo_id_cliente = tipo_id_por_numero(f.id_cliente)
    f.direccion_cliente = buscar(r"^\s*Direcci[oó]n(?:\s+Comprador)?:[ \t]+(.+?)(?:\s{3,}|$)")
    f.total = _dec(buscar(r"VALOR\s+TOTAL(?!\s+SIN)\s+" + _NUM) or buscar(r"VALOR\s+MODIFICACI[OÓ]N\s+" + _NUM))
    for linea in texto.splitlines():
        m = re.match(r"\s*(\d{2})\s*-\s*[A-ZÁÉÍÓÚÑ]", linea)
        if m:
            montos = re.findall(_NUM, linea)
            f.pagos.append((m.group(1), _dec(montos[-1]) if montos else Decimal(0)))
    return f


# --- TXT de comprobantes emitidos del portal SRI ------------------------
def leer_txt(datos: bytes, nombre: str = "") -> list[Factura | NoLeido]:
    for codificacion in ("utf-8-sig", "latin-1"):
        try:
            texto = datos.decode(codificacion)
            break
        except UnicodeDecodeError:
            continue
    lineas = [l for l in texto.splitlines() if l.strip()]
    if not lineas or "CLAVE_ACCESO" not in lineas[0].upper():
        raise ErrorFactura("No es el reporte de comprobantes emitidos del SRI")
    columnas = [c.strip().upper() for c in lineas[0].split("\t")]
    salida: list[Factura | NoLeido] = []
    for i, linea in enumerate(lineas[1:], start=2):
        fila = dict(zip(columnas, (c.strip() for c in linea.split("\t"))))
        clave = fila.get("CLAVE_ACCESO", "")
        etiqueta = f"{nombre} (línea {i})"
        if not clave_acceso_valida(clave):
            salida.append(NoLeido(etiqueta, "clave de acceso no válida"))
            continue
        f = Factura(archivo=etiqueta, origen="txt")
        _desde_clave(f, clave)
        f.id_cliente = fila.get("IDENTIFICACION_RECEPTOR", "")
        f.tipo_id_cliente = tipo_id_por_numero(f.id_cliente)
        f.nombre_cliente = fila.get("RAZON_SOCIAL", "")
        f.total = _dec(fila.get("VALOR_TOTAL", ""))
        f.fecha = _fecha(fila.get("FECHA_EMISION", "")) or f.fecha
        salida.append(f)
    return salida
