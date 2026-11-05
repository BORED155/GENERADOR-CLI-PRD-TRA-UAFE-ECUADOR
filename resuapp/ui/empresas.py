"""Administración de empresas y de sus aplicativos UAFI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout)

from .. import empresas as emp
from .. import uafi
from ..modelo import texto_mayusculas


class DialogoEmpresa(QDialog):
    """Datos de una empresa. Al crearla pide además su uafi.zip."""

    def __init__(self, empresa: emp.Empresa | None = None, parent=None):
        super().__init__(parent)
        self.empresa = empresa
        self.setWindowTitle("Nueva empresa" if empresa is None else f"Empresa: {empresa.nombre}")
        self.setMinimumWidth(560)
        self.nombre = QLineEdit(empresa.nombre if empresa else "")
        self.codigo = QLineEdit(empresa.codigo if empresa else "")
        self.codigo.setMaxLength(5)
        self.codigo.setPlaceholderText("4 o 5 dígitos (aparece en el nombre de las plantillas y del .uaf)")
        self.ruc = QLineEdit(empresa.ruc if empresa else "")
        self.ruc.setMaxLength(13)
        self.usuario = QLineEdit(empresa.usuario if empresa else "")
        self.usuario.setPlaceholderText("Usuario del oficial de cumplimiento en el SISLAFT")
        self.agencia = QLineEdit(empresa.agencia if empresa else "")
        self.agencia.setMaxLength(9)
        self.agencia.setPlaceholderText("Ej.: código + 1000")
        self.codigo.textEdited.connect(self._proponer_agencia)
        self.ruta_uafi = QLineEdit()
        self.ruta_uafi.setPlaceholderText("uafi.zip descargado del SISLAFT (o su carpeta descomprimida)")
        elegir = QPushButton("Elegir…")
        elegir.clicked.connect(self._elegir_uafi)
        fila_uafi = QHBoxLayout()
        fila_uafi.addWidget(self.ruta_uafi, 1)
        fila_uafi.addWidget(elegir)

        form = QFormLayout()
        form.addRow("Nombre de la empresa:", self.nombre)
        form.addRow("Código de registro UAFE:", self.codigo)
        form.addRow("RUC:", self.ruc)
        form.addRow("Usuario SISLAFT:", self.usuario)
        form.addRow("Código de agencia:", self.agencia)
        form.addRow("Aplicativo UAFI:" if empresa is None else "Reemplazar UAFI:", fila_uafi)
        nota = QLabel("El UAFI es personal de cada empresa: descárguelo del SISLAFT en "
                      "<i>Reporte RESU → Estructuras → UAFI</i>. El programa toma de él la estructura y los "
                      "catálogos del sector, y lo abre cuando haya que generar el archivo .uaf.")
        nota.setWordWrap(True)
        nota.setTextFormat(Qt.RichText)
        self.aviso = QLabel()
        self.aviso.setStyleSheet("color: #c62828;")
        self.aviso.setWordWrap(True)
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Ok).setText("Guardar")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botones.accepted.connect(self._aceptar)
        botones.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(nota)
        lay.addWidget(self.aviso)
        lay.addWidget(botones)

    def _proponer_agencia(self, texto: str) -> None:
        if not self.agencia.isModified() and texto.isdigit():
            self.agencia.setText(f"{texto}1000")

    def _elegir_uafi(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(self, "Aplicativo UAFI de la empresa", str(Path.home()),
                                              "UAFI (*.zip);;Todos (*)")
        if ruta:
            self.ruta_uafi.setText(ruta)

    def _aceptar(self) -> None:
        nombre = texto_mayusculas(self.nombre.text())
        codigo = self.codigo.text().strip()
        agencia = self.agencia.text().strip()
        origen = self.ruta_uafi.text().strip()
        if len(nombre) < 3:
            return self.aviso.setText("Escriba el nombre de la empresa.")
        if not (codigo.isdigit() and len(codigo) in (4, 5)):
            return self.aviso.setText("El código de registro debe tener 4 o 5 dígitos.")
        if agencia and not (agencia.isdigit() and len(agencia) in (8, 9) and agencia.startswith(codigo)):
            return self.aviso.setText("El código de agencia debe tener 8 o 9 dígitos y empezar con el código "
                                      "de registro.")
        if self.empresa is None and not origen:
            return self.aviso.setText("Elija el uafi.zip de la empresa.")
        try:
            if self.empresa is None:
                self.empresa = emp.crear(nombre, codigo, Path(origen), ruc=self.ruc.text(),
                                         usuario=self.usuario.text(), agencia=agencia)
            else:
                e = self.empresa
                e.nombre, e.codigo, e.ruc = nombre, codigo, self.ruc.text().strip()
                e.usuario, e.agencia = self.usuario.text().strip(), agencia
                if origen:
                    emp.instalar_uafi(Path(origen), e)
                e.guardar()
        except Exception as ex:  # noqa: BLE001 - se informa al usuario
            return self.aviso.setText(f"No se pudo guardar: {ex}")
        self.accept()


class DialogoEmpresas(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Empresas y aplicativos UAFI")
        self.resize(640, 420)
        self.lista = QListWidget()
        self.lista.itemDoubleClicked.connect(lambda _i: self._editar())
        botones = {}
        for clave, texto in (("nueva", "Agregar empresa…"), ("editar", "Editar…"), ("uafi", "Abrir su UAFI"),
                             ("acceso", "Acceso directo en el escritorio"), ("eliminar", "Eliminar")):
            botones[clave] = QPushButton(texto)
        botones["nueva"].clicked.connect(self._nueva)
        botones["editar"].clicked.connect(self._editar)
        botones["uafi"].clicked.connect(self._abrir_uafi)
        botones["acceso"].clicked.connect(self._acceso)
        botones["eliminar"].clicked.connect(self._eliminar)
        columna = QVBoxLayout()
        for b in botones.values():
            columna.addWidget(b)
        columna.addStretch(1)
        cerrar = QDialogButtonBox(QDialogButtonBox.Close)
        cerrar.button(QDialogButtonBox.Close).setText("Cerrar")
        cerrar.rejected.connect(self.accept)
        fila = QHBoxLayout()
        fila.addWidget(self.lista, 1)
        fila.addLayout(columna)
        lay = QVBoxLayout(self)
        lay.addLayout(fila)
        lay.addWidget(cerrar)
        self._cargar()

    def _cargar(self, seleccionar: str | None = None) -> None:
        self.lista.clear()
        for e in emp.listar():
            estado = "" if e.tiene_uafi else "   ⚠ falta el UAFI"
            sector = ""
            if e.tiene_uafi:
                try:
                    sector = f" · {e.estructura.sector.title()}"
                except Exception:  # noqa: BLE001
                    estado = "   ⚠ UAFI dañado"
            item = QListWidgetItem(f"{e.nombre}  (código {e.codigo}){sector}{estado}")
            item.setData(Qt.UserRole, e)
            self.lista.addItem(item)
            if e.id == seleccionar:
                self.lista.setCurrentItem(item)
        if self.lista.currentRow() < 0 and self.lista.count():
            self.lista.setCurrentRow(0)

    def _actual(self) -> emp.Empresa | None:
        item = self.lista.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _nueva(self) -> None:
        d = DialogoEmpresa(parent=self)
        if d.exec():
            self._cargar(d.empresa.id)
            r = QMessageBox.question(self, "Acceso directo",
                                     f"¿Crear en el escritorio un acceso directo al UAFI de {d.empresa.nombre}?")
            if r == QMessageBox.Yes:
                self._acceso()

    def _editar(self) -> None:
        e = self._actual()
        if e and DialogoEmpresa(e, self).exec():
            self._cargar(e.id)

    def _abrir_uafi(self) -> None:
        e = self._actual()
        if e:
            try:
                uafi.abrir(e)
            except Exception as ex:  # noqa: BLE001
                QMessageBox.warning(self, "UAFI", str(ex))

    def _acceso(self) -> None:
        e = self._actual()
        if e:
            try:
                ruta = uafi.crear_acceso_directo(e)
                QMessageBox.information(self, "Acceso directo", f"Se creó el acceso directo:\n{ruta}")
            except Exception as ex:  # noqa: BLE001
                QMessageBox.warning(self, "Acceso directo", str(ex))

    def _eliminar(self) -> None:
        e = self._actual()
        if not e:
            return
        r = QMessageBox.warning(self, "Eliminar empresa",
                                f"Se borrarán la empresa {e.nombre}, su UAFI instalado aquí y sus reportes "
                                "guardados en este programa (las plantillas exportadas no se tocan).\n\n¿Continuar?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r == QMessageBox.Yes:
            emp.eliminar(e)
            self._cargar()
