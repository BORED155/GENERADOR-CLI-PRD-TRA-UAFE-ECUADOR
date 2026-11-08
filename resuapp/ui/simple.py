"""Pantalla única: empresa y mes → arrastrar facturas de venta → generar CLI, OPR y TRA → abrir el UAFI."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QGridLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QStyledItemDelegate,
                               QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import empresas as emp
from .. import excel, facturas, importar_facturas as imf, sri, uafi
from ..modelo import PROVINCIAS, Reporte, entero, periodo
from ..reglas import validar
from ..rutas import carpeta_documentos
from .campos import ControlBuscador
from .empresas import DialogoEmpresas

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre",
         "Noviembre", "Diciembre"]
COLUMNAS = ["Cliente", "RUC / cédula", "Actividad económica", "Tipo de transacción", "Pago", "Tipo de bien",
            "Área del bien (m²)", "Cantón", "Factura", "Fecha", "Total", "Forma de pago (SRI)", "Archivo"]
C_RUC, C_AEC, C_TTR, C_INST, C_TTB, C_ADB, C_CCO, C_FACT, C_TOTAL, C_FP = 1, 2, 3, 4, 5, 6, 7, 8, 10, 11
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
         "(también carpetas, ZIP o el TXT de comprobantes emitidos del SRI)\n\n"
         "o las plantillas CLI, OPR y TRA para revisarlas y cargarlas")


AYUDA = """
<h2>Cómo usar el Generador RESU UAFE</h2>
<p>Arma los archivos <b>CLI, OPR y TRA</b> del reporte RESU a partir de las facturas de venta del mes,
para cargarlos en el UAFI de la empresa.</p>

<h3>1. Elija la empresa y el mes</h3>
<p>Arriba, en <b>Empresa</b>, escoja con cuál va a trabajar, y el <b>mes y año</b> del reporte.
Si la empresa no está en la lista, agréguela con <b>«Empresas…»</b> (necesita su archivo uafi.zip).
La tabla empieza vacía: agregue las facturas que necesite de ese mes.</p>

<h3>2. Agregue las facturas de venta</h3>
<p><b>Arrastre</b> a la tabla los XML o PDF de las facturas (también una carpeta, un ZIP o el TXT de
comprobantes emitidos del SRI), o use <b>«Agregar facturas…»</b>.<br>
Solo se toman <b>facturas de venta de la empresa, del mes elegido y con cliente identificado</b>
(no consumidor final). Las demás se avisan y no se agregan.</p>

<p><b>¿Ya tiene las plantillas CLI, OPR y TRA?</b> Arrástrelas juntas a la tabla: el programa elige la
empresa y el mes, <b>las revisa con las reglas del manual de la UAFE</b> y le dice si tienen errores
(con el cliente y la operación de cada uno). Si están bien, las carga en la tabla para revisarlas o cambiarlas.</p>

<h3>3. Revise los datos de cada factura</h3>
<p>Cada fila tiene: actividad económica, tipo de transacción, pago, tipo de bien, área del bien, cantón,
<b>total</b> y <b>forma de pago</b>. El total y la forma de pago vienen de la factura; si los cambia, quedan
<b>en negrita</b> (el mouse muestra lo que decía la factura). Al cambiar la forma de pago, el pago de la UAFE
se ajusta solo (por ejemplo, 19 tarjeta de crédito → tarjeta de crédito).</p>
<ul>
<li><b>Flechita ▾</b>: elegir de la lista. &nbsp; <b>Doble clic</b>: escribir para buscar
(por nombre o código, sin importar tildes).</li>
<li>Con <b>varias filas seleccionadas</b>, el cambio se aplica a todas.</li>
<li><b>Clic derecho</b> en una celda: aplicar ese valor a todas las facturas del cliente, o volver al automático.</li>
</ul>
<p><b>Colores:</b>
<span style="color:#888"><i>gris</i></span> = valor automático (lo último usado) ·
<span style="color:#1f4e9c">azul</span> = como en un mes anterior de ese cliente ·
negro = elegido para esa factura o según su forma de pago ·
<span style="background:#ffe08a">ámbar</span> = actividad tomada del SRI que conviene revisar ·
<span style="background:#f8d7da">rojo</span> = ese tipo de transacción no admite ese pago (corríjalo).</p>
<p>La <b>actividad económica</b> es del cliente: una sola por cliente, vale para todas sus facturas.
Si el cliente no la tiene, el programa <b>consulta su RUC en el SRI</b> (necesita internet) y asigna el código
más parecido del catálogo, junto con su cantón. Si la coincidencia no es segura, queda
<span style="background:#ffe08a">en ámbar</span>: el mouse muestra lo que dice el SRI y otras opciones; corríjala con la
flechita o confírmela con clic derecho. Lo que usted ya puso nunca se cambia.
También puede verla con <b>«Consultar RUC en el SRI»</b> (copia el RUC; péguelo con Ctrl+V).</p>

<h3>4. Valide</h3>
<p>Pulse <b style="color:#ef6c00">✔ Validar</b>: revisa todo con las reglas del manual de la UAFE sin generar nada.
Si está bien dice <b>«Listo para generar»</b>; si no, explica cada problema y deja
<span style="background:#f8d7da">en rojo</span> las facturas afectadas (pase el mouse para ver el detalle).
Corrija y vuelva a validar.</p>

<h3>5. Genere los Excel y cárguelos en el UAFI</h3>
<ol>
<li>Pulse <b style="color:#2e7d32">Generar Excel (CLI, OPR, TRA)</b> y elija la carpeta. Si algún dato
podría no ser aceptado por la UAFE, se avisa antes.</li>
<li>Pulse <b style="color:#c62828">Abrir UAFI de la empresa</b>: escriba el usuario, elija el mes,
cargue CLI, OPR y TRA, pulse <b>Validar</b> y luego <b>Guardar</b>.</li>
</ol>
<p><i>En Linux el UAFI guarda el .uaf con un nombre de Windows (por ejemplo «mi carpeta\\RESU….uaf», fuera de
la carpeta elegida). Si lo abrió con el botón rojo, el programa lo corrige solo y le avisa dónde quedó.</i></p>

<h3>Datos de la empresa</h3>
<p>Abajo se ven nombre, RUC, código de registro, usuario SISLAFT y código de agencia.
<b>Doble clic</b> en un dato lo copia para pegarlo en el SISLAFT o el UAFI. Se corrigen en «Empresas…».</p>

<h3>Qué se recuerda solo</h3>
<p>La actividad económica de cada cliente y, de los reportes generados, lo que usó con cada cliente
(tipo de transacción, pago, tipo de bien, área y cantón): el mes siguiente sale en azul.</p>
"""


def _entero_miles(valor: Decimal) -> str:
    """1234.56 -> «1.234» (sin centavos, como va al reporte)."""
    return f"{int(valor):,}".replace(",", ".")


def _dinero(valor: Decimal) -> str:
    """1234.56 -> «1.234,56»."""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _html(texto: str) -> str:
    import html

    return html.escape(texto)


class DelegadoLista(QStyledItemDelegate):
    """Celda con flechita ▾: clic en la flecha = lista para elegir; doble clic = escribir y buscar.

    Campos: aec (actividad económica, del cliente) y ttr, inst, ttb, cco (de la factura)."""

    ANCHO_FLECHA = 18

    def __init__(self, ventana: "VentanaSimple", campo: str):
        super().__init__(ventana)
        self.ventana, self.campo = ventana, campo
        self.modo = "lista"   # «lista» (flechita) o «escribir» (doble clic)

    # --- dibujo de la flechita ---
    def _zona_flecha(self, rect):
        from PySide6.QtCore import QRect

        return QRect(rect.right() - self.ANCHO_FLECHA, rect.top(), self.ANCHO_FLECHA, rect.height())

    def paint(self, painter, option, index):
        from PySide6.QtWidgets import QApplication, QStyle, QStyleOption

        opt = type(option)(option)
        opt.rect = option.rect.adjusted(0, 0, -self.ANCHO_FLECHA, 0)   # que el texto no tape la flecha
        super().paint(painter, opt, index)
        flecha = QStyleOption()
        flecha.rect = self._zona_flecha(option.rect).adjusted(4, 0, -4, 0)
        flecha.palette = option.palette
        flecha.state = QStyle.State_Enabled
        QApplication.style().drawPrimitive(QStyle.PE_IndicatorArrowDown, flecha, painter)

    def sizeHint(self, option, index):
        tam = super().sizeHint(option, index)
        tam.setWidth(tam.width() + self.ANCHO_FLECHA + 4)   # espacio para la flecha
        return tam

    def editorEvent(self, event, model, option, index):
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton and \
                self._zona_flecha(option.rect).contains(event.position().toPoint()):
            self.modo = "lista"
            self.ventana.tabla.setCurrentIndex(index) if not self.ventana.tabla.selectionModel().isSelected(index) \
                else None
            self.ventana.tabla.edit(index)
            return True
        return super().editorEvent(event, model, option, index)

    # --- opciones ---
    def _tabla(self) -> dict[str, str]:
        if self.campo == "aec":
            return self.ventana.empresa.catalogos.tabla("AE")
        return self.ventana.opciones_campo(self.campo)

    def _texto(self, codigo: str, nombre: str) -> str:
        if self.campo == "inst":
            return nombre
        if self.campo == "cco":
            provincia = PROVINCIAS.get(codigo[:2], "")
            return f"{nombre} ({provincia}) — {codigo}" if provincia else f"{nombre} — {codigo}"
        return f"{codigo} — {nombre}"

    def createEditor(self, parent, option, index):
        modo, self.modo = self.modo, "lista"
        tabla = self._tabla()
        if modo == "lista":
            c = QComboBox(parent)
            c.setMaxVisibleItems(18)
            items = [(self._texto(k, v), k) for k, v in tabla.items() if not (self.campo == "cco" and k == "0000")]
            if self.campo in ("cco", "aec"):
                items.sort(key=lambda t: t[0] if self.campo == "cco" else t[1])
            for texto, codigo in items:
                c.addItem(texto, codigo)
            c.activated.connect(lambda _i, ed=c: (self.commitData.emit(ed), self.closeEditor.emit(ed)))
            return c
        # escribir: busca por partes del nombre o el código, sin tildes (y la provincia en los cantones)
        buscable = {k: (f"{v} ({PROVINCIAS.get(k[:2], '')})" if self.campo == "cco" else v)
                    for k, v in tabla.items() if not (self.campo == "cco" and k == "0000")}
        editor = ControlBuscador(None, buscable, "Escriba para buscar y elija de la lista…", parent)
        editor.setAutoFillBackground(True)
        editor.completer.activated.connect(lambda _t, ed=editor: (self.commitData.emit(ed), self.closeEditor.emit(ed)))
        return editor

    def setEditorData(self, editor, index):
        actual = index.data(Qt.UserRole) or ""
        if isinstance(editor, QComboBox):
            editor.setCurrentIndex(max(editor.findData(actual), 0))
            editor.showPopup()
        else:
            editor.edit.setPlaceholderText(f"Actual: {index.data()}  — escriba para buscar")
            editor.codigo = ""
            editor.edit.clear()
            editor.edit.setFocus()

    def updateEditorGeometry(self, editor, option, index):
        r = option.rect
        r.setWidth(max(r.width(), 360))
        editor.setGeometry(r)

    def setModelData(self, editor, model, index):
        codigo = (editor.currentData() if isinstance(editor, QComboBox) else editor.valor()) or ""
        if not codigo or index.row() >= len(self.ventana.lista):
            return
        if self.campo == "aec":
            if codigo != (index.data(Qt.UserRole) or ""):
                self.ventana.guardar_actividad(self.ventana.lista[index.row()], codigo)
        elif self.campo == "fp":
            self.ventana.cambiar_forma_pago(index.row(), codigo)
        else:
            self.ventana.cambiar_campo(index.row(), self.campo, codigo)


class DelegadoTotal(QStyledItemDelegate):
    """Total de la factura: doble clic para escribirlo (acepta 1234,56 o 1234.56)."""

    def __init__(self, ventana: "VentanaSimple"):
        super().__init__(ventana)
        self.ventana = ventana

    def createEditor(self, parent, option, index):
        from PySide6.QtCore import QRegularExpression
        from PySide6.QtGui import QRegularExpressionValidator

        e = QLineEdit(parent)
        e.setAlignment(Qt.AlignRight)
        e.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{1,12}([.,]\d{0,2})?"), e))
        return e

    def setEditorData(self, editor, index):
        editor.setText(str(int(Decimal(index.data(Qt.UserRole) or "0"))))
        editor.selectAll()

    def setModelData(self, editor, model, index):
        texto = editor.text().strip().replace(",", ".")
        if texto:
            self.ventana.cambiar_total(index.row(), texto)


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


class CampoCopiable(QLabel):
    """Dato de la empresa: doble clic lo copia al portapapeles."""

    def __init__(self, ventana: "VentanaSimple"):
        super().__init__()
        self.ventana = ventana
        self.valor = ""
        self.setStyleSheet("QLabel { background: white; border: 1px solid #c8c8c8; border-radius: 3px; "
                           "padding: 5px 8px; font-weight: bold; } QLabel:hover { border-color: #2e7d32; }")
        self.setCursor(Qt.PointingHandCursor)
        self.setTextInteractionFlags(Qt.NoTextInteraction)

    def poner(self, valor: str) -> None:
        self.valor = (valor or "").strip()
        self.setText(self.valor or "—")
        self.setToolTip(f"{self.valor}\nDoble clic para copiar" if self.valor else "Sin dato (complételo en «Empresas…»)")

    def mouseDoubleClickEvent(self, event):
        event.accept()   # el doble clic es solo para copiar: no pasa a la ventana
        if self.valor:
            QGuiApplication.clipboard().setText(self.valor)
            self.ventana.statusBar().showMessage(f"Copiado al portapapeles: {self.valor}", 5000)
            self.setStyleSheet(self.styleSheet().replace("background: white", "background: #d4edda"))
            from PySide6.QtCore import QTimer
            QTimer.singleShot(600, lambda: self.setStyleSheet(
                self.styleSheet().replace("background: #d4edda", "background: white")))


class _SenalUaf(QObject):
    listo = Signal(object, bool, object)


class _SenalSri(QObject):
    resultado = Signal(object, object, object, int, int)   # empresa, factura, contribuyente, hecho, total
    fin = Signal(object, bool)                             # identificaciones que quedaron sin consultar, hubo fallo


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


class VentanaSimple(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Generador RESU UAFE")
        self.setAcceptDrops(True)
        self.empresa: emp.Empresa | None = None
        self.lista: list[facturas.Factura] = []
        self._cargando = False
        self._sin_generar = False      # la tabla tiene cambios que no llegaron a un Excel
        self._avisados: set[str] = set()   # archivos dañados ya avisados en esta sesión
        self._sri_pedidos: set[tuple[str, str]] = set()    # (empresa, cliente) ya consultados en esta sesión
        self._sri_comparadores: dict[str, sri.Comparador] = {}
        self._sri_por_dibujar = False
        self._senal_sri = _SenalSri()
        self._senal_sri.resultado.connect(self._sri_resultado)
        self._senal_sri.fin.connect(self._sri_fin)
        self._marcas: dict[tuple[str, str], list[str]] = {}   # (cliente, factura) -> problemas al validar
        self._senal_uaf = _SenalUaf()
        self._senal_uaf.listo.connect(self._uaf_revisado)

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
        arriba.addSpacing(20)
        b_ayuda = QPushButton("?  Ayuda")
        b_ayuda.setToolTip("Cómo usar el programa")
        b_ayuda.clicked.connect(self.mostrar_ayuda)
        arriba.addWidget(b_ayuda)

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
        b_sri.setStyleSheet("QPushButton { background: #1565c0; color: white; font-weight: bold; padding: 4px 12px; "
                            "border-radius: 4px; }")
        self.delegados = {col: DelegadoLista(self, campo) for col, campo in
                          ((C_AEC, "aec"), (C_TTR, "ttr"), (C_INST, "inst"), (C_TTB, "ttb"), (C_CCO, "cco"))}
        for col, delegado in self.delegados.items():
            self.tabla.setItemDelegateForColumn(col, delegado)
        self.tabla.setItemDelegateForColumn(C_ADB, DelegadoArea(self))
        self.delegados[C_FP] = DelegadoLista(self, "fp")
        self.tabla.setItemDelegateForColumn(C_FP, self.delegados[C_FP])
        self.tabla.setItemDelegateForColumn(C_TOTAL, DelegadoTotal(self))
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
        self.b_validar = QPushButton("✔ Validar")
        self.b_validar.setToolTip("Revisa las facturas de la tabla con las reglas del manual de la UAFE, "
                                  "sin generar los Excel")
        self.b_validar.setStyleSheet(
            "QPushButton { background: #ef6c00; color: white; font-weight: bold; padding: 4px 14px; border-radius: 4px; }"
            "QPushButton:disabled { background: #f5c08f; }")
        self.b_validar.clicked.connect(self.validar_tabla)
        botones_lista.addWidget(self.b_validar)
        botones_lista.addStretch(1)
        botones_lista.addWidget(self.resumen)

        # --- valores por defecto ---
        self.caja = QGroupBox("Empresa")
        self.rejilla = QGridLayout(self.caja)
        self.datos_empresa: dict[str, CampoCopiable] = {}
        for col, (clave, titulo) in enumerate((("nombre", "Nombre"), ("ruc", "RUC"),
                                               ("codigo", "Código de registro"), ("usuario", "Usuario SISLAFT"),
                                               ("agencia", "Código de agencia"))):
            etiqueta = QLabel(titulo)
            etiqueta.setStyleSheet("color: #555;")
            campo = CampoCopiable(self)
            self.datos_empresa[clave] = campo
            self.rejilla.addWidget(etiqueta, 0, col)
            self.rejilla.addWidget(campo, 1, col)
        self.rejilla.setColumnStretch(0, 4)
        for col in range(1, 5):
            self.rejilla.setColumnStretch(col, 1)
        self.opciones_base = imf.Opciones()

        # --- acciones ---
        self.b_generar = QPushButton("Generar Excel  (CLI, OPR, TRA)")
        self.b_generar.setStyleSheet(
            "QPushButton { background: #2e7d32; color: white; font-weight: bold; padding: 8px 18px; border-radius: 4px; }"
            "QPushButton:disabled { background: #a5c9a7; }")
        self.b_generar.clicked.connect(self.generar)
        self.b_uafi = QPushButton("Abrir UAFI de la empresa")
        self.b_uafi.setStyleSheet(
            "QPushButton { background: #c62828; color: white; font-weight: bold; padding: 8px 18px; border-radius: 4px; }"
            "QPushButton:disabled { background: #e3a5a5; }")
        self.b_uafi.clicked.connect(self.abrir_uafi)
        abajo = QHBoxLayout()
        abajo.addStretch(1)
        abajo.addWidget(self.b_generar)
        abajo.addWidget(self.b_uafi)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addLayout(arriba)
        lay.addWidget(self.tabla, 1)
        lay.addSpacing(10)   # separación entre la barra de desplazamiento y los botones
        lay.addLayout(botones_lista)
        lay.addWidget(self.caja)
        lay.addLayout(abajo)
        self.setCentralWidget(central)

        self.c_empresa.currentIndexChanged.connect(lambda _i: self._al_cambiar(self._empresa_elegida))
        self.c_mes.currentIndexChanged.connect(lambda _i: self._al_cambiar(self._cargar_lista))
        self.s_anio.valueChanged.connect(lambda _v: self._al_cambiar(self._cargar_lista))
        cfg = QSettings()
        self.restoreGeometry(cfg.value("simple/geometria", b""))
        if not cfg.value("simple/geometria"):
            self.resize(1180, 720)
        self._llenar_empresas()   # al abrir: sin empresa elegida y la tabla vacía

    # ------------------------------------------------------------------
    # Empresa, mes y lista guardada
    def _llenar_empresas(self, seleccionar: str = "") -> None:
        self.c_empresa.blockSignals(True)
        self.c_empresa.clear()
        self.c_empresa.addItem("— Elija la empresa —", None)
        for e in emp.listar():
            if e.tiene_uafi:
                self.c_empresa.addItem(f"{e.nombre}   (código {e.codigo})", e.id)
        self.c_empresa.setCurrentIndex(max(self.c_empresa.findData(seleccionar), 0) if seleccionar else 0)
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

    def _cargar_lista(self) -> None:
        self.anteriores = imf.ultimos_por_cliente(self.previos, antes_de=periodo(self.anio, self.mes)) \
            if self.empresa else {}
        self.lista = []   # siempre desde cero: se agregan las facturas que se necesiten del mes
        self._seleccion = (self.empresa.id if self.empresa else None, self.c_mes.currentIndex(), self.anio)
        self._mostrar_lista()

    def _puede_descartar(self) -> bool:
        """La tabla no se guarda: antes de vaciarla, pregunta si tiene cambios que no llegaron a un Excel."""
        return not (self.lista and self._sin_generar) or QMessageBox.question(
            self, "Facturas sin generar", f"La tabla tiene {len(self.lista)} factura(s) que todavía no se generaron "
            "y se van a perder. ¿Continuar?") == QMessageBox.Yes

    def _al_cambiar(self, accion) -> None:
        """Empresa, mes o año cambiados a mano: si el usuario no quiere perder la tabla, se vuelve a lo anterior."""
        if self._puede_descartar():
            accion()
            return
        ident, mes, anio = self._seleccion
        self._fijar_seleccion(self.c_empresa.findData(ident), mes, anio)

    def _fijar_seleccion(self, indice_empresa: int, mes: int, anio: int) -> None:
        """Cambia los controles sin disparar sus avisos."""
        for control in (self.c_empresa, self.c_mes, self.s_anio):
            control.blockSignals(True)
        self.c_empresa.setCurrentIndex(max(indice_empresa, 0))
        self.c_mes.setCurrentIndex(mes)
        self.s_anio.setValue(anio)
        for control in (self.c_empresa, self.c_mes, self.s_anio):
            control.blockSignals(False)

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
        if campo == "fp":
            return dict(imf.FORMAS_PAGO_SRI)
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

    def _mostrar_lista(self, conservar_marcas: bool = False) -> None:
        """Dibuja la tabla. Las marcas de «Validar» se quitan cuando algo cambia (conservar_marcas=False)."""
        from ..reglas import INSTRUMENTOS_POR_TRANSACCION

        if not conservar_marcas:
            self._marcas = {}
            self._sin_generar = True

        self.lista.sort(key=lambda f: (f.fecha or dt.date.min, f.numero))
        directorio = self.empresa.directorio_clientes() if self.empresa else {}
        consultas = self.empresa.consultas_sri() if self.empresa else {}
        cat = self.empresa.catalogos if self.empresa else None
        opciones = self._opciones()
        cursiva = self.tabla.font()
        cursiva.setItalic(True)
        self.tabla.setRowCount(len(self.lista))
        for fila, f in enumerate(self.lista):
            formas = ", ".join(f"{c} {imf.FORMAS_PAGO_SRI.get(c, '')}".strip() for c, _v in f.pagos) or "—"
            aec = directorio.get(f.id_cliente, {}).get("AEC", "")
            actividad = f"{aec} — {cat.nombre('AE', aec)}" if aec else "(la de por defecto)"
            v = imf.valores_factura(f, opciones, self.anteriores, self._canton_cliente(f, directorio))
            valores = [f.nombre_cliente, f.id_cliente, actividad, "", "", "", "", "", f.numero,
                       f.fecha.strftime("%d/%m/%Y") if f.fecha else "", _entero_miles(f.total), formas, f.archivo]
            negrita = self.tabla.font()
            negrita.setBold(True)
            for col, texto in enumerate(valores):
                item = QTableWidgetItem(texto)
                if col == C_TOTAL:
                    item.setData(Qt.UserRole, str(f.total))
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    original = f.resu.get("total_factura")
                    if original is not None and Decimal(original) != f.total:
                        item.setFont(negrita)
                        texto_ayuda = f"Cambiado a mano (la factura dice {_dinero(Decimal(original))})"
                    else:
                        texto_ayuda = f"La factura dice {_dinero(f.total)}"
                    en_reporte = "Sin centavos: la UAFE pide valores sin decimales"
                    item.setToolTip(f"{texto}\n{texto_ayuda}\n{en_reporte}\nDoble clic para cambiarlo")
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.tabla.setItem(fila, col, item)
                    continue
                if col == C_FP:
                    codigos = [c for c, _v in f.pagos]
                    item.setData(Qt.UserRole, codigos[0] if len(codigos) == 1 else "")
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    cambio = f.resu.get("fp_factura")
                    if cambio is not None:
                        item.setFont(negrita)
                    item.setToolTip(f"{texto}\n" + (f"Cambiada a mano (la factura dice: {cambio or 'nada'})\n"
                                                    if cambio is not None else "")
                                    + "Flechita: elegir del catálogo · Doble clic: escribir para buscar")
                    self.tabla.setItem(fila, col, item)
                    continue
                item.setToolTip({C_AEC: f"{texto}\nFlechita: elegir de la lista · Doble clic: escribir para buscar\n"
                                        "(una por cliente: vale para todas sus facturas)",
                                 C_RUC: f"{texto}\nDoble clic para copiarlo"}.get(col, texto))
                if col == C_AEC:
                    item.setData(Qt.UserRole, aec)
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                if col == C_AEC and not aec:
                    item.setForeground(QColor("#888888"))
                if col == C_AEC and consultas.get(f.id_cliente, {}).get("codigo") == aec and aec:
                    self._marcar_sri(item, consultas[f.id_cliente], aec)
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
                item.setToolTip(f"{item.text()}\n{explicacion}\n"
                                + ("Doble clic para escribirla" if campo == "adb" else
                                   "Flechita: elegir de la lista · Doble clic: escribir para buscar")
                                + "\n(con varias filas seleccionadas, cambia todas)")
                if campo == "adb":
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabla.setItem(fila, col, item)
            # problemas encontrados al validar
            problemas = self._marcas.get((f.id_cliente, f.numero))
            if problemas:
                for col in (0, C_FACT):
                    it = self.tabla.item(fila, col)
                    it.setBackground(QColor("#f8d7da"))
                    it.setToolTip("⚠ Al validar:\n" + "\n".join(f"• {p}" for p in problemas))
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
        self.b_validar.setEnabled(hay and bool(self.lista))
        self.b_uafi.setEnabled(hay)
        nombre = f" — {self.empresa.nombre} — {MESES[self.mes - 1]} {self.anio}" if hay else ""
        self.setWindowTitle("Generador RESU UAFE" + nombre)

    def _marcar_sri(self, item: QTableWidgetItem, registro: dict, codigo: str) -> None:
        """Ayuda de la celda con lo que dijo el SRI; en ámbar si la coincidencia no es segura."""
        cat = self.empresa.catalogos
        ayuda = f"{item.text()}\nSegún el SRI: {registro.get('texto', '')}\n"
        if sri.es_dudosa(registro, codigo):
            item.setBackground(QColor("#ffe08a"))
            ayuda += "Coincidencia dudosa: revísela.\n"
            otras = "\n".join(f"• {c} — {cat.nombre('AE', c)}" for c in registro.get("otras", []))
            ayuda += f"Otras opciones:\n{otras}\n" if otras else ""
        item.setToolTip(ayuda + "Flechita: elegir de la lista · Clic derecho: confirmar o buscar")

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
        self._mostrar_lista()
        self.statusBar().showMessage(f"{NOMBRE_CAMPO[campo].capitalize()} cambiado en {len(filas)} factura(s).", 6000)

    def cambiar_total(self, fila: int, texto: str) -> None:
        from decimal import InvalidOperation

        try:
            valor = Decimal(int(Decimal(texto)))   # sin centavos, como va al reporte
        except (InvalidOperation, ValueError):
            return
        if fila >= len(self.lista) or valor <= 0:
            self.statusBar().showMessage("El total debe ser mayor que cero.", 6000)
            return
        f = self.lista[fila]
        if valor == f.total:
            return
        f.resu.setdefault("total_factura", str(f.total))   # para mostrar lo que decía la factura
        if len(f.pagos) == 1:
            f.pagos = [(f.pagos[0][0], valor)]
        f.total = valor
        self._mostrar_lista()
        self.statusBar().showMessage(f"Total de la factura {f.numero} cambiado a {_entero_miles(valor)}.", 6000)

    def cambiar_forma_pago(self, fila: int, codigo: str) -> None:
        """Forma de pago del SRI elegida a mano: el pago de la UAFE se vuelve a deducir de ella."""
        if not codigo or fila >= len(self.lista):
            return
        filas = self._filas_objetivo(fila)
        for r in filas:
            f = self.lista[r]
            f.resu.setdefault("fp_factura", ", ".join(c for c, _v in f.pagos))
            f.pagos = [(codigo, f.total)]
            f.resu.pop("inst", None)   # el pago (instrumento) sale de la forma de pago, salvo que se elija
        self._mostrar_lista()
        self.statusBar().showMessage(f"Forma de pago {codigo} {imf.FORMAS_PAGO_SRI.get(codigo, '')} en "
                                     f"{len(filas)} factura(s).", 6000)

    def volver_automatico(self, filas: list[int], campo: str) -> None:
        for r in filas:
            self.lista[r].resu.pop(campo, None)
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
        self._mostrar_lista()
        self.statusBar().showMessage(f"{NOMBRE_CAMPO[campo].capitalize()} aplicado a {n} factura(s) de "
                                     f"{f.nombre_cliente}.", 6000)

    # ------------------------------------------------------------------
    # Datos de la empresa y valores automáticos
    def _construir_opciones(self) -> None:
        """Lee los reportes anteriores de la empresa y muestra sus datos.

        Las facturas sin valor elegido ni mes anterior del mismo cliente usan lo último que se eligió o lo
        más frecuente en los reportes anteriores (opciones_sugeridas); en la tabla salen en gris."""
        e = self.empresa
        for clave, campo in self.datos_empresa.items():
            campo.poner(getattr(e, clave, "") if e is not None else "")
        if e is not None and not e.agencia:
            self.datos_empresa["agencia"].poner(e.agencia_defecto())
        self.caja.setEnabled(e is not None)
        self.previos = []
        self.opciones_base = imf.Opciones()
        if e is None:
            return
        for ruta in sorted(e.carpeta_reportes.glob("RESU*.json")):
            try:
                self.previos.append(Reporte.abrir(ruta))
            except (OSError, ValueError, KeyError):
                pass
        self.opciones_base = imf.opciones_sugeridas(e, self.previos)
        e.directorio_clientes(), e.valores_recordados()     # apartan el archivo si está dañado
        for nombre in e.archivos_danados():
            if f"{e.id}/{nombre}" not in self._avisados:
                self._avisados.add(f"{e.id}/{nombre}")
                QMessageBox.warning(self, "Archivo dañado", f"«{nombre}» de {e.nombre} no se pudo leer y se apartó para "
                                    "no perderlo. El programa volverá a aprender esos datos.")

    def _opciones(self) -> imf.Opciones:
        return imf.Opciones(**self.opciones_base.a_dict())

    # ------------------------------------------------------------------
    # Facturas
    def agregar(self, rutas: list[str] | None = None) -> None:
        if not rutas:
            rutas, _ = QFileDialog.getOpenFileNames(
                self, "Facturas de venta o plantillas CLI, OPR y TRA", str(Path.home()),
                "Facturas y plantillas (*.xml *.pdf *.zip *.txt *.xlsx);;Todos (*)")
        if not rutas:
            return
        plantillas = [r for r in rutas if r.lower().endswith(".xlsx")]
        if plantillas:
            self.importar_plantillas(plantillas)
            rutas = [r for r in rutas if not r.lower().endswith(".xlsx")]
            if not rutas:
                return
        if self.empresa is None:
            QMessageBox.information(self, "Facturas", "Primero elija o agregue una empresa con «Empresas…».")
            return
        leidos = facturas.leer_rutas(rutas)
        propias = [f for f in leidos if isinstance(f, facturas.Factura) and f.tipo == "01" and f.fecha
                   and (not self.empresa.ruc or f.ruc_emisor == self.empresa.ruc)]
        meses = {(f.fecha.year, f.fecha.month) for f in propias}
        if len(meses) == 1 and next(iter(meses)) != (self.anio, self.mes):
            anio, mes = next(iter(meses))
            if not self.lista or QMessageBox.question(
                    self, "Mes", f"Las facturas son de {MESES[mes - 1]} {anio}. ¿Cambiar a ese mes?") == QMessageBox.Yes:
                self._fijar_seleccion(self.c_empresa.currentIndex(), mes - 1, anio)
                self._cargar_lista()        # también si solo cambió el año
        base = Reporte(self.empresa.codigo, self.anio, self.mes)
        propuestas = imf.analizar(leidos, self.empresa, base, self._opciones())
        ya = {f.clave_acceso or f"{f.id_cliente}|{f.numero}" for f in self.lista}
        agregadas, omitidas = 0, []
        for p in propuestas:
            if p.estado == imf.OMITIR or p.factura is None:
                omitidas.append(f"• {p.archivo}: {p.texto}")
                continue
            clave = p.factura.clave_acceso or f"{p.factura.id_cliente}|{p.factura.numero}"
            if clave in ya:
                omitidas.append(f"• {p.archivo}: ya está en la lista")
                continue
            ya.add(clave)
            self.lista.append(p.factura)
            agregadas += 1
        self._mostrar_lista()
        self._consultar_sri()
        if omitidas:
            texto = f"Se agregaron {agregadas} factura(s).\n\nNo se agregaron {len(omitidas)}:\n" + "\n".join(omitidas[:25])
            if len(omitidas) > 25:
                texto += f"\n… y {len(omitidas) - 25} más."
            QMessageBox.information(self, "Facturas", texto)

    # ------------------------------------------------------------------
    # Actividad económica y cantón desde el SRI (en segundo plano, para no congelar la ventana)
    def _consultar_sri(self) -> None:
        e = self.empresa
        if e is None:
            return
        directorio, hechas = e.directorio_clientes(), e.consultas_sri()
        pendientes: dict[str, facturas.Factura] = {}
        for f in self.lista:
            datos = directorio.get(f.id_cliente, {})
            if (not datos.get("AEC") or not datos.get("CCC")) and f.id_cliente not in hechas \
                    and (e.id, f.id_cliente) not in self._sri_pedidos and sri.ruc_de(f.id_cliente):
                pendientes[f.id_cliente] = f
        if pendientes:
            self._sri_pedidos |= {(e.id, i) for i in pendientes}
            self.statusBar().showMessage(f"Consultando {len(pendientes)} cliente(s) en el SRI…")
            self._lanzar_sri(e, list(pendientes.values()))

    def _lanzar_sri(self, e: emp.Empresa, lista: list[facturas.Factura]) -> None:
        import threading

        threading.Thread(target=self._trabajo_sri, args=(e, lista), daemon=True).start()

    def _trabajo_sri(self, e: emp.Empresa, lista: list[facturas.Factura]) -> None:
        """Solo consulta (en otro hilo); guardar y dibujar se hace en la ventana, al recibir la señal."""
        import time

        for hecho, f in enumerate(lista, start=1):
            try:
                c = sri.consultar(f.id_cliente)
            except sri.SinConexion:
                self._senal_sri.fin.emit({(e.id, x.id_cliente) for x in lista[hecho - 1:]}, True)
                return
            self._senal_sri.resultado.emit(e, f, c, hecho, len(lista))
            time.sleep(0.2)                              # sin apurar al servicio del SRI
        self._senal_sri.fin.emit(set(), False)

    def _sri_resultado(self, e: emp.Empresa, f: facturas.Factura, c, hecho: int, total: int) -> None:
        if c is not None:
            comparador = self._sri_comparadores.setdefault(e.id, sri.Comparador(e.catalogos.tabla("AE")))
            sri.aplicar(e, f.id_cliente, f.nombre_cliente, f.tipo_id_cliente, c, comparador)
        self.statusBar().showMessage(f"Consultando en el SRI: {hecho} de {total}…")
        self._sri_por_dibujar = True
        self._sri_dibujar()

    def _sri_fin(self, sin_consultar: set, fallo: bool) -> None:
        self._sri_pedidos -= sin_consultar               # se reintenta la próxima vez que se agreguen facturas
        self.statusBar().showMessage("No se pudo consultar el SRI (sin internet o servicio no disponible). Esos clientes "
                                     "quedan con la actividad por defecto." if fallo else "Consulta en el SRI terminada.", 10000)
        self._sri_dibujar()

    def _sri_dibujar(self) -> None:
        """Redibuja con lo nuevo, sin interrumpir si el usuario está escribiendo en una celda."""
        from PySide6.QtCore import QTimer

        if not self._sri_por_dibujar:
            return
        if self.tabla.state() == QAbstractItemView.EditingState:
            QTimer.singleShot(800, self._sri_dibujar)
            return
        self._sri_por_dibujar = False
        self._mostrar_lista(conservar_marcas=True)

    # ------------------------------------------------------------------
    # Plantillas CLI, OPR y TRA
    def importar_plantillas(self, rutas: list[str]) -> bool:
        """Lee las plantillas, las revisa con las reglas del manual y, si están bien, las carga en la tabla."""
        rutas_p = [Path(r) for r in rutas]
        # empresa: la del código de las plantillas (se elige sola)
        try:
            cabecera, _datos = excel._leer(rutas_p[0])
        except Exception as ex:  # noqa: BLE001
            QMessageBox.warning(self, "Plantillas", f"No se pudo leer {rutas_p[0].name}:\n{ex}")
            return False
        codigo = cabecera[1] if len(cabecera) > 1 else ""
        e = next((x for x in emp.listar() if x.tiene_uafi and x.codigo == codigo), None)
        if e is None:
            QMessageBox.warning(self, "Plantillas", f"Las plantillas son del código de registro {codigo or '(vacío)'} "
                                                    "y no hay ninguna empresa con ese código.\n"
                                                    "Agréguela con «Empresas…».")
            return False
        try:
            nuevo, avisos = excel.importar(rutas_p, e.estructura, e.catalogos)
        except Exception as ex:  # noqa: BLE001
            QMessageBox.warning(self, "Plantillas", f"No se pudieron leer las plantillas:\n{ex}")
            return False
        prefijos = {n.prefijo for n in e.estructura.niveles}
        leidos = set()
        for r in rutas_p:
            try:
                cab, _d = excel._leer(r)
                leidos.add((cab[0] if cab else "").upper())
            except Exception:  # noqa: BLE001
                pass
        faltan = sorted(prefijos - leidos)
        mensajes = validar(nuevo, e.estructura, e.catalogos)
        errores = [m for m in mensajes if m.es_error]
        problemas = [f"• Falta la plantilla {p}" for p in faltan] + [f"• {a}" for a in avisos]
        for m in errores:
            cli = nuevo.registro(m.ruta[:1]) if m.ruta else None
            ope = nuevo.registro(m.ruta[:2]) if len(m.ruta) >= 2 else None
            donde = (f"Operación {ope.get('NCT')} ({cli.get('NRS')})" if ope is not None else
                     f"Cliente {cli.get('NRS')}" if cli is not None else "Reporte")
            problemas.append(f"• {donde}: {m.texto}")
        operaciones = sum(len(c.hijos) for c in nuevo.clientes)
        transacciones = sum(len(o.hijos) for c in nuevo.clientes for o in c.hijos)
        resumen = (f"<b>{e.nombre} — {MESES[nuevo.mes - 1]} {nuevo.anio}</b><br>"
                   f"Clientes: {len(nuevo.clientes)} · Operaciones: {operaciones} · Transacciones: {transacciones}")
        self.ultima_revision = problemas
        if problemas and not self._confirmar_problemas(resumen, problemas):
            return False
        if self.lista and QMessageBox.question(
                self, "Plantillas", "La tabla ya tiene facturas. ¿Reemplazarlas por las de las plantillas?") \
                != QMessageBox.Yes:
            return False
        self._fijar_seleccion(self.c_empresa.findData(e.id), nuevo.mes - 1, nuevo.anio)     # la empresa se elige sola
        self._empresa_elegida()
        e.recordar_clientes([c.valores for c in nuevo.clientes])   # actividad, dirección, cantón… del CLI
        self.lista = imf.facturas_desde_reporte(nuevo)
        self._mostrar_lista()
        if not problemas:
            QMessageBox.information(self, "Plantillas", f"✔ Las plantillas están bien (sin errores).<br><br>{resumen}"
                                    "<br><br>Se cargaron en la tabla.")
        return True

    def _confirmar_problemas(self, resumen: str, problemas: list[str]) -> bool:
        """Muestra los problemas de las plantillas. True si el usuario quiere cargarlas igual."""
        caja = QMessageBox(self)
        caja.setIcon(QMessageBox.Warning)
        caja.setWindowTitle("Revisión de las plantillas")
        caja.setTextFormat(Qt.RichText)
        caja.setText(f"{resumen}<br><br>Se encontraron <b>{len(problemas)} problema(s)</b> que la UAFE podría "
                     "no aceptar:<br><br>" + "<br>".join(_html(x) for x in problemas[:20])
                     + ("<br>…" if len(problemas) > 20 else ""))
        cargar = caja.addButton("Cargar igual para corregir", QMessageBox.AcceptRole)
        cancelar = caja.addButton("No cargar", QMessageBox.RejectRole)
        caja.setDefaultButton(cancelar)
        caja.exec()
        return caja.clickedButton() is cargar

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
            aec = self.empresa.directorio_clientes().get(f.id_cliente, {}).get("AEC", "")
            if sri.es_dudosa(self.empresa.consultas_sri().get(f.id_cliente, {}), aec):
                menu.addAction("Confirmar esta actividad (quitar el ámbar)", lambda: self.guardar_actividad(f, aec))
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
        consulta = e.consultas_sri().get(f.id_cliente)
        if consulta and "codigo" in consulta:          # ya la revisó el usuario: deja de marcarse
            e.guardar_consulta_sri(f.id_cliente, {"texto": consulta.get("texto", "")})
        fila = self.tabla.currentRow()
        self._mostrar_lista()
        self.tabla.selectRow(fila)
        self.statusBar().showMessage(f"Actividad {codigo} guardada para {f.nombre_cliente}.", 6000)

    def _doble_clic(self, fila: int, columna: int) -> None:
        if fila >= len(self.lista):
            return
        if columna == C_RUC:
            self.copiar_ruc(self.lista[fila].id_cliente)
        elif columna in (C_AEC, C_FP, C_TOTAL) or columna in CAMPO_COLUMNA:
            if columna in self.delegados:
                self.delegados[columna].modo = "escribir"   # doble clic: escribir para buscar
            self.tabla.editItem(self.tabla.item(fila, columna))

    def quitar(self) -> None:
        filas = sorted({i.row() for i in self.tabla.selectedIndexes()}, reverse=True)
        for fila in filas:
            del self.lista[fila]
        self._mostrar_lista()

    def vaciar(self) -> None:
        if self.lista and QMessageBox.question(self, "Quitar todas", "¿Quitar todas las facturas de este mes?") \
                == QMessageBox.Yes:
            self.lista = []
            self._mostrar_lista()

    # ------------------------------------------------------------------
    # Generar y UAFI
    def _agencia_valida(self) -> str:
        """Mensaje de error del código de agencia, o "" si está bien."""
        e = self.empresa
        agencia = e.agencia_defecto().strip()
        if agencia.isdigit() and len(agencia) in (8, 9) and agencia.startswith(e.codigo):
            return ""
        return (f"El código de agencia ({agencia or 'vacío'}) debe tener 8 o 9 dígitos y empezar con el código de "
                f"la empresa ({e.codigo}). Corríjalo en «Empresas…».")

    def _revisar(self, lista: list[facturas.Factura] | None = None):
        """Arma el reporte con la tabla y lo revisa con las reglas del manual.

        Devuelve (reporte, errores, advertencias, afectadas) donde cada error/advertencia es un texto
        «• Factura … (cliente): problema» y afectadas = {(cliente, factura): [problemas]}."""
        e = self.empresa
        rep, propuestas = imf.construir_reporte(e, self.anio, self.mes, lista if lista is not None else self.lista,
                                                self._opciones(), self.anteriores)
        errores, advertencias = [], []
        afectadas: dict[tuple[str, str], list[str]] = {}
        for p in propuestas:                 # lo que está en la tabla pero no entrará al reporte
            if p.estado == imf.OMITIR and p.factura is not None:
                errores.append(f"• Factura {p.factura.numero} ({p.factura.nombre_cliente}): no entra al reporte. {p.texto}")
                afectadas.setdefault((p.factura.id_cliente, p.factura.numero), []).append(p.texto)
        consultas = e.consultas_sri()
        for c in rep.clientes:
            if sri.es_dudosa(consultas.get(c.get("IDE"), {}), c.get("AEC")):
                advertencias.append(f"• Cliente {c.get('NRS')}: actividad tomada del SRI con coincidencia dudosa; revísela.")
        for m in validar(rep, e.estructura, e.catalogos):
            cliente = rep.registro(m.ruta[:1]) if m.ruta else None
            operacion = rep.registro(m.ruta[:2]) if len(m.ruta) >= 2 else None
            if operacion is not None:
                donde = f"Factura {operacion.get('NCT')} ({cliente.get('NRS')})"
                claves = [(cliente.get("IDE"), operacion.get("NCT"))]
            elif cliente is not None:
                donde = f"Cliente {cliente.get('NRS')}"
                claves = [(cliente.get("IDE"), o.get("NCT")) for o in cliente.hijos]
            else:
                donde, claves = "Reporte", []
            (errores if m.es_error else advertencias).append(f"• {donde}: {m.texto}")
            if m.es_error:
                for k in claves:
                    afectadas.setdefault(k, []).append(m.texto)
        return rep, errores, advertencias, afectadas

    def validar_tabla(self) -> None:
        """Botón «Validar»: revisa sin generar y marca en la tabla las facturas con problemas."""
        e = self.empresa
        if e is None or not self.lista:
            return
        rep, errores, advertencias, afectadas = self._revisar()
        agencia = self._agencia_valida()
        if agencia:
            errores.insert(0, f"• Empresa: {agencia}")
        self._marcas = afectadas
        self._mostrar_lista(conservar_marcas=True)
        t = rep.totales(e.estructura)
        resumen = (f"<b>{e.nombre} — {MESES[self.mes - 1]} {self.anio}</b><br>"
                   f"Clientes: {t.get('CLIENTE', 0)} · Operaciones: {t.get('OPERACION', 0)} · "
                   f"Total: $ {t.get('VVT', 0):,}".replace(",", "."))
        if not errores:
            texto = f"✔ <b>Listo para generar el Excel.</b><br><br>{resumen}"
            if advertencias:
                texto += (f"<br><br>Hay {len(advertencias)} advertencia(s) para revisar (no impiden generar):<br>"
                          + "<br>".join(_html(a) for a in advertencias[:10]))
            QMessageBox.information(self, "Validar", texto)
            return
        caja = QMessageBox(self)
        caja.setIcon(QMessageBox.Warning)
        caja.setWindowTitle("Validar")
        caja.setTextFormat(Qt.RichText)
        caja.setText(f"{resumen}<br><br>Hay <b>{len(errores)} problema(s)</b> que la UAFE podría no aceptar "
                     f"(las facturas afectadas quedan <span style='background:#f8d7da'>en rojo</span> en la tabla):"
                     "<br><br>" + "<br>".join(_html(x) for x in errores[:20]) + ("<br>…" if len(errores) > 20 else "")
                     + (f"<br><br>Además, {len(advertencias)} advertencia(s)." if advertencias else ""))
        caja.exec()

    def generar(self) -> None:
        e = self.empresa
        if e is None or not self.lista:
            return
        agencia = self._agencia_valida()
        if agencia:
            QMessageBox.warning(self, "Código de agencia", agencia)
            return
        opciones = self._opciones()
        rep, errores, _adv, afectadas = self._revisar()
        con_problema = set(afectadas)   # (cliente, factura)
        if errores:
            caja = QMessageBox(self)
            caja.setIcon(QMessageBox.Warning)
            caja.setWindowTitle("Revisar")
            caja.setText(f"Hay {len(errores)} dato(s) que la UAFE podría no aceptar:\n\n" + "\n".join(errores[:15])
                         + ("\n…" if len(errores) > 15 else ""))
            b_todas = caja.addButton("Generar con todas", QMessageBox.AcceptRole)
            b_sin = caja.addButton(f"Generar sin esas facturas ({len(con_problema)})", QMessageBox.ActionRole)
            b_cancelar = caja.addButton("Cancelar", QMessageBox.RejectRole)
            caja.setDefaultButton(b_cancelar)
            caja.exec()
            if caja.clickedButton() is b_sin:
                lista = [f for f in self.lista if (f.id_cliente, f.numero) not in con_problema]
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
        self._sin_generar = False
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
            proceso = uafi.abrir(self.empresa)
            self.statusBar().showMessage(f"Abriendo el UAFI de {self.empresa.nombre}…", 6000)
        except Exception as ex:  # noqa: BLE001
            QMessageBox.warning(self, "UAFI", str(ex))
            return
        self._vigilar_uaf(proceso)

    # ------------------------------------------------------------------
    # El UAFI está hecho para Windows: en Linux guarda «carpeta\RESU….uaf» fuera de la carpeta
    # elegida. Mientras esté abierto se revisa cada pocos segundos y se corrige (reparar_uaf).
    def _vigilar_uaf(self, proceso) -> None:
        import sys
        import threading
        import time

        from PySide6.QtCore import QTimer

        from .. import reparar_uaf

        if sys.platform.startswith("win"):
            return   # en Windows la barra invertida sí es el separador de carpetas
        desde = time.time() - 5
        carpetas = [Path.home()]
        exportar = QSettings().value(f"exportar/{self.empresa.id}", "")
        if exportar and not str(exportar).startswith(str(Path.home())):
            carpetas.append(Path(str(exportar)))
        estado = {"ocupado": False}
        reloj = QTimer(self)

        def revisar():
            if estado["ocupado"]:
                return
            estado["ocupado"] = True
            terminado = proceso.poll() is not None

            def trabajo():
                try:
                    cambios = reparar_uaf.reparar_todo(carpetas, desde)
                except Exception:  # noqa: BLE001
                    cambios = []
                estado["ocupado"] = False
                self._senal_uaf.listo.emit(cambios, terminado, reloj)

            threading.Thread(target=trabajo, daemon=True).start()

        reloj.timeout.connect(revisar)
        reloj.start(3000)

    def _uaf_revisado(self, cambios: list, terminado: bool, reloj) -> None:
        if terminado:
            reloj.stop()
            reloj.deleteLater()
        for viejo, nuevo in cambios:
            self.statusBar().showMessage(f"Archivo .uaf corregido: {nuevo}", 15000)
            QMessageBox.information(
                self, "Archivo .uaf",
                f"El UAFI guardó el archivo con un nombre de Windows:<br><b>{_html(viejo.name)}</b><br><br>"
                f"Se corrigió y quedó en:<br><b>{_html(str(nuevo))}</b>")

    def mostrar_ayuda(self) -> None:
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser

        d = QDialog(self)
        d.setWindowTitle("Ayuda — Generador RESU UAFE")
        d.resize(720, 640)
        texto = QTextBrowser()
        texto.setOpenExternalLinks(False)
        texto.setHtml(AYUDA)
        botones = QDialogButtonBox(QDialogButtonBox.Close)
        botones.button(QDialogButtonBox.Close).setText("Cerrar")
        botones.rejected.connect(d.reject)
        lay = QVBoxLayout(d)
        lay.addWidget(texto)
        lay.addWidget(botones)
        d.exec()

    def administrar_empresas(self) -> None:
        DialogoEmpresas(self).exec()
        actual, lista, sin_generar = self.c_empresa.currentData() or "", self.lista, self._sin_generar
        self._llenar_empresas(actual)
        if actual and self.c_empresa.currentData() == actual:     # corregir un dato no debe vaciar la tabla
            self.lista, self._sin_generar = lista, sin_generar
            self._mostrar_lista()
            self._sin_generar = sin_generar

    # ------------------------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        rutas = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if rutas:
            self.agregar(rutas)

    def closeEvent(self, event):
        if not self._puede_descartar():
            event.ignore()
            return
        cfg = QSettings()
        cfg.setValue("simple/geometria", self.saveGeometry())
        super().closeEvent(event)
