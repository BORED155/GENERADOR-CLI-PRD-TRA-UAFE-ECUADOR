import datetime as dt
import zipfile

import pytest

from fabrica import CODIGO, cedula_ficticia, cliente, operacion, reporte, transaccion
from resuapp import empresas, excel, uafi
from resuapp.modelo import Reporte, entero, periodo
from resuapp.reglas import validar

HOY = dt.date(2026, 3, 5)


def errores(rep, est_cat):
    est, cat = est_cat
    return [m for m in validar(rep, est, cat, hoy=HOY) if m.es_error]


def test_estructura_del_uafi(estructura_y_catalogos):
    est, cat = estructura_y_catalogos
    assert [n.nombre for n in est.niveles] == ["CLIENTE", "OPERACION", "TRANSACCION"]
    assert est.es_inmobiliaria
    assert [n.prefijo for n in est.niveles] == ["CLI", "OPR", "TRA"]
    assert [c.nombre for c in est.niveles[1].propios][:2] == ["NCT", "VTO"]
    assert cat.contiene("C", "0101") and cat.nombre("TT", "96") == "APORTES"


@pytest.mark.parametrize("texto,esperado", [
    ("5568", "5568"), ("5568.60", "5568"), ("5.568,60", "5568"), ("5,568.99", "5568"), ("$ 12.000", "12000"),
    ("12,000", "12000"), ("0", "0"), ("", ""), ("1500,5", "1500"),
])
def test_entero_trunca(texto, esperado):
    assert entero(texto) == esperado


def test_periodo_ultimo_dia():
    assert periodo(2026, 2) == "20260228"
    assert periodo(2024, 2) == "20240229"
    assert periodo(2026, 12) == "20261231"


def test_reporte_correcto_sin_errores(estructura_y_catalogos):
    assert errores(reporte(), estructura_y_catalogos) == []


def test_errores_tipicos(estructura_y_catalogos):
    rep = reporte(cliente(
        operacion(
            transaccion(TTR="92", VDE="100", VCH="11900", VVT="12000"),          # débito no permitido en venta
            transaccion(NFA="FAC-2", VVT="500"),                                   # total distinto a la suma
            transaccion(NFA="FAC-3", RPT="2"),                                     # terceros sin datos
            transaccion(NFA="FAC-4", FTR="20260130"),                              # fuera del mes
            transaccion(NFA="FAC-5", CAT="123451000"),                             # agencia de otro código
        ),
        operacion(NCT="SIN-PAGOS", VTO="50"),                                       # sin transacciones, VTO corto
        TID="C", IDE="12345", NRS="ABC", CCC="9999",
    ))
    rep.clientes[0].hijos[1].hijos = []
    textos = " | ".join(m.texto for m in errores(rep, estructura_y_catalogos))
    assert "no se usa en «venta bienes inmuebles»" in textos
    assert "distinto de la suma" in textos
    assert textos.count("obligatorio cuando el pago es «de terceros»") == 3
    assert "debe ser del mes que se reporta" in textos
    assert "debe empezar con el código de registro" in textos
    assert "sin transacción" in textos
    assert "entre 3 y 12 dígitos" in textos
    assert "cédula debe tener 10 dígitos" in textos
    assert "debe tener entre 5 y 150" in textos            # NRS: mínimo del manual
    assert "no existe en el catálogo" in textos            # cantón 9999


def test_terceros_con_datos_correctos(estructura_y_catalogos):
    t = transaccion(RPT="2", TIT="C", IDT=cedula_ficticia("170000000"), NRT="TERCERO DE PRUEBA")
    assert errores(reporte(cliente(operacion(t))), estructura_y_catalogos) == []
    t = transaccion(RPT="1", TIT="C", IDT="0", NRT="0")
    assert any("debe ser 0" in m.texto for m in errores(reporte(cliente(operacion(t))), estructura_y_catalogos))


def test_fechas_futuras_y_repetidos(estructura_y_catalogos):
    rep = Reporte(CODIGO, 2026, 3, [cliente(operacion(transaccion(FTR="20260310"), FDO="20260301"))])
    assert any("todavía no termina" in m.texto for m in errores(rep, estructura_y_catalogos))
    rep = reporte(cliente(), cliente())
    assert any("repetida" in m.texto for m in errores(rep, estructura_y_catalogos))


def test_exportar_e_importar(tmp_path, estructura_y_catalogos):
    est, cat = estructura_y_catalogos
    rep = reporte(cliente(operacion(transaccion(), transaccion(NFA="FAC-2", VCH="0", VEF="3000", VVT="3000")),
                          CCC="0101"))
    rutas = excel.exportar(rep, est, tmp_path)
    assert [r.name for r in rutas] == [f"CLI{CODIGO}20260228.xlsx", f"OPR{CODIGO}20260228.xlsx",
                                       f"TRA{CODIGO}20260228.xlsx"]
    with zipfile.ZipFile(rutas[2]) as z:
        hoja = z.read("xl/worksheets/sheet1.xml").decode()
        assert "inlineStr" not in hoja and 't="s"' in hoja  # el UAFI (POI 3.9) necesita sharedStrings
    from openpyxl import load_workbook
    filas = list(load_workbook(rutas[2]).active.iter_rows(values_only=True))
    assert filas[0][:4] == ("TRA", 99999, 20260228, 2)
    assert filas[1][:7] == ("C", cedula_ficticia(), CODIGO, 20260228, "CONTRATO-1", 20260215, "FAC-001")
    clientes = list(load_workbook(rutas[0]).active.iter_rows(values_only=True))
    assert clientes[1][7] == "0101"  # el cantón conserva el cero inicial

    otro, avisos = excel.importar(list(reversed(rutas)), est, cat)
    assert avisos == []
    assert (otro.codigo, otro.anio, otro.mes) == (CODIGO, 2026, 2)
    assert otro.a_dict()["clientes"] == rep.a_dict()["clientes"]


def test_importar_huerfanos_y_cantones_sin_cero(tmp_path, estructura_y_catalogos):
    est, cat = estructura_y_catalogos
    excel.escribir_xlsx(tmp_path / "CLI.xlsx", [["CLI", 99999, 20260228, 1],
                                                ["C", "1711111110", "NOMBRE PRUEBA", "L6810", 0, "ECU",
                                                 "DIRECCION DE PRUEBA", 101, 99999, 20260228]])
    excel.escribir_xlsx(tmp_path / "OPR.xlsx", [["OPR", 99999, 20260228, 1],
                                                ["C", "0000000000", 99999, 20260228, "X1", 1000, 20260201,
                                                 "CAS", 0, "DIRECCION BIEN", 1701, "EC"]])
    excel.escribir_xlsx(tmp_path / "TRA.xlsx", [["TRA", 99999, 20260228, 0]])
    rep, avisos = excel.importar([tmp_path / "CLI.xlsx", tmp_path / "OPR.xlsx", tmp_path / "TRA.xlsx"], est, cat)
    assert rep.clientes[0].get("CCC") == "0101"
    assert any("no se encontró a qué cliente" in a for a in avisos)


def test_empresas_desde_zip(datos, uafi_zip):
    e = empresas.crear("Constructora Prueba S.A.", CODIGO, uafi_zip, usuario="USUARIO01")
    assert e.id == "constructora-prueba-s-a" and e.tiene_uafi
    assert e.agencia_defecto() == "999991000"
    lista = empresas.listar()
    assert [x.nombre for x in lista] == ["Constructora Prueba S.A."]
    assert lista[0].estructura.es_inmobiliaria
    e.recordar_clientes([{"IDE": "123", "NRS": "X", "CDR": CODIGO}])
    assert e.directorio_clientes() == {"123": {"IDE": "123", "NRS": "X"}}
    cmd = uafi.comando(e) if uafi.buscar_java() else None
    if cmd:
        assert cmd[-1] == uafi.CLASE_PRINCIPAL and "-classpath" in cmd
    empresas.eliminar(e)
    assert empresas.listar() == []


def test_zip_que_no_es_uafi(datos, tmp_path):
    malo = tmp_path / "otro.zip"
    with zipfile.ZipFile(malo, "w") as z:
        z.writestr("hola.txt", "x")
    with pytest.raises(FileNotFoundError):
        empresas.crear("Otra", "12345", malo)
    assert empresas.listar() == []


def test_guardar_y_abrir_reporte(tmp_path):
    rep = reporte()
    ruta = tmp_path / rep.nombre_archivo()
    rep.guardar(ruta)
    assert Reporte.abrir(ruta).a_dict() == rep.a_dict()


def test_totales_como_cabecera(estructura_y_catalogos):
    est, _ = estructura_y_catalogos
    rep = reporte(cliente(operacion(transaccion(), transaccion(NFA="FAC-2", VCH="0", VEF="3000", VVT="3000"))))
    t = rep.totales(est)
    assert (t["CLIENTE"], t["OPERACION"], t["TRANSACCION"]) == (1, 1, 2)
    assert (t["VTO"], t["VCH"], t["VEF"], t["VVT"]) == (85000, 12000, 3000, 15000)
