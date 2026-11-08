import pytest
import sys
import time

from resuapp import reparar_uaf

# El programa solo hace esta corrección fuera de Windows: allí «\\» sí separa carpetas y no se puede crear ese archivo.
pytestmark = pytest.mark.skipif(sys.platform.startswith("win"), reason="solo Linux y Mac")


def test_corrige_nombre_de_windows(tmp_path):
    (tmp_path / "prueb" / "mi carpeta").mkdir(parents=True)
    malo = tmp_path / "prueb" / "mi carpeta\\RESU9999920260831.uaf"
    malo.write_bytes(b"contenido")
    otro = tmp_path / "prueb" / "RESU9999820261031.uaf"          # bien guardado: no se toca
    otro.write_bytes(b"ok")
    cambios = reparar_uaf.reparar_todo([tmp_path], desde=time.time() - 60)
    final = tmp_path / "prueb" / "mi carpeta" / "RESU9999920260831.uaf"
    assert cambios == [(malo, final)]
    assert final.read_bytes() == b"contenido" and not malo.exists() and otro.exists()


def test_carpeta_inexistente_y_repetidos(tmp_path):
    a = tmp_path / "x\\y\\RESU1.uaf"
    a.write_bytes(b"1")
    assert reparar_uaf.reparar(a) == tmp_path / "x" / "y" / "RESU1.uaf"   # crea las carpetas
    b = tmp_path / "x\\y\\RESU1.uaf"
    b.write_bytes(b"2")                                                  # mismo nombre, otro contenido
    assert reparar_uaf.reparar(b).name == "RESU1 (2).uaf"
    c = tmp_path / "x\\y\\RESU1.uaf"
    c.write_bytes(b"1")                                                  # idéntico: no se duplica
    assert reparar_uaf.reparar(c).name == "RESU1.uaf" and not c.exists()


def test_solo_los_recientes(tmp_path):
    viejo = tmp_path / "a\\RESU.uaf"
    viejo.write_bytes(b"v")
    assert reparar_uaf.candidatos([tmp_path], desde=time.time() + 60) == []


def test_ventana_vigila_y_corrige(datos, uafi_zip, tmp_path, monkeypatch):
    """Simula el UAFI: mientras está abierto guarda «carpeta\\RESU….uaf» y la app lo corrige."""
    from pathlib import Path

    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from resuapp import empresas
    from resuapp.ui import simple

    app = QApplication.instance() or QApplication([])
    avisos = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: avisos.append(a[2])))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    class UafiFalso:
        def __init__(self):
            self.abierto = True

        def poll(self):
            return None if self.abierto else 0

    proceso = UafiFalso()
    monkeypatch.setattr(simple.uafi, "abrir", lambda e: proceso)
    empresas.crear("Constructora Prueba", "99999", uafi_zip, ruc="1799999907001")
    v = simple.VentanaSimple()
    v.c_empresa.setCurrentIndex(1)
    v.abrir_uafi()
    (tmp_path / "Descargas" / "mi carpeta").mkdir(parents=True)
    (tmp_path / "Descargas" / "mi carpeta\\RESU9999920260831.uaf").write_bytes(b"uaf")
    proceso.abierto = False
    fin = QEventLoop()
    QTimer.singleShot(7000, fin.quit)
    fin.exec()
    assert (tmp_path / "Descargas" / "mi carpeta" / "RESU9999920260831.uaf").read_bytes() == b"uaf"
    assert avisos and "Se corrigió" in avisos[0]
    v.close()
