"""Reporte RESU en memoria: clientes > operaciones > transacciones (según la estructura del sector)."""

from __future__ import annotations

import calendar
import json
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator

from .estructura import Archivo, Campo, Estructura

# Campos que el programa llena solo en todos los niveles.
AUTOMATICOS = {"CDR", "FCT"}
# Instrumentos monetarios de la transacción (sector inmobiliario y constructor).
INSTRUMENTOS = ["VDE", "VCR", "VEF", "VCH", "VBB", "VSR", "VTC", "VFC", "VCV"]
PROVINCIAS = {
    "01": "AZUAY", "02": "BOLÍVAR", "03": "CAÑAR", "04": "CARCHI", "05": "COTOPAXI", "06": "CHIMBORAZO",
    "07": "EL ORO", "08": "ESMERALDAS", "09": "GUAYAS", "10": "IMBABURA", "11": "LOJA", "12": "LOS RÍOS",
    "13": "MANABÍ", "14": "MORONA SANTIAGO", "15": "NAPO", "16": "PASTAZA", "17": "PICHINCHA",
    "18": "TUNGURAHUA", "19": "ZAMORA CHINCHIPE", "20": "GALÁPAGOS", "21": "SUCUMBÍOS", "22": "ORELLANA",
    "23": "SANTO DOMINGO DE LOS TSÁCHILAS", "24": "SANTA ELENA", "90": "ZONAS NO DELIMITADAS",
}


def periodo(anio: int, mes: int) -> str:
    """Último día del mes en formato AAAAMMDD (fecha de corte)."""
    return f"{anio:04d}{mes:02d}{calendar.monthrange(anio, mes)[1]:02d}"


def entero(texto: str) -> str:
    """'5.568,60' / '5568.60' / '$ 5,568.6' -> '5568'. Trunca los decimales como pide la UAFE."""
    t = re.sub(r"[^\d,.\-]", "", str(texto or ""))
    if not t:
        return ""
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        partes = t.split(",")
        t = t.replace(",", ".") if len(partes) == 2 and len(partes[1]) != 3 else t.replace(",", "")
    elif t.count(".") > 1 or (t.count(".") == 1 and len(t.split(".")[1]) == 3 and len(t.split(".")[0]) <= 3
                               and t.split(".")[0] not in ("", "0")):
        t = t.replace(".", "")
    try:
        return str(int(Decimal(t)))
    except InvalidOperation:
        return str(texto).strip()


def texto_mayusculas(texto: str) -> str:
    """Mayúsculas, sin espacios repetidos ni saltos de línea."""
    return " ".join(str(texto or "").split()).upper()


def sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def normalizar(campo: Campo, valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    if campo.es_numero:
        return entero(valor)
    if campo.es_fecha:
        return re.sub(r"\D", "", str(valor))
    return texto_mayusculas(valor)


@dataclass
class Registro:
    valores: dict[str, str] = field(default_factory=dict)
    hijos: list["Registro"] = field(default_factory=list)

    def get(self, nombre: str) -> str:
        return self.valores.get(nombre, "")

    def copiar(self) -> "Registro":
        return Registro(dict(self.valores), [h.copiar() for h in self.hijos])

    def a_dict(self) -> dict:
        d: dict = {"valores": self.valores}
        if self.hijos:
            d["hijos"] = [h.a_dict() for h in self.hijos]
        return d

    @classmethod
    def de_dict(cls, d: dict) -> "Registro":
        return cls(dict(d.get("valores", {})), [cls.de_dict(h) for h in d.get("hijos", [])])


Ruta = tuple[int, ...]


@dataclass
class Reporte:
    codigo: str
    anio: int
    mes: int
    clientes: list[Registro] = field(default_factory=list)

    @property
    def periodo(self) -> str:
        return periodo(self.anio, self.mes)

    # --- recorrido ---
    def recorrer(self) -> Iterator[tuple[Ruta, Registro, list[Registro]]]:
        """(ruta, registro, ancestros) en el orden en que se exportan."""
        def visitar(lista: list[Registro], ruta: Ruta, ancestros: list[Registro]):
            for i, reg in enumerate(lista):
                r = ruta + (i,)
                yield r, reg, ancestros
                yield from visitar(reg.hijos, r, ancestros + [reg])
        yield from visitar(self.clientes, (), [])

    def registro(self, ruta: Ruta) -> Registro | None:
        lista, reg = self.clientes, None
        for i in ruta:
            if not 0 <= i < len(lista):
                return None
            reg = lista[i]
            lista = reg.hijos
        return reg

    def valores_completos(self, nivel: Archivo, reg: Registro, ancestros: list[Registro]) -> dict[str, str]:
        """Valores de todos los campos del nivel, con las FK heredadas y los automáticos."""
        heredados: dict[str, str] = {}
        for anc in ancestros:
            heredados.update(anc.valores)
        salida = {}
        for c in nivel.campos:
            if c.nombre == "CDR":
                salida[c.nombre] = self.codigo
            elif c.nombre == "FCT":
                salida[c.nombre] = self.periodo
            elif c.llave == "FK":
                salida[c.nombre] = heredados.get(c.nombre, "")
            else:
                salida[c.nombre] = reg.get(c.nombre)
        return salida

    # --- totales (como la cabecera del .uaf) ---
    def totales(self, estructura: Estructura) -> dict[str, int]:
        conteo = [0] * len(estructura.niveles)
        sumas: dict[str, int] = {}
        for ruta, reg, _anc in self.recorrer():
            nivel = len(ruta) - 1
            if nivel >= len(conteo):
                continue
            conteo[nivel] += 1
            for c in estructura.niveles[nivel].propios:
                if c.es_numero and c.nombre not in ("IMT", "ADB"):
                    try:
                        sumas[c.nombre] = sumas.get(c.nombre, 0) + int(reg.get(c.nombre) or 0)
                    except ValueError:
                        pass
        res = {estructura.niveles[i].nombre: n for i, n in enumerate(conteo)}
        res.update(sumas)
        return res

    # --- archivo ---
    def a_dict(self) -> dict:
        return {"formato": "resuapp-1", "codigo": self.codigo, "anio": self.anio, "mes": self.mes,
                "clientes": [c.a_dict() for c in self.clientes]}

    @classmethod
    def de_dict(cls, d: dict) -> "Reporte":
        return cls(str(d.get("codigo", "")), int(d["anio"]), int(d["mes"]),
                   [Registro.de_dict(c) for c in d.get("clientes", [])])

    def guardar(self, ruta: Path) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_suffix(ruta.suffix + ".tmp")
        tmp.write_text(json.dumps(self.a_dict(), ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(ruta)

    @classmethod
    def abrir(cls, ruta: Path) -> "Reporte":
        return cls.de_dict(json.loads(Path(ruta).read_text("utf-8")))

    def nombre_archivo(self) -> str:
        return f"RESU{self.codigo}{self.periodo}.json"
