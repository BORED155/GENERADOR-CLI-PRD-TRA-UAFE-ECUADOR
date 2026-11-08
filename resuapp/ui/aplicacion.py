"""Arranque de la interfaz gráfica."""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .. import empresas as emp


def ejecutar(argv: list[str]) -> int:
    app = QApplication(sys.argv[:1] + argv)
    app.setOrganizationName("resuapp")
    app.setApplicationName("Generador RESU UAFE")
    app.setApplicationDisplayName("Generador RESU UAFE")
    import traceback

    from PySide6.QtWidgets import QMessageBox

    def avisar_error(tipo, valor, rastro):
        traceback.print_exception(tipo, valor, rastro)
        QMessageBox.warning(None, "Generador RESU UAFE: algo falló",
                            f"{valor}\n\n" + "".join(traceback.format_exception(tipo, valor, rastro))[-1500:])
    sys.excepthook = avisar_error               # sin esto, un error en la ventana no muestra nada

    from .simple import VentanaSimple

    ventana = VentanaSimple()
    ventana.show()
    if not emp.listar():
        QTimer.singleShot(300, ventana.administrar_empresas)
    return app.exec()
