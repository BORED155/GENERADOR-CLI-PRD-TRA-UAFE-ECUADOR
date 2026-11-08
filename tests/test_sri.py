"""Consulta del RUC en el SRI: siempre con respuestas inventadas, sin salir a internet."""

from __future__ import annotations

import datetime as dt
import io
import json
import urllib.error
import urllib.request
from decimal import Decimal as D

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from fabrica import CODIGO
from resuapp import empresas, facturas as fa, sri
from resuapp.ui import simple

CLIENTE = "1799999915001"
CATALOGO = {
    "J612": "ACTIVIDADES DE TELECOMUNICACIONES INALÁMBRICAS.",
    "J61200": "ACTIVIDADES DE TELECOMUNICACIONES INALÁMBRICAS.",
    "G454003": "Actividades de mantenimiento y reparación de motocicletas.",
    "F410010": "Construcción de todo tipo de edificios residenciales: casas familiares, edificios multifamiliares.",
    "F41002": "CONSTRUCCIÓN DE EDIFICIOS NO RESIDENCIALES.",
    "H49230": "TRANSPORTE DE CARGA POR CARRETERA.",
    "H4923": "TRANSPORTE DE CARGA POR CARRETERA.",
    "M749013": "Actividades de intermediación en materia de patentes.",
    "K641": "INTERMEDIACIÓN MONETARIA.",
}


def test_ruc_de():
    assert sri.ruc_de("1799999915001") == "1799999915001"
    assert sri.ruc_de("1711111111") == "1711111111001"           # cédula: se intenta con 001
    assert sri.ruc_de("AB123456") == "" and sri.ruc_de("") == ""


def test_compara_por_palabras_no_por_letras():
    c = sri.Comparador(CATALOGO)
    assert c.buscar("ACTIVIDADES DE TELEFONÍA MÓVIL Y REDES DE TELECOMUNICACIONES INALÁMBRICAS.")[0][0] == "J61200"
    # «actividades de intermediación» no debe llevar a patentes
    assert c.buscar("ACTIVIDADES DE INTERMEDIACIÓN MONETARIA REALIZADA POR LA BANCA COMERCIAL.")[0][0] == "K641"


def test_iguales_prefiere_el_detalle_y_no_repite_nombres():
    resultado = sri.Comparador(CATALOGO).buscar("SERVICIOS DE TRANSPORTE DE CARGA POR CARRETERA.")
    assert resultado[0] == ("H49230", 1.0) and [c for c, _p in resultado].count("H4923") == 0


def test_sin_palabras_en_comun():
    c = sri.Comparador(CATALOGO)
    assert c.buscar("") == [] and c.buscar("ZZZ QQQ") == []


@pytest.mark.parametrize("direccion, esperado", [
    ("PICHINCHA / QUITO / IÑAQUITO / AV. AMAZONAS", "1701"),
    ("MANABI / MANTA / MANTA / AV 2", ""),                       # no está en este catálogo
    ("QUITO", ""),
    ("", ""),
])
def test_canton_de_direccion(direccion, esperado):
    assert sri.canton_de_direccion(direccion, {"1701": "QUITO", "1311": "PICHINCHA", "0000": "N/A"}) == esperado


class _Respuesta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _fake_urlopen(monkeypatch, respuestas):
    pedidos = []

    def abrir(pedido, timeout):
        pedidos.append(pedido.full_url)
        r = respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return _Respuesta(r)

    monkeypatch.undo()                  # quita el bloqueo general de red de conftest solo para esta prueba
    monkeypatch.setattr(urllib.request, "urlopen", abrir)
    return pedidos


def test_consultar_lee_actividad_y_matriz(monkeypatch):
    contribuyente = json.dumps({"contribuyentes": [{"actividadEconomicaPrincipal": " VENTA DE ALGO. "}]}).encode()
    locales = json.dumps([{"matriz": "NO", "direccionCompleta": "A / B"}, {"matriz": "SI", "direccionCompleta": "C / D"}]).encode()
    pedidos = _fake_urlopen(monkeypatch, [contribuyente, locales])
    c = sri.consultar("1711111111")
    assert (c.actividad, c.direccion) == ("VENTA DE ALGO.", "C / D") and "1711111111001" in pedidos[0]


@pytest.mark.parametrize("respuesta", [b"", b"[]", b'{"contribuyentes": []}', b'{"contribuyentes": ["raro"]}'])
def test_ruc_que_no_existe(monkeypatch, respuesta):
    _fake_urlopen(monkeypatch, [respuesta])
    assert sri.consultar(CLIENTE) is None


@pytest.mark.parametrize("problema", [urllib.error.URLError("sin red"), TimeoutError(), b"<html>captcha</html>"])
def test_servicio_caido(monkeypatch, problema):
    _fake_urlopen(monkeypatch, [problema])
    with pytest.raises(sri.SinConexion):
        sri.consultar(CLIENTE)


def test_pasaporte_no_se_consulta(monkeypatch):
    pedidos = _fake_urlopen(monkeypatch, [])
    assert sri.consultar("AB123456") is None and pedidos == []


@pytest.fixture
def empresa(datos, uafi_zip):
    return empresas.crear("Constructora Prueba", CODIGO, uafi_zip)


def _comparador(e):
    return sri.Comparador(e.catalogos.tabla("AE"))


def test_aplicar_completa_actividad_y_canton(empresa):
    c = sri.Contribuyente("CONSTRUCCION DE EDIFICIOS", "PICHINCHA / QUITO / X / CALLE")
    sri.aplicar(empresa, CLIENTE, "cliente ficticio", "04", c, _comparador(empresa))
    d = empresa.directorio_clientes()[CLIENTE]
    assert (d["AEC"], d["CCC"], d["TID"], d["NRS"]) == ("F4100", "1701", "R", "CLIENTE FICTICIO")
    assert empresa.consultas_sri()[CLIENTE]["codigo"] == "F4100"


def test_aplicar_no_cambia_lo_que_ya_tiene(empresa):
    empresa.recordar_clientes([{"IDE": CLIENTE, "AEC": "L6810", "CCC": "0101"}])
    c = sri.Contribuyente("CONSTRUCCION DE EDIFICIOS", "PICHINCHA / QUITO / X / CALLE")
    sri.aplicar(empresa, CLIENTE, "X", "04", c, _comparador(empresa))
    d = empresa.directorio_clientes()[CLIENTE]
    assert (d["AEC"], d["CCC"]) == ("L6810", "0101") and "codigo" not in empresa.consultas_sri()[CLIENTE]


def test_es_dudosa():
    assert sri.es_dudosa({"codigo": "A", "puntaje": 0.6}, "A")
    assert not sri.es_dudosa({"codigo": "A", "puntaje": 0.9}, "A")
    assert not sri.es_dudosa({"codigo": "A", "puntaje": 0.6}, "B")      # el usuario ya puso otra
    assert not sri.es_dudosa({}, "A")


def _factura():
    return fa.Factura("f", id_cliente=CLIENTE, tipo_id_cliente="04", nombre_cliente="CLIENTE FICTICIO", fecha=dt.date(2026, 2, 15),
                      direccion_cliente="CALLE FICTICIA 123", estab="001", pto_emi="001", secuencial="000000001",
                      total=D(500), pagos=[("20", D(500))])


def _ventana():
    QApplication.instance() or QApplication([])
    v = simple.VentanaSimple()
    v.c_empresa.setCurrentIndex(1)
    v.c_mes.setCurrentIndex(1)
    v.s_anio.setValue(2026)
    v.lista = [_factura()]
    v._mostrar_lista()
    return v


def test_ventana_asigna_marca_y_no_repite(empresa, monkeypatch):
    llamadas = []

    def falso(ident):
        llamadas.append(ident)
        return sri.Contribuyente("INMOBILIARIAS Y ALGO MUY DISTINTO DE PRUEBA", "PICHINCHA / QUITO / X / Y")

    monkeypatch.setattr(sri, "consultar", falso)
    v = _ventana()
    v._consultar_sri()
    assert llamadas == [CLIENTE]
    item = v.tabla.item(0, simple.C_AEC)
    assert item.data(Qt.UserRole) == "L6810" and item.background().color().name() == "#ffe08a"
    assert "Según el SRI" in item.toolTip() and "dudosa" in item.toolTip()
    _r, _e, advertencias, _a = v._revisar()
    assert any("dudosa" in a for a in advertencias)
    v._sri_pedidos.clear()                                     # otra sesión: ya está guardado, no se consulta de nuevo
    v._consultar_sri()
    assert llamadas == [CLIENTE]
    v.guardar_actividad(v.lista[0], "L6810")                    # confirmada: se quita el ámbar
    assert v.tabla.item(0, simple.C_AEC).background().color().name() != "#ffe08a"
    v._sin_generar = False
    v.close()


def test_sin_internet_no_marca_y_se_puede_reintentar(empresa):
    v = _ventana()
    v._consultar_sri()                                         # conftest: el SRI no responde
    assert "No se pudo consultar" in v.statusBar().currentMessage()
    assert "AEC" not in empresa.directorio_clientes().get(CLIENTE, {}) and not v._sri_pedidos
    v._sin_generar = False
    v.close()


def test_no_redibuja_mientras_se_escribe(empresa, monkeypatch):
    from PySide6.QtWidgets import QAbstractItemView

    v = _ventana()
    monkeypatch.setattr(v.tabla, "state", lambda: QAbstractItemView.EditingState)
    dibujos = []
    monkeypatch.setattr(v, "_mostrar_lista", lambda **k: dibujos.append(k))
    v._sri_por_dibujar = True
    v._sri_dibujar()
    assert dibujos == [] and v._sri_por_dibujar
    v._sin_generar = False
    v.close()
