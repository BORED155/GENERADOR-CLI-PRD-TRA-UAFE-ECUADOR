"""Controles de edición generados según el tipo de cada campo de la estructura."""

from __future__ import annotations

from PySide6.QtCore import QDate, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox, QCompleter, QDateEdit, QHBoxLayout, QLineEdit, QWidget

from ..estructura import Campo, Catalogos
from ..modelo import entero, texto_mayusculas

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


class ControlTexto(Control):
    def __init__(self, campo: Campo, parent=None):
        super().__init__(campo, parent)
        self.edit = QLineEdit()
        self.edit.setMaxLength(max(campo.maximo, 1))
        self._lay.addWidget(self.edit)
        self.edit.textEdited.connect(lambda _t: self.cambiado.emit())
        self.edit.editingFinished.connect(self._normalizar)

    def _normalizar(self) -> None:
        limpio = texto_mayusculas(self.edit.text())
        if limpio != self.edit.text():
            self.edit.setText(limpio)
            self.cambiado.emit()

    def valor(self) -> str:
        return texto_mayusculas(self.edit.text())

    def poner_valor(self, valor: str) -> None:
        self.edit.setText(valor or "")
        self.edit.setCursorPosition(0)


class ControlNumero(Control):
    def __init__(self, campo: Campo, parent=None):
        super().__init__(campo, parent)
        self.edit = QLineEdit()
        self.edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.edit.setPlaceholderText("0")
        self.edit.setToolTip("Valor entero en dólares. Si escribe decimales se truncan (5.568,60 → 5568).")
        self._lay.addWidget(self.edit)
        self.edit.textEdited.connect(lambda _t: self.cambiado.emit())
        self.edit.editingFinished.connect(self._normalizar)

    def _normalizar(self) -> None:
        limpio = entero(self.edit.text())
        if limpio != self.edit.text():
            self.edit.setText(limpio)
            self.cambiado.emit()

    def valor(self) -> str:
        return entero(self.edit.text())

    def poner_valor(self, valor: str) -> None:
        self.edit.setText(valor or "")


class ControlFecha(Control):
    def __init__(self, campo: Campo, parent=None):
        super().__init__(campo, parent)
        self.edit = QDateEdit()
        self.edit.setCalendarPopup(True)
        self.edit.setDisplayFormat("dd/MM/yyyy")
        self.edit.setMinimumDate(QDate(1900, 1, 1))
        self.edit.setSpecialValueText(" ")
        self.edit.setDate(self.edit.minimumDate())
        self._lay.addWidget(self.edit)
        self.edit.dateChanged.connect(lambda _d: self.cambiado.emit())

    def valor(self) -> str:
        fecha = self.edit.date()
        return "" if fecha == self.edit.minimumDate() else fecha.toString("yyyyMMdd")

    def poner_valor(self, valor: str) -> None:
        fecha = QDate.fromString(valor or "", "yyyyMMdd")
        self.edit.setDate(fecha if fecha.isValid() else self.edit.minimumDate())

    def proponer(self, fecha: QDate) -> None:
        """Al abrir el calendario de una fecha vacía, mostrar el mes del reporte."""
        if self.valor() == "":
            self.edit.calendarWidget().setCurrentPage(fecha.year(), fecha.month())


class ControlCatalogo(Control):
    """Lista desplegable con búsqueda por código o por nombre; guarda solo el código."""

    def __init__(self, campo: Campo, tabla: dict[str, str], extra: dict[str, str] | None = None, parent=None):
        super().__init__(campo, parent)
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.NoInsert)
        self.combo.setMaxVisibleItems(18)
        self.combo.setMinimumContentsLength(28)
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.modelo = QStandardItemModel(self)
        opciones = dict(extra or {})
        opciones.update(tabla)
        self.codigos = list(opciones)
        for codigo in sorted(opciones, key=lambda c: (len(c) > 4, c)):
            item = QStandardItem(f"{codigo}{SEPARADOR}{opciones[codigo]}")
            item.setData(codigo, Qt.UserRole)
            item.setToolTip(opciones[codigo])
            self.modelo.appendRow(item)
        self.combo.setModel(self.modelo)
        filtro = QSortFilterProxyModel(self)
        filtro.setSourceModel(self.modelo)
        filtro.setFilterCaseSensitivity(Qt.CaseInsensitive)
        completer = QCompleter(filtro, self)
        completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.combo.setCompleter(completer)
        self.combo.lineEdit().textEdited.connect(lambda t: filtro.setFilterFixedString(t.split(SEPARADOR)[0]))
        self.combo.lineEdit().setPlaceholderText("Escriba el código o parte del nombre")
        self.combo.setCurrentIndex(-1)
        self._lay.addWidget(self.combo)
        self.combo.currentIndexChanged.connect(lambda _i: self.cambiado.emit())
        self.combo.lineEdit().editingFinished.connect(self._resolver)

    def _resolver(self) -> None:
        """Si escribió un código exacto (o un nombre único) selecciona esa opción."""
        texto = self.combo.currentText().strip()
        codigo = texto.split(SEPARADOR)[0].strip().upper()
        if codigo in self.codigos:
            self.poner_valor(codigo)
            return
        coincidencias = [i for i in range(self.modelo.rowCount())
                         if texto and texto.upper() in self.modelo.item(i).text().upper()]
        if len(coincidencias) == 1:
            self.combo.setCurrentIndex(coincidencias[0])

    def valor(self) -> str:
        i = self.combo.currentIndex()
        if i >= 0 and self.combo.currentText() == self.combo.itemText(i):
            return self.combo.itemData(i, Qt.UserRole)
        return self.combo.currentText().split(SEPARADOR)[0].strip().upper()

    def poner_valor(self, valor: str) -> None:
        for i in range(self.modelo.rowCount()):
            if self.modelo.item(i).data(Qt.UserRole) == valor:
                self.combo.setCurrentIndex(i)
                self.combo.lineEdit().setCursorPosition(0)
                return
        self.combo.setCurrentIndex(-1)
        self.combo.setEditText(valor or "")


def crear_control(campo: Campo, catalogos: Catalogos) -> Control:
    if campo.tiene_catalogo and catalogos.tabla(campo.catalogo):
        extra = {"0": "NO APLICA / SIN TERCERO"} if campo.nombre == "TIT" else None
        tabla = dict(catalogos.tabla(campo.catalogo))
        if campo.catalogo == "TI":
            tabla.pop("X", None)  # «N/A» lo pone el UAFI cuando se escribe 0
        return ControlCatalogo(campo, tabla, extra)
    if campo.es_fecha:
        return ControlFecha(campo)
    if campo.es_numero:
        return ControlNumero(campo)
    return ControlTexto(campo)


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
