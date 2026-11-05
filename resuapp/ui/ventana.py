"""Ventana principal: empresa y período arriba; clientes, operaciones y transacciones en el centro."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSettings, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMainWindow, QMessageBox, QPushButton, QSpinBox, QSplitter, QTableView,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import empresas as emp
from .. import excel, facturas, importar_facturas, uafi
from ..estructura import Archivo
from ..modelo import INSTRUMENTOS, Registro, Reporte, calcular_total
from ..reglas import Mensaje, validar
from ..rutas import carpeta_documentos
from .editor import DialogoRegistro, etiqueta
from .empresas import DialogoEmpresas
from .importar_facturas import DialogoFacturas

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre",
         "Noviembre", "Diciembre"]
NOMBRES = {"CLIENTE": ("Clientes", "cliente"), "OPERACION": ("Operaciones", "operación"),
           "TRANSACCION": ("Transacciones", "transacción")}
# Campos que se recuerdan para proponerlos en el siguiente registro del mismo nivel.
NO_RECORDAR = {"TID", "IDE", "NRS", "AEC", "IMT", "DIR", "NCT", "VTO", "FDO", "ADB", "DRB", "FTR", "NFA",
               "TIT", "IDT", "NRT", *INSTRUMENTOS, "VVT"}


def _plural(nivel: Archivo) -> str:
    return NOMBRES.get(nivel.nombre, (nivel.nombre.capitalize(), nivel.nombre.lower()))[0]


def _singular(nivel: Archivo) -> str:
    return NOMBRES.get(nivel.nombre, (nivel.nombre.capitalize(), nivel.nombre.lower()))[1]


def _miles(valor: str) -> str:
    return f"{int(valor):,}".replace(",", ".") if valor.isdigit() else valor


class ModeloNivel(QAbstractTableModel):
    def __init__(self, nivel: Archivo, parent=None):
        super().__init__(parent)
        self.nivel = nivel
        self.campos = [c for c in nivel.propios if c.nombre not in ("CDR", "FCT")]
        self.registros: list[Registro] = []
        self.ruta_padre: tuple = ()
        self.errores: dict[tuple, set[str]] = {}

    def poner(self, registros: list[Registro], ruta_padre: tuple, mensajes: list[Mensaje]) -> None:
        self.beginResetModel()
        self.registros, self.ruta_padre = registros, ruta_padre
        self.errores = {}
        for m in mensajes:
            if m.es_error and len(m.ruta) == len(ruta_padre) + 1 and m.ruta[:-1] == ruta_padre:
                self.errores.setdefault(m.ruta, set()).add(m.campo)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.registros)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.campos)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and section < len(self.campos):
            campo = self.campos[section]
            if role == Qt.DisplayRole:
                return etiqueta(campo.etiqueta)
            if role == Qt.ToolTipRole:
                return f"{campo.nombre}: {campo.etiqueta}"
        if orientation == Qt.Vertical and role == Qt.DisplayRole:
            return section + 1
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        reg, campo = self.registros[index.row()], self.campos[index.column()]
        valor = reg.get(campo.nombre)
        ruta = self.ruta_padre + (index.row(),)
        if role == Qt.DisplayRole:
            if campo.es_fecha and len(valor) == 8:
                return f"{valor[6:]}/{valor[4:6]}/{valor[:4]}"
            if campo.es_numero:
                return _miles(valor)
            return valor
        if role == Qt.TextAlignmentRole and campo.es_numero:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ForegroundRole and campo.nombre in self.errores.get(ruta, ()):
            return QColor("#c62828")
        if role == Qt.BackgroundRole and ruta in self.errores:
            return QColor(198, 40, 40, 28)
        return None


class VistaNivel(QTableView):
    """Tabla con una marca de agua cuando está vacía."""

    def __init__(self, marca: str, parent=None):
        super().__init__(parent)
        self.marca = marca
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setDefaultSectionSize(24)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.horizontalHeader().setStretchLastSection(True)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.model() is not None and self.model().rowCount() == 0 and self.marca:
            p = QPainter(self.viewport())
            p.setPen(QColor(128, 128, 128, 170))
            fuente = p.font()
            fuente.setPointSizeF(fuente.pointSizeF() * 1.25)
            p.setFont(fuente)
            p.drawText(self.viewport().rect().adjusted(20, 10, -20, -10), Qt.AlignCenter | Qt.TextWordWrap,
                       self.marca)


class PanelNivel(QWidget):
    def __init__(self, ventana: "VentanaPrincipal", indice: int, nivel: Archivo):
        super().__init__()
        self.ventana, self.indice, self.nivel = ventana, indice, nivel
        self.titulo = QLabel()
        self.titulo.setStyleSheet("font-weight: bold;")
        marcas = {
            0: "Arrastre aquí sus facturas de venta (XML, PDF o el TXT de comprobantes emitidos del SRI)\n"
               "y se crean solos los clientes, operaciones y transacciones.\n\n"
               "También puede usar «Agregar» o arrastrar plantillas CLI, OPR y TRA que ya tenga.",
            1: "Elija un cliente arriba y agregue sus operaciones (contratos).",
            2: "Elija una operación arriba y agregue sus transacciones (pagos).",
        }
        self.vista = VistaNivel(marcas.get(indice, ""))
        self.modelo = ModeloNivel(nivel, self)
        self.vista.setModel(self.modelo)
        self.vista.doubleClicked.connect(lambda _i: self.editar())
        self.botones = {}
        barra = QHBoxLayout()
        barra.addWidget(self.titulo)
        barra.addStretch(1)
        for clave, texto in (("agregar", "Agregar"), ("editar", "Editar"), ("duplicar", "Duplicar"),
                             ("eliminar", "Eliminar")):
            b = QPushButton(texto)
            b.clicked.connect(getattr(self, clave))
            barra.addWidget(b)
            self.botones[clave] = b
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.addLayout(barra)
        lay.addWidget(self.vista)

    # --- estado ---
    def ruta_padre(self) -> tuple | None:
        """Ruta del registro padre seleccionado (None si el nivel no tiene padre elegido)."""
        if self.indice == 0:
            return ()
        return self.ventana.paneles[self.indice - 1].ruta_seleccionada()

    def ruta_seleccionada(self) -> tuple | None:
        filas = self.vista.selectionModel().selectedRows() if self.vista.selectionModel() else []
        padre = self.ruta_padre()
        if not filas or padre is None:
            return None
        return padre + (filas[0].row(),)

    def refrescar(self, mensajes: list[Mensaje], conservar: int | None = None) -> None:
        padre = self.ruta_padre()
        rep = self.ventana.reporte
        registros = rep.lista_de(padre) if (rep is not None and padre is not None) else []
        fila = conservar if conservar is not None else (self.vista.currentIndex().row())
        self.modelo.poner(registros, padre or (), mensajes)
        errores = sum(1 for r in self.modelo.errores)
        texto = f"{_plural(self.nivel)} ({len(registros)})"
        if self.indice > 0 and padre is not None:
            anc = rep.registro(padre)
            if self.indice == 1:
                texto += f" de {anc.get('NRS') or anc.get('IDE')}"
            elif self.indice == 2:
                texto += f" de la operación {anc.get('NCT')}"
        if errores:
            texto += f"   ⚠ {errores} con errores"
        self.titulo.setText(texto)
        habilitado = padre is not None and rep is not None
        self.botones["agregar"].setEnabled(habilitado)
        for clave in ("editar", "duplicar", "eliminar"):
            self.botones[clave].setEnabled(habilitado and bool(registros))
        if registros:
            fila = min(max(fila, 0), len(registros) - 1)
            self.vista.selectRow(fila)
        self.vista.resizeColumnsToContents()
        for col in range(self.modelo.columnCount()):
            self.vista.setColumnWidth(col, min(self.vista.columnWidth(col), 320))

    # --- acciones ---
    def _ancestros(self, ruta_padre: tuple) -> list[Registro]:
        rep = self.ventana.reporte
        return [rep.registro(ruta_padre[:i + 1]) for i in range(len(ruta_padre))]

    def _dialogo(self, registro: Registro, ruta: tuple, titulo: str) -> dict | None:
        padre = ruta[:-1]
        d = DialogoRegistro(self.ventana.empresa, self.ventana.reporte, self.nivel, registro,
                            self._ancestros(padre), ruta, titulo, self.ventana)
        return d.valores() if d.exec() else None

    def _valores_iniciales(self, ruta_padre: tuple) -> dict[str, str]:
        e, rep = self.ventana.empresa, self.ventana.reporte
        v: dict[str, str] = {}
        if self.nivel.nombre == "CLIENTE":
            v.update(NAC="ECU")
        elif self.nivel.nombre == "OPERACION":
            cliente = rep.registro(ruta_padre)
            v.update(PUB="EC", DRB=cliente.get("DIR"), CCO=cliente.get("CCC"))
        elif self.nivel.nombre == "TRANSACCION":
            v.update(MND="USD", CAT=e.agencia_defecto(), RPT="0", TIT="0", IDT="0", NRT="0",
                     **{k: "0" for k in INSTRUMENTOS})
            operacion = rep.registro(ruta_padre)
            if operacion.get("FDO")[:6] == rep.periodo[:6]:
                v["FTR"] = operacion.get("FDO")
        recordados = e.valores_recordados().get(self.nivel.nombre, {})
        v.update({k: val for k, val in recordados.items() if k not in NO_RECORDAR and val})
        calcular_total(e.estructura, self.nivel, v)
        return {k: val for k, val in v.items() if self.nivel.campo(k) is not None}

    def agregar(self) -> None:
        padre = self.ruta_padre()
        if padre is None:
            return
        lista = self.ventana.reporte.lista_de(padre)
        ruta = padre + (len(lista),)
        valores = self._dialogo(Registro(self._valores_iniciales(padre)), ruta, f"Nueva {_singular(self.nivel)}"
                                if self.nivel.nombre != "CLIENTE" else "Nuevo cliente")
        if valores is None:
            return
        lista.append(Registro(valores))
        self._recordar(valores)
        self.ventana.cambio(self.indice, len(lista) - 1)
        if self.indice + 1 < len(self.ventana.paneles):
            siguiente = self.ventana.paneles[self.indice + 1]
            texto = "¿Agregar ahora su primera operación?" if self.indice == 0 else "¿Agregar ahora su transacción?"
            if QMessageBox.question(self.ventana, _singular(self.nivel).capitalize(), texto) == QMessageBox.Yes:
                siguiente.agregar()

    def editar(self) -> None:
        ruta = self.ruta_seleccionada()
        if ruta is None:
            return
        reg = self.ventana.reporte.registro(ruta)
        valores = self._dialogo(reg, ruta, f"Editar {_singular(self.nivel)}")
        if valores is None:
            return
        reg.valores = valores
        self._recordar(valores)
        if self.nivel.nombre == "CLIENTE":
            # las operaciones creadas desde facturas sin dirección toman la del cliente
            for op in reg.hijos:
                if not op.get("DRB") and valores.get("DIR"):
                    op.valores["DRB"] = valores["DIR"]
                if not op.get("CCO") and valores.get("CCC"):
                    op.valores["CCO"] = valores["CCC"]
        self.ventana.cambio(self.indice, ruta[-1])

    def duplicar(self) -> None:
        ruta = self.ruta_seleccionada()
        if ruta is None:
            return
        original = self.ventana.reporte.registro(ruta)
        lista = self.ventana.reporte.lista_de(ruta[:-1])
        copia = Registro(dict(original.valores))
        valores = self._dialogo(copia, ruta[:-1] + (len(lista),), f"Duplicar {_singular(self.nivel)}")
        if valores is None:
            return
        lista.append(Registro(valores))
        self.ventana.cambio(self.indice, len(lista) - 1)

    def eliminar(self) -> None:
        ruta = self.ruta_seleccionada()
        if ruta is None:
            return
        reg = self.ventana.reporte.registro(ruta)
        detalle = ""
        if reg.hijos:
            detalle = f"\n\nTambién se eliminarán sus {len(reg.hijos)} registro(s) dependientes."
        r = QMessageBox.question(self.ventana, "Eliminar", f"¿Eliminar esta {_singular(self.nivel)}?{detalle}"
                                 if self.nivel.nombre != "CLIENTE" else f"¿Eliminar este cliente?{detalle}")
        if r != QMessageBox.Yes:
            return
        del self.ventana.reporte.lista_de(ruta[:-1])[ruta[-1]]
        self.ventana.cambio(self.indice, max(ruta[-1] - 1, 0))

    def _recordar(self, valores: dict[str, str]) -> None:
        e = self.ventana.empresa
        e.recordar_valores(self.nivel.nombre, {k: v for k, v in valores.items() if k not in NO_RECORDAR})
        if self.nivel.nombre == "CLIENTE":
            e.recordar_clientes([valores])


class PanelMensajes(QTreeWidget):
    def __init__(self, ventana: "VentanaPrincipal"):
        super().__init__()
        self.ventana = ventana
        self.setHeaderLabels(["Tipo", "Dónde", "Mensaje"])
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.itemDoubleClicked.connect(self._ir)

    def mostrar(self, mensajes: list[Mensaje], reporte: Reporte | None) -> None:
        self.clear()
        for m in mensajes:
            item = QTreeWidgetItem([m.severidad.value, self._donde(m, reporte), m.texto])
            item.setForeground(0, QColor("#c62828" if m.es_error else "#b26a00"))
            item.setData(0, Qt.UserRole, m.ruta)
            item.setToolTip(2, m.texto)
            self.addTopLevelItem(item)
        self.resizeColumnToContents(0)
        self.setColumnWidth(1, min(max(self.sizeHintForColumn(1), 120), 380))

    @staticmethod
    def _donde(m: Mensaje, reporte: Reporte | None) -> str:
        if not m.ruta or reporte is None:
            return "Reporte"
        partes = []
        for i in range(len(m.ruta)):
            reg = reporte.registro(m.ruta[:i + 1])
            if reg is None:
                break
            if i == 0:
                partes.append(f"Cliente {m.ruta[0] + 1} ({reg.get('IDE') or 'sin identificación'})")
            elif i == 1:
                partes.append(f"Operación {reg.get('NCT') or m.ruta[1] + 1}")
            else:
                partes.append(f"Transacción {reg.get('NFA') or m.ruta[2] + 1}")
        return " › ".join(partes)

    def _ir(self, item: QTreeWidgetItem) -> None:
        ruta = item.data(0, Qt.UserRole)
        if ruta:
            self.ventana.ir_a(tuple(ruta))


class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Generador RESU UAFE")
        self.setAcceptDrops(True)
        self.empresa: emp.Empresa | None = None
        self.reporte: Reporte | None = None
        self.mensajes: list[Mensaje] = []
        self.paneles: list[PanelNivel] = []

        # --- barra superior ---
        self.combo_empresa = QComboBox()
        self.combo_empresa.setMinimumContentsLength(28)
        self.anio = QSpinBox()
        self.anio.setRange(2010, 2100)
        self.mes = QComboBox()
        self.mes.addItems(MESES)
        anterior = dt.date.today().replace(day=1) - dt.timedelta(days=1)
        self.anio.setValue(anterior.year)
        self.mes.setCurrentIndex(anterior.month - 1)
        b_empresas = QPushButton("Empresas…")
        b_empresas.clicked.connect(self.administrar_empresas)
        b_facturas = QPushButton("Agregar facturas…")
        b_facturas.setStyleSheet("font-weight: bold;")
        b_facturas.setToolTip("Facturas de venta en XML o PDF, o el TXT de comprobantes emitidos del portal SRI")
        b_facturas.clicked.connect(lambda: self.agregar_facturas())
        b_importar = QPushButton("Importar Excel…")
        b_importar.setToolTip("Cargar plantillas CLI, OPR y TRA que ya tenga hechas")
        b_importar.clicked.connect(self.importar_excel)
        self.b_exportar = QPushButton("Generar plantillas Excel")
        self.b_exportar.setStyleSheet("font-weight: bold;")
        self.b_exportar.clicked.connect(self.exportar)
        self.b_uafi = QPushButton("Abrir UAFI de la empresa")
        self.b_uafi.clicked.connect(self.abrir_uafi)
        superior = QHBoxLayout()
        superior.addWidget(QLabel("Empresa:"))
        superior.addWidget(self.combo_empresa, 1)
        superior.addWidget(b_empresas)
        superior.addSpacing(16)
        superior.addWidget(QLabel("Período:"))
        superior.addWidget(self.mes)
        superior.addWidget(self.anio)
        superior.addSpacing(16)
        superior.addWidget(b_facturas)
        superior.addWidget(b_importar)
        superior.addWidget(self.b_exportar)
        superior.addWidget(self.b_uafi)

        self.divisor = QSplitter(Qt.Vertical)
        self.msj = PanelMensajes(self)
        self.contenedor_paneles = QSplitter(Qt.Vertical)
        self.divisor.addWidget(self.contenedor_paneles)
        self.divisor.addWidget(self.msj)
        self.divisor.setStretchFactor(0, 4)
        self.divisor.setStretchFactor(1, 1)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addLayout(superior)
        lay.addWidget(self.divisor, 1)
        self.setCentralWidget(central)
        self.totales = QLabel()
        self.statusBar().addPermanentWidget(self.totales)

        accion = QAction("Validar", self, shortcut=QKeySequence("F5"), triggered=self.revalidar)
        self.addAction(accion)

        self.combo_empresa.currentIndexChanged.connect(self._empresa_elegida)
        self.anio.valueChanged.connect(lambda _v: self._cargar_reporte())
        self.mes.currentIndexChanged.connect(lambda _i: self._cargar_reporte())

        cfg = QSettings()
        self.restoreGeometry(cfg.value("ventana/geometria", b""))
        self._llenar_empresas(cfg.value("ventana/empresa", ""))
        if self.combo_empresa.count() == 0:
            self.resize(1200, 760)

    # ------------------------------------------------------------------
    # Empresas y período
    def _llenar_empresas(self, seleccionar: str = "") -> None:
        self.combo_empresa.blockSignals(True)
        self.combo_empresa.clear()
        for e in emp.listar():
            self.combo_empresa.addItem(f"{e.nombre}  ({e.codigo})", e.id)
        indice = max(self.combo_empresa.findData(seleccionar), 0)
        self.combo_empresa.setCurrentIndex(indice if self.combo_empresa.count() else -1)
        self.combo_empresa.blockSignals(False)
        self._empresa_elegida()

    def _empresa_elegida(self) -> None:
        ident = self.combo_empresa.currentData()
        self.empresa = next((e for e in emp.listar() if e.id == ident), None)
        if self.empresa is not None and not self.empresa.tiene_uafi:
            QMessageBox.warning(self, "UAFI", f"La empresa {self.empresa.nombre} no tiene su aplicativo UAFI. "
                                              "Agréguelo en «Empresas…».")
            self.empresa = None
        self._construir_paneles()
        self._cargar_reporte()

    def _construir_paneles(self) -> None:
        for p in self.paneles:
            p.setParent(None)
            p.deleteLater()
        self.paneles = []
        if self.empresa is None:
            return
        for i, nivel in enumerate(self.empresa.estructura.niveles):
            panel = PanelNivel(self, i, nivel)
            self.paneles.append(panel)
            self.contenedor_paneles.addWidget(panel)
        for i, panel in enumerate(self.paneles[:-1]):
            siguiente = self.paneles[i + 1]
            panel.vista.selectionModel().selectionChanged.connect(
                lambda _a, _b, s=siguiente: s.refrescar(self.mensajes, 0))

    def _ruta_reporte(self) -> Path | None:
        if self.empresa is None or self.reporte is None:
            return None
        return self.empresa.carpeta_reportes / self.reporte.nombre_archivo()

    def _cargar_reporte(self) -> None:
        if self.empresa is None:
            self.reporte = None
            self.setWindowTitle("Generador RESU UAFE")
            self.revalidar()
            if self.combo_empresa.count() == 0:
                self.statusBar().showMessage("Para empezar, agregue una empresa con su uafi.zip en «Empresas…».")
            return
        rep = Reporte(self.empresa.codigo, self.anio.value(), self.mes.currentIndex() + 1)
        ruta = self.empresa.carpeta_reportes / rep.nombre_archivo()
        if ruta.is_file():
            try:
                rep = Reporte.abrir(ruta)
                rep.codigo = self.empresa.codigo
            except (OSError, ValueError, KeyError) as ex:
                QMessageBox.warning(self, "Reporte", f"No se pudo abrir el reporte guardado:\n{ex}")
        self.reporte = rep
        self.setWindowTitle(f"Generador RESU UAFE — {self.empresa.nombre} — "
                            f"{MESES[rep.mes - 1]} {rep.anio}")
        self.revalidar()

    def administrar_empresas(self) -> None:
        DialogoEmpresas(self).exec()
        self._llenar_empresas(self.combo_empresa.currentData() or "")
        if self.combo_empresa.count() and self.empresa is None:
            self.combo_empresa.setCurrentIndex(self.combo_empresa.count() - 1)

    # ------------------------------------------------------------------
    # Cambios, validación y navegación
    def cambio(self, indice_panel: int, fila: int) -> None:
        """Se modificó el reporte: guardar, revalidar y dejar seleccionada la fila indicada."""
        ruta = self._ruta_reporte()
        if ruta is not None:
            try:
                self.reporte.guardar(ruta)
                self.statusBar().showMessage("Guardado automáticamente.", 3000)
            except OSError as ex:
                QMessageBox.warning(self, "Guardar", f"No se pudo guardar el reporte:\n{ex}")
        self.revalidar(indice_panel, fila)

    def revalidar(self, indice_panel: int | None = None, fila: int | None = None) -> None:
        if self.empresa is None or self.reporte is None:
            self.mensajes = []
            self.msj.mostrar([], None)
            self.totales.setText("")
            return
        self.mensajes = validar(self.reporte, self.empresa.estructura, self.empresa.catalogos)
        self.msj.mostrar(self.mensajes, self.reporte)
        for i, panel in enumerate(self.paneles):
            panel.refrescar(self.mensajes, fila if i == indice_panel else None)
        self._mostrar_totales()

    def _mostrar_totales(self) -> None:
        t = self.reporte.totales(self.empresa.estructura)
        errores = sum(m.es_error for m in self.mensajes)
        partes = [f"{_plural(n)}: {t.get(n.nombre, 0)}" for n in self.empresa.estructura.niveles]
        if "VTO" in t:
            partes.append(f"Total operaciones: $ {_miles(str(t['VTO']))}")
        if "VVT" in t:
            partes.append(f"Total transacciones: $ {_miles(str(t['VVT']))}")
        estado = (f"<span style='color:#c62828'>⚠ {errores} error(es)</span>" if errores
                  else "<span style='color:#2e7d32'>✔ Sin errores</span>")
        self.totales.setText("   ·   ".join(partes) + "   ·   " + estado)

    def ir_a(self, ruta: tuple) -> None:
        for i in range(min(len(ruta), len(self.paneles))):
            self.paneles[i].vista.selectRow(ruta[i])
            self.paneles[i].vista.setFocus()

    # ------------------------------------------------------------------
    # Excel y UAFI
    def importar_excel(self, rutas: list[str] | None = None) -> None:
        if self.empresa is None:
            QMessageBox.information(self, "Importar", "Primero agregue o elija una empresa.")
            return
        if not rutas:
            rutas, _ = QFileDialog.getOpenFileNames(self, "Plantillas CLI, OPR y TRA", str(Path.home()),
                                                    "Plantillas Excel (*.xlsx)")
        if not rutas:
            return
        try:
            nuevo, avisos = excel.importar([Path(r) for r in rutas], self.empresa.estructura,
                                           self.empresa.catalogos)
        except Exception as ex:  # noqa: BLE001
            QMessageBox.warning(self, "Importar", f"No se pudieron leer las plantillas:\n{ex}")
            return
        if nuevo.codigo and nuevo.codigo != self.empresa.codigo:
            r = QMessageBox.warning(self, "Importar", f"Las plantillas son del código {nuevo.codigo} y la empresa "
                                    f"elegida tiene el código {self.empresa.codigo}.\n¿Importarlas de todos modos?",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        destino = Reporte(self.empresa.codigo, nuevo.anio, nuevo.mes)
        ruta = self.empresa.carpeta_reportes / destino.nombre_archivo()
        if ruta.is_file() and Reporte.abrir(ruta).clientes:
            r = QMessageBox.question(self, "Importar", f"Ya hay un reporte de {MESES[nuevo.mes - 1]} {nuevo.anio}. "
                                     "¿Reemplazarlo con las plantillas?")
            if r != QMessageBox.Yes:
                return
        destino.clientes = nuevo.clientes
        destino.guardar(ruta)
        self.empresa.recordar_clientes([c.valores for c in destino.clientes])
        self.anio.blockSignals(True)
        self.mes.blockSignals(True)
        self.anio.setValue(nuevo.anio)
        self.mes.setCurrentIndex(nuevo.mes - 1)
        self.anio.blockSignals(False)
        self.mes.blockSignals(False)
        self._cargar_reporte()
        texto = f"Se importaron {len(destino.clientes)} cliente(s)."
        if avisos:
            texto += "\n\n" + "\n".join(avisos[:15])
        QMessageBox.information(self, "Importar", texto)

    def exportar(self) -> None:
        if self.empresa is None or self.reporte is None:
            return
        self.revalidar()
        errores = sum(m.es_error for m in self.mensajes)
        if errores:
            r = QMessageBox.warning(self, "Generar plantillas",
                                    f"El reporte tiene {errores} error(es) (en rojo abajo). El UAFI o el SISLAFT "
                                    "lo rechazarán.\n\n¿Generar las plantillas de todos modos?",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        cfg = QSettings()
        base = Path(cfg.value(f"exportar/{self.empresa.id}", str(carpeta_documentos() / self.empresa.nombre)))
        sugerida = base / f"{self.reporte.anio}-{self.reporte.mes:02d}"
        try:
            sugerida.mkdir(parents=True, exist_ok=True)
        except OSError:
            sugerida = Path.home()
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta donde guardar las plantillas", str(sugerida))
        if not carpeta:
            return
        destino = Path(carpeta)
        existentes = [destino / excel.nombre_plantilla(n, self.reporte) for n in self.empresa.estructura.niveles]
        if any(p.exists() for p in existentes):
            r = QMessageBox.question(self, "Generar plantillas", "Ya existen plantillas de este período en esa "
                                     "carpeta. ¿Reemplazarlas?")
            if r != QMessageBox.Yes:
                return
        try:
            rutas = excel.exportar(self.reporte, self.empresa.estructura, destino)
        except OSError as ex:
            QMessageBox.warning(self, "Generar plantillas", f"No se pudieron guardar:\n{ex}")
            return
        cfg.setValue(f"exportar/{self.empresa.id}", str(destino.parent))
        caja = QMessageBox(self)
        caja.setWindowTitle("Plantillas generadas")
        caja.setTextFormat(Qt.RichText)
        caja.setText(
            "Se generaron:<br><b>" + "<br>".join(r.name for r in rutas) + f"</b><br>en {destino}<br><br>"
            "<b>Para obtener el archivo .uaf:</b><ol>"
            "<li>Abra el UAFI de la empresa.</li>"
            f"<li>Escriba su usuario{f' (<b>{self.empresa.usuario}</b>)' if self.empresa.usuario else ''} y elija "
            f"<b>{MESES[self.reporte.mes - 1]} {self.reporte.anio}</b>.</li>"
            "<li>Pulse «Cargar» y elija, en orden, CLI, OPR y TRA.</li>"
            "<li>Pulse «Validar» y luego «Guardar»: se crea el RESU…uaf para subirlo al SISLAFT.</li></ol>")
        b_uafi = caja.addButton("Abrir el UAFI", QMessageBox.AcceptRole)
        b_carpeta = caja.addButton("Abrir la carpeta", QMessageBox.ActionRole)
        caja.addButton("Cerrar", QMessageBox.RejectRole)
        caja.exec()
        if caja.clickedButton() is b_uafi:
            self.abrir_uafi()
        elif caja.clickedButton() is b_carpeta:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(destino)))

    def abrir_uafi(self) -> None:
        if self.empresa is None:
            return
        try:
            uafi.abrir(self.empresa)
            self.statusBar().showMessage(f"Abriendo el UAFI de {self.empresa.nombre}…", 5000)
        except Exception as ex:  # noqa: BLE001
            QMessageBox.warning(self, "UAFI", str(ex))

    # ------------------------------------------------------------------
    def agregar_facturas(self, rutas: list[str] | None = None) -> None:
        if self.empresa is None or self.reporte is None:
            QMessageBox.information(self, "Facturas", "Primero agregue o elija una empresa.")
            return
        if not rutas:
            rutas, _ = QFileDialog.getOpenFileNames(
                self, "Facturas de venta", str(Path.home()),
                "Facturas (*.xml *.pdf *.zip *.txt);;Todos (*)")
        if not rutas:
            return
        leidos = facturas.leer_rutas(rutas)
        # Si todas las facturas son de otro mes, ofrecer cambiar el período.
        propias = [f for f in leidos if isinstance(f, facturas.Factura) and f.tipo == "01" and f.fecha
                   and (not self.empresa.ruc or f.ruc_emisor == self.empresa.ruc)]
        meses = {(f.fecha.year, f.fecha.month) for f in propias}
        if len(meses) == 1 and next(iter(meses)) != (self.reporte.anio, self.reporte.mes):
            anio, mes = next(iter(meses))
            r = QMessageBox.question(self, "Período", f"Las facturas son de {MESES[mes - 1]} {anio}. "
                                     f"¿Cambiar el período del reporte a {MESES[mes - 1]} {anio}?")
            if r == QMessageBox.Yes:
                self.anio.blockSignals(True)
                self.anio.setValue(anio)
                self.anio.blockSignals(False)
                self.mes.setCurrentIndex(mes - 1)
                self._cargar_reporte()
        previos = []
        for ruta in sorted(self.empresa.carpeta_reportes.glob("RESU*.json")):
            try:
                previos.append(Reporte.abrir(ruta))
            except (OSError, ValueError, KeyError):
                pass
        opciones = importar_facturas.opciones_sugeridas(self.empresa, previos)
        propuestas = importar_facturas.analizar(leidos, self.empresa, self.reporte, opciones)
        if not propuestas:
            QMessageBox.information(self, "Facturas", "No se encontraron facturas en lo seleccionado.")
            return
        dialogo = DialogoFacturas(self.empresa, self.reporte, propuestas, opciones, self)
        if not dialogo.exec():
            return
        n = importar_facturas.aplicar(self.reporte, propuestas, self.empresa, opciones)
        self.cambio(0, len(self.reporte.clientes) - 1)
        errores = sum(m.es_error for m in self.mensajes)
        texto = f"Se agregaron {n} factura(s)."
        if errores:
            texto += (f"\n\nQuedan {errores} dato(s) por completar (abajo, en rojo). Doble clic en cada mensaje "
                      "para ir al registro; lo que complete de cada cliente se recuerda para los próximos meses.")
        else:
            texto += "\n\nTodo está completo: ya puede «Generar plantillas Excel»."
        QMessageBox.information(self, "Facturas", texto)

    @staticmethod
    def _rutas_soltadas(event) -> list[str]:
        return [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and self._rutas_soltadas(event):
            event.acceptProposedAction()

    def dropEvent(self, event):
        rutas = self._rutas_soltadas(event)
        excels = [r for r in rutas if r.lower().endswith(".xlsx")]
        otras = [r for r in rutas if not r.lower().endswith(".xlsx")]
        if excels:
            self.importar_excel(excels)
        if otras:
            self.agregar_facturas(otras)

    def closeEvent(self, event):
        cfg = QSettings()
        cfg.setValue("ventana/geometria", self.saveGeometry())
        cfg.setValue("ventana/empresa", self.combo_empresa.currentData() or "")
        super().closeEvent(event)
