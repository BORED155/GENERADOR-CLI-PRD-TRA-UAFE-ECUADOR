"""Vista previa de las facturas antes de agregarlas al reporte."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..empresas import Empresa
from ..importar_facturas import (AVISO, FORMAS_PAGO_SRI, LISTA, NOMBRE_INSTRUMENTO, OMITIR, Opciones, Propuesta,
                                 instrumentos, revisar)
from ..modelo import Reporte, entero

COLUMNAS = ["", "Estado", "Cliente", "Factura", "Fecha", "Total", "Forma de pago SRI", "Instrumento UAFE",
            "Tipo de transacción", "Observaciones", "Archivo"]
C_INC, C_EST, C_CLI, C_FAC, C_FEC, C_TOT, C_FP, C_INS, C_TTR, C_OBS, C_ARC = range(len(COLUMNAS))
ICONOS = {LISTA: ("✔ Lista", "#2e7d32"), AVISO: ("⚠ Revisar", "#b26a00"), OMITIR: ("✖ No se importa", "#757575")}


def _combo(opciones: dict[str, str], valor: str, ancho: int = 0) -> QComboBox:
    c = QComboBox()
    for codigo, nombre in opciones.items():
        c.addItem(f"{codigo} — {nombre}", codigo)
    i = c.findData(valor)
    c.setCurrentIndex(max(i, 0))
    if ancho:
        c.setMinimumWidth(ancho)
    return c


class DialogoFacturas(QDialog):
    def __init__(self, empresa: Empresa, reporte: Reporte, propuestas: list[Propuesta], opciones: Opciones,
                 parent=None):
        super().__init__(parent)
        self.empresa, self.reporte, self.propuestas, self.opciones = empresa, reporte, propuestas, opciones
        self.setWindowTitle("Agregar facturas de venta al RESU")
        self.setSizeGripEnabled(True)
        self.resize(1300, 620)
        cat = empresa.catalogos
        self.tipos_tx = dict(sorted(cat.tabla("TT").items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0))
        self.instr = dict(NOMBRE_INSTRUMENTO)

        # --- valores para todas las facturas ---
        self.c_ttr = _combo(self.tipos_tx, opciones.ttr, 300)
        self.c_ttb = _combo(dict(sorted(cat.tabla("TB").items())), opciones.ttb, 180)
        self.e_adb = QLineEdit(opciones.adb)
        self.e_adb.setMaximumWidth(80)
        self.e_adb.setToolTip("Área del bien en m². 0 si no se conoce.")
        self.c_i20 = _combo(self.instr, opciones.instrumento_20, 200)
        self.c_i20.setToolTip("La forma de pago 20 del SRI (transferencias, cheques…) no dice cuál fue: elija "
                              "cómo registrarla.")
        fila1 = QHBoxLayout()
        fila1.addWidget(QLabel("Tipo de transacción:"))
        fila1.addWidget(self.c_ttr)
        fila1.addSpacing(12)
        fila1.addWidget(QLabel("Tipo de bien:"))
        fila1.addWidget(self.c_ttb)
        fila1.addSpacing(12)
        fila1.addWidget(QLabel("Área del bien:"))
        fila1.addWidget(self.e_adb)
        fila1.addSpacing(12)
        fila1.addWidget(QLabel("Pago «20 - otros con sistema financiero» como:"))
        fila1.addWidget(self.c_i20)
        fila1.addStretch(1)
        self.c_ttr.currentIndexChanged.connect(self._ttr_para_todas)
        self.c_i20.currentIndexChanged.connect(self._i20_cambiado)

        self.tabla = QTableWidget(len(propuestas), len(COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(COLUMNAS)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tabla.horizontalHeader().setStretchLastSection(True)
        for fila, p in enumerate(propuestas):
            self._llenar_fila(fila, p)
        self.tabla.resizeColumnsToContents()
        for col, ancho in ((C_CLI, 250), (C_FP, 150), (C_INS, 170), (C_TTR, 190)):
            self.tabla.setColumnWidth(col, min(self.tabla.columnWidth(col), ancho))
        self.tabla.setColumnWidth(C_OBS, 420)
        self.tabla.setWordWrap(True)
        self.tabla.resizeRowsToContents()
        self.tabla.itemChanged.connect(self._marcado)

        self.resumen = QLabel()
        self.resumen.setWordWrap(True)
        nota = QLabel("Cada factura se agrega como una operación (número = número de factura, valor = total sin "
                      "decimales) con su transacción. Los datos que la factura no trae (actividad económica, "
                      "cantón…) se completan una vez en Clientes y el programa los recuerda.")
        nota.setWordWrap(True)
        nota.setStyleSheet("color: palette(mid);")
        self.botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        self.botones.accepted.connect(self._aceptar)
        self.botones.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(fila1)
        lay.addWidget(self.tabla, 1)
        lay.addWidget(nota)
        lay.addWidget(self.resumen)
        lay.addWidget(self.botones)
        self._actualizar_resumen()

    # ------------------------------------------------------------------
    def _llenar_fila(self, fila: int, p: Propuesta) -> None:
        self.tabla.blockSignals(True)
        marca = QTableWidgetItem()
        if p.estado == OMITIR:
            marca.setFlags(Qt.ItemIsEnabled)
        else:
            marca.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            marca.setCheckState(Qt.Checked if p.incluir else Qt.Unchecked)
        self.tabla.setItem(fila, C_INC, marca)
        f = p.factura
        valores = [
            "", "",
            f"{f.id_cliente}  {f.nombre_cliente}" if f else "",
            f.numero if f and f.secuencial else "",
            f.fecha.strftime("%d/%m/%Y") if f and f.fecha else "",
            f"{f.total:,.2f}" if f else "",
            ", ".join(f"{c} {FORMAS_PAGO_SRI.get(c, '')}".strip() for c, _v in f.pagos) if f else "",
            "", "", p.texto, p.archivo,
        ]
        for col, texto in enumerate(valores):
            if col in (C_INC, C_INS, C_TTR):
                continue
            item = QTableWidgetItem(texto)
            item.setToolTip(texto)
            if col == C_TOT:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tabla.setItem(fila, col, item)
        self._pintar_estado(fila, p)
        if p.estado != OMITIR and f is not None:
            varias = len([v for _c, v in f.pagos if v > 0]) > 1
            ci = _combo(self.instr, p.instrumento)
            ci.setEnabled(not varias)
            if varias:
                ci.setToolTip("Varias formas de pago: se reparte según la factura.")
            ci.currentIndexChanged.connect(lambda _i, fi=fila, c=ci: self._cambio_fila(fi, instrumento=c.currentData()))
            self.tabla.setCellWidget(fila, C_INS, ci)
            ct = _combo(self.tipos_tx, p.ttr)
            ct.currentIndexChanged.connect(lambda _i, fi=fila, c=ct: self._cambio_fila(fi, ttr=c.currentData()))
            self.tabla.setCellWidget(fila, C_TTR, ct)
        self.tabla.blockSignals(False)

    def _pintar_estado(self, fila: int, p: Propuesta) -> None:
        texto, color = ICONOS[p.estado]
        item = QTableWidgetItem(texto)
        item.setForeground(QColor(color))
        self.tabla.setItem(fila, C_EST, item)
        obs = self.tabla.item(fila, C_OBS)
        if obs is not None:
            obs.setText(p.texto)
            obs.setToolTip(p.texto)

    def _opciones_actuales(self) -> Opciones:
        return Opciones(ttr=self.c_ttr.currentData(), ttb=self.c_ttb.currentData(),
                        adb=entero(self.e_adb.text()) or "0", instrumento_20=self.c_i20.currentData())

    def _cambio_fila(self, fila: int, ttr: str | None = None, instrumento: str | None = None) -> None:
        p = self.propuestas[fila]
        if ttr is not None:
            p.ttr = ttr
        if instrumento is not None:
            p.instrumento = instrumento
        revisar(p, self._opciones_actuales())
        self.tabla.blockSignals(True)
        self._pintar_estado(fila, p)
        self.tabla.blockSignals(False)
        self._actualizar_resumen()

    def _ttr_para_todas(self) -> None:
        for fila, p in enumerate(self.propuestas):
            combo = self.tabla.cellWidget(fila, C_TTR)
            if combo is not None:
                combo.setCurrentIndex(max(combo.findData(self.c_ttr.currentData()), 0))

    def _i20_cambiado(self) -> None:
        anterior = self.opciones.instrumento_20
        nuevo = self.c_i20.currentData()
        self.opciones.instrumento_20 = nuevo
        for fila, p in enumerate(self.propuestas):
            if p.factura is None or p.estado == OMITIR:
                continue
            formas = [c for c, _v in p.factura.pagos]
            if not formas or formas[0] not in ("01", "16", "17", "18", "19", "21"):
                combo = self.tabla.cellWidget(fila, C_INS)
                if combo is not None and (combo.currentData() == anterior or not formas):
                    combo.setCurrentIndex(max(combo.findData(nuevo), 0))

    def _marcado(self, item: QTableWidgetItem) -> None:
        if item.column() == C_INC:
            self.propuestas[item.row()].incluir = item.checkState() == Qt.Checked
            self._actualizar_resumen()

    def _actualizar_resumen(self) -> None:
        elegidas = [p for p in self.propuestas if p.incluir and p.estado != OMITIR]
        avisos = sum(p.estado == AVISO for p in elegidas)
        omitidas = sum(p.estado == OMITIR for p in self.propuestas)
        clientes = {p.factura.id_cliente for p in elegidas}
        total = sum(int(p.factura.total) for p in elegidas)
        texto = (f"<b>{len(elegidas)}</b> factura(s) de <b>{len(clientes)}</b> cliente(s), total "
                 f"<b>$ {total:,}</b>".replace(",", "."))
        if avisos:
            texto += f" · <span style='color:#b26a00'>{avisos} para revisar después de agregar</span>"
        if omitidas:
            texto += f" · {omitidas} archivo(s) no se importan (ver Observaciones)"
        self.resumen.setText(texto)
        boton = self.botones.button(QDialogButtonBox.Ok)
        boton.setText(f"Agregar {len(elegidas)} factura(s)")
        boton.setEnabled(bool(elegidas))

    def _aceptar(self) -> None:
        nuevas = self._opciones_actuales()
        self.opciones.__dict__.update(nuevas.__dict__)
        for p in self.propuestas:
            if p.factura is not None and p.estado != OMITIR:
                instrumentos(p, self.opciones)
        self.accept()
