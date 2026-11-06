"""Pantalla única: empresa y mes → arrastrar facturas de venta → generar CLI, OPR y TRA → abrir el UAFI."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QSettings, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QStyledItemDelegate,
                               QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import empresas as emp
from .. import excel, facturas, importar_facturas as imf, uafi
from ..modelo import Reporte, entero, periodo
from ..reglas import validar
from ..rutas import carpeta_documentos
from .campos import ControlBuscador
from .empresas import DialogoEmpresas

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre",
         "Noviembre", "Diciembre"]
COLUMNAS = ["Cliente", "RUC / cédula", "Actividad económica", "Tipo de transacción", "Pago", "Tipo de bien",
            "Área del bien (m²)", "Cantón", "Factura", "Fecha", "Total", "Forma de pago (SRI)", "Archivo"]
C_RUC, C_AEC, C_TTR, C_INST, C_TTB, C_ADB, C_CCO, C_TOTAL, C_FP = 1, 2, 3, 4, 5, 6, 7, 10, 11
# columna -> campo de la factura (importar_facturas.CAMPOS_FACTURA)
CAMPO_COLUMNA = {C_TTR: "ttr", C_INST: "inst", C_TTB: "ttb", C_ADB: "adb", C_CCO: "cco"}
NOMBRE_CAMPO = {"ttr": "tipo de transacción", "inst": "pago", "ttb": "tipo de bien", "adb": "área del bien",
                "cco": "cantón"}
ORIGEN = {
    imf.FACTURA: ("Elegido para esta factura", None, False),
    imf.PAGO: ("Según la forma de pago de la factura", None, False),
    imf.ANTERIOR: ("Como en el reporte de {periodo} de este cliente", "#1f4e9c", False),
    imf.CLIENTE: ("Cantón del cliente (de su dirección o de su ficha)", None, False),
    imf.DEFECTO: ("Valor por defecto (cuadro de abajo)", "#888888", True),
    imf.VARIOS: ("Se reparte según las formas de pago de la factura", "#888888", True),
}
URL_CONSULTA_RUC = "https://srienlinea.sri.gob.ec/sri-en-linea/SriRucWeb/ConsultaRuc/Consultas/consultaRuc"
MARCA = ("Arrastre aquí los XML o PDF de sus facturas de venta del mes\n"
         "(también carpetas, ZIP o el TXT de comprobantes emitidos del SRI)")


class DelegadoActividad(QStyledItemDelegate):
    """Editor dentro de la celda «Actividad económica»: se escribe y se filtra el catálogo."""

    def __init__(self, ventana: "VentanaSimple"):
        super().__init__(ventana)
        self.ventana = ventana

    def createEditor(self, parent, option, index):
        editor = ControlBuscador(None, self.ventana.empresa.catalogos.tabla("AE"),
                                 "Escriba la actividad o su código y elija de la lista…", parent)
        editor.setAutoFillBackground(True)
        editor.completer.activated.connect(lambda _t, ed=editor: (self.commitData.emit(ed), self.closeEditor.emit(ed)))
        return editor

    def setEditorData(self, editor, index):
        actual = index.data(Qt.UserRole) or ""
        if actual:
            editor.edit.setPlaceholderText(f"Actual: {index.data()}  — escriba para buscar otra")
        editor.codigo = ""
        editor.edit.clear()
        editor.edit.setFocus()

    def setModelData(self, editor, model, index):
        codigo = editor.valor()
        if codigo and codigo != (index.data(Qt.UserRole) or "") and index.row() < len(self.ventana.lista):
            self.ventana.guardar_actividad(self.ventana.lista[index.row()], codigo)


class DelegadoOpciones(QStyledItemDelegate):
    """Lista desplegable dentro de la celda (tipo de transacción, pago, tipo de bien)."""

    def __init__(self, ventana: "VentanaSimple", campo: str):
        super().__init__(ventana)
        self.ventana, self.campo = ventana, campo

    def createEditor(self, parent, option, index):
        c = QComboBox(parent)
        for codigo, nombre in self.ventana.opciones_campo(self.campo).items():
            c.addItem(f"{codigo} — {nombre}" if self.campo != "inst" else nombre, codigo)
        c.activated.connect(lambda _i, ed=c: (self.commitData.emit(ed), self.closeEditor.emit(ed)))
        return c

    def setEditorData(self, editor, index):
        editor.setCurrentIndex(max(editor.findData(index.data(Qt.UserRole) or ""), 0))
        editor.showPopup()

    def setModelData(self, editor, model, index):
        self.ventana.cambiar_campo(index.row(), self.campo, editor.currentData() or "")


class DelegadoArea(QStyledItemDelegate):
    def __init__(self, ventana: "VentanaSimple"):
        super().__init__(ventana)
        self.ventana = ventana

    def createEditor(self, parent, option, index):
        from PySide6.QtGui import QIntValidator

        e = QLineEdit(parent)
        e.setValidator(QIntValidator(0, 99_999_999, e))
        e.setPlaceholderText("m²")
        return e

    def setEditorData(self, editor, index):
        editor.setText(index.data(Qt.UserRole) or "")
        editor.selectAll()

    def setModelData(self, editor, model, index):
        valor = entero(editor.text()) or "0"
        self.ventana.cambiar_campo(index.row(), "adb", valor)


class DelegadoCanton(QStyledItemDelegate):
    def __init__(self, ventana: "VentanaSimple"):
        super().__init__(ventana)
        self.ventana = ventana

    def createEditor(self, parent, option, index):
        editor = ControlBuscador(None, self.ventana.empresa.catalogos.tabla("C"),
                                 "Escriba el cantón (ej.: Quito) o su código…", parent)
        editor.setAutoFillBackground(True)
        editor.completer.activated.connect(lambda _t, ed=editor: (self.commitData.emit(ed), self.closeEditor.emit(ed)))
        return editor

    def setEditorData(self, editor, index):
        editor.edit.setPlaceholderText(f"Actual: {index.data()}  — escriba para buscar otro")
        editor.codigo = ""
        editor.edit.clear()
        editor.edit.setFocus()

    def setModelData(self, editor, model, index):
        if editor.valor():
            self.ventana.cambiar_campo(index.row(), "cco", editor.valor())


class TablaFacturas(QTableWidget):
    def __init__(self):
        super().__init__(0, len(COLUMNAS))
        self.setHorizontalHeaderLabels(COLUMNAS)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.horizontalHeader().setStretchLastSection(True)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.rowCount() == 0:
            p = QPainter(self.viewport())
            p.setPen(QColor(128, 128, 128, 170))
            fuente = p.font()
            fuente.setPointSizeF(fuente.pointSizeF() * 1.3)
            p.setFont(fuente)
            p.drawText(self.viewport().rect().adjusted(20, 10, -20, -10), Qt.AlignCenter | Qt.TextWordWrap, MARCA)


def _combo_dict(opciones: dict[str, str]) -> QComboBox:
    c = QComboBox()
    for codigo, nombre in opciones.items():
        c.addItem(f"{codigo} — {nombre}", codigo)
    return c


class VentanaSimple(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Generador RESU UAFE")
        self.setAcceptDrops(True)
        self.empresa: emp.Empresa | None = None
        self.lista: list[facturas.Factura] = []
        self._cargando = False

        # --- empresa y mes ---
        self.c_empresa = QComboBox()
        self.c_empresa.setMinimumContentsLength(30)
        b_empresas = QPushButton("Empresas…")
        b_empresas.setToolTip("Agregar otra empresa (con su uafi.zip) o cambiar sus datos")
        b_empresas.clicked.connect(self.administrar_empresas)
        self.c_mes = QComboBox()
        self.c_mes.addItems(MESES)
        self.s_anio = QSpinBox()
        self.s_anio.setRange(2010, 2100)
        anterior = dt.date.today().replace(day=1) - dt.timedelta(days=1)
        self.s_anio.setValue(anterior.year)
        self.c_mes.setCurrentIndex(anterior.month - 1)
        arriba = QHBoxLayout()
        arriba.addWidget(QLabel("Empresa:"))
        arriba.addWidget(self.c_empresa, 1)
        arriba.addWidget(b_empresas)
        arriba.addSpacing(20)
        arriba.addWidget(QLabel("Mes:"))
        arriba.addWidget(self.c_mes)
        arriba.addWidget(self.s_anio)

        # --- facturas ---
        self.tabla = TablaFacturas()
        b_agregar = QPushButton("Agregar facturas…")
        b_agregar.clicked.connect(lambda: self.agregar())
        b_quitar = QPushButton("Quitar seleccionadas")
        b_quitar.clicked.connect(self.quitar)
        b_vaciar = QPushButton("Quitar todas")
        b_vaciar.clicked.connect(self.vaciar)
        b_sri = QPushButton("Consultar RUC en el SRI")
        b_sri.setToolTip("Copia el RUC de la factura elegida y abre la consulta de RUC del SRI "
                         "(pegue con Ctrl+V) para ver su actividad económica.")
        b_sri.clicked.connect(lambda: self.consultar_ruc())
        self.tabla.setItemDelegateForColumn(C_AEC, DelegadoActividad(self))
        for col, campo in ((C_TTR, "ttr"), (C_INST, "inst"), (C_TTB, "ttb")):
            self.tabla.setItemDelegateForColumn(col, DelegadoOpciones(self, campo))
        self.tabla.setItemDelegateForColumn(C_ADB, DelegadoArea(self))
        self.tabla.setItemDelegateForColumn(C_CCO, DelegadoCanton(self))
        self.anteriores: dict[str, dict[str, str]] = {}
        self.previos: list[Reporte] = []
        self.tabla.cellDoubleClicked.connect(self._doble_clic)
        self.tabla.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabla.customContextMenuRequested.connect(self._menu_tabla)
        self.resumen = QLabel()
        botones_lista = QHBoxLayout()
        botones_lista.addWidget(b_agregar)
        botones_lista.addWidget(b_quitar)
        botones_lista.addWidget(b_vaciar)
        botones_lista.addSpacing(16)
        botones_lista.addWidget(b_sri)
        botones_lista.addStretch(1)
        botones_lista.addWidget(self.resumen)

        # --- valores por defecto ---
        self.caja = QGroupBox("Valores por defecto")
        self.rejilla = QGridLayout(self.caja)
        self.controles: dict[str, QWidget] = {}

        # --- acciones ---
        self.b_generar = QPushButton("Generar Excel  (CLI, OPR, TRA)")
        self.b_generar.setStyleSheet("font-weight: bold; padding: 8px 18px;")
        self.b_generar.clicked.connect(self.generar)
        self.b_uafi = QPushButton("Abrir UAFI de la empresa")
        self.b_uafi.setStyleSheet("padding: 8px 18px;")
        self.b_uafi.clicked.connect(self.abrir_uafi)
        abajo = QHBoxLayout()
        abajo.addStretch(1)
        abajo.addWidget(self.b_generar)
        abajo.addWidget(self.b_uafi)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addLayout(arriba)
        lay.addWidget(self.tabla, 1)
        lay.addLayout(botones_lista)
        lay.addWidget(self.caja)
        lay.addLayout(abajo)
        self.setCentralWidget(central)

        self.c_empresa.currentIndexChanged.connect(self._empresa_elegida)
        self.c_mes.currentIndexChanged.connect(lambda _i: self._cargar_lista())
        self.s_anio.valueChanged.connect(lambda _v: self._cargar_lista())
        cfg = QSettings()
        self.restoreGeometry(cfg.value("simple/geometria", b""))
        if not cfg.value("simple/geometria"):
            self.resize(1180, 720)
        self._llenar_empresas(cfg.value("simple/empresa", ""))

    # ------------------------------------------------------------------
    # Empresa, mes y lista guardada
    def _llenar_empresas(self, seleccionar: str = "") -> None:
        self.c_empresa.blockSignals(True)
        self.c_empresa.clear()
        for e in emp.listar():
            if e.tiene_uafi:
                self.c_empresa.addItem(f"{e.nombre}   (código {e.codigo})", e.id)
        self.c_empresa.setCurrentIndex(max(self.c_empresa.findData(seleccionar), 0) if self.c_empresa.count() else -1)
        self.c_empresa.blockSignals(False)
        self._empresa_elegida()

    def _empresa_elegida(self) -> None:
        ident = self.c_empresa.currentData()
        self.empresa = next((e for e in emp.listar() if e.id == ident), None)
        self._construir_opciones()
        self._cargar_lista()

    @property
    def anio(self) -> int:
        return self.s_anio.value()

    @property
    def mes(self) -> int:
        return self.c_mes.currentIndex() + 1

    def _ruta_lista(self) -> Path | None:
        if self.empresa is None:
            return None
        return self.empresa.carpeta_reportes / f"FACTURAS{self.empresa.codigo}{periodo(self.anio, self.mes)}.json"

    def _cargar_lista(self) -> None:
        from ..modelo import periodo as _periodo

        self.anteriores = imf.ultimos_por_cliente(self.previos, antes_de=_periodo(self.anio, self.mes)) \
            if self.empresa else {}
        self.lista = []
        ruta = self._ruta_lista()
        if ruta is not None and ruta.is_file():
            try:
                self.lista = [imf.factura_de_dict(d) for d in json.loads(ruta.read_text("utf-8"))]
            except (OSError, ValueError, KeyError):
                self.lista = []
        self._mostrar_lista()

    def _guardar_lista(self) -> None:
        ruta = self._ruta_lista()
        if ruta is not None:
            ruta.write_text(json.dumps([imf.factura_a_dict(f) for f in self.lista], ensure_ascii=False, indent=1),
                            "utf-8")

    def _canton_cliente(self, f: facturas.Factura, directorio: dict) -> str:
        datos = directorio.get(f.id_cliente, {})
        if datos.get("CCC"):
            return datos["CCC"]
        direccion = datos.get("DIR") or f.direccion_cliente
        return imf.canton_por_direccion(direccion, self.empresa.catalogos.tabla("C")) if direccion else ""

    def opciones_campo(self, campo: str) -> dict[str, str]:
        cat = self.empresa.catalogos
        if campo == "ttr":
            return dict(sorted(cat.tabla("TT").items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0))
        if campo == "ttb":
            return dict(sorted(cat.tabla("TB").items()))
        if campo == "inst":
            return dict(imf.NOMBRE_INSTRUMENTO)
        if campo == "cco":
            return cat.tabla("C")
        return {}

    def _texto_campo(self, campo: str, valor: str) -> str:
        cat = self.empresa.catalogos
        def con_nombre(tabla: str) -> str:
            nombre = cat.nombre(tabla, valor)
            return f"{valor} — {nombre}" if nombre else valor

        if campo == "ttr":
            return con_nombre("TT") if valor else ""
        if campo == "ttb":
            return con_nombre("TB") if valor else ""
        if campo == "inst":
            return imf.NOMBRE_INSTRUMENTO.get(valor, valor) if valor else "Varios (según la factura)"
        if campo == "cco":
            return f"{cat.nombre('C', valor) or valor} ({valor})" if valor else ""
        return valor

    def _mostrar_lista(self) -> None:
        from ..reglas import INSTRUMENTOS_POR_TRANSACCION

        self.lista.sort(key=lambda f: (f.fecha or dt.date.min, f.numero))
        directorio = self.empresa.directorio_clientes() if self.empresa else {}
        cat = self.empresa.catalogos if self.empresa else None
        opciones = self._opciones() if self.controles else imf.Opciones()
        cursiva = self.tabla.font()
        cursiva.setItalic(True)
        self.tabla.setRowCount(len(self.lista))
        for fila, f in enumerate(self.lista):
            formas = ", ".join(f"{c} {imf.FORMAS_PAGO_SRI.get(c, '')}".strip() for c, _v in f.pagos) or "—"
            aec = directorio.get(f.id_cliente, {}).get("AEC", "")
            actividad = f"{aec} — {cat.nombre('AE', aec)}" if aec else "(la de por defecto)"
            v = imf.valores_factura(f, opciones, self.anteriores, self._canton_cliente(f, directorio))
            valores = [f.nombre_cliente, f.id_cliente, actividad, "", "", "", "", "", f.numero,
                       f.fecha.strftime("%d/%m/%Y") if f.fecha else "", f"{f.total:,.2f}", formas, f.archivo]
            for col, texto in enumerate(valores):
                item = QTableWidgetItem(texto)
                item.setToolTip({C_AEC: f"{texto}\nDoble clic para escribir y buscar la actividad\n"
                                        "(una por cliente: vale para todas sus facturas)",
                                 C_RUC: f"{texto}\nDoble clic para copiarlo"}.get(col, texto))
                if col == C_AEC:
                    item.setData(Qt.UserRole, aec)
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                if col == C_TOTAL:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == C_AEC and not aec:
                    item.setForeground(QColor("#888888"))
                self.tabla.setItem(fila, col, item)
            for col, campo in CAMPO_COLUMNA.items():
                valor, origen = v[campo]
                item = QTableWidgetItem(self._texto_campo(campo, valor))
                item.setData(Qt.UserRole, valor)
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                explicacion, color, en_cursiva = ORIGEN[origen]
                periodo_ant = self.anteriores.get(f.id_cliente, {}).get("_periodo", "")
                explicacion = explicacion.format(periodo=f"{periodo_ant[4:6]}/{periodo_ant[:4]}" if periodo_ant else "")
                if color:
                    item.setForeground(QColor(color))
                if en_cursiva:
                    item.setFont(cursiva)
                item.setToolTip(f"{item.text()}\n{explicacion}\nDoble clic para cambiarlo "
                                "(con varias filas seleccionadas, cambia todas)")
                if campo == "adb":
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabla.setItem(fila, col, item)
            # tipo de transacción que no admite ese pago (tabla 2 del manual)
            permitidos = INSTRUMENTOS_POR_TRANSACCION.get(v["ttr"][0])
            inst = v["inst"][0]
            if permitidos is not None and inst and inst not in permitidos:
                for col in (C_TTR, C_INST):
                    it = self.tabla.item(fila, col)
                    it.setBackground(QColor("#f8d7da"))
                    it.setToolTip(f"{it.toolTip()}\n⚠ El tipo de transacción {v['ttr'][0]} no admite pago con "
                                  f"{imf.NOMBRE_INSTRUMENTO.get(inst, inst).lower()}.")
        self.tabla.resizeColumnsToContents()
        for col, ancho in ((0, 300), (C_AEC, 260), (C_TTR, 230), (C_TTB, 200), (C_CCO, 170), (C_FP, 240)):
            self.tabla.setColumnWidth(col, min(self.tabla.columnWidth(col), ancho))
        clientes = {f.id_cliente for f in self.lista}
        total = sum(int(f.total) for f in self.lista)
        self.resumen.setText(f"<b>{len(self.lista)}</b> factura(s) · <b>{len(clientes)}</b> cliente(s) · "
                             f"total <b>$ {total:,}</b>".replace(",", "."))
        hay = self.empresa is not None
        self.b_generar.setEnabled(hay and bool(self.lista))
        self.b_uafi.setEnabled(hay)
        nombre = f" — {self.empresa.nombre} — {MESES[self.mes - 1]} {self.anio}" if hay else ""
        self.setWindowTitle("Generador RESU UAFE" + nombre)

    def _filas_objetivo(self, fila: int) -> list[int]:
        """La fila editada y, si está entre las seleccionadas, todas las seleccionadas."""
        seleccion = sorted({i.row() for i in self.tabla.selectedIndexes()})
        return seleccion if fila in seleccion and len(seleccion) > 1 else [fila]

    def cambiar_campo(self, fila: int, campo: str, valor: str) -> None:
        if not valor or fila >= len(self.lista):
            return
        filas = self._filas_objetivo(fila)
        for r in filas:
            self.lista[r].resu[campo] = valor
        self._guardar_lista()
        self._mostrar_lista()
        self.statusBar().showMessage(f"{NOMBRE_CAMPO[campo].capitalize()} cambiado en {len(filas)} factura(s).", 6000)

    def volver_automatico(self, filas: list[int], campo: str) -> None:
        for r in filas:
            self.lista[r].resu.pop(campo, None)
        self._guardar_lista()
        self._mostrar_lista()

    def aplicar_al_cliente(self, fila: int, campo: str) -> None:
        f = self.lista[fila]
        valor = self.tabla.item(fila, next(c for c, k in CAMPO_COLUMNA.items() if k == campo)).data(Qt.UserRole)
        if not valor:
            return
        n = 0
        for otra in self.lista:
            if otra.id_cliente == f.id_cliente:
                otra.resu[campo] = valor
                n += 1
        self._guardar_lista()
        self._mostrar_lista()
        self.statusBar().showMessage(f"{NOMBRE_CAMPO[campo].capitalize()} aplicado a {n} factura(s) de "
                                     f"{f.nombre_cliente}.", 6000)

    # ------------------------------------------------------------------
    # Valores por defecto
    def _construir_opciones(self) -> None:
        while self.rejilla.count():
            w = self.rejilla.takeAt(0).widget()
            if w is not None:
                w.hide()            # que no quede dibujado encima mientras se borra
                w.setParent(None)
                w.deleteLater()
        self.controles = {}
        self.caja.setEnabled(self.empresa is not None)
        if self.empresa is None:
            return
        e, cat = self.empresa, self.empresa.catalogos
        previos = []
        for ruta in sorted(e.carpeta_reportes.glob("RESU*.json")):
            try:
                previos.append(Reporte.abrir(ruta))
            except (OSError, ValueError, KeyError):
                pass
        self.previos = previos
        op = imf.opciones_sugeridas(e, previos)
        cliente = e.estructura.niveles[0]
        tipos_tx = dict(sorted(cat.tabla("TT").items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0))
        c_ttr = _combo_dict(tipos_tx)
        c_ttb = _combo_dict(dict(sorted(cat.tabla("TB").items())))
        e_adb = QLineEdit(op.adb)
        e_adb.setMaximumWidth(90)
        c_inst = _combo_dict(imf.NOMBRE_INSTRUMENTO)
        c_inst.setToolTip("Cómo registrar la forma de pago «20 - otros con utilización del sistema financiero» "
                          "(transferencias, cheques…), que la factura no detalla.")
        c_aec = ControlBuscador(cliente.campo("AEC"), cat.tabla("AE"),
                                "Escriba la actividad (ej.: construcción de edificios) o su código…")
        c_aec.setToolTip("Para clientes nuevos. Los clientes que ya estaban en reportes anteriores conservan la suya.")
        c_ccc = ControlBuscador(cliente.campo("CCC"), cat.tabla("C"), "Escriba el cantón (ej.: Quito) o su código…")
        c_ccc.setToolTip("Si la dirección de la factura no menciona un cantón conocido.")
        e_cat = QLineEdit(e.agencia_defecto())
        e_cat.setMaxLength(9)
        e_cat.setMaximumWidth(120)
        for combo, valor in ((c_ttr, op.ttr), (c_ttb, op.ttb), (c_inst, op.instrumento_20)):
            combo.setCurrentIndex(max(combo.findData(valor), 0))
        c_aec.poner_valor(op.aec)
        c_ccc.poner_valor(op.ccc)
        self.controles = {"ttr": c_ttr, "ttb": c_ttb, "adb": e_adb, "instrumento_20": c_inst, "aec": c_aec,
                          "ccc": c_ccc, "agencia": e_cat}
        nota = QLabel("Se usan en las facturas que no tienen un valor elegido ni datos de un mes anterior del mismo "
                      "cliente (en la tabla salen <i>en gris</i>; los de un mes anterior, <span style='color:#1f4e9c'>"
                      "en azul</span>). Doble clic en una celda de la tabla para cambiar solo esa factura.")
        nota.setWordWrap(True)
        self.rejilla.addWidget(nota, 0, 0, 1, 4)
        filas = [("Tipo de transacción:", c_ttr, "Tipo de bien:", c_ttb),
                 ("Pago «20 - otros con sistema financiero» como:", c_inst, "Área del bien (m²):", e_adb),
                 ("Actividad económica (clientes nuevos):", c_aec, "Código de agencia:", e_cat),
                 ("Cantón (si la dirección no lo dice):", c_ccc, "", None)]
        for r, (t1, w1, t2, w2) in enumerate(filas, start=1):
            self.rejilla.addWidget(QLabel(t1), r, 0, Qt.AlignRight)
            self.rejilla.addWidget(w1, r, 1)
            if w2 is not None:
                self.rejilla.addWidget(QLabel(t2), r, 2, Qt.AlignRight)
                self.rejilla.addWidget(w2, r, 3)
        self.rejilla.setColumnStretch(1, 3)
        self.rejilla.setColumnStretch(3, 1)
        # al cambiar un valor por defecto, la tabla muestra el nuevo en las facturas que lo usan
        for combo in (c_ttr, c_ttb, c_inst):
            combo.currentIndexChanged.connect(lambda _i: self._mostrar_lista())
        e_adb.editingFinished.connect(self._mostrar_lista)
        for buscador in (c_aec, c_ccc):
            buscador.cambiado.connect(lambda: self._mostrar_lista() if self.controles else None)

    def _opciones(self) -> imf.Opciones:
        c = self.controles
        return imf.Opciones(ttr=c["ttr"].currentData(), ttb=c["ttb"].currentData(),
                            adb=entero(c["adb"].text()) or "0", instrumento_20=c["instrumento_20"].currentData(),
                            aec=c["aec"].valor(), ccc=c["ccc"].valor() or "1701")

    # ------------------------------------------------------------------
    # Facturas
    def agregar(self, rutas: list[str] | None = None) -> None:
        if self.empresa is None:
            QMessageBox.information(self, "Facturas", "Primero elija o agregue una empresa con «Empresas…».")
            return
        if not rutas:
            rutas, _ = QFileDialog.getOpenFileNames(self, "Facturas de venta", str(Path.home()),
                                                    "Facturas (*.xml *.pdf *.zip *.txt);;Todos (*)")
        if not rutas:
            return
        leidos = facturas.leer_rutas(rutas)
        propias = [f for f in leidos if isinstance(f, facturas.Factura) and f.tipo == "01" and f.fecha
                   and (not self.empresa.ruc or f.ruc_emisor == self.empresa.ruc)]
        meses = {(f.fecha.year, f.fecha.month) for f in propias}
        if len(meses) == 1 and next(iter(meses)) != (self.anio, self.mes):
            anio, mes = next(iter(meses))
            if not self.lista or QMessageBox.question(
                    self, "Mes", f"Las facturas son de {MESES[mes - 1]} {anio}. ¿Cambiar a ese mes?") == QMessageBox.Yes:
                self.s_anio.blockSignals(True)
                self.s_anio.setValue(anio)
                self.s_anio.blockSignals(False)
                self.c_mes.setCurrentIndex(mes - 1)
        base = Reporte(self.empresa.codigo, self.anio, self.mes)
        propuestas = imf.analizar(leidos, self.empresa, base, self._opciones())
        ya = {f.clave_acceso or f.numero for f in self.lista}
        agregadas, omitidas = 0, []
        for p in propuestas:
            if p.estado == imf.OMITIR or p.factura is None:
                omitidas.append(f"• {p.archivo}: {p.texto}")
                continue
            clave = p.factura.clave_acceso or p.factura.numero
            if clave in ya:
                omitidas.append(f"• {p.archivo}: ya está en la lista")
                continue
            ya.add(clave)
            self.lista.append(p.factura)
            agregadas += 1
        self._guardar_lista()
        self._mostrar_lista()
        if omitidas:
            texto = f"Se agregaron {agregadas} factura(s).\n\nNo se agregaron {len(omitidas)}:\n" + "\n".join(omitidas[:25])
            if len(omitidas) > 25:
                texto += f"\n… y {len(omitidas) - 25} más."
            QMessageBox.information(self, "Facturas", texto)

    def _ruc_elegido(self) -> str:
        fila = self.tabla.currentRow()
        if 0 <= fila < len(self.lista):
            return self.lista[fila].id_cliente
        return ""

    def copiar_ruc(self, ruc: str | None = None) -> None:
        ruc = ruc or self._ruc_elegido()
        if ruc:
            QGuiApplication.clipboard().setText(ruc)
            self.statusBar().showMessage(f"RUC / cédula {ruc} copiado al portapapeles.", 5000)

    def consultar_ruc(self, ruc: str | None = None) -> None:
        ruc = ruc or self._ruc_elegido()
        if ruc:
            QGuiApplication.clipboard().setText(ruc)
            self.statusBar().showMessage(f"RUC {ruc} copiado: péguelo con Ctrl+V en la página del SRI.", 10000)
        else:
            self.statusBar().showMessage("Elija una factura de la tabla para copiar su RUC.", 6000)
        QDesktopServices.openUrl(QUrl(URL_CONSULTA_RUC))

    def _menu_tabla(self, punto) -> None:
        indice = self.tabla.indexAt(punto)
        if not indice.isValid() or indice.row() >= len(self.lista):
            return
        fila, col = indice.row(), indice.column()
        f = self.lista[fila]
        menu = QMenu(self)
        if col == C_AEC:
            self.tabla.selectRow(fila)
            menu.addAction("Asignar actividad económica…", lambda: self.asignar_actividad(f))
        elif col in CAMPO_COLUMNA:
            campo = CAMPO_COLUMNA[col]
            filas = self._filas_objetivo(fila)
            nombre = NOMBRE_CAMPO[campo]
            menu.addAction(f"Cambiar {nombre}…", lambda: self.tabla.editItem(self.tabla.item(fila, col)))
            menu.addAction(f"Aplicar este {nombre} a todas las facturas de este cliente",
                           lambda: self.aplicar_al_cliente(fila, campo))
            if any(campo in self.lista[r].resu for r in filas):
                menu.addAction(f"Volver al automático (mes anterior o por defecto)"
                               + (f" en {len(filas)} facturas" if len(filas) > 1 else ""),
                               lambda: self.volver_automatico(filas, campo))
        else:
            return
        menu.exec(self.tabla.viewport().mapToGlobal(punto))

    def asignar_actividad(self, f: facturas.Factura) -> None:
        """Guarda la actividad económica de un cliente (se usa este mes y los siguientes)."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox

        e = self.empresa
        directorio = e.directorio_clientes()
        d = QDialog(self)
        d.setWindowTitle("Actividad económica del cliente")
        d.setMinimumWidth(720)
        buscador = ControlBuscador(None, e.catalogos.tabla("AE"),
                                   "Escriba la actividad (ej.: construcción de edificios) o su código…")
        buscador.poner_valor(directorio.get(f.id_cliente, {}).get("AEC", ""))
        consulta = QPushButton("Consultar RUC en el SRI")
        consulta.clicked.connect(lambda: self.consultar_ruc(f.id_cliente))
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Ok).setText("Guardar")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botones.accepted.connect(d.accept)
        botones.rejected.connect(d.reject)
        lay = QVBoxLayout(d)
        lay.addWidget(QLabel(f"<b>{f.nombre_cliente}</b> — {f.id_cliente}"))
        fila = QHBoxLayout()
        fila.addWidget(buscador, 1)
        fila.addWidget(consulta)
        lay.addLayout(fila)
        lay.addWidget(botones)
        if d.exec() != QDialog.Accepted or not buscador.valor():
            return
        self.guardar_actividad(f, buscador.valor())

    def guardar_actividad(self, f: facturas.Factura, codigo: str) -> None:
        """Recuerda la actividad económica del cliente (este mes y los siguientes)."""
        e = self.empresa
        datos = e.directorio_clientes().get(f.id_cliente) or {
            "IDE": f.id_cliente, "NRS": " ".join(f.nombre_cliente.upper().split()),
            "TID": imf.TIPO_ID.get(f.tipo_id_cliente, "")}
        datos["AEC"] = codigo
        e.recordar_clientes([datos])
        fila = self.tabla.currentRow()
        self._mostrar_lista()
        self.tabla.selectRow(fila)
        self.statusBar().showMessage(f"Actividad {codigo} guardada para {f.nombre_cliente}.", 6000)

    def _doble_clic(self, fila: int, columna: int) -> None:
        if fila >= len(self.lista):
            return
        if columna == C_RUC:
            self.copiar_ruc(self.lista[fila].id_cliente)
        elif columna == C_AEC or columna in CAMPO_COLUMNA:
            self.tabla.editItem(self.tabla.item(fila, columna))

    def quitar(self) -> None:
        filas = sorted({i.row() for i in self.tabla.selectedIndexes()}, reverse=True)
        for fila in filas:
            del self.lista[fila]
        self._guardar_lista()
        self._mostrar_lista()

    def vaciar(self) -> None:
        if self.lista and QMessageBox.question(self, "Quitar todas", "¿Quitar todas las facturas de este mes?") \
                == QMessageBox.Yes:
            self.lista = []
            self._guardar_lista()
            self._mostrar_lista()

    # ------------------------------------------------------------------
    # Generar y UAFI
    def generar(self) -> None:
        e = self.empresa
        if e is None or not self.lista:
            return
        agencia = self.controles["agencia"].text().strip()
        if not (agencia.isdigit() and len(agencia) in (8, 9) and agencia.startswith(e.codigo)):
            QMessageBox.warning(self, "Código de agencia", f"El código de agencia debe tener 8 o 9 dígitos y empezar "
                                                          f"con el código de la empresa ({e.codigo}).")
            return
        if agencia != e.agencia:
            e.agencia = agencia
            e.guardar()
        opciones = self._opciones()
        rep, _props = imf.construir_reporte(e, self.anio, self.mes, self.lista, opciones, self.anteriores)
        mensajes = [m for m in validar(rep, e.estructura, e.catalogos) if m.es_error]
        if mensajes:
            con_problema: set[str] = set()   # números de factura afectados
            lineas = []
            for m in mensajes:
                cliente = rep.registro(m.ruta[:1]) if m.ruta else None
                operacion = rep.registro(m.ruta[:2]) if len(m.ruta) >= 2 else None
                if operacion is not None:
                    con_problema.add(operacion.get("NCT"))
                    donde = f"Factura {operacion.get('NCT')} ({cliente.get('NRS')})"
                elif cliente is not None:
                    con_problema.update(o.get("NCT") for o in cliente.hijos)
                    donde = f"Cliente {cliente.get('NRS')}"
                else:
                    donde = "Reporte"
                lineas.append(f"• {donde}: {m.texto}")
            caja = QMessageBox(self)
            caja.setIcon(QMessageBox.Warning)
            caja.setWindowTitle("Revisar")
            caja.setText(f"Hay {len(mensajes)} dato(s) que la UAFE podría no aceptar:\n\n" + "\n".join(lineas[:15])
                         + ("\n…" if len(lineas) > 15 else ""))
            b_todas = caja.addButton("Generar con todas", QMessageBox.AcceptRole)
            b_sin = caja.addButton(f"Generar sin esas facturas ({len(con_problema)})", QMessageBox.ActionRole)
            b_cancelar = caja.addButton("Cancelar", QMessageBox.RejectRole)
            caja.setDefaultButton(b_cancelar)
            caja.exec()
            if caja.clickedButton() is b_sin:
                lista = [f for f in self.lista if f.numero not in con_problema]
                if not lista:
                    QMessageBox.information(self, "Generar", "No queda ninguna factura para generar.")
                    return
                rep, _props = imf.construir_reporte(e, self.anio, self.mes, lista, opciones, self.anteriores)
            elif caja.clickedButton() is not b_todas:
                return
        cfg = QSettings()
        base = Path(cfg.value(f"exportar/{e.id}", str(carpeta_documentos() / e.nombre)))
        sugerida = base / f"{self.anio}-{self.mes:02d}"
        try:
            sugerida.mkdir(parents=True, exist_ok=True)
        except OSError:
            sugerida = Path.home()
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta donde guardar los Excel", str(sugerida))
        if not carpeta:
            return
        destino = Path(carpeta)
        existentes = [destino / excel.nombre_plantilla(n, rep) for n in e.estructura.niveles]
        if any(p.exists() for p in existentes) and QMessageBox.question(
                self, "Generar", "Ya existen esos archivos en la carpeta. ¿Reemplazarlos?") != QMessageBox.Yes:
            return
        try:
            rutas = excel.exportar(rep, e.estructura, destino)
        except OSError as ex:
            QMessageBox.warning(self, "Generar", f"No se pudieron guardar:\n{ex}")
            return
        rep.guardar(e.carpeta_reportes / rep.nombre_archivo())
        cfg.setValue(f"exportar/{e.id}", str(destino.parent))
        t = rep.totales(e.estructura)
        caja = QMessageBox(self)
        caja.setWindowTitle("Excel generados")
        caja.setTextFormat(Qt.RichText)
        caja.setText(
            "<b>" + "<br>".join(r.name for r in rutas) + f"</b><br><br>Carpeta: {destino}<br>"
            f"Clientes: {t.get('CLIENTE', 0)} · Operaciones: {t.get('OPERACION', 0)} · "
            f"Transacciones: {t.get('TRANSACCION', 0)} · Total: $ {t.get('VVT', 0):,}".replace(",", ".") +
            "<br><br><b>En el UAFI:</b> escriba su usuario, elija "
            f"<b>{MESES[self.mes - 1]} {self.anio}</b>, cargue CLI, OPR y TRA, pulse Validar y luego Guardar.")
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
            self.statusBar().showMessage(f"Abriendo el UAFI de {self.empresa.nombre}…", 6000)
        except Exception as ex:  # noqa: BLE001
            QMessageBox.warning(self, "UAFI", str(ex))

    def administrar_empresas(self) -> None:
        DialogoEmpresas(self).exec()
        self._llenar_empresas(self.c_empresa.currentData() or "")

    # ------------------------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        rutas = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if rutas:
            self.agregar(rutas)

    def closeEvent(self, event):
        cfg = QSettings()
        cfg.setValue("simple/geometria", self.saveGeometry())
        cfg.setValue("simple/empresa", self.c_empresa.currentData() or "")
        super().closeEvent(event)
