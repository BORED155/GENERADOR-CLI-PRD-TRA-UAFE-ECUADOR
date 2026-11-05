"""Validación del reporte RESU.

Reúne dos fuentes:
  * lo que revisa el aplicativo UAFI al cargar las plantillas (longitudes, tipos, catálogos,
    fechas, código de registro, terceros según la procedencia de los recursos, un hijo por padre);
  * las normas del «Manual de generación de estructuras y contenidos RESU» del sector
    inmobiliario y constructor, que el SISLAFT revisa después al recibir el .uaf.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum

from .estructura import Archivo, Campo, Catalogos, Estructura
from .modelo import INSTRUMENTOS, Reporte, Ruta


class Severidad(Enum):
    ERROR = "Error"
    AVISO = "Advertencia"


@dataclass
class Mensaje:
    severidad: Severidad
    ruta: Ruta              # posición del registro (cliente, operación, transacción); () = reporte
    campo: str              # nombre del campo ("" si es del registro completo)
    texto: str
    nivel: str = ""         # CLIENTE / OPERACION / TRANSACCION

    @property
    def es_error(self) -> bool:
        return self.severidad is Severidad.ERROR


# Tabla 2 del manual: instrumentos monetarios permitidos por tipo de transacción.
_TODOS = set(INSTRUMENTOS)
INSTRUMENTOS_POR_TRANSACCION = {
    "91": _TODOS - {"VCR"},
    "92": {"VCR", "VEF", "VCH", "VBB", "VSR", "VCV"},
    "94": _TODOS,
    "95": _TODOS - {"VCR"},
    "96": _TODOS - {"VCR"},
    "97": _TODOS - {"VCR", "VFC"},
    "98": {"VCR", "VEF", "VCH", "VBB", "VSR", "VCV"},
    "99": {"VCR", "VEF", "VCH", "VBB", "VCV"},
    "103": _TODOS - {"VCR"},
}

# Longitudes del manual que son más estrictas que las del UAFI (el SISLAFT las revisa al recibir).
LONGITUDES_MANUAL = {"NRS": (5, 150), "DRB": (8, 150), "CAT": (8, 9), "NCT": (1, 40), "IDE": (3, 20)}
NO_PERMITIDOS = {"N/A", "NA", "NULL", "NULO"}
TIPOS_IDENTIFICACION = {"C", "R", "P", "A"}


def cedula_valida(cedula: str) -> bool:
    """Dígito verificador de la cédula ecuatoriana (módulo 10)."""
    if len(cedula) != 10 or not cedula.isdigit():
        return False
    provincia = int(cedula[:2])
    if not (1 <= provincia <= 24 or provincia == 30) or int(cedula[2]) > 5:
        return False
    suma = 0
    for i, d in enumerate(cedula[:9]):
        v = int(d) * (2 if i % 2 == 0 else 1)
        suma += v - 9 if v > 9 else v
    return (10 - suma % 10) % 10 == int(cedula[9])


def fecha_valida(texto: str) -> dt.date | None:
    if len(texto) != 8 or not texto.isdigit():
        return None
    try:
        return dt.date(int(texto[:4]), int(texto[4:6]), int(texto[6:]))
    except ValueError:
        return None


class Validador:
    def __init__(self, estructura: Estructura, catalogos: Catalogos, hoy: dt.date | None = None):
        self.est = estructura
        self.cat = catalogos
        self.hoy = hoy or dt.date.today()
        self.mensajes: list[Mensaje] = []

    def _msg(self, sev: Severidad, ruta: Ruta, nivel: Archivo | None, campo: str, texto: str) -> None:
        self.mensajes.append(Mensaje(sev, ruta, campo, texto, nivel.nombre if nivel else ""))

    def error(self, ruta, nivel, campo, texto):
        self._msg(Severidad.ERROR, ruta, nivel, campo, texto)

    def aviso(self, ruta, nivel, campo, texto):
        self._msg(Severidad.AVISO, ruta, nivel, campo, texto)

    # ------------------------------------------------------------------
    def validar(self, rep: Reporte) -> list[Mensaje]:
        self.mensajes = []
        if not rep.codigo or not rep.codigo.isdigit() or len(rep.codigo) not in (4, 5) or int(rep.codigo) == 0:
            self.error((), None, "CDR", "El código de registro de la empresa debe tener 4 o 5 dígitos.")
        if not rep.clientes:
            self.error((), None, "", "El reporte no tiene clientes.")
        corte = fecha_valida(rep.periodo)
        if corte and corte > self.hoy:
            self.error((), None, "FCT", f"El período {rep.periodo[:4]}-{rep.periodo[4:6]} todavía no termina: "
                                        "el UAFI no acepta fechas futuras.")
        vistos: list[set] = [set() for _ in self.est.niveles]
        for ruta, reg, ancestros in rep.recorrer():
            n = len(ruta) - 1
            if n >= len(self.est.niveles):
                continue
            nivel = self.est.niveles[n]
            valores = rep.valores_completos(nivel, reg, ancestros)
            self._validar_registro(rep, ruta, nivel, valores)
            # Un padre debe tener al menos un hijo (el UAFI no genera el .uaf si falta).
            if nivel.hijo is not None and not reg.hijos:
                self.error(ruta, nivel, "", f"{_nombre_nivel(nivel)} sin {_nombre_nivel(nivel.hijo).lower()}: "
                                             f"debe registrar al menos una.")
            # Llaves únicas
            clave = tuple(valores.get(c.nombre, "") for c in nivel.campos if c.llave in ("PK", "FK"))
            if clave in vistos[n]:
                self.error(ruta, nivel, "", f"{_nombre_nivel(nivel)} repetida: ya existe otra con los mismos "
                                             f"{', '.join(c.etiqueta.lower() for c in nivel.llaves)}.")
            vistos[n].add(clave)
        return self.mensajes

    def validar_registro(self, rep: Reporte, ruta: Ruta, nivel: Archivo, v: dict[str, str]) -> list[Mensaje]:
        """Revisa un solo registro (para mostrar los errores mientras se edita)."""
        self.mensajes = []
        self._validar_registro(rep, ruta, nivel, v)
        return self.mensajes

    def _validar_registro(self, rep: Reporte, ruta: Ruta, nivel: Archivo, v: dict[str, str]) -> None:
        for campo in nivel.propios:
            self._validar_campo(rep, ruta, nivel, campo, v.get(campo.nombre, ""), v)
        if self.est.es_inmobiliaria:
            self._reglas_inmobiliaria(rep, ruta, nivel, v)

    def _validar_campo(self, rep: Reporte, ruta: Ruta, nivel: Archivo, c: Campo, valor: str, v: dict) -> None:
        if c.nombre in ("CDR", "FCT"):
            return
        terceros = c.nombre in ("TIT", "IDT", "NRT") and nivel.campo("RPT") is not None
        if terceros:
            return  # se revisan junto con la procedencia de los recursos
        if valor == "":
            self.error(ruta, nivel, c.nombre, f"{_etq(c.etiqueta)}: campo vacío, se requiere un valor.")
            return
        if valor.upper() in NO_PERMITIDOS:
            self.error(ruta, nivel, c.nombre, f"{_etq(c.etiqueta)}: no se permite «{valor}».")
            return
        if c.es_fecha:
            fecha = fecha_valida(valor)
            if fecha is None:
                self.error(ruta, nivel, c.nombre, f"{_etq(c.etiqueta)}: fecha «{valor}» no válida (formato AAAAMMDD).")
            elif fecha > self.hoy:
                self.error(ruta, nivel, c.nombre, f"{_etq(c.etiqueta)}: no se pueden ingresar fechas futuras.")
            elif valor > rep.periodo:
                self.error(ruta, nivel, c.nombre, f"{_etq(c.etiqueta)}: la fecha {_fecha(valor)} es posterior al "
                                                  f"corte del reporte ({_fecha(rep.periodo)}).")
            return
        if c.es_numero:
            if not valor.isdigit():
                self.error(ruta, nivel, c.nombre, f"{_etq(c.etiqueta)}: «{valor}» no es un número entero positivo "
                                                  "(sin puntos, comas ni decimales).")
            elif len(valor) > c.maximo:
                self.error(ruta, nivel, c.nombre, f"{_etq(c.etiqueta)}: máximo {c.maximo} dígitos.")
            elif len(valor) > 1 and valor.startswith("0"):
                self.error(ruta, nivel, c.nombre, f"{_etq(c.etiqueta)}: no complete con ceros a la izquierda.")
            return
        minimo, maximo = c.minimo, c.maximo
        if self.est.es_inmobiliaria and c.nombre in LONGITUDES_MANUAL:
            minimo, maximo = max(minimo, LONGITUDES_MANUAL[c.nombre][0]), min(maximo, LONGITUDES_MANUAL[c.nombre][1])
        if not minimo <= len(valor) <= maximo:
            self.error(ruta, nivel, c.nombre, f"{_etq(c.etiqueta)}: «{valor}» tiene {len(valor)} caracteres; "
                                              f"debe tener entre {minimo} y {maximo}.")
            return
        if c.tiene_catalogo and not self.cat.contiene(c.catalogo, valor):
            self.error(ruta, nivel, c.nombre, f"{_etq(c.etiqueta)}: el código «{valor}» no existe en el catálogo.")

    # ------------------------------------------------------------------
    def _reglas_inmobiliaria(self, rep: Reporte, ruta: Ruta, nivel: Archivo, v: dict[str, str]) -> None:
        if nivel.nombre == "CLIENTE":
            self._identificacion(ruta, nivel, "TID", "IDE", v)
            if v.get("NRS") in ("0",):
                self.error(ruta, nivel, "NRS", "Nombres / razón social: no se permite cero.")
        elif nivel.nombre == "OPERACION":
            vto = v.get("VTO", "")
            if vto.isdigit():
                if int(vto) == 0:
                    self.error(ruta, nivel, "VTO", "Valor total de la operación: no puede ser cero.")
                elif not 3 <= len(vto) <= 12:
                    self.error(ruta, nivel, "VTO", "Valor total de la operación: debe tener entre 3 y 12 dígitos "
                                                   "(mínimo 100).")
            if v.get("NCT") == "0":
                self.error(ruta, nivel, "NCT", "Número de contrato: no se permite cero.")
        elif nivel.nombre == "TRANSACCION":
            self._transaccion(rep, ruta, nivel, v)

    def _identificacion(self, ruta, nivel, campo_tipo: str, campo_num: str, v: dict, terceros: bool = False) -> None:
        tipo, num = v.get(campo_tipo, ""), v.get(campo_num, "")
        quien = "del tercero" if terceros else "del cliente"
        if tipo and tipo not in TIPOS_IDENTIFICACION:
            self.error(ruta, nivel, campo_tipo, f"Tipo de identificación {quien}: use C (cédula), R (RUC), "
                                                f"P (pasaporte) o A (análogo).")
            return
        if tipo == "C":
            if len(num) != 10 or not num.isdigit():
                self.error(ruta, nivel, campo_num, f"Identificación {quien}: una cédula debe tener 10 dígitos.")
            elif not cedula_valida(num):
                self.aviso(ruta, nivel, campo_num, f"Identificación {quien}: la cédula {num} no cumple el "
                                                   "dígito verificador; revísela.")
        elif tipo == "R":
            if len(num) != 13 or not num.isdigit():
                self.error(ruta, nivel, campo_num, f"Identificación {quien}: un RUC debe tener 13 dígitos.")
            elif not num.endswith("001"):
                self.aviso(ruta, nivel, campo_num, f"Identificación {quien}: el RUC {num} normalmente termina "
                                                   "en 001; revíselo.")
        elif tipo in ("P", "A") and not 3 <= len(num) <= 20:
            self.error(ruta, nivel, campo_num, f"Identificación {quien}: pasaporte o análogo de 3 a 20 caracteres.")

    def _transaccion(self, rep: Reporte, ruta, nivel, v: dict[str, str]) -> None:
        ftr = v.get("FTR", "")
        if fecha_valida(ftr) and ftr[:6] != rep.periodo[:6]:
            self.error(ruta, nivel, "FTR", f"Fecha de transacción {_fecha(ftr)}: debe ser del mes que se reporta "
                                           f"({rep.periodo[4:6]}/{rep.periodo[:4]}).")
        if v.get("NFA") == "0":
            self.error(ruta, nivel, "NFA", "Número de factura: no se permite cero.")
        # Instrumentos y total
        suma, numeros_ok = 0, True
        for nombre in INSTRUMENTOS:
            valor = v.get(nombre, "")
            if valor.isdigit():
                suma += int(valor)
            else:
                numeros_ok = False
        vvt = v.get("VVT", "")
        if numeros_ok and vvt.isdigit():
            if int(vvt) == 0:
                self.error(ruta, nivel, "VVT", "Valor total: no puede ser cero; registre el valor en el "
                                               "instrumento con que se pagó.")
            elif int(vvt) != suma:
                self.error(ruta, nivel, "VVT", f"Valor total ({vvt}) distinto de la suma de los instrumentos "
                                               f"monetarios ({suma}).")
        permitidos = INSTRUMENTOS_POR_TRANSACCION.get(v.get("TTR", ""))
        if permitidos is not None and numeros_ok:
            for nombre in INSTRUMENTOS:
                if nombre not in permitidos and int(v.get(nombre) or 0) > 0:
                    campo = nivel.campo(nombre)
                    tipo = self.cat.nombre("TT", v["TTR"]) or v["TTR"]
                    self.error(ruta, nivel, nombre, f"{_etq(campo.etiqueta) if campo else nombre}: no se usa en "
                                                    f"«{tipo.lower()}» (tabla 2 del manual); debe ser 0.")
        cat = v.get("CAT", "")
        if cat and rep.codigo and not cat.startswith(rep.codigo):
            self.error(ruta, nivel, "CAT", f"Código de agencia {cat}: debe empezar con el código de registro "
                                           f"de la empresa ({rep.codigo}).")
        # Procedencia de los recursos y datos del tercero (igual que el UAFI)
        rpt = v.get("RPT", "")
        tercero = {k: v.get(k, "") for k in ("TIT", "IDT", "NRT")}
        etiquetas = {"TIT": "Tipo de identificación del tercero", "IDT": "Identificación del tercero",
                     "NRT": "Nombre del tercero"}
        if rpt in ("0", "1"):
            for k, valor in tercero.items():
                if valor != "0":
                    self.error(ruta, nivel, k, f"{etiquetas[k]}: con pago «{self.cat.nombre('PT', rpt).lower()}» "
                                               "debe ser 0.")
        elif rpt in ("2", "3"):
            for k, valor in tercero.items():
                if valor in ("", "0"):
                    self.error(ruta, nivel, k, f"{etiquetas[k]}: obligatorio cuando el pago es "
                                               f"«{self.cat.nombre('PT', rpt).lower()}».")
            if tercero["TIT"] not in ("", "0"):
                self._identificacion(ruta, nivel, "TIT", "IDT", v, terceros=True)
            if tercero["NRT"] not in ("", "0") and len(tercero["NRT"]) > 150:
                self.error(ruta, nivel, "NRT", "Nombre del tercero: máximo 150 caracteres.")


def _etq(etiqueta: str) -> str:
    """'NOMBRES APELLIDOS RAZÓN SOCIAL' -> 'Nombres apellidos razón social'."""
    return etiqueta.strip().capitalize()


def _nombre_nivel(nivel: Archivo) -> str:
    return {"CLIENTE": "Cliente", "OPERACION": "Operación", "TRANSACCION": "Transacción"}.get(
        nivel.nombre, nivel.nombre.capitalize())


def _fecha(aaaammdd: str) -> str:
    return f"{aaaammdd[6:]}/{aaaammdd[4:6]}/{aaaammdd[:4]}" if len(aaaammdd) == 8 else aaaammdd


def validar(rep: Reporte, estructura: Estructura, catalogos: Catalogos, hoy: dt.date | None = None) -> list[Mensaje]:
    return Validador(estructura, catalogos, hoy).validar(rep)
