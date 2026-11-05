import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from fabrica import CODIGO, reporte
from resuapp import empresas


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_ventana_con_empresa_y_reporte(app, datos, uafi_zip):
    from resuapp.ui.ventana import VentanaPrincipal

    e = empresas.crear("Constructora Prueba", CODIGO, uafi_zip)
    reporte().guardar(e.carpeta_reportes / reporte().nombre_archivo())
    v = VentanaPrincipal()
    v.anio.setValue(2026)
    v.mes.setCurrentIndex(1)
    assert v.empresa is not None and len(v.paneles) == 3
    assert v.paneles[0].modelo.rowCount() == 1
    assert v.paneles[1].modelo.rowCount() == 1 and v.paneles[2].modelo.rowCount() == 1
    assert "Sin errores" in v.totales.text()
    v.reporte.clientes[0].valores["CCC"] = "9999"
    v.cambio(0, 0)
    assert "1 error" in v.totales.text()
    assert v.msj.topLevelItemCount() == 1
    v.close()


def test_editor_transaccion(app, datos, uafi_zip):
    from resuapp.ui.editor import DialogoRegistro

    e = empresas.crear("Constructora Prueba", CODIGO, uafi_zip)
    rep = reporte()
    cli = rep.clientes[0]
    op = cli.hijos[0]
    tx = op.hijos[0]
    d = DialogoRegistro(e, rep, e.estructura.niveles[2], tx, [cli, op], (0, 0, 0), "Editar")
    assert not d.controles["VVT"].isEnabled()
    d.controles["TTR"].poner_valor("92")       # venta: no admite débito
    d._revisar()
    assert not d.controles["VDE"].isEnabled() and d.controles["VCR"].isEnabled()
    d.controles["VEF"].poner_valor("500")
    d._revisar()
    assert d.valores()["VVT"] == "12500"
    assert not d.controles["TIT"].isEnabled()
    d.controles["RPT"].poner_valor("2")
    d._revisar()
    assert d.controles["TIT"].isEnabled() and "obligatorio" in d.aviso.text()
