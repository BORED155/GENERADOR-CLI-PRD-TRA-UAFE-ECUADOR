"""Controles de edición generados según el tipo de cada campo de la estructura."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCompleter, QHBoxLayout, QLineEdit, QWidget

from ..estructura import Campo

SEPARADOR = " — "


class Control(QWidget):
    """Interfaz común: valor(), poner_valor(). Emite `cambiado` al editar."""

    cambiado = Signal()

    def __init__(self, campo: Campo, parent=None):
        super().__init__(parent)
        self.campo = campo
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)

    def valor(self) -> str:
        raise NotImplementedError

    def poner_valor(self, valor: str) -> None:
        raise NotImplementedError


def _normal(texto: str) -> str:
    import unicodedata

    sin = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return " ".join(sin.upper().split())


class ControlBuscador(Control):
    """Campo de texto que filtra un catálogo mientras se escribe.

    Busca por código o por cualquier parte del nombre, sin importar tildes, mayúsculas ni el orden de
    las palabras («construccion edificios» encuentra «CONSTRUCCIÓN DE EDIFICIOS…»). Guarda el código.
    """

    MAXIMO = 300

    def __init__(self, campo: Campo | None, tabla: dict[str, str], ayuda: str = "", parent=None):
        from PySide6.QtCore import QStringListModel

        super().__init__(campo, parent)
        self.tabla = tabla
        self.opciones = [(codigo, f"{codigo}{SEPARADOR}{nombre}", _normal(f"{codigo} {nombre}"))
                         for codigo, nombre in sorted(tabla.items(), key=lambda kv: (len(kv[0]) > 4, kv[0]))]
        self.por_texto = {texto: codigo for codigo, texto, _n in self.opciones}
        self.codigo = ""
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(ayuda or "Escriba parte del nombre o el código…")
        self.edit.setClearButtonEnabled(True)
        self.modelo = QStringListModel(self)
        self.completer = QCompleter(self.modelo, self)
        self.completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self.completer.setMaxVisibleItems(14)
        self.completer.setWidget(self.edit)
        self.completer.activated.connect(self._elegido)
        self._lay.addWidget(self.edit)
        self.setFocusProxy(self.edit)
        self.edit.textEdited.connect(self._filtrar)
        self.edit.editingFinished.connect(self._resolver)

    def coincidencias(self, texto: str) -> list[str]:
        palabras = _normal(texto).split()
        if not palabras:
            return [t for _c, t, _n in self.opciones[:self.MAXIMO]]
        salida = [t for _c, t, n in self.opciones if all(p in n for p in palabras)]
        # primero las que empiezan con lo escrito (p. ej. un código)
        salida.sort(key=lambda t: not _normal(t).startswith(palabras[0]))
        return salida[:self.MAXIMO]

    def _filtrar(self, texto: str) -> None:
        self.codigo = ""
        self.modelo.setStringList(self.coincidencias(texto))
        if self.modelo.rowCount():
            self.completer.popup().setMinimumWidth(max(self.edit.width(), 520))
            self.completer.complete()
        else:
            self.completer.popup().hide()
        self.cambiado.emit()

    def _elegido(self, texto: str) -> None:
        self.poner_valor(self.por_texto.get(texto, ""))
        self.cambiado.emit()

    def _resolver(self) -> None:
        """Al salir del campo: si quedó un código exacto o una sola coincidencia, la toma."""
        if self.codigo:
            return
        texto = self.edit.text().strip()
        codigo = texto.split(SEPARADOR)[0].strip().upper()
        if codigo in self.tabla:
            self.poner_valor(codigo)
            return
        lista = self.coincidencias(texto) if texto else []
        if len(lista) == 1:
            self.poner_valor(self.por_texto[lista[0]])

    def valor(self) -> str:
        return self.codigo

    def poner_valor(self, valor: str) -> None:
        self.codigo = valor if valor in self.tabla else ""
        self.edit.setText(f"{valor}{SEPARADOR}{self.tabla[valor]}" if self.codigo else "")
        self.edit.setCursorPosition(0)
        self.edit.setToolTip(self.edit.text())


# Provincias del Ecuador (dos primeros dígitos del código de cantón, codificación del INEC).
