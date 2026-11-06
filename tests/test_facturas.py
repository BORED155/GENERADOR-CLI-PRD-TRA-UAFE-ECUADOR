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
    v.c_empresa.setCurrentIndex(1)
    v.agregar([str(tmp_path / "f.xml")])
    assert (v.mes, v.anio, len(v.lista)) == (2, 2026, 1)       # cambió solo al mes de la factura
    v.agregar([str(tmp_path / "f.xml")])
    assert len(v.lista) == 1                                    # no se repite
    v2 = VentanaSimple()
    v2.c_empresa.setCurrentIndex(1)
    v2.c_mes.setCurrentIndex(1)
    v2.s_anio.setValue(2026)
    assert len(v2.lista) == 0                                   # cada vez empieza desde cero
    v.close(); v2.close()


# --- datos del RESU por factura ------------------------------------------------------------

def _factura(secuencial="000000123", forma="20", total="1000", cliente=CLIENTE, resu=None):
    f = facturas.Factura("f.xml", ruc_emisor=RUC_EMPRESA, tipo_id_cliente="04", id_cliente=cliente,
                         nombre_cliente="Cliente Ficticio S.A.", direccion_cliente="AV. AMAZONAS Y PATRIA QUITO",
                         estab="001", pto_emi="001", secuencial=secuencial, fecha=dt.date(2026, 2, 15),
                         clave_acceso=clave(secuencial=secuencial), total=Decimal(total),
                         pagos=[(forma, Decimal(total))] if forma else [])
    f.resu = dict(resu or {})
    return f


def test_valores_por_factura_y_su_origen():
    from fabrica import cliente, operacion, reporte, transaccion

    op = imf.Opciones(ttr="103", ttb="OFI", adb="0", instrumento_20="VDE", ccc="1701")
    # sin nada previo: valores por defecto; el cantón, el del cliente
    v = imf.valores_factura(_factura(), op, {}, canton_cliente="0901")
    assert v["ttr"] == ("103", imf.DEFECTO) and v["inst"] == ("VDE", imf.DEFECTO)
    assert v["ttb"] == ("OFI", imf.DEFECTO) and v["cco"] == ("0901", imf.CLIENTE)
    # con un reporte anterior del mismo cliente: se toma lo que se usó entonces
    anterior = reporte(cliente(operacion(transaccion(TTR="96", VCH="12000", VVT="12000"), TTB="DEP", ADB="95",
                                         CCO="1701"), IDE=CLIENTE))
    previos = imf.ultimos_por_cliente([anterior], antes_de="20260331")
    v = imf.valores_factura(_factura(), op, previos, canton_cliente="0901")
    assert v["ttr"] == ("96", imf.ANTERIOR) and v["inst"] == ("VCH", imf.ANTERIOR)
    assert (v["ttb"], v["adb"], v["cco"]) == (("DEP", imf.ANTERIOR), ("95", imf.ANTERIOR), ("1701", imf.ANTERIOR))
    assert imf.ultimos_por_cliente([anterior], antes_de="20260228") == {}   # el del mismo mes no cuenta
    # la forma de pago de la factura manda sobre lo anterior (tarjeta de crédito)
    assert imf.valores_factura(_factura(forma="19"), op, previos)["inst"] == ("VTC", imf.PAGO)
    # lo elegido para la factura manda sobre todo
    v = imf.valores_factura(_factura(forma="19", resu={"inst": "VEF", "ttb": "LOC"}), op, previos)
    assert v["inst"] == ("VEF", imf.FACTURA) and v["ttb"] == ("LOC", imf.FACTURA)
    # varias formas de pago sin elección: se reparte
    f = _factura()
    f.pagos = [("19", Decimal("600")), ("20", Decimal("400"))]
    assert imf.valores_factura(f, op, previos)["inst"] == ("", imf.VARIOS)


def test_cada_factura_con_sus_datos_en_el_reporte(datos, uafi_zip):
    e = empresas.crear("Constructora Prueba", CODIGO, uafi_zip, ruc=RUC_EMPRESA)
    op = imf.Opciones(ttr="96", ttb="DEP", adb="0", instrumento_20="VDE", aec="L6810", ccc="1701")
    a = _factura("000000001", total="1000")                                  # por defecto
    b = _factura("000000002", total="2500", resu={"ttr": "94", "inst": "VCH", "ttb": "LOC", "adb": "120",
                                                   "cco": "0901"})           # elegido para esta factura
    rep, _ = imf.construir_reporte(e, 2026, 2, [a, b], op)
    ops = {o.get("NCT"): o for c in rep.clientes for o in c.hijos}
    oa, ob = ops["001-001-000000001"], ops["001-001-000000002"]
    assert (oa.get("TTB"), oa.get("ADB"), oa.get("CCO"), oa.hijos[0].get("TTR"), oa.hijos[0].get("VDE")) == \
        ("DEP", "0", "1701", "96", "1000")
    assert (ob.get("TTB"), ob.get("ADB"), ob.get("CCO"), ob.hijos[0].get("TTR"), ob.hijos[0].get("VCH"),
            ob.hijos[0].get("VDE")) == ("LOC", "120", "0901", "94", "2500", "0")
    assert len(rep.clientes) == 1   # mismo cliente: una sola ficha, dos operaciones
    # las elecciones se guardan con la lista del mes
    assert imf.factura_de_dict(imf.factura_a_dict(b)).resu == b.resu


def test_ventana_datos_por_factura(datos, uafi_zip, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    from resuapp.ui import simple
    from resuapp.ui.simple import VentanaSimple

    empresas.crear("Constructora Prueba", CODIGO, uafi_zip, ruc=RUC_EMPRESA)
    v = VentanaSimple()
    v.c_empresa.setCurrentIndex(1)
    v.c_mes.setCurrentIndex(1)
    v.s_anio.setValue(2026)
    v.lista = [_factura("000000001"), _factura("000000002"), _factura("000000003", cliente="1799999923001")]
    v._mostrar_lista()
    ttb_defecto = v.tabla.item(0, simple.C_TTB).data(simple.Qt.UserRole)
    assert v.tabla.item(0, simple.C_TTB).font().italic()            # por defecto: en cursiva
    # cambiar el tipo de bien de una sola factura
    v.cambiar_campo(0, "ttb", "LOC")
    assert v.tabla.item(0, simple.C_TTB).data(simple.Qt.UserRole) == "LOC"
    assert not v.tabla.item(0, simple.C_TTB).font().italic()
    assert v.tabla.item(1, simple.C_TTB).data(simple.Qt.UserRole) == ttb_defecto
    # con dos filas seleccionadas, el cambio va a las dos
    v.tabla.clearSelection()
    for r in (1, 2):
        v.tabla.selectionModel().select(v.tabla.model().index(r, simple.C_ADB),
                                        simple.QItemSelectionModel.Select | simple.QItemSelectionModel.Rows)
    v.cambiar_campo(1, "adb", "150")
    assert [v.tabla.item(r, simple.C_ADB).text() for r in range(3)][1:] == ["150", "150"]
    # aplicar a todas las facturas del mismo cliente
    v.aplicar_al_cliente(0, "ttb")
    assert [f.resu.get("ttb") for f in v.lista[:2]] == ["LOC", "LOC"] and "ttb" not in v.lista[2].resu
    # volver al automático
    v.volver_automatico([0], "ttb")
    assert "ttb" not in v.lista[0].resu
    v.close()


def test_lista_de_cantones(datos, uafi_zip):
    from PySide6.QtWidgets import QApplication

    from resuapp.ui.campos import ComboCanton

    app = QApplication.instance() or QApplication([])
    tabla = {"0000": "N/A", "1701": "QUITO", "0901": "GUAYAQUIL", "0402": "BOLIVAR", "1302": "BOLIVAR"}
    c = ComboCanton(tabla)
    textos = [c.itemText(i) for i in range(c.count())]
    assert textos == ["BOLIVAR (CARCHI) — 0402", "BOLIVAR (MANABÍ) — 1302", "GUAYAQUIL (GUAYAS) — 0901",
                      "QUITO (PICHINCHA) — 1701"]                     # todos, por nombre, sin «N/A»
    c.poner_valor("1302")
    assert c.valor() == "1302"
    c.setEditText("quito")                                            # escribir filtra y resuelve
    assert c.valor() == "1701"
    c.setEditText("bolivar")                                          # dos coincidencias: hay que elegir
    assert c.valor() == ""


def test_flechita_lista_y_doble_clic_escribir(datos, uafi_zip, monkeypatch):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QComboBox, QMessageBox

    from resuapp.ui import simple
    from resuapp.ui.campos import ControlBuscador

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    empresas.crear("Constructora Prueba", CODIGO, uafi_zip, ruc=RUC_EMPRESA)
    v = simple.VentanaSimple()
    v.c_empresa.setCurrentIndex(1)
    v.resize(1400, 600)
    v.show()
    v.c_mes.setCurrentIndex(1)
    v.s_anio.setValue(2026)
    v.lista = [_factura("000000001")]
    v._mostrar_lista()
    app.processEvents()
    t = v.tabla
    # clic en la flechita del pago: se abre la lista
    r = t.visualRect(t.model().index(0, simple.C_INST))
    QTest.mouseClick(t.viewport(), Qt.LeftButton, pos=QPoint(r.right() - 6, r.center().y()))
    editor = t.indexWidget(t.model().index(0, simple.C_INST)) or t.focusWidget()
    combo = editor if isinstance(editor, QComboBox) else editor.findChild(QComboBox)
    assert combo is not None and combo.count() == len(v.opciones_campo("inst"))
    combo.hidePopup()
    combo.setCurrentIndex(combo.findData("VDE"))
    combo.activated.emit(combo.currentIndex())
    app.processEvents()
    assert v.lista[0].resu["inst"] == "VDE"
    # doble clic en el cantón: se escribe para buscar (por provincia, sin tildes)
    v._doble_clic(0, simple.C_CCO)
    app.processEvents()
    buscador = t.focusWidget()
    while buscador is not None and not isinstance(buscador, ControlBuscador):
        buscador = buscador.parentWidget()
    assert isinstance(buscador, ControlBuscador)
    assert any("PORTOVIEJO (MANABÍ)" in x for x in buscador.coincidencias("portoviejo manabi")) or \
        not v.empresa.catalogos.tabla("C").get("1301")   # el catálogo de prueba puede no traerlo
    v.close()


def test_datos_de_la_empresa_se_copian(datos, uafi_zip):
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from resuapp.ui import simple

    app = QApplication.instance() or QApplication([])
    e = empresas.crear("Constructora Prueba", CODIGO, uafi_zip, ruc=RUC_EMPRESA)
    e.usuario = "PRUE1234"
    e.agencia = CODIGO + "1000"
    e.guardar()
    v = simple.VentanaSimple()
    v.c_empresa.setCurrentIndex(1)
    d = v.datos_empresa
    assert (d["nombre"].text(), d["ruc"].text(), d["codigo"].text(), d["usuario"].text(), d["agencia"].text()) == \
        ("Constructora Prueba", RUC_EMPRESA, CODIGO, "PRUE1234", CODIGO + "1000")
    QTest.mouseDClick(d["usuario"], simple.Qt.LeftButton)
    assert QGuiApplication.clipboard().text() == "PRUE1234"
    QTest.mouseDClick(d["ruc"], simple.Qt.LeftButton)
    assert QGuiApplication.clipboard().text() == RUC_EMPRESA
    assert not hasattr(v, "controles")          # ya no hay cuadro de valores por defecto
    v.close()


def test_abre_limpia_y_ayuda(datos, uafi_zip):
    from PySide6.QtWidgets import QApplication

    from resuapp.ui import simple

    app = QApplication.instance() or QApplication([])
    empresas.crear("Constructora Prueba", CODIGO, uafi_zip, ruc=RUC_EMPRESA)
    v = simple.VentanaSimple()
    v.c_empresa.setCurrentIndex(1)
    v.c_mes.setCurrentIndex(1)
    v.s_anio.setValue(2026)
    v.lista = [_factura("000000001")]
    v.close()
    # al volver a abrir: sin empresa, tabla vacía y botones desactivados
    v2 = simple.VentanaSimple()
    assert v2.c_empresa.currentIndex() == 0 and v2.empresa is None
    assert v2.tabla.rowCount() == 0 and not v2.b_generar.isEnabled()
    assert v2.datos_empresa["ruc"].text() == "—"
    # al elegir la empresa y el mes, también empieza vacía
    v2.c_empresa.setCurrentIndex(1)
    v2.c_mes.setCurrentIndex(1)
    v2.s_anio.setValue(2026)
    assert v2.tabla.rowCount() == 0
    assert "Flechita" in simple.AYUDA and "Generar Excel" in simple.AYUDA
    v2.close()



# --- plantillas CLI, OPR y TRA -------------------------------------------------------------

def _plantillas(e, carpeta, **cambio_tra):
    """Genera plantillas de febrero 2026 con 3 operaciones (2 clientes) y, si se pide, cambia un dato del TRA."""
    from openpyxl import load_workbook

    from resuapp import excel

    op = imf.Opciones(ttr="96", ttb="DEP", adb="0", instrumento_20="VDE", aec="L6810", ccc="1701")
    lista = [_factura("000000001", total="1000"),
             _factura("000000002", total="2500", resu={"ttr": "94", "inst": "VCH", "ttb": "CAS", "adb": "120"}),
             _factura("000000003", total="800", cliente="1799999923001")]
    rep, _ = imf.construir_reporte(e, 2026, 2, lista, op)
    rutas = excel.exportar(rep, e.estructura, carpeta)
    if cambio_tra:
        tra = next(r for r in rutas if r.name.upper().startswith("TRA"))
        libro = load_workbook(tra)
        hoja = libro.worksheets[0]
        nombres = [n.nombre for n in e.estructura.niveles[2].campos]
        for campo, valor in cambio_tra.items():   # fila 2 = primera transacción (pagada con débito)
            hoja.cell(row=2, column=nombres.index(campo) + 1, value=valor)
        libro.save(tra)
    return rep, rutas


def test_plantillas_correctas_se_cargan_y_se_regeneran_igual(datos, uafi_zip, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    from resuapp.ui import simple

    app = QApplication.instance() or QApplication([])
    avisos = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: avisos.append(a[2])))
    e = empresas.crear("Constructora Prueba", CODIGO, uafi_zip, ruc=RUC_EMPRESA)
    original, rutas = _plantillas(e, tmp_path)
    v = simple.VentanaSimple()                     # sin empresa: la elige sola por el código
    assert v.importar_plantillas([str(r) for r in reversed(rutas)])   # en cualquier orden
    assert v.empresa.id == e.id and (v.mes, v.anio) == (2, 2026)
    assert v.tabla.rowCount() == 3 and v.ultima_revision == []
    assert "sin errores" in avisos[-1]
    # al generar otra vez sin cambiar nada, sale igual a las plantillas
    nuevo, _ = imf.construir_reporte(v.empresa, 2026, 2, v.lista, v._opciones(), v.anteriores)
    def plano(rep):
        return sorted((c.get("IDE"), o.get("NCT"), tuple(sorted(o.valores.items())),
                       tuple(tuple(sorted(t.valores.items())) for t in o.hijos))
                      for c in rep.clientes for o in c.hijos)
    assert plano(nuevo) == plano(original)
    # un cambio en la tabla se refleja solo en esa operación
    v.cambiar_campo(0, "ttb", "CAS")
    nuevo, _ = imf.construir_reporte(v.empresa, 2026, 2, v.lista, v._opciones(), v.anteriores)
    assert sorted(o.get("TTB") for c in nuevo.clientes for o in c.hijos) == ["CAS", "CAS", "DEP"]
    v.close()


def test_plantillas_con_errores_se_avisan(datos, uafi_zip, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from resuapp.ui import simple

    app = QApplication.instance() or QApplication([])
    e = empresas.crear("Constructora Prueba", CODIGO, uafi_zip, ruc=RUC_EMPRESA)
    _rep, rutas = _plantillas(e, tmp_path, TTR="92")   # venta pagada con débito: no lo admite el manual
    vistos = []
    monkeypatch.setattr(simple.VentanaSimple, "_confirmar_problemas",
                        lambda self, resumen, problemas: vistos.extend(problemas) or False)
    v = simple.VentanaSimple()
    assert not v.importar_plantillas([str(r) for r in rutas])
    assert any("tabla 2 del manual" in p and "001-001-000000001" in p for p in vistos), vistos
    assert v.tabla.rowCount() == 0                         # «No cargar»
    # faltan plantillas
    vistos.clear()
    assert not v.importar_plantillas([str(rutas[0])])
    assert any("Falta la plantilla" in p for p in vistos)
    v.close()


def test_boton_validar(datos, uafi_zip, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    from resuapp.ui import simple

    app = QApplication.instance() or QApplication([])
    informes, avisos = [], []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: informes.append(a[2])))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: avisos.append(self.text()) or 0)
    e = empresas.crear("Constructora Prueba", CODIGO, uafi_zip, ruc=RUC_EMPRESA)
    e.agencia = CODIGO + "1000"
    e.guardar()
    e.recordar_clientes([{"IDE": CLIENTE, "TID": "R", "NRS": "CLIENTE FICTICIO S.A.", "AEC": "L6810"}])
    v = simple.VentanaSimple()
    v.c_empresa.setCurrentIndex(1)
    v.c_mes.setCurrentIndex(1)
    v.s_anio.setValue(2026)
    assert not v.b_validar.isEnabled()                       # sin facturas no hay qué validar
    v.lista = [_factura("000000001", total="1000"), _factura("000000002", total="50")]   # 50 < mínimo 100
    v._mostrar_lista()
    v.validar_tabla()
    assert avisos and "problema" in avisos[-1] and "000000002" in avisos[-1]
    malo = next(r for r in range(2) if v.lista[r].numero.endswith("2"))
    assert v.tabla.item(malo, simple.C_FACT).background().color().name() == "#f8d7da"
    assert v.tabla.item(1 - malo, simple.C_FACT).background().style() == simple.Qt.NoBrush
    # al cambiar algo, las marcas se quitan hasta volver a validar
    v.cambiar_campo(0, "adb", "10")
    assert v.tabla.item(malo, simple.C_FACT).background().style() == simple.Qt.NoBrush
    # sin la factura mala: listo para generar
    del v.lista[malo]
    v._mostrar_lista()
    v.validar_tabla()
    assert "Listo para generar" in informes[-1]
    v.close()
