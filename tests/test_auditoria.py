"""Casos que encontró la auditoría (todos con datos ficticios)."""

from __future__ import annotations

import datetime as dt
import json
import zipfile
from decimal import Decimal as D

import pytest
from openpyxl import load_workbook
from PySide6.QtWidgets import QApplication, QMessageBox

from fabrica import CODIGO, reporte
from resuapp import empresas, excel, facturas as fa, importar_facturas as imf
from resuapp.modelo import INSTRUMENTOS, Reporte

CLIENTE = "1711111110"
CANTONES = {"1701": "QUITO", "1311": "PICHINCHA", "1308": "MANTA", "1101": "LOJA", "0901": "GUAYAQUIL", "0402": "BOLÍVAR",
            "1302": "BOLÍVAR", "0204": "SAN MIGUEL", "1704": "SAN MIGUEL DE LOS BANCOS"}


@pytest.mark.parametrize("direccion, esperado", [
    ("PICHINCHA / QUITO / CALLE SUCRE Y BOLIVAR", "1701"),      # calle y provincia con nombre de otro cantón
    ("GUAYAS GUAYAQUIL AV. QUITO 45", "0901"),
    ("AV. LOJA 123 Y CALLE MANTA, QUITO", ""),                  # sin provincia: mejor no inventar
    ("LOJA, LOJA, CALLE MANTA", "1101"),                        # aquí sí aparece la provincia, además del cantón
    ("SAN MIGUEL DE LOS BANCOS, BARRIO CENTRAL", "1704"),       # el nombre más completo manda
    ("AV. AMAZONAS, QUITO", "1701"),
    ("CALLE SIN CIUDAD", ""),
])
def test_canton_por_direccion(direccion, esperado):
    assert imf.canton_por_direccion(direccion, CANTONES) == esperado


@pytest.fixture
def empresa(datos, uafi_zip):
    return empresas.crear("Constructora Prueba", CODIGO, uafi_zip)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _reporte_repartido():
    rep = reporte()
    tr = rep.clientes[0].hijos[0].hijos[0]
    tr.valores.update({n: "0" for n in INSTRUMENTOS})
    tr.valores.update(VEF="100", VCH="200", VVT="300")
    return rep, tr


def _recargar(empresa, rep, total=None):
    lista = imf.facturas_desde_reporte(rep)
    if total is not None:
        lista[0].total = D(total)
    nuevo, _ = imf.construir_reporte(empresa, rep.anio, rep.mes, lista, imf.Opciones(instrumento_20="VDE"), {})
    return nuevo.clientes[0].hijos[0].hijos[0]


def test_recargar_plantillas_conserva_el_pago_repartido(empresa):
    rep, _tr = _reporte_repartido()
    tr = _recargar(empresa, rep)
    assert {n: tr.get(n) for n in INSTRUMENTOS if tr.get(n) != "0"} == {"VEF": "100", "VCH": "200"}


def test_cambiar_total_de_un_pago_repartido_mantiene_la_proporcion(empresa):
    rep, _tr = _reporte_repartido()
    tr = _recargar(empresa, rep, total=600)
    assert (tr.get("VEF"), tr.get("VCH"), tr.get("VVT")) == ("200", "400", "600")


def test_total_editado_con_varias_formas_de_pago_nunca_da_negativos():
    f = fa.Factura("x", total=D(100), pagos=[("01", D(600)), ("20", D(400))])
    valores = imf.instrumentos(imf.Propuesta("x", imf.LISTA, f, instrumento="VDE"), imf.Opciones())
    assert {k: v for k, v in valores.items() if v} == {"VEF": 60, "VDE": 40}


def _factura(anio, n=1):
    return fa.Factura(f"f{n}", id_cliente=CLIENTE, tipo_id_cliente="05", nombre_cliente="CLIENTE FICTICIO",
                      direccion_cliente="CALLE FICTICIA 123", fecha=dt.date(anio, 2, 15), estab="001", pto_emi="001",
                      secuencial=f"{n:09d}", total=D(500), pagos=[("20", D(500))])


def _ventana(respuesta, monkeypatch):
    from resuapp.ui.simple import VentanaSimple

    preguntas = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: preguntas.append(a[2]) or respuesta))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    v = VentanaSimple()
    v.c_empresa.setCurrentIndex(1)
    v.c_mes.setCurrentIndex(1)
    v.s_anio.setValue(2026)
    return v, preguntas


def test_lo_que_no_entra_al_reporte_se_avisa(app, empresa, monkeypatch):
    v, _p = _ventana(QMessageBox.Yes, monkeypatch)
    v.lista = [_factura(2026, 1), _factura(2025, 2)]
    v._mostrar_lista()
    rep, errores, _adv, afectadas = v._revisar()
    assert sum(len(c.hijos) for c in rep.clientes) == 1
    assert any("no entra al reporte" in e and "000000002" in e for e in errores)
    assert (CLIENTE, "001-001-000000002") in afectadas
    v._sin_generar = False
    v.close()


def test_cambiar_de_mes_pregunta_antes_de_vaciar(app, empresa, monkeypatch):
    v, preguntas = _ventana(QMessageBox.No, monkeypatch)
    v.lista = [_factura(2026)]
    v._mostrar_lista()
    v.c_mes.setCurrentIndex(5)
    assert len(preguntas) == 1 and len(v.lista) == 1 and v.c_mes.currentIndex() == 1       # dijo No: todo sigue igual
    v.s_anio.setValue(2020)
    assert len(preguntas) == 2 and len(v.lista) == 1 and v.anio == 2026
    v.c_empresa.setCurrentIndex(0)
    assert len(preguntas) == 3 and len(v.lista) == 1 and v.c_empresa.currentIndex() == 1
    assert not v.close() and len(preguntas) == 4                                            # tampoco cierra
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    v.c_mes.setCurrentIndex(5)
    assert v.lista == [] and v.c_mes.currentIndex() == 5
    assert v.close()


def test_ya_generado_no_pregunta(app, empresa, monkeypatch):
    v, preguntas = _ventana(QMessageBox.No, monkeypatch)
    v.lista = [_factura(2026)]
    v._mostrar_lista()
    v._sin_generar = False                                  # lo que deja generar() al terminar bien
    assert v.close() and preguntas == []


def test_abrir_empresas_no_vacia_la_tabla(app, empresa, monkeypatch):
    from resuapp.ui import simple

    v, _p = _ventana(QMessageBox.Yes, monkeypatch)
    v.lista = [_factura(2026)]
    v._mostrar_lista()
    monkeypatch.setattr(simple.DialogoEmpresas, "exec", lambda self: 0)
    v.administrar_empresas()
    assert len(v.lista) == 1 and v._sin_generar
    v._sin_generar = False
    v.close()


def test_archivo_danado_se_aparta_y_no_se_pisa(empresa):
    empresa.recordar_clientes([{"IDE": "111", "AEC": "A"}])
    ruta = empresa.carpeta / "clientes.json"
    ruta.write_text('{"111": {"IDE"', "utf-8")
    assert empresa.directorio_clientes() == {}
    assert empresa.archivos_danados() == ["clientes.json.danado"]
    assert (empresa.carpeta / "clientes.json.danado").read_text("utf-8").startswith('{"111"')
    empresa.recordar_clientes([{"IDE": "222"}])
    assert list(json.loads(ruta.read_text("utf-8"))) == ["222"] and not list(empresa.carpeta.glob("*.tmp"))


def test_empresa_danada_sigue_en_la_lista(empresa):
    (empresa.carpeta / "empresa.json").write_text("{", "utf-8")
    assert "dañado" in empresas.listar()[0].nombre


def test_area_con_tres_decimales_no_se_multiplica():
    assert excel._texto(85.125) == "85.12" or excel._texto(85.125) == "85.13"
    assert excel._texto(1234.0) == "1234"


@pytest.mark.parametrize("texto, esperado", [("1234.56", "1234.56"), ("1,234.56", "1234.56"), ("1.234,56", "1234.56"),
                                             ("1234,56", "1234.56"), ("1,234", "1234"), ("12.345.678,90", "12345678.90")])
def test_numeros_de_facturas(texto, esperado):
    assert fa._dec(texto) == D(esperado)


@pytest.mark.parametrize("total, esperado", [("1.234,56", "1234.56"), ("1,234.56", "1234.56"), ("123.456,78", "123456.78"), ("85.00", "85.00")])
def test_total_del_ride_en_ambos_formatos(total, esperado):
    base = "150220260117900000010011001001000000012123456789"
    clave = next(base[:48] + str(i) for i in range(10) if fa.clave_acceso_valida(base[:48] + str(i)))
    f = fa.factura_desde_texto_ride(f"{clave}\nIdentificación: {CLIENTE}\nVALOR TOTAL   {total}\n")
    assert f.total == D(esperado)


def test_caracter_de_control_no_dana_el_excel(tmp_path, estructura_y_catalogos):
    est, _cat = estructura_y_catalogos
    rep = reporte()
    rep.clientes[0].valores["NRS"] = "CLIENTE\x01 RARO"
    hoja = load_workbook(excel.exportar(rep, est, tmp_path)[0]).worksheets[0]
    assert "CLIENTE RARO" in [c.value for c in hoja[2]]


def test_zip_con_contrasena_se_informa(tmp_path):
    ruta = tmp_path / "c.zip"
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("a.xml", "<a/>")
    b = bytearray(ruta.read_bytes())
    for i in range(len(b) - 3):
        if b[i:i + 4] == b"PK\x03\x04":
            b[i + 6] |= 1
        elif b[i:i + 4] == b"PK\x01\x02":
            b[i + 8] |= 1
    ruta.write_bytes(bytes(b))
    leidos = fa.leer_rutas([ruta])
    assert isinstance(leidos[0], fa.NoLeido) and "contraseña" in leidos[0].motivo


def test_pdf_danado_no_pierde_el_lote(tmp_path):
    malo = tmp_path / "malo.pdf"
    malo.write_bytes(b"%PDF-1.4 esto no es un pdf")
    leidos = fa.leer_rutas([malo])
    assert isinstance(leidos[0], fa.NoLeido)


def test_valor_no_numerico_en_plantilla_no_rompe_la_carga():
    rep = reporte()
    rep.clientes[0].hijos[0].valores["VTO"] = "12-3"
    assert imf.facturas_desde_reporte(rep)[0].total == 0
