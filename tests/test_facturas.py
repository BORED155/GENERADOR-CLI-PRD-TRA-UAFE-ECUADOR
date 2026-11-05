import datetime as dt
from decimal import Decimal

from fabrica import CODIGO
from resuapp import empresas, facturas, importar_facturas as imf, reglas
from resuapp.modelo import Reporte

RUC_EMPRESA = "1799999907001"
CLIENTE = "1799999915001"


def clave(fecha="15022026", tipo="01", ruc=RUC_EMPRESA, secuencial="000000123"):
    base = f"{fecha}{tipo}{ruc}2001001{secuencial}123456781"
    suma, factor = 0, 2
    for d in reversed(base):
        suma += int(d) * factor
        factor = 2 if factor == 7 else factor + 1
    dv = {11: 0, 10: 1}.get(11 - suma % 11, 11 - suma % 11)
    return base + str(dv)


def xml_factura(total="12500.75", pagos=(("20", "12500.75"),), cliente=CLIENTE, direccion="AV. AMAZONAS Y PATRIA QUITO"):
    pag = "".join(f"<pago><formaPago>{c}</formaPago><total>{v}</total></pago>" for c, v in pagos)
    interno = (f"<factura id='comprobante'><infoTributaria><ambiente>2</ambiente><razonSocial>EMPRESA</razonSocial>"
               f"<ruc>{RUC_EMPRESA}</ruc><claveAcceso>{clave()}</claveAcceso><codDoc>01</codDoc><estab>001</estab>"
               f"<ptoEmi>001</ptoEmi><secuencial>000000123</secuencial></infoTributaria><infoFactura>"
               f"<fechaEmision>15/02/2026</fechaEmision><tipoIdentificacionComprador>04</tipoIdentificacionComprador>"
               f"<razonSocialComprador>Cliente  Ficticio S.A.</razonSocialComprador>"
               f"<identificacionComprador>{cliente}</identificacionComprador>"
               f"<direccionComprador>{direccion}</direccionComprador>"
               f"<importeTotal>{total}</importeTotal><pagos>{pag}</pagos></infoFactura></factura>")
    return (f"<autorizacion><estado>AUTORIZADO</estado><numeroAutorizacion>{clave()}</numeroAutorizacion>"
            f"<comprobante><![CDATA[{interno}]]></comprobante></autorizacion>").encode()


def test_clave_acceso():
    assert facturas.clave_acceso_valida(clave())
    assert not facturas.clave_acceso_valida(clave()[:-1] + "0") or clave()[-1] == "0"


def test_leer_xml_txt_y_ride(tmp_path):
    f = facturas.leer_xml(xml_factura(pagos=(("20", "10000.00"), ("19", "2500.75"))), "f.xml")
    assert (f.tipo, f.id_cliente, f.numero, f.fecha, f.total) == ("01", CLIENTE, "001-001-000000123",
                                                                 dt.date(2026, 2, 15), Decimal("12500.75"))
    assert f.pagos == [("20", Decimal("10000.00")), ("19", Decimal("2500.75"))]
    assert f.direccion_cliente == "AV. AMAZONAS Y PATRIA QUITO"
    txt = tmp_path / "ComprobantesElectronicos.txt"
    txt.write_text("FECHA_EMISION\tCOMPROBANTE\tNUMERO_COMPROBANTE\tIDENTIFICACION_RECEPTOR\tRAZON_SOCIAL\t"
                   f"CLAVE_ACCESO\tVALOR_TOTAL\n15/02/2026\tFactura\t001-001-000000123\t{CLIENTE}\tCLIENTE SA\t"
                   f"{clave()}\t1265\n01/02/2026\tFactura\tx\t1\tx\t123\t5\n", "latin-1")
    leidos = facturas.leer_rutas([txt])
    assert isinstance(leidos[0], facturas.Factura) and leidos[0].total == Decimal("1265")
    assert isinstance(leidos[1], facturas.NoLeido)
    ride = (f"FACTURA\nNo. 001-001-000000123\n{clave()}\nRazón Social / Nombres y Apellidos:   CLIENTE SA\n"
            f"Identificación   {CLIENTE}\nDireccion:   CALLE FICTICIA 123 Y OTRA\n"
            "20 - OTROS CON UTILIZACION DEL SISTEMA   1811.25\nVALOR TOTAL   1811.25\n")
    r = facturas.factura_desde_texto_ride(ride, "r.pdf")
    assert (r.id_cliente, r.direccion_cliente, r.total, r.pagos) == (
        CLIENTE, "CALLE FICTICIA 123 Y OTRA", Decimal("1811.25"), [("20", Decimal("1811.25"))])


def test_canton_por_direccion(estructura_y_catalogos):
    _, cat = estructura_y_catalogos
    assert imf.canton_por_direccion("PICHINCHA / QUITO / AV. 6 DE DICIEMBRE", cat.tabla("C")) == "1701"
    assert imf.canton_por_direccion("AV. SIN CIUDAD 123", cat.tabla("C")) == ""


def test_de_factura_a_reporte_valido(datos, uafi_zip, tmp_path):
    e = empresas.crear("Constructora Prueba", CODIGO, uafi_zip, ruc=RUC_EMPRESA)
    rep = Reporte(CODIGO, 2026, 2)
    leidos = [facturas.leer_xml(xml_factura(pagos=(("20", "10000.00"), ("19", "2500.75"))), "f.xml"),
              facturas.leer_xml(xml_factura(), "repetida.xml")]
    op = imf.Opciones(ttr="96", ttb="DEP", adb="80", instrumento_20="VDE")
    props = imf.analizar(leidos, e, rep, op)
    assert [p.estado for p in props] == [imf.AVISO, imf.OMITIR]           # falta actividad económica
    assert "Repetida" in props[1].texto
    assert props[0].cliente["CCC"] == "1701" and props[0].cliente["TID"] == "R"
    assert imf.aplicar(rep, props, e, op) == 1
    cli = rep.clientes[0]
    tx = cli.hijos[0].hijos[0]
    assert cli.hijos[0].get("NCT") == "001-001-000000123" and cli.hijos[0].get("VTO") == "12500"
    assert (tx.get("VDE"), tx.get("VTC"), tx.get("VVT"), tx.get("TTR")) == ("10000", "2500", "12500", "96")
    errores = [m for m in reglas.validar(rep, e.estructura, e.catalogos, hoy=dt.date(2026, 3, 5)) if m.es_error]
    assert [m.campo for m in errores] == ["AEC"]
    cli.valores["AEC"] = "F4100"
    assert not [m for m in reglas.validar(rep, e.estructura, e.catalogos, hoy=dt.date(2026, 3, 5)) if m.es_error]
    # la próxima vez el cliente sale completo desde el directorio, y lo que ya está no se repite
    e.recordar_clientes([cli.valores])
    props = imf.analizar([facturas.leer_xml(xml_factura(), "f.xml")], e, Reporte(CODIGO, 2026, 2), op)
    assert props[0].estado == imf.LISTA
    assert imf.analizar([leidos[0]], e, rep, op)[0].texto == "Ya está en el reporte"


def test_facturas_que_no_se_importan(datos, uafi_zip):
    e = empresas.crear("Constructora Prueba", CODIGO, uafi_zip, ruc=RUC_EMPRESA)
    rep = Reporte(CODIGO, 2026, 3)
    props = imf.analizar([facturas.leer_xml(xml_factura(), "f.xml")], e, rep, imf.Opciones())
    assert "otro mes" in props[0].texto
    rep = Reporte(CODIGO, 2026, 2)
    cf = facturas.leer_xml(xml_factura(cliente="9999999999999"), "cf.xml")
    otra = facturas.leer_xml(xml_factura(), "compra.xml")
    otra.ruc_emisor = "1790000000001"
    textos = [p.texto for p in imf.analizar([cf, otra], e, rep, imf.Opciones())]
    assert "Consumidor final" in textos[0] and "¿es una compra?" in textos[1]


def test_instrumento_no_permitido(datos, uafi_zip):
    e = empresas.crear("Constructora Prueba", CODIGO, uafi_zip, ruc=RUC_EMPRESA)
    op = imf.Opciones(ttr="92", instrumento_20="VDE")    # venta: no admite débito
    p = imf.analizar([facturas.leer_xml(xml_factura(), "f.xml")], e, Reporte(CODIGO, 2026, 2), op)[0]
    assert "no admite pago con débito" in p.texto


def test_reporte_completo_sin_pedir_datos(datos, uafi_zip, tmp_path):
    """Modo simple: con los valores por defecto el reporte sale sin errores y en las plantillas oficiales."""
    import zipfile

    from resuapp import excel

    e = empresas.crear("Constructora Prueba", CODIGO, uafi_zip, ruc=RUC_EMPRESA)
    sin_direccion = facturas.leer_xml(xml_factura(direccion=""), "f.xml")
    op = imf.Opciones(ttr="96", ttb="DEP", adb="0", instrumento_20="VDE", aec="L6810", ccc="1701")
    rep, _ = imf.construir_reporte(e, 2026, 2, [sin_direccion], op)
    cli = rep.clientes[0]
    assert (cli.get("AEC"), cli.get("CCC"), cli.get("DIR"), cli.get("NAC")) == ("L6810", "1701", "QUITO - ECUADOR", "ECU")
    assert cli.hijos[0].get("DRB") == "QUITO - ECUADOR"
    assert "AEC" not in e.directorio_clientes().get(CLIENTE, {})   # el valor por defecto no se guarda como propio
    assert not [m for m in reglas.validar(rep, e.estructura, e.catalogos, hoy=dt.date(2026, 3, 5)) if m.es_error]
    rutas = excel.exportar(rep, e.estructura, tmp_path)
    with zipfile.ZipFile(rutas[0]) as z:
        assert "xl/printerSettings/printerSettings1.bin" in z.namelist()   # viene de la plantilla oficial
        assert b"<cp:lastModifiedBy></cp:lastModifiedBy>" in z.read("docProps/core.xml")   # sin datos de autor
    # las facturas se guardan y se recuperan igual
    assert imf.factura_a_dict(imf.factura_de_dict(imf.factura_a_dict(sin_direccion))) == imf.factura_a_dict(sin_direccion)


def test_ventana_simple(datos, uafi_zip, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    from resuapp.ui.simple import VentanaSimple

    empresas.crear("Constructora Prueba", CODIGO, uafi_zip, ruc=RUC_EMPRESA)
    (tmp_path / "f.xml").write_bytes(xml_factura())
    v = VentanaSimple()
    v.agregar([str(tmp_path / "f.xml")])
    assert (v.mes, v.anio, len(v.lista)) == (2, 2026, 1)       # cambió solo al mes de la factura
    v.agregar([str(tmp_path / "f.xml")])
    assert len(v.lista) == 1                                    # no se repite
    v2 = VentanaSimple()
    v2.c_mes.setCurrentIndex(1)
    v2.s_anio.setValue(2026)
    assert len(v2.lista) == 1                                   # la lista del mes queda guardada
    v.close(); v2.close()
