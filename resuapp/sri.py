"""Consulta de un RUC en el SRI y comparación de su actividad con el catálogo de la UAFE.

Usa el servicio público del portal del SRI (sin clave). No está documentado oficialmente: si deja de responder, el
programa sigue funcionando con los valores por defecto.
"""

from __future__ import annotations

import http.client
import json
import math
import re
import urllib.request
from collections import Counter
from dataclasses import dataclass

from .importar_facturas import TIPO_ID
from .modelo import PROVINCIAS, sin_tildes

URL = "https://srienlinea.sri.gob.ec/sri-catastro-sujeto-servicio-internet/rest"
TIEMPO_MAXIMO = 15
LIMITE_RESPUESTA = 2_000_000
# Solo se da por segura una coincidencia casi total; lo demás se asigna igual, pero se marca para revisar.
UMBRAL_SEGURA = 0.85
VACIAS = frozenset("DE DEL LA LAS EL LOS Y E O U EN POR PARA AL CON SIN SUS COMO QUE OTRO OTROS OTRA OTRAS ACTIVIDAD "
                   "ACTIVIDADES SERVICIO SERVICIOS TIPO TIPOS TODO TODOS TODA TODAS NCP INCLUIDO INCLUIDA REALIZADA "
                   "REALIZADAS".split())


class SinConexion(Exception):
    """El SRI no respondió (sin internet, servicio caído o respuesta inesperada)."""


@dataclass
class Contribuyente:
    actividad: str
    direccion: str = ""


def ruc_de(identificacion: str) -> str:
    """El RUC que se puede consultar: el mismo, o cédula + 001. Vacío si es pasaporte u otra cosa."""
    if identificacion.isdigit() and len(identificacion) == 13:
        return identificacion
    return identificacion + "001" if identificacion.isdigit() and len(identificacion) == 10 else ""


def _get(ruta: str):
    pedido = urllib.request.Request(URL + ruta, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(pedido, timeout=TIEMPO_MAXIMO) as respuesta:
            datos = respuesta.read(LIMITE_RESPUESTA)
    except (OSError, http.client.HTTPException) as e:
        raise SinConexion(str(e)) from e
    if not datos:                                # el SRI responde vacío (204) si el RUC no existe
        return None
    try:
        return json.loads(datos)
    except ValueError as e:
        raise SinConexion("respuesta inesperada") from e


def consultar(identificacion: str) -> Contribuyente | None:
    """Actividad y dirección de la matriz. None si ese RUC no existe. SinConexion si el SRI no responde."""
    ruc = ruc_de(identificacion)
    if not ruc:
        return None
    datos = _get(f"/ConsultaRuc/obtenerPorNumerosRuc?&ruc={ruc}")
    lista = datos.get("contribuyentes") if isinstance(datos, dict) else None
    primero = lista[0] if isinstance(lista, list) and lista else None
    if not isinstance(primero, dict):
        return None
    locales = _get(f"/Establecimiento/consultarPorNumeroRuc?numeroRuc={ruc}")
    locales = [x for x in locales if isinstance(x, dict)] if isinstance(locales, list) else []
    matriz = next((x for x in locales if x.get("matriz") == "SI"), locales[0] if locales else {})
    return Contribuyente(str(primero.get("actividadEconomicaPrincipal") or "").strip(),
                         str(matriz.get("direccionCompleta") or "").strip())


def _plano(texto: str) -> str:
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", sin_tildes(texto.upper())).split())


def _raices(texto: str) -> set[str]:
    """Palabras importantes recortadas: «telecomunicaciones» y «telecomunicación» cuentan igual."""
    return {p[:6] for p in _plano(texto).split() if p not in VACIAS and len(p) > 2}


class Comparador:
    """Busca en el catálogo por palabras importantes; las poco comunes pesan más que «venta» o «productos»."""

    def __init__(self, catalogo: dict[str, str]):
        self.catalogo = catalogo
        self.raices = {codigo: _raices(nombre) for codigo, nombre in catalogo.items()}
        frecuencia = Counter(r for grupo in self.raices.values() for r in grupo)
        total = len(self.raices)
        self.peso = {r: math.log(1 + total / (1 + n)) for r, n in frecuencia.items()}

    def _suma(self, raices: set[str]) -> float:
        return sum(self.peso.get(r, 0.0) for r in raices)

    def buscar(self, texto: str, cuantos: int = 3) -> list[tuple[str, float]]:
        """[(código, puntaje de 0 a 1)], el mejor primero. A igual puntaje, el código más detallado."""
        buscado = _raices(texto)
        suma_buscado = sum(self.peso.get(r, 1.0) for r in buscado)
        if not suma_buscado:
            return []
        hallados = []
        for codigo, raices in self.raices.items():
            comunes = self._suma(buscado & raices)
            if comunes:
                puntaje = 0.7 * comunes / suma_buscado + 0.3 * comunes / self._suma(raices)
                hallados.append((round(puntaje, 3), len(codigo), codigo))
        hallados.sort(key=lambda h: (-h[0], -h[1], h[2]))
        salida, vistos = [], set()
        for puntaje, _largo, codigo in hallados:         # K641, K6419… con el mismo nombre cuentan una sola vez
            if _plano(self.catalogo[codigo]) not in vistos:
                vistos.add(_plano(self.catalogo[codigo]))
                salida.append((codigo, puntaje))
            if len(salida) == cuantos:
                break
        return salida


def canton_de_direccion(direccion: str, cantones: dict[str, str]) -> str:
    """«PICHINCHA / QUITO / IÑAQUITO / AV…» → 1701. El SRI separa provincia y cantón, así que no hay que adivinar."""
    partes = [_plano(p) for p in direccion.split("/")]
    if len(partes) < 2:
        return ""
    hallados = [c for c, n in cantones.items() if _plano(n) == partes[1] and _plano(PROVINCIAS.get(c[:2], "")) == partes[0]]
    return hallados[0] if len(hallados) == 1 else ""


def aplicar(empresa, identificacion: str, nombre: str, tipo_id_sri: str, c: Contribuyente, comparador: Comparador) -> None:
    """Completa lo que falta del cliente. Nunca cambia una actividad o un cantón que ya tenga."""
    datos = empresa.directorio_clientes().get(identificacion) or {
        "IDE": identificacion, "NRS": " ".join(nombre.upper().split()), "TID": TIPO_ID.get(tipo_id_sri, "")}
    registro: dict = {"texto": c.actividad}
    if not datos.get("AEC"):
        mejores = comparador.buscar(c.actividad)
        if mejores:
            datos["AEC"] = mejores[0][0]
            registro.update(codigo=mejores[0][0], puntaje=mejores[0][1], otras=[m[0] for m in mejores[1:]])
    if not datos.get("CCC"):
        canton = canton_de_direccion(c.direccion, empresa.catalogos.tabla("C"))
        if canton:
            datos["CCC"] = canton
    empresa.recordar_clientes([datos])
    empresa.guardar_consulta_sri(identificacion, registro)


def es_dudosa(registro: dict, codigo: str) -> bool:
    return registro.get("codigo") == codigo and registro.get("puntaje", 1) < UMBRAL_SEGURA
