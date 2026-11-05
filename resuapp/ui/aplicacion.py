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
    from .simple import VentanaSimple

    ventana = VentanaSimple()
    ventana.show()
    if not emp.listar():
        QTimer.singleShot(300, ventana.administrar_empresas)
    return app.exec()
